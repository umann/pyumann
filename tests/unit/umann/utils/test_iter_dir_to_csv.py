"""Tests for the iter_dir_to_csv CLI helper functions."""

import importlib.util
from pathlib import Path


def _load_iter_dir_to_csv_module():
    """Load the script as a module for direct function-level testing."""
    module_path = Path(__file__).resolve().parents[4] / "bin" / "iter_dir_to_csv.py"
    spec = importlib.util.spec_from_file_location("iter_dir_to_csv", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_matches_filename_filter_jpg():
    """fnmatch filtering should match only the basename pattern."""
    module = _load_iter_dir_to_csv_module()
    test_files = [
        "image1.jpg",
        "image2.png",
        "image3.jpg",
        "document.pdf",
    ]

    filtered_files = [f for f in test_files if module.matches_filename_filter(f, "*.jpg")]

    assert filtered_files == [
        "image1.jpg",
        "image3.jpg",
    ], f"Expected ['image1.jpg', 'image3.jpg'], got {filtered_files}"
