# Copyright (c) 2023 PaddlePaddle Authors. All Rights Reserved.
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import gc
import random
import unittest

import numpy as np
import paddle
from PIL import Image
from ppdiffusers_test.test_pipelines_common import PipelineTesterMixin

from paddlenlp.transformers import (
    CLIPImageProcessor,
    CLIPVisionConfig,
    CLIPVisionModelWithProjection,
)
from ppdiffusers import (
    AutoencoderKL,
    DPMSolverMultistepScheduler,
    PNDMScheduler,
    StableDiffusionImageVariationPipeline,
    UNet2DConditionModel,
)
from ppdiffusers.utils import floats_tensor, load_image, load_numpy, nightly, slow
from ppdiffusers.utils.testing_utils import require_paddle_gpu


class StableDiffusionImageVariationPipelineFastTests(PipelineTesterMixin,
    unittest.TestCase):
    pipeline_class = StableDiffusionImageVariationPipeline

    def get_dummy_components(self):
        paddle.seed(0)
        unet = UNet2DConditionModel(block_out_channels=(32, 64),
            layers_per_block=2, sample_size=32, in_channels=4, out_channels
            =4, down_block_types=('DownBlock2D', 'CrossAttnDownBlock2D'),
            up_block_types=('CrossAttnUpBlock2D', 'UpBlock2D'),
            cross_attention_dim=32)
        scheduler = PNDMScheduler(skip_prk_steps=True)
        paddle.seed(0)
        vae = AutoencoderKL(block_out_channels=[32, 64], in_channels=3,
            out_channels=3, down_block_types=['DownEncoderBlock2D',
            'DownEncoderBlock2D'], up_block_types=['UpDecoderBlock2D',
            'UpDecoderBlock2D'], latent_channels=4)
        paddle.seed(0)
        image_encoder_config = CLIPVisionConfig(hidden_size=32,
            projection_dim=32, intermediate_size=37, layer_norm_eps=1e-05,
            num_attention_heads=4, num_hidden_layers=5, image_size=32,
            patch_size=4)
        image_encoder = CLIPVisionModelWithProjection(image_encoder_config)
        feature_extractor = CLIPImageProcessor(crop_size=32, size=32)
        components = {'unet': unet, 'scheduler': scheduler, 'vae': vae,
            'image_encoder': image_encoder, 'feature_extractor':
            feature_extractor, 'safety_checker': None}
        return components

    def get_dummy_inputs(self, seed=0):
        image = floats_tensor((1, 3, 32, 32), rng=random.Random(seed))
        image = image.cpu().transpose(perm=[0, 2, 3, 1])[0]
        image = Image.fromarray(np.uint8(image)).convert('RGB').resize((32, 32)
            )
        generator = paddle.Generator().manual_seed(seed)

        inputs = {'image': image, 'generator': generator,
            'num_inference_steps': 2, 'guidance_scale': 6.0, 'output_type':
            'numpy'}
        return inputs

    def test_stable_diffusion_img_variation_default_case(self):
        components = self.get_dummy_components()
        sd_pipe = StableDiffusionImageVariationPipeline(**components)
        sd_pipe = sd_pipe
        sd_pipe.set_progress_bar_config(disable=None)
        inputs = self.get_dummy_inputs()
        image = sd_pipe(**inputs).images
        image_slice = image[(0), -3:, -3:, (-1)]
        assert image.shape == (1, 64, 64, 3)
        expected_slice = np.array([0.5167, 0.5746, 0.4835, 0.4914, 0.5605, 
            0.4691, 0.5201, 0.4898, 0.4958])
        assert np.abs(image_slice.flatten() - expected_slice).max() < 0.001

    def test_stable_diffusion_img_variation_multiple_images(self):
        components = self.get_dummy_components()
        sd_pipe = StableDiffusionImageVariationPipeline(**components)
        sd_pipe = sd_pipe
        sd_pipe.set_progress_bar_config(disable=None)
        inputs = self.get_dummy_inputs()
        inputs['image'] = 2 * [inputs['image']]
        output = sd_pipe(**inputs)
        image = output.images
        image_slice = image[(-1), -3:, -3:, (-1)]
        assert image.shape == (2, 64, 64, 3)
        expected_slice = np.array([0.6568, 0.547, 0.5684, 0.5444, 0.5945, 
            0.6221, 0.5508, 0.5531, 0.5263])
        assert np.abs(image_slice.flatten() - expected_slice).max() < 0.001

    def test_stable_diffusion_img_variation_num_images_per_prompt(self):
        components = self.get_dummy_components()
        sd_pipe = StableDiffusionImageVariationPipeline(**components)
        sd_pipe = sd_pipe
        sd_pipe.set_progress_bar_config(disable=None)
        inputs = self.get_dummy_inputs()
        images = sd_pipe(**inputs).images
        assert images.shape == (1, 64, 64, 3)
        batch_size = 2
        inputs = self.get_dummy_inputs()
        inputs['image'] = batch_size * [inputs['image']]
        images = sd_pipe(**inputs).images
        assert images.shape == (batch_size, 64, 64, 3)
        num_images_per_prompt = 2
        inputs = self.get_dummy_inputs()
        images = sd_pipe(**inputs, num_images_per_prompt=num_images_per_prompt
            ).images
        assert images.shape == (num_images_per_prompt, 64, 64, 3)
        batch_size = 2
        inputs = self.get_dummy_inputs()
        inputs['image'] = batch_size * [inputs['image']]
        images = sd_pipe(**inputs, num_images_per_prompt=num_images_per_prompt
            ).images
        assert images.shape == (batch_size * num_images_per_prompt, 64, 64, 3)


@slow
@require_paddle_gpu
class StableDiffusionImageVariationPipelineSlowTests(unittest.TestCase):

    def tearDown(self):
        super().tearDown()
        gc.collect()
        paddle.device.cuda.empty_cache()

    def get_inputs(self, device, generator_device='cpu', dtype='float32',
        seed=0):
        generator = paddle.Generator().manual_seed(seed)
        init_image = load_image(
            'https://huggingface.co/datasets/ppdiffusers/test-arrays/resolve/main/stable_diffusion_imgvar/input_image_vermeer.png'
            )
        latents = np.random.RandomState(seed).standard_normal((1, 4, 64, 64))
        """Class Method: *.to, not convert, please check whether it is torch.Tensor.*/Optimizer.*/nn.Module.*, and convert manually"""
>>>        latents = paddle.to_tensor(data=latents).cast(dtype)
        inputs = {'image': init_image, 'latents': latents, 'generator':
            generator, 'num_inference_steps': 3, 'guidance_scale': 7.5,
            'output_type': 'numpy'}
        return inputs

    def test_stable_diffusion_img_variation_pipeline_default(self):
        sd_pipe = StableDiffusionImageVariationPipeline.from_pretrained(
            'lambdalabs/sd-image-variations-ppdiffusers', safety_checker=None)
        sd_pipe = sd_pipe
        sd_pipe.set_progress_bar_config(disable=None)
        inputs = self.get_inputs()
        image = sd_pipe(**inputs).images
        image_slice = image[(0), -3:, -3:, (-1)].flatten()
        assert image.shape == (1, 512, 512, 3)
        expected_slice = np.array([0.84491, 0.90789, 0.75708, 0.78734, 
            0.83485, 0.70099, 0.66938, 0.68727, 0.61379])
        assert np.abs(image_slice - expected_slice).max() < 0.0001

    def test_stable_diffusion_img_variation_intermediate_state(self):
        number_of_steps = 0

>>>        def callback_fn(step: int, timestep: int, latents: torch.FloatTensor
            ) ->None:
            callback_fn.has_been_called = True
            nonlocal number_of_steps
            number_of_steps += 1
            if step == 1:
                latents = latents.detach().cpu().numpy()
                assert latents.shape == (1, 4, 64, 64)
                latents_slice = latents[(0), -3:, -3:, (-1)]
                expected_slice = np.array([-0.1621, 0.2837, -0.7979, -
                    0.1221, -1.3057, 0.7681, -2.1191, 0.0464, 1.6309])
                assert np.abs(latents_slice.flatten() - expected_slice).max(
                    ) < 0.05
            elif step == 2:
                latents = latents.detach().cpu().numpy()
                assert latents.shape == (1, 4, 64, 64)
                latents_slice = latents[(0), -3:, -3:, (-1)]
                expected_slice = np.array([0.6299, 1.75, 1.1992, -2.1582, -
                    1.8994, 0.7334, -0.709, 1.0137, 1.5273])
                assert np.abs(latents_slice.flatten() - expected_slice).max(
                    ) < 0.05
        callback_fn.has_been_called = False
        pipe = StableDiffusionImageVariationPipeline.from_pretrained(
            'fusing/sd-image-variations-ppdiffusers', safety_checker=None,
            paddle_dtype=paddle.float16)
        pipe.set_progress_bar_config(disable=None)
        pipe.enable_attention_slicing()
        inputs = self.get_inputs(dtype='float16')
        pipe(**inputs, callback=callback_fn, callback_steps=1)
        assert callback_fn.has_been_called
        assert number_of_steps == inputs['num_inference_steps']

    def test_stable_diffusion_pipeline_with_sequential_cpu_offloading(self):
        paddle.device.cuda.empty_cache()

        model_id = 'fusing/sd-image-variations-ppdiffusers'
        pipe = StableDiffusionImageVariationPipeline.from_pretrained(model_id,
            safety_checker=None, paddle_dtype=paddle.float16)
        pipe.set_progress_bar_config(disable=None)
        pipe.enable_attention_slicing(1)
        pipe.enable_sequential_cpu_offload()
        inputs = self.get_inputs(dtype='float16')
        _ = pipe(**inputs)
        mem_bytes = paddle.device.cuda.max_memory_allocated()        assert mem_bytes < 2.6 * 10 ** 9


@nightly
@require_paddle_gpu
class StableDiffusionImageVariationPipelineNightlyTests(unittest.TestCase):

    def tearDown(self):
        super().tearDown()
        gc.collect()
        paddle.device.cuda.empty_cache()

    def get_inputs(self, device, generator_device='cpu', dtype='float32',
        seed=0):
        generator = paddle.Generator().manual_seed(seed)
        init_image = load_image(
            'https://huggingface.co/datasets/ppdiffusers/test-arrays/resolve/main/stable_diffusion_imgvar/input_image_vermeer.png'
            )
        latents = np.random.RandomState(seed).standard_normal((1, 4, 64, 64))
        """Class Method: *.to, not convert, please check whether it is torch.Tensor.*/Optimizer.*/nn.Module.*, and convert manually"""
>>>        latents = paddle.to_tensor(data=latents).cast(dtype)
        inputs = {'image': init_image, 'latents': latents, 'generator':
            generator, 'num_inference_steps': 50, 'guidance_scale': 7.5,
            'output_type': 'numpy'}
        return inputs

    def test_img_variation_pndm(self):
        sd_pipe = StableDiffusionImageVariationPipeline.from_pretrained(
            'fusing/sd-image-variations-ppdiffusers')
        sd_pipe
        sd_pipe.set_progress_bar_config(disable=None)
        inputs = self.get_inputs()
        image = sd_pipe(**inputs).images[0]
        expected_image = load_numpy(
            'https://huggingface.co/datasets/ppdiffusers/test-arrays/resolve/main/stable_diffusion_imgvar/lambdalabs_variations_pndm.npy'
            )
        max_diff = np.abs(expected_image - image).max()
        assert max_diff < 0.001

    def test_img_variation_dpm(self):
        sd_pipe = StableDiffusionImageVariationPipeline.from_pretrained(
            'fusing/sd-image-variations-ppdiffusers')
        sd_pipe.scheduler = DPMSolverMultistepScheduler.from_config(sd_pipe
            .scheduler.config)
        sd_pipe
        sd_pipe.set_progress_bar_config(disable=None)
        inputs = self.get_inputs()
        inputs['num_inference_steps'] = 25
        image = sd_pipe(**inputs).images[0]
        expected_image = load_numpy(
            'https://huggingface.co/datasets/ppdiffusers/test-arrays/resolve/main/stable_diffusion_imgvar/lambdalabs_variations_dpm_multi.npy'
            )
        max_diff = np.abs(expected_image - image).max()
        assert max_diff < 0.001