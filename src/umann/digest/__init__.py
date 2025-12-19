"""Soul digest module for extracting metadata-free content from media files."""

# Import plugins to auto-register them
from umann.digest.soul import plugins  # noqa: F401
from umann.digest.soul import Soul, extract_soul

__all__ = ["Soul", "extract_soul"]
