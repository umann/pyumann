"""Root conftest.py with shared fixtures across all test types."""

import pytest

from .utils import get_test_data_dir


@pytest.fixture
def test_data_dir():
    """Return path to the test data directory."""
    return get_test_data_dir()
