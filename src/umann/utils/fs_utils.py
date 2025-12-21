"""Filesystem/path utility functions for the project.

This module focuses on repository- and project-root related path helpers.
"""

# all annotations are stored as strings and not evaluated at runtime, which can provide a minor performance improvement
from __future__ import annotations

import os
import re
import typing as t
from functools import lru_cache
from hashlib import md5

if t.TYPE_CHECKING:
    from pathlib import Path

SLASH = "/"
SLASHB = "\\"


# def uabspath_expanduser(path: str) -> str:
#     """Return the absolute path with user home expanded, slashes internally."""
#     return volume_convert(os.path.abspath(os.path.expanduser(path)))


def urelpath(path: str) -> str:
    """Return the path relative to the current working directory, slashes internally."""
    return volume_convert(os.path.relpath(path))


def urealpath(path: str) -> str:
    """Return the real path with symlinks resolved, slashes internally."""
    return volume_convert(os.path.realpath(path))


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
    ret = urealpath(os.path.join(*parts))
    if relative or as_module:
        ret = urelpath(ret)
    if as_module:
        ret = ret.removesuffix(".py").replace(SLASH, ".").removeprefix("src.")
    return ret


def md5_file(fname: str) -> str:
    hash_md5 = md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def volume_convert(fname: str) -> str:
    """Convert volume paths to os-compatible paths."""
    fname = fname.replace(SLASHB, SLASH)
    if isinstance(fname, str):
        if vol_type() == "win":
            fname = re.sub(r"^/mnt/([a-zA-Z])/", lambda m: f"{m.group(1).upper()}:/", fname)
        else:
            fname = re.sub(r"^([a-zA-Z]):/", lambda m: f"/mnt/{m.group(1).lower()}/", fname)
    return fname


@lru_cache
def vol_type() -> t.Literal["win", "unx"]:
    """Return the volume type of the current OS."""
    return "win" if os.name + "" == "nt" else "unx"
