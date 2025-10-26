"""Common utilities for tests."""

from pathlib import Path


def get_test_data_dir() -> Path:
    """Return path to the test data directory.

    This is the single source of truth for test data location,
    used by both unittest TestCases and pytest fixtures.
    """
    return Path(__file__).parent.parent / "fixtures" / "data"
