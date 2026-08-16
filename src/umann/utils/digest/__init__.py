"""Soul digest module for extracting metadata-free content from media files."""

# Import plugins to auto-register them
from umann.utils.digest.soul import plugins  # noqa: F401
from umann.utils.digest.soul import Soul, extract_soul

__all__ = ["Soul", "extract_soul"]
