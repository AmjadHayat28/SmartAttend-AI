"""Fail visibly if installed recognition dependencies cannot load native libraries."""

import importlib

import pytest


@pytest.mark.parametrize("module", ["cv2", "onnxruntime", "insightface.app"])
def test_recognition_runtime_imports(module):
    assert importlib.import_module(module) is not None
