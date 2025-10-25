"""Filesystem/path utility functions for the project.

This module focuses on repository- and project-root related path helpers.
"""

from __future__ import annotations

import os
import typing as t
from functools import lru_cache


@lru_cache
def project_root(file: t.Optional[str] = None, *, relative: bool = False) -> str:
    """Return the absolute or relative project root directory.

    If ``file`` is provided, its path is appended relative to the project root.

    Args:
        file: Optional path (relative to project root) to append.
        relative: If True, return a path relative to the current working directory.

    Returns:
        The project root path (optionally joined with ``file``).
    """
    # Go up from this file to src/, then one more level to the repository root
    parts = [os.path.dirname(__file__), "..", "..", ".."]
    if file:
        parts.append(file)
    ret = os.path.realpath(os.path.join(*parts))
    return os.path.relpath(ret) if relative else ret
