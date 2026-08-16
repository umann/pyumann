"""Platform detection utilities."""

import os
import typing as t
from functools import lru_cache


@lru_cache
def vol_type() -> t.Literal["win", "unx"]:
    """Return the volume type of the current OS."""
    return "win" if os.name + "" == "nt" else "unx"
