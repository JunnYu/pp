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

import unittest

import numpy as np
import paddle
from ppdiffusers_test.test_pipelines_common import PipelineTesterMixin

from ppdiffusers import DDIMPipeline, DDIMScheduler, UNet2DModel
from ppdiffusers.utils.testing_utils import require_paddle_gpu, slow


class DDIMPipelineFastTests(PipelineTesterMixin, unittest.TestCase):
    pipeline_class = DDIMPipeline
    test_cpu_offload = False

    def get_dummy_components(self):
        paddle.seed(0)
        unet = UNet2DModel(
            block_out_channels=(32, 64),
            layers_per_block=2,
            sample_size=32,
            in_channels=3,
            out_channels=3,
            down_block_types=("DownBlock2D", "AttnDownBlock2D"),
            up_block_types=("AttnUpBlock2D", "UpBlock2D"),
        )
        scheduler = DDIMScheduler()
        components = {"unet": unet, "scheduler": scheduler}
        return components

    def get_dummy_inputs(self, seed=0):
        generator = paddle.Generator().manual_seed(seed)

        inputs = {"batch_size": 1, "generator": generator, "num_inference_steps": 2, "output_type": "numpy"}
        return inputs

    def test_inference(self):
        components = self.get_dummy_components()
        pipe = self.pipeline_class(**components)
        pipe.set_progress_bar_config(disable=None)
        inputs = self.get_dummy_inputs()
        image = pipe(**inputs).images
        image_slice = image[(0), -3:, -3:, (-1)]
        self.assertEqual(image.shape, (1, 32, 32, 3))
        expected_slice = np.array([1.0, 0.5717, 0.4717, 1.0, 0.0, 1.0, 0.0003, 0.0, 0.0009])
        max_diff = np.abs(image_slice.flatten() - expected_slice).max()
        self.assertLessEqual(max_diff, 0.001)


@slow
@require_paddle_gpu
class DDIMPipelineIntegrationTests(unittest.TestCase):
    def test_inference_cifar10(self):
        model_id = "google/ddpm-cifar10-32"
        unet = UNet2DModel.from_pretrained(model_id)
        scheduler = DDIMScheduler()
        ddim = DDIMPipeline(unet=unet, scheduler=scheduler)
        ddim.set_progress_bar_config(disable=None)
        generator = paddle.Generator().manual_seed(0)
        image = ddim(generator=generator, eta=0.0, output_type="numpy").images
        image_slice = image[(0), -3:, -3:, (-1)]
        assert image.shape == (1, 32, 32, 3)
        expected_slice = np.array([0.1723, 0.1617, 0.16, 0.1626, 0.1497, 0.1513, 0.1505, 0.1442, 0.1453])
        assert np.abs(image_slice.flatten() - expected_slice).max() < 0.01

    def test_inference_ema_bedroom(self):
        model_id = "google/ddpm-ema-bedroom-256"
        unet = UNet2DModel.from_pretrained(model_id)
        scheduler = DDIMScheduler.from_pretrained(model_id)
        ddpm = DDIMPipeline(unet=unet, scheduler=scheduler)
        ddpm.set_progress_bar_config(disable=None)
        generator = paddle.Generator().manual_seed(0)
        image = ddpm(generator=generator, output_type="numpy").images
        image_slice = image[(0), -3:, -3:, (-1)]
        assert image.shape == (1, 256, 256, 3)
        expected_slice = np.array([0.006, 0.0201, 0.0344, 0.0024, 0.0018, 0.0002, 0.0022, 0.0, 0.0069])
        assert np.abs(image_slice.flatten() - expected_slice).max() < 0.01