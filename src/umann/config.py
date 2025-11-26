"""Manage app configuration loading and access."""

import os
import typing as t
from functools import lru_cache
from pathlib import Path

from munch import Munch, munchify

from umann.utils.data_utils import get_multi, merge_struct, recurse
from umann.utils.fs_utils import project_root, volume_convert
from umann.utils.yaml_utils import yaml_safe_load_file


def _load_config(config_path: str, must_exist: bool = True, merge_into: dict = None) -> Munch[str, t.Any]:
    config_dict = yaml_safe_load_file(config_path, **({} if must_exist else {"default": {}}))
    if merge_into is not None:
        config_dict = merge_struct(merge_into, config_dict)
    return munchify(config_dict)


@lru_cache
def load_config() -> Munch[str, t.Any]:
    config_path = os.getenv("PYUMANN_CONFIG") or project_root("config.yaml")
    config = _load_config(config_path)
    if config_override_path := os.getenv("PYUMANN_CONFIG_OVERRIDE"):
        config = _load_config(config_override_path, merge_into=config)
    else:
        config_override_path = str(Path.home() / ".pyumann_config_override.yaml")
        config = _load_config(config_override_path, merge_into=config, must_exist=False)
    config = recurse(config, volume_convert)
    return config


def get_config(datapath: str | None = None, default: t.Any | None = None) -> Munch[str, t.Any]:
    config = load_config()
    return get_multi(config, datapath, default) if datapath else config
