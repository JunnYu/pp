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
import tempfile
import unittest

import numpy as np
import paddle
from PIL import Image
from ppdiffusers_test.test_pipelines_common import PipelineTesterMixin

from paddlenlp.transformers import (
    CLIPTextConfig,
    CLIPTextModel,
    CLIPTokenizer,
    DPTConfig,
    DPTFeatureExtractor,
    DPTForDepthEstimation,
)
from ppdiffusers import (
    AutoencoderKL,
    DDIMScheduler,
    DPMSolverMultistepScheduler,
    LMSDiscreteScheduler,
    PNDMScheduler,
    StableDiffusionDepth2ImgPipeline,
    UNet2DConditionModel,
)
from ppdiffusers.utils import floats_tensor, load_image, load_numpy, nightly, slow
from ppdiffusers.utils.testing_utils import require_paddle_gpu


class StableDiffusionDepth2ImgPipelineFastTests(PipelineTesterMixin, unittest.TestCase):
    pipeline_class = StableDiffusionDepth2ImgPipeline
    test_save_load_optional_components = False

    def get_dummy_components(self):
        paddle.seed(0)
        unet = UNet2DConditionModel(
            block_out_channels=(32, 64),
            layers_per_block=2,
            sample_size=32,
            in_channels=5,
            out_channels=4,
            down_block_types=("DownBlock2D", "CrossAttnDownBlock2D"),
            up_block_types=("CrossAttnUpBlock2D", "UpBlock2D"),
            cross_attention_dim=32,
            attention_head_dim=(2, 4),
            use_linear_projection=True,
        )
        scheduler = PNDMScheduler(skip_prk_steps=True)
        paddle.seed(0)
        vae = AutoencoderKL(
            block_out_channels=[32, 64],
            in_channels=3,
            out_channels=3,
            down_block_types=["DownEncoderBlock2D", "DownEncoderBlock2D"],
            up_block_types=["UpDecoderBlock2D", "UpDecoderBlock2D"],
            latent_channels=4,
        )
        paddle.seed(0)
        text_encoder_config = CLIPTextConfig(
            bos_token_id=0,
            eos_token_id=2,
            hidden_size=32,
            intermediate_size=37,
            layer_norm_eps=1e-05,
            num_attention_heads=4,
            num_hidden_layers=5,
            pad_token_id=1,
            vocab_size=1000,
        )
        text_encoder = CLIPTextModel(text_encoder_config).eval()
        tokenizer = CLIPTokenizer.from_pretrained("hf-internal-testing/tiny-random-clip")
        backbone_config = {
            "global_padding": "same",
            "layer_type": "bottleneck",
            "depths": [3, 4, 9],
            "out_features": ["stage1", "stage2", "stage3"],
            "embedding_dynamic_padding": True,
            "hidden_sizes": [96, 192, 384, 768],
            "num_groups": 2,
        }
        depth_estimator_config = DPTConfig(
            image_size=32,
            patch_size=16,
            num_channels=3,
            hidden_size=32,
            num_hidden_layers=4,
            backbone_out_indices=(0, 1, 2, 3),
            num_attention_heads=4,
            intermediate_size=37,
            hidden_act="gelu",
            hidden_dropout_prob=0.1,
            attention_probs_dropout_prob=0.1,
            is_decoder=False,
            initializer_range=0.02,
            is_hybrid=True,
            backbone_config=backbone_config,
            backbone_featmap_shape=[1, 384, 24, 24],
        )
        depth_estimator = DPTForDepthEstimation(depth_estimator_config)
        feature_extractor = DPTFeatureExtractor.from_pretrained(
            "hf-internal-testing/tiny-random-DPTForDepthEstimation"
        )
        components = {
            "unet": unet,
            "scheduler": scheduler,
            "vae": vae,
            "text_encoder": text_encoder,
            "tokenizer": tokenizer,
            "depth_estimator": depth_estimator,
            "feature_extractor": feature_extractor,
        }
        return components

    def get_dummy_inputs(self, seed=0):
        image = floats_tensor((1, 3, 32, 32), rng=random.Random(seed))
        image = image.cpu().transpose(perm=[0, 2, 3, 1])[0]
        image = Image.fromarray(np.uint8(image)).convert("RGB").resize((32, 32))
        generator = paddle.Generator().manual_seed(seed)

        inputs = {
            "prompt": "A painting of a squirrel eating a burger",
            "image": image,
            "generator": generator,
            "num_inference_steps": 2,
            "guidance_scale": 6.0,
            "output_type": "numpy",
        }
        return inputs

    def test_save_load_local(self):
        components = self.get_dummy_components()
        pipe = self.pipeline_class(**components)
        pipe.set_progress_bar_config(disable=None)
        inputs = self.get_dummy_inputs()
        output = pipe(**inputs)[0]
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe.save_pretrained(tmpdir)
            pipe_loaded = self.pipeline_class.from_pretrained(tmpdir)
            pipe_loaded
            pipe_loaded.set_progress_bar_config(disable=None)
        inputs = self.get_dummy_inputs()
        output_loaded = pipe_loaded(**inputs)[0]
        max_diff = np.abs(output - output_loaded).max()
        self.assertLess(max_diff, 0.0001)

    def test_save_load_float16(self):
        components = self.get_dummy_components()
        for name, module in components.items():
            if hasattr(module, "to"):
                components[name] = module.to(dtype=paddle.float16)
        pipe = self.pipeline_class(**components)
        pipe.set_progress_bar_config(disable=None)
        inputs = self.get_dummy_inputs()
        output = pipe(**inputs)[0]
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe.save_pretrained(tmpdir)
            pipe_loaded = self.pipeline_class.from_pretrained(tmpdir, paddle_dtype=paddle.float16)
            pipe_loaded
            pipe_loaded.set_progress_bar_config(disable=None)
        for name, component in pipe_loaded.components.items():
            if hasattr(component, "dtype"):
                self.assertTrue(
                    component.dtype == "float16",
                    f"`{name}.dtype` switched from `float16` to {component.dtype} after loading.",
                )
        inputs = self.get_dummy_inputs()
        output_loaded = pipe_loaded(**inputs)[0]
        max_diff = np.abs(output - output_loaded).max()
        self.assertLess(max_diff, 0.02, "The output of the fp16 pipeline changed after saving and loading.")

    def test_float16_inference(self):
        components = self.get_dummy_components()
        pipe = self.pipeline_class(**components)
        pipe.set_progress_bar_config(disable=None)
        for name, module in components.items():
            if hasattr(module, "to"):
                components[name] = module.to(dtype=paddle.float16)
        pipe_fp16 = self.pipeline_class(**components)
        pipe_fp16
        pipe_fp16.set_progress_bar_config(disable=None)
        output = pipe(**self.get_dummy_inputs())[0]
        output_fp16 = pipe_fp16(**self.get_dummy_inputs())[0]
        max_diff = np.abs(output - output_fp16).max()
        self.assertLess(max_diff, 0.013, "The outputs of the fp16 and fp32 pipelines are too different.")

    def test_dict_tuple_outputs_equivalent(self):
        components = self.get_dummy_components()
        pipe = self.pipeline_class(**components)
        pipe.set_progress_bar_config(disable=None)
        output = pipe(**self.get_dummy_inputs())[0]
        output_tuple = pipe(**self.get_dummy_inputs(), return_dict=False)[0]
        max_diff = np.abs(output - output_tuple).max()
        self.assertLess(max_diff, 0.0001)

    def test_progress_bar(self):
        super().test_progress_bar()

    def test_stable_diffusion_depth2img_default_case(self):
        components = self.get_dummy_components()
        pipe = StableDiffusionDepth2ImgPipeline(**components)
        pipe.set_progress_bar_config(disable=None)
        inputs = self.get_dummy_inputs()
        image = pipe(**inputs).images
        image_slice = image[0, -3:, -3:, -1]
        assert image.shape == (1, 32, 32, 3)
        expected_slice = np.array([0.6312, 0.4984, 0.4154, 0.4788, 0.5535, 0.4599, 0.4017, 0.5359, 0.4716])
        assert np.abs(image_slice.flatten() - expected_slice).max() < 0.001

    def test_stable_diffusion_depth2img_negative_prompt(self):
        components = self.get_dummy_components()
        pipe = StableDiffusionDepth2ImgPipeline(**components)
        pipe.set_progress_bar_config(disable=None)
        inputs = self.get_dummy_inputs()
        negative_prompt = "french fries"
        output = pipe(**inputs, negative_prompt=negative_prompt)
        image = output.images
        image_slice = image[0, -3:, -3:, -1]
        assert image.shape == (1, 32, 32, 3)
        if torch_device == "mps":
            expected_slice = np.array([0.5825, 0.5135, 0.4095, 0.5452, 0.6059, 0.4211, 0.3994, 0.5177, 0.4335])
        else:
            expected_slice = np.array([0.6296, 0.5125, 0.389, 0.4456, 0.5955, 0.4621, 0.381, 0.531, 0.4626])
        assert np.abs(image_slice.flatten() - expected_slice).max() < 0.001

    def test_stable_diffusion_depth2img_multiple_init_images(self):
        components = self.get_dummy_components()
        pipe = StableDiffusionDepth2ImgPipeline(**components)
        pipe.set_progress_bar_config(disable=None)
        inputs = self.get_dummy_inputs()
        inputs["prompt"] = [inputs["prompt"]] * 2
        inputs["image"] = 2 * [inputs["image"]]
        image = pipe(**inputs).images
        image_slice = image[(-1), -3:, -3:, (-1)]
        assert image.shape == (2, 32, 32, 3)
        expected_slice = np.array([0.6267, 0.5232, 0.6001, 0.6738, 0.5029, 0.6429, 0.5364, 0.4159, 0.4674])
        assert np.abs(image_slice.flatten() - expected_slice).max() < 0.001

    def test_stable_diffusion_depth2img_num_images_per_prompt(self):
        components = self.get_dummy_components()
        pipe = StableDiffusionDepth2ImgPipeline(**components)
        pipe.set_progress_bar_config(disable=None)
        inputs = self.get_dummy_inputs()
        images = pipe(**inputs).images
        assert images.shape == (1, 32, 32, 3)
        batch_size = 2
        inputs = self.get_dummy_inputs()
        inputs["prompt"] = [inputs["prompt"]] * batch_size
        images = pipe(**inputs).images
        assert images.shape == (batch_size, 32, 32, 3)
        num_images_per_prompt = 2
        inputs = self.get_dummy_inputs()
        images = pipe(**inputs, num_images_per_prompt=num_images_per_prompt).images
        assert images.shape == (num_images_per_prompt, 32, 32, 3)
        batch_size = 2
        inputs = self.get_dummy_inputs()
        inputs["prompt"] = [inputs["prompt"]] * batch_size
        images = pipe(**inputs, num_images_per_prompt=num_images_per_prompt).images
        assert images.shape == (batch_size * num_images_per_prompt, 32, 32, 3)

    def test_stable_diffusion_depth2img_pil(self):
        components = self.get_dummy_components()
        pipe = StableDiffusionDepth2ImgPipeline(**components)
        pipe.set_progress_bar_config(disable=None)
        inputs = self.get_dummy_inputs()
        image = pipe(**inputs).images
        image_slice = image[0, -3:, -3:, -1]
        expected_slice = np.array([0.6312, 0.4984, 0.4154, 0.4788, 0.5535, 0.4599, 0.4017, 0.5359, 0.4716])
        assert np.abs(image_slice.flatten() - expected_slice).max() < 0.001


@slow
@require_paddle_gpu
class StableDiffusionDepth2ImgPipelineSlowTests(unittest.TestCase):
    def tearDown(self):
        super().tearDown()
        gc.collect()
        paddle.device.cuda.empty_cache()

    def get_inputs(self, device="cpu", dtype="float32", seed=0):
        generator = paddle.Generator().manual_seed(seed)
        init_image = load_image(
            "https://huggingface.co/datasets/hf-internal-testing/ppdiffusers-images/resolve/main/depth2img/two_cats.png"
        )
        inputs = {
            "prompt": "two tigers",
            "image": init_image,
            "generator": generator,
            "num_inference_steps": 3,
            "strength": 0.75,
            "guidance_scale": 7.5,
            "output_type": "numpy",
        }
        return inputs

    def test_stable_diffusion_depth2img_pipeline_default(self):
        pipe = StableDiffusionDepth2ImgPipeline.from_pretrained(
            "stabilityai/stable-diffusion-2-depth", safety_checker=None
        )
        pipe.set_progress_bar_config(disable=None)
        pipe.enable_attention_slicing()
        inputs = self.get_inputs()
        image = pipe(**inputs).images
        image_slice = image[(0), 253:256, 253:256, (-1)].flatten()
        assert image.shape == (1, 480, 640, 3)
        expected_slice = np.array([0.9057, 0.9365, 0.9258, 0.8937, 0.8555, 0.8541, 0.826, 0.7747, 0.7421])
        assert np.abs(expected_slice - image_slice).max() < 0.0001

    def test_stable_diffusion_depth2img_pipeline_k_lms(self):
        pipe = StableDiffusionDepth2ImgPipeline.from_pretrained(
            "stabilityai/stable-diffusion-2-depth", safety_checker=None
        )
        pipe.scheduler = LMSDiscreteScheduler.from_config(pipe.scheduler.config)
        pipe.set_progress_bar_config(disable=None)
        pipe.enable_attention_slicing()
        inputs = self.get_inputs()
        image = pipe(**inputs).images
        image_slice = image[(0), 253:256, 253:256, (-1)].flatten()
        assert image.shape == (1, 480, 640, 3)
        expected_slice = np.array([0.6363, 0.6274, 0.6309, 0.637, 0.6226, 0.6286, 0.6213, 0.6453, 0.6306])
        assert np.abs(expected_slice - image_slice).max() < 0.0001

    def test_stable_diffusion_depth2img_pipeline_ddim(self):
        pipe = StableDiffusionDepth2ImgPipeline.from_pretrained(
            "stabilityai/stable-diffusion-2-depth", safety_checker=None
        )
        pipe.scheduler = DDIMScheduler.from_config(pipe.scheduler.config)
        pipe.set_progress_bar_config(disable=None)
        pipe.enable_attention_slicing()
        inputs = self.get_inputs()
        image = pipe(**inputs).images
        image_slice = image[(0), 253:256, 253:256, (-1)].flatten()
        assert image.shape == (1, 480, 640, 3)
        expected_slice = np.array([0.6424, 0.6524, 0.6249, 0.6041, 0.6634, 0.642, 0.6522, 0.6555, 0.6436])
        assert np.abs(expected_slice - image_slice).max() < 0.0001

    def test_stable_diffusion_depth2img_intermediate_state(self):
        number_of_steps = 0

        def callback_fn(step: int, timestep: int, latents: paddle.Tensor) -> None:
            callback_fn.has_been_called = True
            nonlocal number_of_steps
            number_of_steps += 1
            if step == 1:
                latents = latents.detach().cpu().numpy()
                assert latents.shape == (1, 4, 60, 80)
                latents_slice = latents[(0), -3:, -3:, (-1)]
                expected_slice = np.array(
                    [-0.7168, -1.5137, -0.1418, -2.9219, -2.7266, -2.4414, -2.1035, -3.0078, -1.7051]
                )
                assert np.abs(latents_slice.flatten() - expected_slice).max() < 0.05
            elif step == 2:
                latents = latents.detach().cpu().numpy()
                assert latents.shape == (1, 4, 60, 80)
                latents_slice = latents[(0), -3:, -3:, (-1)]
                expected_slice = np.array(
                    [-0.7109, -1.5068, -0.1403, -2.916, -2.7207, -2.4414, -2.1035, -3.0059, -1.709]
                )
                assert np.abs(latents_slice.flatten() - expected_slice).max() < 0.05

        callback_fn.has_been_called = False
        pipe = StableDiffusionDepth2ImgPipeline.from_pretrained(
            "stabilityai/stable-diffusion-2-depth", safety_checker=None, paddle_dtype=paddle.float16
        )
        pipe.set_progress_bar_config(disable=None)
        pipe.enable_attention_slicing()
        inputs = self.get_inputs(dtype="float16")
        pipe(**inputs, callback=callback_fn, callback_steps=1)
        assert callback_fn.has_been_called
        assert number_of_steps == 2

    def test_stable_diffusion_pipeline_with_sequential_cpu_offloading(self):
        paddle.device.cuda.empty_cache()

        pipe = StableDiffusionDepth2ImgPipeline.from_pretrained(
            "stabilityai/stable-diffusion-2-depth", safety_checker=None, paddle_dtype=paddle.float16
        )
        pipe.set_progress_bar_config(disable=None)
        pipe.enable_attention_slicing(1)
        pipe.enable_sequential_cpu_offload()
        inputs = self.get_inputs(dtype="float16")
        _ = pipe(**inputs)
        mem_bytes = paddle.device.cuda.max_memory_allocated()
        assert mem_bytes < 2.9 * 10**9


@nightly
@require_paddle_gpu
class StableDiffusionImg2ImgPipelineNightlyTests(unittest.TestCase):
    def tearDown(self):
        super().tearDown()
        gc.collect()
        paddle.device.cuda.empty_cache()

    def get_inputs(self, device="cpu", dtype="float32", seed=0):
        generator = paddle.Generator().manual_seed(seed)
        init_image = load_image(
            "https://huggingface.co/datasets/hf-internal-testing/ppdiffusers-images/resolve/main/depth2img/two_cats.png"
        )
        inputs = {
            "prompt": "two tigers",
            "image": init_image,
            "generator": generator,
            "num_inference_steps": 3,
            "strength": 0.75,
            "guidance_scale": 7.5,
            "output_type": "numpy",
        }
        return inputs

    def test_depth2img_pndm(self):
        pipe = StableDiffusionDepth2ImgPipeline.from_pretrained("stabilityai/stable-diffusion-2-depth")
        pipe.set_progress_bar_config(disable=None)
        inputs = self.get_inputs()
        image = pipe(**inputs).images[0]
        expected_image = load_numpy(
            "https://huggingface.co/datasets/ppdiffusers/test-arrays/resolve/main/stable_diffusion_depth2img/stable_diffusion_2_0_pndm.npy"
        )
        max_diff = np.abs(expected_image - image).max()
        assert max_diff < 0.001

    def test_depth2img_ddim(self):
        pipe = StableDiffusionDepth2ImgPipeline.from_pretrained("stabilityai/stable-diffusion-2-depth")
        pipe.scheduler = DDIMScheduler.from_config(pipe.scheduler.config)
        pipe.set_progress_bar_config(disable=None)
        inputs = self.get_inputs()
        image = pipe(**inputs).images[0]
        expected_image = load_numpy(
            "https://huggingface.co/datasets/ppdiffusers/test-arrays/resolve/main/stable_diffusion_depth2img/stable_diffusion_2_0_ddim.npy"
        )
        max_diff = np.abs(expected_image - image).max()
        assert max_diff < 0.001

    def test_img2img_lms(self):
        pipe = StableDiffusionDepth2ImgPipeline.from_pretrained("stabilityai/stable-diffusion-2-depth")
        pipe.scheduler = LMSDiscreteScheduler.from_config(pipe.scheduler.config)
        pipe.set_progress_bar_config(disable=None)
        inputs = self.get_inputs()
        image = pipe(**inputs).images[0]
        expected_image = load_numpy(
            "https://huggingface.co/datasets/ppdiffusers/test-arrays/resolve/main/stable_diffusion_depth2img/stable_diffusion_2_0_lms.npy"
        )
        max_diff = np.abs(expected_image - image).max()
        assert max_diff < 0.001

    def test_img2img_dpm(self):
        pipe = StableDiffusionDepth2ImgPipeline.from_pretrained("stabilityai/stable-diffusion-2-depth")
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
        pipe.set_progress_bar_config(disable=None)
        inputs = self.get_inputs()
        inputs["num_inference_steps"] = 30
        image = pipe(**inputs).images[0]
        expected_image = load_numpy(
            "https://huggingface.co/datasets/ppdiffusers/test-arrays/resolve/main/stable_diffusion_depth2img/stable_diffusion_2_0_dpm_multi.npy"
        )
        max_diff = np.abs(expected_image - image).max()
        assert max_diff < 0.001
