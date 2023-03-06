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

import os
import sys
import unittest

git_repo_path = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
sys.path.append(os.path.join(git_repo_path, "utils"))
import check_dummies
from check_dummies import (
    create_dummy_files,
    create_dummy_object,
    find_backend,
    read_init,
)

check_dummies.PATH_TO_PPDIFFUSERS = os.path.join(git_repo_path, "src", "ppdiffusers")


class CheckDummiesTester(unittest.TestCase):
    def test_find_backend(self):
        simple_backend = find_backend("    if not is_paddle_available():")
        self.assertEqual(simple_backend, "paddle")
        double_backend = find_backend("    if not (is_paddle_available() and is_paddlenlp_available()):")
        self.assertEqual(double_backend, "paddle_and_paddlenlp")
        triple_backend = find_backend(
            "    if not (is_paddle_available() and is_paddlenlp_available() and is_fastdeploy_available()):"
        )
        self.assertEqual(triple_backend, "paddle_and_paddlenlp_and_fastdeploy")

    def test_read_init(self):
        objects = read_init()
        self.assertIn("paddle", objects)
        self.assertIn("paddle_and_paddlenlp", objects)
        self.assertIn("paddle_and_paddlenlp_and_fastdeploy", objects)
        self.assertIn("UNet2DModel", objects["paddle"])
        self.assertIn("StableDiffusionPipeline", objects["paddle_and_paddlenlp"])
        self.assertIn("LMSDiscreteScheduler", objects["paddle_and_scipy"])
        self.assertIn("FastDeployStableDiffusionPipeline", objects["paddle_and_paddlenlp_and_fastdeploy"])

    def test_create_dummy_object(self):
        dummy_constant = create_dummy_object("CONSTANT", "'paddle'")
        self.assertEqual(dummy_constant, "\nCONSTANT = None\n")
        dummy_function = create_dummy_object("function", "'paddle'")
        self.assertEqual(
            dummy_function,
            """
def function(*args, **kwargs):
    requires_backends(function, 'paddle')
""",
        )
        expected_dummy_class = """
class FakeClass(metaclass=DummyObject):
    _backends = 'paddle'

    def __init__(self, *args, **kwargs):
        requires_backends(self, 'paddle')

    @classmethod
    def from_config(cls, *args, **kwargs):
        requires_backends(cls, 'paddle')

    @classmethod
    def from_pretrained(cls, *args, **kwargs):
        requires_backends(cls, 'paddle')
"""
        dummy_class = create_dummy_object("FakeClass", "'paddle'")
        self.assertEqual(dummy_class, expected_dummy_class)

    def test_create_dummy_files(self):
        expected_dummy_pypaddle_file = """# This file is autogenerated by the command `make fix-copies`, do not edit.
from ..utils import DummyObject, requires_backends


CONSTANT = None


def function(*args, **kwargs):
    requires_backends(function, ["paddle"])


class FakeClass(metaclass=DummyObject):
    _backends = ["paddle"]

    def __init__(self, *args, **kwargs):
        requires_backends(self, ["paddle"])

    @classmethod
    def from_config(cls, *args, **kwargs):
        requires_backends(cls, ["paddle"])

    @classmethod
    def from_pretrained(cls, *args, **kwargs):
        requires_backends(cls, ["paddle"])
"""
        dummy_files = create_dummy_files({"paddle": ["CONSTANT", "function", "FakeClass"]})
        self.assertEqual(dummy_files["paddle"], expected_dummy_pypaddle_file)
