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

from ppdiffusers import (
    AutoencoderKL,
    DDIMScheduler,
    DiTPipeline,
    DPMSolverMultistepScheduler,
    Transformer2DModel,
)
from ppdiffusers.utils import load_numpy, slow
from ppdiffusers.utils.testing_utils import require_paddle_gpu


class DiTPipelineFastTests(PipelineTesterMixin, unittest.TestCase):
    pipeline_class = DiTPipeline
    test_cpu_offload = False

    def get_dummy_components(self):
        paddle.seed(0)
        transformer = Transformer2DModel(
            sample_size=16,
            num_layers=2,
            patch_size=4,
            attention_head_dim=8,
            num_attention_heads=2,
            in_channels=4,
            out_channels=8,
            attention_bias=True,
            activation_fn="gelu-approximate",
            num_embeds_ada_norm=1000,
            norm_type="ada_norm_zero",
            norm_elementwise_affine=False,
        )
        vae = AutoencoderKL()
        scheduler = DDIMScheduler()
        components = {"transformer": transformer.eval(), "vae": vae.eval(), "scheduler": scheduler}
        return components

    def get_dummy_inputs(self, seed=0):
        generator = paddle.Generator().manual_seed(seed)

        inputs = {"class_labels": [1], "generator": generator, "num_inference_steps": 2, "output_type": "numpy"}
        return inputs

    def test_inference(self):
        components = self.get_dummy_components()
        pipe = self.pipeline_class(**components)
        pipe.set_progress_bar_config(disable=None)
        inputs = self.get_dummy_inputs()
        image = pipe(**inputs).images
        image_slice = image[(0), -3:, -3:, (-1)]
        self.assertEqual(image.shape, (1, 16, 16, 3))
        expected_slice = np.array([0.438, 0.4141, 0.5159, 0.0, 0.4282, 0.668, 0.5485, 0.2545, 0.6719])
        max_diff = np.abs(image_slice.flatten() - expected_slice).max()
        self.assertLessEqual(max_diff, 0.001)

    def test_inference_batch_single_identical(self):
        self._test_inference_batch_single_identical(relax_max_difference=True)


@require_paddle_gpu
@slow
class DiTPipelineIntegrationTests(unittest.TestCase):
    def tearDown(self):
        super().tearDown()
        gc.collect()
        paddle.device.cuda.empty_cache()

    def test_dit_256(self):
        generator = paddle.Generator().manual_seed(0)
        pipe = DiTPipeline.from_pretrained("facebook/DiT-XL-2-256")
        pipe.to("gpu")

        words = ["vase", "umbrella", "white shark", "white wolf"]
        ids = pipe.get_label_ids(words)
        images = pipe(ids, generator=generator, num_inference_steps=40, output_type="np").images
        for word, image in zip(words, images):
            expected_image = load_numpy(
                f"https://huggingface.co/datasets/hf-internal-testing/ppdiffusers-images/resolve/main/dit/{word}.npy"
            )
            assert np.abs((expected_image - image).max()) < 0.001

    def test_dit_512_fp16(self):
        pipe = DiTPipeline.from_pretrained("facebook/DiT-XL-2-512", paddle_dtype=paddle.float16)
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config)
        pipe.to("gpu")

        words = ["vase", "umbrella"]
        ids = pipe.get_label_ids(words)
        generator = paddle.Generator().manual_seed(0)
        images = pipe(ids, generator=generator, num_inference_steps=25, output_type="np").images
        for word, image in zip(words, images):
            expected_image = load_numpy(
                f"https://huggingface.co/datasets/hf-internal-testing/ppdiffusers-images/resolve/main/dit/{word}_fp16.npy"
            )
            assert np.abs((expected_image - image).max()) < 0.75