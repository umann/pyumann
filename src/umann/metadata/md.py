"""ExifTool metadata operations CLI.

This module provides command-line interface to ExifTool for reading and writing
metadata in image files.
"""

import glob
import os
import re
import sys

import click
import yaml
from munch import Munch

from umann.metadata import chk_tz as _chk_tz
from umann.metadata.chk_datetime import check_datetime_consistency
from umann.metadata.chk_tz import NoCaptureDateTimeError, NoGpsError, TzMismatchError
from umann.metadata.et import TRANSFORMATORS, get_metadata_multi, set_metadata
from umann.utils.digest import extract_soul
from umann.utils.digest.soul import SoulError


@click.group()
def cli():
    """ExifTool metadata operations CLI.

    Get metadata: md image.jpg  (or: md get image.jpg)
    Set metadata: md set --tags '{"Key": "value"}' image.jpg
    Check timezone: md chk image.jpg
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
@click.option("--quiet", "-q", is_flag=True, help="Do not print metadata (just build cache")
@click.argument("wildcards", nargs=-1, required=True)
def cli_command_get(**kwargs):
    """Get metadata from image files (default command).

    Examples:
        md get image.jpg
        md get *.jpg --transform set_exif_types
        md get image.jpg --dictify
    """
    cliopt = Munch(kwargs)

    # Expand globs, but preserve raw values when no filesystem match (useful in tests/mocks)
    # expanded_fnames = [f for wildcard in cliopt.wildcards for f in glob.glob(wildcard)]

    if "ALL" in cliopt.transformations:
        cliopt.transformations = tuple(TRANSFORMATORS.keys())
    tr_kwargs = dict(transformations=cliopt.transformations)

    # Fetch metadata
    metadata_map = get_metadata_multi(cliopt.wildcards, **tr_kwargs)
    if not cliopt.quiet:
        # Print metadata
        output_obj = metadata_map  # if multi else next(iter(metadata_map.values()))
        print(yaml.safe_dump(output_obj, sort_keys=False, allow_unicode=True).strip())


@cli.command(name="cleanup")
@click.argument("fnames", nargs=-1, required=True)
def cli_command_cleanup(**kwargs):
    """Cleanup metadata cache of fnames (filename, quoted glob and dir).

    Example:
        md cleanup image.jpg "images/x*..jpg" images/etc/
    """
    cliopt = Munch(kwargs)

    # Expand globs, but preserve raw values when no filesystem match (useful in tests/mocks)
    expanded_fnames = [f for wildcard in cliopt.fnames for f in glob.glob(wildcard)]

    if "ALL" in cliopt.transformations:
        cliopt.transformations = tuple(TRANSFORMATORS.keys())
    tr_kwargs = dict(transformations=cliopt.transformations)
    # multi = len(expanded_fnames) != 1 or cliopt.dictify

    # Fetch metadata
    metadata_map = get_metadata_multi(expanded_fnames, **tr_kwargs)
    if not cliopt.quiet:
        # Print metadata
        output_obj = metadata_map  # if multi else next(iter(metadata_map.values()))
        print(yaml.safe_dump(output_obj, sort_keys=False, allow_unicode=True, width=float("inf")).strip())


@cli.command(name="set")
@click.option(
    "--tags",
    "tags_yaml",
    required=True,
    help='YAML or JSON string of tags to set (e.g., \'{"IPTC:Keywords": "tag1, tag2"}\')',
)
@click.argument("fnames", nargs=-1, required=True)
def cli_command_set(fnames, tags_yaml):
    """Set metadata tags in image files.

    Examples:
        md set --tags '{"IPTC:Keywords": "tag1, tag2"}' image.jpg
    """
    # Expand globs
    expanded_fnames = [f for wildcard in fnames for f in glob.glob(wildcard)]

    tags = yaml.safe_load(tags_yaml)
    set_metadata(expanded_fnames, tags)
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
        md chk image.jpg
        md chk *.jpg --tolerance 500
    """
    cliopt = Munch(kwargs)

    # Expand globs
    expanded_fnames = [f for wildcard in cliopt.fnames for f in glob.glob(wildcard) if f.endswith(".jpg")]

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
            print(yaml.safe_dump({fname: errors_dict}, sort_keys=False, allow_unicode=True, width=1e4).strip())
    if exit_code != 0:
        sys.exit(exit_code)


# @cli.command(name="enrich")
# @click.option("--picasa-faces", is_flag=True, help="Add Picasa face metadata where available")
# @click.argument("fnames", nargs=-1, required=True)
# def cli_command_enrich(**kwargs):
#     """Enrich metadata in image files."""
#     pass


@cli.command(name="soul")
@click.argument("fnames", nargs=-1, required=True)
def cli_command_soul(**kwargs):
    """Print soul md5's of files in md5sum format.

    For files without soul, print "_" chars instead.

    For files with broken soul, print 32 chars from error message.

    \b
    Example:

        \b
        md soul tests/fixtures/data/test*jpg*
        a10753441f92dcf6c3fea4dde18e8692  tests/fixtures/data/test.jpg
        ________________________________  tests/fixtures/data/test.jpg.metadata.G0.yaml
        ________________________________  tests/fixtures/data/test.jpg.metadata.G1.yaml
        ERR:Expected_JPEG_SOI_marker,_go  tests/fixtures/data/test_error.jpg
    """
    cliopt = Munch(kwargs)

    # Expand globs
    expanded_fnames: list[str] = []
    for wildcard in cliopt.fnames:
        matches = glob.glob(wildcard)
        expanded_fnames.extend(matches if matches else [wildcard])

    # TODO: from cache.
    # Process each file
    for fname in expanded_fnames:
        try:
            md5_soul = extract_soul(fname)
            if md5_soul is None:
                # For files without soul (soulless files)
                print(f"{'_' * 32}  {fname}")
            else:
                print(f"{md5_soul}  {fname}")
        except SoulError as e:
            # For errors, print 32 chars from error message
            print(f"{('ERR:' + (str(e) + '_' * 32))[:32].replace(' ', '_')}  {fname}")


def main():
    """Entry point that adds default 'get' subcommand if needed.

    This allows: md image.jpg  (instead of requiring: md get image.jpg)
    """
    # Skip argv rewrites while shell completion is running
    if "_MD_COMPLETE" not in os.environ:
        # If first arg exists and is not a known subcommand or option, prepend 'get'
        if sys.argv[1:] and not re.search(r"^(get|set|chk|soul|-h|--help)$", sys.argv[1]):
            sys.argv.insert(1, "get")
    cli()


# entry point `md` is defined in pyproject.toml
if __name__ == "__main__":
    main()
