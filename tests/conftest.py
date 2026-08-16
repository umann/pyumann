"""Root conftest.py with shared fixtures across all test types."""

import os
import tempfile
from pathlib import Path

import pytest

from .utils import get_test_data_dir

# This runs while pytest loads conftest, before it imports test modules. Keeping
# the override directory alive for the process ensures SQLite can use WAL files.
_db_tmpdir = tempfile.TemporaryDirectory(prefix="pyumann-tests-")  # pylint: disable=consider-using-with
_db_override = Path(_db_tmpdir.name) / "config.override.yaml"
_db_override.write_text(
    f"memoize:\n  db:\n    path: {Path(_db_tmpdir.name) / 'md.sqlite'}\n",
    encoding="utf-8",
)
os.environ["PYUMANN_CONFIG_OVERRIDE"] = str(_db_override)


@pytest.fixture
def test_data_dir():
    """Return path to the test data directory."""
    return get_test_data_dir()
