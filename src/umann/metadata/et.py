"""ExifTool interface for metadata operations.

This module provides a high-level interface to ExifTool for reading and writing
metadata in image files. It includes both command-line and programmatic interfaces.
"""

import copy
import glob
import re
import shlex
import sys
import typing as t
from contextlib import suppress
from functools import lru_cache
from pathlib import Path

import click
import exiftool
import yaml
from munch import Munch, munchify

from umann.config import get_config
from umann.metadata import chk_tz as _chk_tz
from umann.metadata.chk_datetime import check_datetime_consistency
from umann.metadata.chk_tz import NoCaptureDateTimeError, NoGpsError, TzMismatchError
from umann.metadata.memoize import get_file_rec
from umann.utils.data_utils import get_multi, pop_multi, set_multi
from umann.utils.encoding_utils import fix_str_encoding
from umann.utils.fs_utils import project_root

TYPE_NAME_TO_CLASS = {"int": int, "float": float}
EXIFTOOL_GROUP = get_config("exiftool.group", "G1")
EXIFTOOL_ARGS = ["-struct", f"-{EXIFTOOL_GROUP}"]


@lru_cache
def default() -> dict[str, t.Any]:
    """Get default ExifTool configuration.

    Returns:
        Default configuration dictionary with common arguments and config file path.
        The configuration is cached for performance.
    """
    return {"common_args": EXIFTOOL_ARGS, "config_file": project_root(".ExifTool_config")}


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


def fix_iptc_encoding(metadata: dict[str, t.Any]) -> dict[str, t.Any]:
    """Fix IPTC encoding issues in metadata dictionary.

    Applies fix_iptc_encoding to all IPTC and MWG string fields.
    """

    if not isinstance(metadata, dict):
        return metadata
    metadata = copy.deepcopy(metadata)

    def fix_recursive(obj: t.Any, key: str = "") -> t.Any:
        if isinstance(obj, dict):
            return type(obj)({k: fix_recursive(v, k) for k, v in obj.items()})
        if isinstance(obj, list):
            return type(obj)(fix_recursive(item, key) for item in obj)
        if isinstance(obj, str) and (key.startswith("IPTC:") or key.startswith("MWG:")):
            return type(obj)(fix_str_encoding(obj))
        return obj

    return fix_recursive(metadata)


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


TRANSFORMATORS = dict(
    cool_in=cool_in,
    simple_out=simple_out,
    cool_out=cool_out,
    check=check,
    fix_iptc_encoding=fix_iptc_encoding,
)


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


def get_metadata_multi(fnames: t.Iterable[str], /, one_by_one: bool = True, **kwargs) -> dict[str, dict[str, t.Any]]:
    """Get metadata for multiple files."""

    if one_by_one:
        ret = {}
        for fname in fnames:
            # print(fname)
            ret[fname] = get_metadata(fname, **kwargs)
        return ret
    with helper() as extl:
        fnames = list(fnames)  # not to consume it if iterator/generator
        transformed = []
        for md in extl.get_metadata(fnames):
            transformed.append(transform_metadata(md, **kwargs))
        return dict(zip(fnames, transformed))
        # return dict(zip(fnames, [transform_metadata(md, **kwargs) for md in extl.get_metadata(fnames)]))


def get_metadata(fname: str, /, **kwargs) -> dict[str, t.Any]:
    """Get metadata for one file."""

    def _get(fname):
        with helper() as extl:
            return transform_metadata(extl.get_metadata(fname)[0], **kwargs)

    try:
        md = get_file_rec(fname, func=_get, cmd=shlex.join(["exiftool", *EXIFTOOL_ARGS]))
    except Exception as e:
        print(f"Error getting metadata for {fname}: {e}", file=sys.stderr)
        raise
    return transform_metadata(md or {}, **kwargs)


def set_metadata(fname_s: str | t.Iterable[str], tags, /, **kwargs):
    """Set metadata for one or multiple files."""
    with helper() as extl:
        return extl.set_tags(fname_s, transform_metadata(tags, **kwargs))


def check_timezone_consistency(metadata: dict[str, t.Any], /, tolerance_in_meters: int = 200) -> None:
    """Public wrapper that normalizes missing-data errors to TzMismatchError.

    This keeps unit-test expectations simple when importing from `umann.metadata.et`.
    The CLI uses the underlying implementation directly to skip files with missing data.
    """
    try:
        return _chk_tz.check_timezone_consistency(metadata, tolerance_in_meters=tolerance_in_meters)
    except (NoCaptureDateTimeError, NoGpsError) as exc:
        raise TzMismatchError(str(exc)) from exc


@click.group()
def cli():
    """ExifTool metadata operations CLI.

    Get metadata: et image.jpg  (or: et get image.jpg)
    Set metadata: et set --tags '{"Key": "value"}' image.jpg
    Check timezone: et chk image.jpg
    """


@cli.command(name="get")
@click.option("--dictify", "-d", is_flag=True, help="Use dict[fname, metadata] output format even if 1 fname is given")
@click.option(
    "--transform",
    "-t",
    "transformations",
    multiple=True,
    type=click.Choice(list(TRANSFORMATORS) + ["ALL"]),
    help="Apply transformations on data [Multiple]",
)
@click.option("--fix-iptc-encoding/--no-fix-iptc-encoding", default=True, help="Fix IPTC encoding issues in metadata")
@click.argument("fnames", nargs=-1, required=True)
def cli_command_get(**kwargs):
    """Get metadata from image files (default command).

    Examples:
        et get image.jpg
        et get *.jpg --transform cool_out
        et get image.jpg --dictify
    """
    cliopt = Munch(kwargs)

    # Expand globs, but preserve raw values when no filesystem match (useful in tests/mocks)
    expanded_fnames: list[str] = []
    for wildcard in cliopt.fnames:
        matches = glob.glob(wildcard)
        expanded_fnames.extend(matches if matches else [wildcard])

    if "ALL" in cliopt.transformations:
        cliopt.transformations = tuple(TRANSFORMATORS.keys())
    if kwargs.get("fix_iptc_encoding"):
        if "fix_iptc_encoding" not in cliopt.transformations:
            cliopt.transformations += ("fix_iptc_encoding",)
    else:
        cliopt.transformations = tuple(t for t in cliopt.transformations if t != "fix_iptc_encoding")
    tr_kwargs = dict(transformations=cliopt.transformations)
    multi = len(expanded_fnames) != 1 or cliopt.dictify

    # Fetch metadata
    metadata_map = get_metadata_multi(expanded_fnames, **tr_kwargs)

    # Print metadata
    output_obj = metadata_map if multi else next(iter(metadata_map.values()))
    print(yaml.safe_dump(output_obj, sort_keys=False, allow_unicode=True).strip())


@cli.command(name="set")
@click.option(
    "--tags",
    "tags_yaml",
    required=True,
    help='YAML or JSON string of tags to set (e.g., \'{"IPTC:Keywords": "tag1, tag2"}\')',
)
@click.option(
    "--transform",
    "transformations",
    multiple=True,
    type=click.Choice(list(TRANSFORMATORS) + ["ALL"]),
    help="Apply input transformations on tags [Multiple]",
)
@click.argument("fnames", nargs=-1, required=True)
def cli_command_set(fnames, tags_yaml, transformations):
    """Set metadata tags in image files.

    Examples:
        et set --tags '{"IPTC:Keywords": "tag1, tag2"}' image.jpg
        et set --tags '{"XMP:Subject": "test"}' *.jpg --transform cool_in
    """
    # Expand globs
    expanded_fnames: list[str] = []
    for wildcard in fnames:
        matches = glob.glob(wildcard)
        expanded_fnames.extend(matches if matches else [wildcard])

    if "ALL" in transformations:
        transformations = tuple(TRANSFORMATORS.keys())
    tr_kwargs = dict(transformations=transformations)

    tags = yaml.safe_load(tags_yaml)
    set_metadata(expanded_fnames, tags, **tr_kwargs)
    click.echo(f"Metadata updated for {len(expanded_fnames)} file(s).")


@cli.command(name="chk")
@click.option(
    "--tolerance_meters",
    "-m",
    type=int,
    default=200,
    help="Border tolerance in meters for timezone checks (default: 200)",
)
@click.option("--geotz", is_flag=True, help="Check Location & DateTime vs. Time Zone")
@click.option("--dt", is_flag=True, help="Check Date, Time and Ofsset fileds consistency")
@click.argument("fnames", nargs=-1, required=True)
def cli_command_chk(**kwargs):
    """Check consistency in image metadata.

    Verifies that timezone offset tags match the GPS coordinates and capture datetime.

    Examples:
        et chk image.jpg
        et chk *.jpg --tolerance 500
    """
    cliopt = Munch(kwargs)

    # Expand globs
    expanded_fnames: list[str] = []
    for wildcard in cliopt.fnames:
        matches = glob.glob(wildcard)
        expanded_fnames.extend(i for i in (matches if matches else [wildcard]) if i.endswith(".jpg"))

    metadata_map = get_metadata_multi(expanded_fnames)

    all_checks = ["geotz", "dt"]
    if not any(getattr(cliopt, check) for check in all_checks):
        cliopt.update({check: True for check in all_checks})

    exit_code = 0
    for fname, md in metadata_map.items():
        errors_dict = {}
        if cliopt.dt:
            errors_dict.update(check_datetime_consistency(md))
        if cliopt.geotz and not errors_dict:
            try:
                _chk_tz.check_timezone_consistency(md, tolerance_in_meters=cliopt.tolerance_meters)
            except (NoCaptureDateTimeError, NoGpsError):
                pass
            except TzMismatchError as e:
                errors_dict.update({"TzMismatchError": str(e)})
        if errors_dict:
            exit_code = 1
            print(yaml.safe_dump({fname: errors_dict}, sort_keys=False, allow_unicode=True).strip())
    if exit_code != 0:
        sys.exit(exit_code)


def main():
    """Entry point that adds default 'get' subcommand if needed.

    This allows: et image.jpg  (instead of requiring: et get image.jpg)
    """
    # If first arg exists and is not a known subcommand or option, prepend 'get'
    if sys.argv[1:] and not re.search(r"^(get|set|chk|-h|--help)$", sys.argv[1]):
        sys.argv.insert(1, "get")
    cli()


# entry point `et` is defined in pyproject.toml
if __name__ == "__main__":
    main()
