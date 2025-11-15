"""Filesystem/path utility functions for the project.

This module focuses on repository- and project-root related path helpers.
"""

import os
import typing as t  # pylint: disable=unused-import
from functools import lru_cache

from click import Path


@lru_cache
def project_root(file: str | Path | None = None, *, relative: bool = False, as_module: bool = False) -> str:
    """Return the absolute or relative project root directory.

    If ``file`` is provided, its path is appended relative to the project root.

    Args:
        file: Optional path (relative to project root) to append.
        relative: If True, return a path relative to the current working directory.
        as_module: If True, return the path in module notation
            (dots instead of slashes, no .py suffix).

    Returns:
        The project root path (optionally joined with ``file``).
    """
    # Go up from this file to src/, then one more level to the repository root
    parts = [os.path.dirname(__file__), "..", "..", ".."]
    if file:
        parts.append(str(file))
    ret = os.path.realpath(os.path.join(*parts))
    if relative or as_module:
        ret = os.path.relpath(ret, os.getcwd())
    if as_module:
        ret = ret.removesuffix(".py").replace(os.path.sep, ".").removeprefix("src.")
    return ret
