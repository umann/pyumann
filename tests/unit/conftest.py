"""Unit test configuration and fixtures."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_exiftool():
    """Provide a mock ExifTool instance for unit tests."""
    with patch("exiftool.ExifToolHelper") as mock:
        helper = MagicMock()
        mock.return_value.__enter__.return_value = helper
        yield helper
