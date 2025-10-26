"""ExifTool interface for metadata operations.

This module provides a high-level interface to ExifTool for reading and writing
metadata in image files. It includes both command-line and programmatic interfaces.
"""

import copy
import re
import typing as t
from contextlib import suppress
from functools import lru_cache
from pathlib import Path

import click
import exiftool
import yaml
from munch import Munch, munchify

from umann.metadata.chk_tz import TzMismatchError, check_timezone_consistency
from umann.utils.data_utils import get_multi, pop_multi, set_multi
from umann.utils.fs_utils import project_root

TYPE_NAME_TO_CLASS = {"int": int, "float": float}


@lru_cache
def default() -> dict[str, t.Any]:
    """Get default ExifTool configuration.

    Returns:
        Default configuration dictionary with common arguments and config file path.
        The configuration is cached for performance.
    """
    return {"common_args": ["-struct", "-G0"], "config_file": project_root(".ExifTool_config")}


def helper(**kwargs) -> exiftool.ExifToolHelper:
    """Create an ExifTool helper with default configuration.

    Args:
        **kwargs: Additional configuration to override defaults.

    Returns:
        Configured ExifTool helper instance.
    """
    return exiftool.ExifToolHelper(**(default() | kwargs))


def cool_in(tags: dict[str, t.Any]) -> dict[str, t.Any]:
    """Apply cool (relaxed) input transformations to metadata."""
    # Example transformation: combine GPSLatitude and GPSLongitude into GPSPosition
    tags = tags.copy()
    for prefix in ("Composite:", "EXIF:"):
        if pos := tags.pop(f"{prefix}GPSPosition", None):
            tags[f"{prefix}GPSLatitude"], tags[f"{prefix}GPSLongitude"] = map(float, re.split(r"\s*[,;]\s*", pos))
    for key in ("XMP:Subject", "IPTC:Keywords", "Composite:Keywords"):
        if (keywords := tags.pop(key, None)) and isinstance(keywords, str):
            tags[key] = [kw.strip() for kw in re.split(r"\s*[,;]\s*", keywords) if kw.strip()]
    return tags


def simple_out(metadata: dict[str, t.Any]) -> dict[str, t.Any]:
    """Apply simple output transformations to metadata."""

    metadata = copy.deepcopy(metadata)
    md_yaml = munchify(read_metadata_yaml())
    for path, val_to_del in md_yaml._del.items():  # pylint: disable=protected-access
        pop_multi(metadata, path, default=None, pop_list_items=True, val_to_del=val_to_del)

    return metadata


def check(metadata: dict[str, t.Any]) -> dict[str, t.Any]:
    """Check metadata for consistency across equivalent fields.

    Args:
        metadata: Metadata dictionary to check.

    Returns:
        The same metadata dictionary if checks pass.

    Raises:
        ValueError: If equivalent fields have different values.
    """
    md_yaml = munchify(read_metadata_yaml())
    for group in md_yaml._eq:  # pylint: disable=protected-access
        if len(set(i for i in (get_multi(metadata, path, None) for path in group) if i is not None)) > 1:
            # Build error dict with non-None values
            error_dict = {}
            for path in group:
                val = get_multi(metadata, path, None)
                if val is not None:
                    error_dict[path] = val
            raise ValueError(error_dict)
    return metadata


def cool_out(metadata: dict[str, t.Any]) -> dict[str, t.Any]:
    """
    Convert numeric fields to Python numeric types, size to [width]x[height], GPSPosition to signed %8f comma separated
    """
    metadata = copy.deepcopy(metadata)
    md_yaml = munchify(read_metadata_yaml())

    def numberify(data, path, type_class):
        if (val := get_multi(data, path, None)) is not None and val != "":
            with suppress(ValueError):
                set_multi(data, path, type_class(val))

    for type_name, paths in md_yaml._type.items():  # pylint: disable=protected-access
        type_class = TYPE_NAME_TO_CLASS.get(type_name, type_name)
        for path in paths:
            if ".[]." in path:
                path_before, path_after = path.split(".[].")
                for lst in get_multi(metadata, path_before, []):
                    numberify(lst, path_after, type_class)
            else:
                numberify(metadata, path, type_class)

    convert = dict(
        x_separated=lambda val: "x".join(val.split()),
        signed_8f_comma_separated=lambda val: ", ".join(f"{float(v):+.8f}" for v in val.split()),
        flatten_if_not_multiple=lambda val: val[0] if isinstance(val, list) and len(val) == 1 else val,
    )
    for key, func in convert.items():
        for path in get_multi(md_yaml, f"_convert.{key}", []):
            if (val := get_multi(metadata, path, None)) is not None:
                set_multi(metadata, path, func(val))

    return metadata


TRANSFORMATORS = dict(cool_in=cool_in, simple_out=simple_out, cool_out=cool_out, check=check)


def transform_metadata(metadata: dict[str, t.Any], /, transformations: t.Iterable[str] = ()) -> dict[str, t.Any]:
    """Transform metadata output as needed.

    Args:
        metadata: The original metadata dictionary.
        transformations: A list of transformation types to apply.

    Returns:
        The transformed metadata dictionary.
    """

    for transformation, func in TRANSFORMATORS.items():
        if transformation in transformations:
            metadata = func(metadata)
    return metadata


@lru_cache
def read_metadata_yaml() -> Munch:
    """Load and parse the metadata tags YAML configuration file.

    Returns:
        A Munch object containing the parsed YAML configuration for metadata transformations.
        The result is cached for performance.
    """
    with open(Path(__file__).parent / "metadata_tags.yaml", encoding="utf-8") as infh:
        return munchify(yaml.safe_load(infh))


def get_metadata_multi(fnames: t.Iterable[str], /, **kwargs) -> dict[str, dict[str, t.Any]]:
    """Get metadata for multiple files."""
    fnames = list(fnames)  # not to consume it if iterator/generator
    with helper() as extl:
        return dict(zip(fnames, [transform_metadata(md, **kwargs) for md in extl.get_metadata(fnames)]))


def get_metadata(fname: str, /, **kwargs) -> dict[str, t.Any]:
    """Get metadata for one file."""
    with helper() as extl:
        return transform_metadata(extl.get_metadata(fname)[0], **kwargs)


def set_metadata(fname_s: str | t.Iterable[str], tags, /, **kwargs):
    """Set metadata for one or multiple files."""
    with helper() as extl:
        return extl.set_tags(fname_s, transform_metadata(tags, **kwargs))


@click.command()
@click.option("--dictify", "-d", is_flag=True, help="Use dict[fname, metadata] output format even if 1 fname is given")
@click.option("--set", "tags_yaml", help="YAML or JSON format string of tags to set")
@click.option("--chk-tz", is_flag=True, help="Check if timezone tags are consistent with GPS coordinates")
@click.option(
    "--transform",
    "transformations",
    multiple=True,
    type=click.Choice(list(TRANSFORMATORS) + ["ALL"]),
    help="Do transformations on data  [Multiple]",
)
@click.argument("fnames", nargs=-1, required=True)
def main(**kwargs):
    """Command-line interface for ExifTool metadata operations.

    This function provides a command-line interface for reading and writing
    metadata using ExifTool. It supports both single and multiple file operations,
    and can output metadata in YAML format or set metadata from YAML/JSON input.
    """
    fnames = kwargs.pop("fnames")
    transformations = kwargs.get("transformations", ())
    if "ALL" in transformations:
        transformations = tuple(TRANSFORMATORS.keys())
    tr_kwargs = dict(transformations=transformations)
    multi = len(fnames) != 1 or kwargs.get("dictify", False)
    if tags_yaml := kwargs.pop("tags_yaml"):
        tags = yaml.safe_load(tags_yaml)
        set_metadata(fnames, tags, **tr_kwargs)
    else:
        # Fetch metadata
        metadata_map = (
            get_metadata_multi(fnames, **tr_kwargs) if multi else {fnames[0]: get_metadata(fnames[0], **tr_kwargs)}
        )

        # If --chk-tz provided, perform checks and raise on issues
        if kwargs.get("chk_tz", False):
            errors = []
            for fname, md in metadata_map.items():
                try:
                    check_timezone_consistency(md)
                except TzMismatchError as e:
                    errors.append(f"{fname}: {e}")
            if errors:
                raise click.ClickException("\n".join(["Timezone consistency check failed:"] + errors))
            # Success: no output required
            return

        # Default: print metadata
        print(
            yaml.safe_dump(
                metadata_map if multi else next(iter(metadata_map.values())), sort_keys=False, allow_unicode=True
            ).strip()
        )


# entry point `et` is defined in pyproject.toml
if __name__ == "__main__":
    main()
