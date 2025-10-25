"""Integration test configuration and fixtures."""

import shutil
from pathlib import Path

import pytest


def pytest_runtest_setup(item):
    """Skip integration tests if exiftool is not installed."""
    if "integration" in item.nodeid:
        if shutil.which("exiftool") is None:
            pytest.skip("exiftool not installed")


@pytest.fixture
def sample_image(test_data_dir) -> Path:
    """Provide path to sample test image."""
    return test_data_dir / "kalaka.jpg"
