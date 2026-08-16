"""Unit tests for metadata cache handling."""

# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import ANY, Mock, patch

import pytest
from munch import Munch

from umann.metadata import memoize

pytestmark = pytest.mark.unit


def test_handle_metadata_converts_extractor_exception_to_metadata():
    """Extractor failures are returned and cached as metadata dictionaries."""
    extractor = Mock(side_effect=ValueError("invalid sidecar line"))
    res = Munch(fname="test.jpg", func=extractor)

    with (
        patch.object(memoize, "get_config", return_value=[]),
        patch.object(memoize, "has_metadata_ext", return_value=True),
        patch.object(memoize, "_handle_content_metadata") as handle_content,
        patch.object(memoize, "_handle_file_metadata") as handle_file,
    ):
        metadata = memoize._handle_metadata(Mock(), res, res.fname)

    assert metadata == {"Error": "ValueError: invalid sidecar line"}
    assert res.file_metadata == {}
    assert res.content_metadata == metadata
    handle_content.assert_called_once_with(ANY, res)
    handle_file.assert_called_once_with(ANY, res)


def test_handle_metadata_imports_configured_sidecar_engine():
    """Configured sidecar engines need not have been imported by another module."""
    extractor = Mock(return_value={"XMP:Label": "keep"})
    module = SimpleNamespace(get_sidecar_metadata=extractor)
    res = Munch(fname="test.sidecar", func=Mock())

    with (
        patch.object(memoize, "get_config", return_value=[{"fnmatch": "*.sidecar", "engine": "sidecar"}]),
        patch.object(memoize, "has_metadata_ext", return_value=False),
        patch.object(memoize.importlib, "import_module", return_value=module) as import_module,
        patch.object(memoize, "_handle_content_metadata"),
        patch.object(memoize, "_handle_file_metadata"),
    ):
        metadata = memoize._handle_metadata(Mock(), res, res.fname)

    import_module.assert_called_once_with("umann.metadata.sidecar")
    extractor.assert_called_once_with("test.sidecar")
    assert metadata == {"XMP:Label": "keep"}


def test_handle_metadata_contains_missing_sidecar_engine_error():
    """A missing configured engine must not abort processing the remaining files."""
    res = Munch(fname="test.sidecar", func=Mock())

    with (
        patch.object(memoize, "get_config", return_value=[{"fnmatch": "*.sidecar", "engine": "sidecar"}]),
        patch.object(memoize, "has_metadata_ext", return_value=False),
        patch.object(memoize.importlib, "import_module", side_effect=ModuleNotFoundError("no sidecar engine")),
        patch.object(memoize, "_handle_content_metadata"),
        patch.object(memoize, "_handle_file_metadata"),
    ):
        metadata = memoize._handle_metadata(Mock(), res, res.fname)

    assert metadata == {"Error": "ModuleNotFoundError: no sidecar engine"}
