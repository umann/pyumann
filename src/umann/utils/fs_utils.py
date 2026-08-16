"""Filesystem/path utility functions for the project.

This module focuses on repository- and project-root related path helpers.
"""

# all annotations are stored as strings and not evaluated at runtime, which can provide a minor performance improvement
from __future__ import annotations

import os
import re
import stat
import subprocess
import typing as t
from functools import lru_cache
from hashlib import md5

from munch import Munch

from umann.constant import SLASH, SLASHB
from umann.platform import vol_type
from umann.utils.data_utils import listify
from umann.utils.log_utils import setup_package_logger

_logger = setup_package_logger()

if t.TYPE_CHECKING:
    from pathlib import Path


PATH_RE0 = r"(?=/)(?P<dir>.*/)(?P<bas>[^/]+?)(?P<ext>(?:[.][^./]*)?)"
VOL_RE0 = FULLPATH_PATTERN = dict(
    win=r"(?P<vol>[A-Z]:)",
    unx=r"(?P<vol>(?:/mnt/[a-z])?)",
)[vol_type()]

FULLPATH_PATTERN = re.compile(rf"^{VOL_RE0}{PATH_RE0}$")
DIR_PATTERN = re.compile(rf"^{VOL_RE0}" + r"(?P<dir>/.*)$")

# EXCLUDE_RE patterns converted to .gitignore format:
# $Recycle.Bin/
# Config.Msi/
# Documents and Settings/
# PerfLogs/
# Program Files/
# Program Files (x86)/
# ProgramData/
# Recovery/
# System Volume Information/
# Windows/
# DumpStack.log.tmp
# hiberfil.sys
# pagefile.sys
# swapfile.sys
# .bzvol/
# Users/All Users/
# Users/Default/
# Users/Default User/
# Users/Public/
# Users/*/.aws/
# Users/*/.azure/
# Users/*/.cache/
# Users/*/.dbus-keyrings/
# Users/*/.docker/
# Users/*/.ms-ad/
# Users/*/.pylint.d/
# Users/*/.virtualenvs/
# Users/*/.vscode/
# Users/*/AppData/
# Users/*/Muse Hub/
# Users/*/ntuser.dat*
# usr/local/cache/

# EXCLUDE_RE = re.compile(
#     r"""
# ^/mnt/[a-z]/(?:                                   # /mnt/c/...
#     \$Recycle\.Bin
#   | Config\.Msi
#   | Documents\ and\ Settings
#   | PerfLogs
#   | Program\ Files
#   | Program\ Files\ \(x86\)
#   | ProgramData
#   | Recovery
#   | System\ Volume\ Information
#   | Windows
#   | DumpStack\.log\.tmp
#   | (?:hiberfil|pagefile|swapfile)\.sys
#   | \.bzvol
#   | Users/(?:                                     # /mnt/c/Users/...
#         All\ Users
#       | Default
#       | Default\ User
#       | Public
#       | [^/]+/(?:                                 # /mnt/c/Users/<user>/...
#             \.(?:aws|azure|cache|dbus-keyrings|docker|ms-ad|pylint\.d|virtualenvs|vscode)
#           | AppData
#           | Muse\ Hub
#           | ntuser\.dat[^/]*
#         )
#     )
#   | usr/local/cache
# )(?:/|$)                                          # stop at dir boundary
# """,
#     re.X | re.I,
# )


# def uabspath_expanduser(path: str) -> str:
#     """Return the absolute path with user home expanded, slashes internally."""
#     return volume_convert(os.path.abspath(os.path.expanduser(path)))


class NotARegularFileError(OSError):
    """Exception raised when a given path is not a regular file."""


def urelpath(path: str) -> str:
    """Return the path relative to the current working directory, slashes internally."""
    return volume_convert(os.path.relpath(path))


def urealpath(path: str) -> str:
    """Return the real path with symlinks resolved, slashes internally."""
    end = SLASH if str(path).endswith(SLASH) else ""
    return volume_convert(os.path.realpath(path)) + end


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
    # _logger.debug(f"Calculating MD5 for file: {fname}")
    hash_md5 = md5()
    # Use 1MB chunks for better throughput on large files (vs 8KB default)
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            hash_md5.update(chunk)
    ret = hash_md5.hexdigest()
    _logger.debug(f"Calculated MD5 for file: {fname}: {ret}")
    return ret


def volume_convert(fname: t.Any) -> t.Any:
    """Convert volume paths to os-compatible paths.

    - If ``fname`` is not a string, return it unchanged (e.g., booleans in config).
    - Normalize backslashes to forward slashes for portability.
    - Map Linux ``/mnt/<drive>/`` to Windows ``<Drive>:/`` on Windows, and vice versa on Unix.
    """
    if not isinstance(fname, str):
        return fname
    if re.search(r"^(?:/mnt/[a-zA-Z]/|[a-zA-Z]:[/\\])", fname):
        fname = fname.replace(SLASHB, SLASH)
        if vol_type() == "win":
            fname = re.sub(r"^/mnt/([a-zA-Z])/", lambda m: f"{m.group(1).upper()}:/", fname)
        else:
            fname = re.sub(r"^([a-zA-Z]):/", lambda m: f"/mnt/{m.group(1).lower()}/", fname)
    return fname


def iter_files(
    dirs_and_files: t.Iterable[str],
    *,
    fnmatch: str | None = None,
    gitignore: str | None = None,
    include_md5: bool = False,
) -> t.Iterator[Munch[t.Literal["fullpath", "size", "mtime"], str | int | float]]:
    """Yield file attributes by calling bin/iter_dir_to_csv.

    Args:
        dirs_and_files: Iterable of paths (files or directories).
        fnmatch: Optional shell-style glob applied to the basename.
        gitignore: Path to gitignore-style patterns file.
        include_md5: If True, include MD5 hash in output (adds 'md5' key to Munch).

    Yields:
        Munch with keys: fullpath, size, mtime (and optionally md5).
    """
    # Build command
    cmd = [project_root("bin/iter_dir_to_csv")]
    if include_md5:
        cmd.append("--md5")
    if fnmatch:
        cmd.extend(["--fnmatch", fnmatch])
    if gitignore:
        cmd.extend(["--gitignore", gitignore])

    # Add all paths
    cmd.extend(listify(dirs_and_files))

    ret = []
    # Execute and parse CSV output
    try:
        _logger.debug(f"{cmd=}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        _logger.debug(f"{len(result.stdout)=}")
        for line in result.stdout.splitlines():
            # "/mnt/f/photos/1",61352,1740251823.1235
            fullpath, size_str, mtime_str = re.findall(r'^"(.*)",(.*),(.*)$', line)[0]
            try:
                size = int(size_str)
                mtime = float(mtime_str)
            except ValueError:
                _logger.warning(f"Skipping row with invalid size/mtime: {line}")
                continue
            if size < 0:
                _logger.warning(f"Skipping row with of nonexistent file: {line}")
                continue
            result_munch = Munch(get_file_attrs(fullpath, dry=True, is_abs=True) | Munch(size=size, mtime=mtime))
            ret.append(result_munch)
        _logger.debug(f"loop end {len(ret)=}")
    except subprocess.CalledProcessError as e:
        _logger.error(f"iter_dir_to_csv failed: {e.stderr}")
        raise
    except FileNotFoundError:
        _logger.error(f"iter_dir_to_csv executable not found at {cmd[0]}")
        raise
    return ret


def get_file_attrs(
    fname: str, dry: bool = False, is_abs: bool = False
) -> Munch[t.Literal["vol", "dir", "bas", "ext", "size", "mtime"], str | int | float]:
    """return vol, dir, bas, ext, size, mtime; last 2 None if does not exist OR missing if dry
    raise if exists but not regular file
    """
    assert not dry or is_abs
    abs_path = fname if is_abs else urealpath(fname)
    if match := FULLPATH_PATTERN.search(abs_path):
        ret = Munch(match.groupdict())
    else:
        raise ValueError(f"Cannot parse volume, dir, bas, ext from {fname=} ({abs_path=})")
    if not dry:
        if isinstance(fname, os.stat_result):
            fstat = fname
            fname = fstat.path
        else:
            fstat = os.stat(fname)  # raises FileNotFoundError
        if not stat.S_ISREG(fstat.st_mode):
            raise NotARegularFileError(f"Not a regular file: {fname}")
        ret |= dict(size=fstat.st_size, mtime=fstat.st_mtime)
    return ret


def split_path(fname: str | t.Iterable[str], is_dir: bool = False) -> Munch[str, str] | list[Munch[str, str]]:
    if not isinstance(fname, str):
        return [split_path(f) for f in fname]
    if is_dir:
        fname = fname.rstrip(SLASH) + SLASH
        pattern = DIR_PATTERN
    else:
        pattern = FULLPATH_PATTERN
    if match := pattern.search(abs_path := urealpath(fname)):
        return Munch(match.groupdict())

    raise ValueError(f"Cannot parse {list(pattern.groupindex)} from {is_dir=} fname={fname!r} (abs_path={abs_path!r})")


def get_dry_file_attrs(
    fname: str,
) -> tuple[str, str, str, str]:  # Munch[t.Literal["vol", "dir", "bas", "ext", "size", "mtime"], t.Any]:
    """return vol, dir, bas, ext
    Does not check physical existence
    """
    if match := FULLPATH_PATTERN.search(abs_path := urealpath(fname)):
        return tuple(match.groups())
        # return Munch(match.groupdict())
    raise ValueError(f"Cannot parse volume, dir, bas, ext from {fname=} ({abs_path=})")


def get_dry_dir_attrs(dname: str) -> tuple[str, str]:
    """return (vol, dir) from dname as fullpath dir name
    Does not check physical existence
    """
    if match := DIR_PATTERN.search(abs_path := urealpath(dname).rstrip(SLASHB) + SLASHB):
        return tuple(match.groups())
    raise ValueError(f"Cannot parse volume, from {dname=} ({abs_path=})")


def read_file(fname: str) -> str:
    with open(fname, "r", encoding="utf-8") as f:
        return f.read()
