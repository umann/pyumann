"""Manage app configuration loading and access."""

import os
import typing as t
from functools import lru_cache

import yaml

from umann.utils.data_utils import get_multi
from umann.utils.fs_utils import project_root


@lru_cache
def load_config() -> dict[str, t.Any]:
    config_path = os.getenv("PYUMANN_CONFIG") or project_root("config.yaml")
    with open(config_path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    return config


def get_config(path: str | None = None, default: t.Any | None = None) -> dict[str, t.Any]:
    config = load_config()
    return get_multi(config, path, default) if path else config
