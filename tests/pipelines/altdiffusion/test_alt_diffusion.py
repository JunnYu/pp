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
import unittest

import numpy as np
import paddle
from ppdiffusers_test.test_pipelines_common import PipelineTesterMixin

from paddlenlp.transformers import CLIPTextConfig, CLIPTextModel, XLMRobertaTokenizer
from ppdiffusers import (
    AltDiffusionPipeline,
    AutoencoderKL,
    DDIMScheduler,
    PNDMScheduler,
    UNet2DConditionModel,
)
from ppdiffusers.pipelines.alt_diffusion.modeling_roberta_series import (
    RobertaSeriesConfig,
    RobertaSeriesModelWithTransformation,
)
from ppdiffusers.utils import slow
from ppdiffusers.utils.testing_utils import require_paddle_gpu


class AltDiffusionPipelineFastTests(PipelineTesterMixin, unittest.TestCase):
    pipeline_class = AltDiffusionPipeline

    def get_dummy_components(self):
        paddle.seed(0)
        unet = UNet2DConditionModel(
            block_out_channels=(32, 64),
            layers_per_block=2,
            sample_size=32,
            in_channels=4,
            out_channels=4,
            down_block_types=("DownBlock2D", "CrossAttnDownBlock2D"),
            up_block_types=("CrossAttnUpBlock2D", "UpBlock2D"),
            cross_attention_dim=32,
        )
        scheduler = DDIMScheduler(
            beta_start=0.00085,
            beta_end=0.012,
            beta_schedule="scaled_linear",
            clip_sample=False,
            set_alpha_to_one=False,
        )
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
            projection_dim=32,
            intermediate_size=37,
            layer_norm_eps=1e-05,
            num_attention_heads=4,
            num_hidden_layers=5,
            pad_token_id=1,
            vocab_size=5002,
        )
        text_encoder = CLIPTextModel(text_encoder_config).eval()
        tokenizer = XLMRobertaTokenizer.from_pretrained(
            "hf-internal-testing/tiny-xlm-roberta", model_max_length=77
        )  # must set model_max_length 77 here
        components = {
            "unet": unet,
            "scheduler": scheduler,
            "vae": vae,
            "text_encoder": text_encoder,
            "tokenizer": tokenizer,
            "safety_checker": None,
            "feature_extractor": None,
        }
        return components

    def get_dummy_inputs(self, seed=0):
        generator = paddle.Generator().manual_seed(seed)
        inputs = {
            "prompt": "A painting of a squirrel eating a burger",
            "generator": generator,
            "num_inference_steps": 2,
            "guidance_scale": 6.0,
            "output_type": "numpy",
        }
        return inputs

    def test_alt_diffusion_ddim(self):
        components = self.get_dummy_components()
        paddle.seed(0)
        text_encoder_config = RobertaSeriesConfig(
            hidden_size=32,
            project_dim=32,
            intermediate_size=37,
            layer_norm_eps=1e-05,
            num_attention_heads=4,
            num_hidden_layers=5,
            vocab_size=5002,
        )
        text_encoder = RobertaSeriesModelWithTransformation(text_encoder_config).eval()
        components["text_encoder"] = text_encoder
        alt_pipe = AltDiffusionPipeline(**components)
        alt_pipe.set_progress_bar_config(disable=None)
        inputs = self.get_dummy_inputs()
        inputs["prompt"] = "A photo of an astronaut"
        output = alt_pipe(**inputs)
        image = output.images
        image_slice = image[0, -3:, -3:, -1]
        assert image.shape == (1, 64, 64, 3)
        expected_slice = np.array(
            [0.5748162, 0.60447145, 0.48821217, 0.50100636, 0.5431185, 0.45763683, 0.49657696, 0.48132733, 0.47573093]
        )
        assert np.abs(image_slice.flatten() - expected_slice).max() < 0.01

    def test_alt_diffusion_pndm(self):
        components = self.get_dummy_components()
        components["scheduler"] = PNDMScheduler(skip_prk_steps=True)
        paddle.seed(0)
        text_encoder_config = RobertaSeriesConfig(
            hidden_size=32,
            project_dim=32,
            intermediate_size=37,
            layer_norm_eps=1e-05,
            num_attention_heads=4,
            num_hidden_layers=5,
            vocab_size=5002,
        )
        text_encoder = RobertaSeriesModelWithTransformation(text_encoder_config).eval()
        components["text_encoder"] = text_encoder
        alt_pipe = AltDiffusionPipeline(**components)
        alt_pipe.set_progress_bar_config(disable=None)
        inputs = self.get_dummy_inputs()
        output = alt_pipe(**inputs)
        image = output.images
        image_slice = image[0, -3:, -3:, -1]
        assert image.shape == (1, 64, 64, 3)
        expected_slice = np.array(
            [0.51605093, 0.5707241, 0.47365507, 0.50578886, 0.5633877, 0.4642503, 0.5182081, 0.48763484, 0.49084237]
        )
        assert np.abs(image_slice.flatten() - expected_slice).max() < 0.01


@slow
@require_paddle_gpu
class AltDiffusionPipelineIntegrationTests(unittest.TestCase):
    def tearDown(self):
        super().tearDown()
        gc.collect()
        paddle.device.cuda.empty_cache()

    def test_alt_diffusion(self):
        alt_pipe = AltDiffusionPipeline.from_pretrained("BAAI/AltDiffusion", safety_checker=None)
        alt_pipe.set_progress_bar_config(disable=None)
        prompt = "A painting of a squirrel eating a burger"
        generator = paddle.Generator().manual_seed(0)
        output = alt_pipe([prompt], generator=generator, guidance_scale=6.0, num_inference_steps=20, output_type="np")
        image = output.images
        image_slice = image[0, -3:, -3:, -1]
        assert image.shape == (1, 512, 512, 3)
        expected_slice = np.array([0.101, 0.08, 0.0794, 0.0885, 0.0843, 0.0762, 0.0769, 0.0729, 0.0586])
        assert np.abs(image_slice.flatten() - expected_slice).max() < 0.01

    def test_alt_diffusion_fast_ddim(self):
        scheduler = DDIMScheduler.from_pretrained("BAAI/AltDiffusion", subfolder="scheduler")
        alt_pipe = AltDiffusionPipeline.from_pretrained("BAAI/AltDiffusion", scheduler=scheduler, safety_checker=None)
        alt_pipe.set_progress_bar_config(disable=None)
        prompt = "A painting of a squirrel eating a burger"
        generator = paddle.Generator().manual_seed(0)
        output = alt_pipe([prompt], generator=generator, num_inference_steps=2, output_type="numpy")
        image = output.images
        image_slice = image[0, -3:, -3:, -1]
        assert image.shape == (1, 512, 512, 3)
        expected_slice = np.array([0.4019, 0.4052, 0.381, 0.4119, 0.3916, 0.3982, 0.4651, 0.4195, 0.5323])
        assert np.abs(image_slice.flatten() - expected_slice).max() < 0.01
