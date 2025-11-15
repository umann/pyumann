"""High-precision timezone lookup using timezone-boundary-builder polygons.

Provides accurate IANA timezone resolution from GPS coordinates using
Shapely polygons and R-tree spatial indexing. Includes auto-download
and pickle caching for optimal performance.
"""

import datetime as dt
import io
import json
import pickle
import re
import sys
import urllib.request
import zipfile
from functools import lru_cache
from pathlib import Path
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

from munch import Munch
from rtree import index
from shapely.errors import GEOSException
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.prepared import PreparedGeometry, prep

from umann.utils.fs_utils import project_root


def _needs_rebuild(index_pkl: Path, geojson_dir: Path, timezones_json: Path) -> bool:
    """Check if pickle index needs rebuild (makefile-style dependency check).

    Returns True if:
    - Pickle doesn't exist
    - timezones.json is newer than pickle
    - Any GeoJSON file is newer than pickle
    """
    if not index_pkl.exists():
        return True

    pkl_mtime = index_pkl.stat().st_mtime

    # Check timezones.json
    if timezones_json.stat().st_mtime > pkl_mtime:
        return True

    # Check all GeoJSON files
    for geojson_file in geojson_dir.glob("*-tz.json"):
        if geojson_file.stat().st_mtime > pkl_mtime:
            return True

    return False


def _build_and_save_pickle(tz_data_dir: Path) -> None:  # pragma: no cover  # pylint: disable=too-many-locals
    """Build timezone index from GeoJSON files and save as pickle."""
    geojson_dir = tz_data_dir / "geojson"
    timezones_json = tz_data_dir / "timezones.json"
    index_pkl = tz_data_dir / "tz_index.pkl"

    print(f"Building timezone index from {geojson_dir}...", file=sys.stderr)

    # Load mapping from geojson file IDs to IANA tz names
    tz_mapping = json.loads(timezones_json.read_text(encoding="utf-8"))

    # Build reverse mapping: geojson_id -> iana_tz_name
    id_to_tz = {}
    for iana_name, entries in tz_mapping.items():
        for entry in entries:
            geojson_id = entry.get("id")
            if geojson_id:
                id_to_tz[geojson_id] = iana_name

    geoms_raw = []
    tz_names = []
    bounds_list = []

    for geojson_file in sorted(geojson_dir.glob("*-tz.json")):
        geojson_id = geojson_file.stem
        tz_name = id_to_tz.get(geojson_id)

        if not tz_name:
            continue

        data = json.loads(geojson_file.read_text(encoding="utf-8"))
        geom = shape(data)

        geoms_raw.append(geom)
        tz_names.append(tz_name)
        bounds_list.append(geom.bounds)

    # Save pickle
    index_data = {
        "version": 1,
        "tz_names": tz_names,
        "geoms": geoms_raw,
        "bounds": bounds_list,
    }

    with open(index_pkl, "wb") as f:
        pickle.dump(index_data, f, protocol=pickle.HIGHEST_PROTOCOL)

    print(f"Saved timezone index with {len(tz_names)} polygons to {index_pkl}", file=sys.stderr)


# --------------------
# Data bootstrap/update
# --------------------


def _expected_geojson_ids(timezones_json: Path) -> list[str]:
    """Return sorted list of expected geojson IDs from timezones.json.

    Each entry has an "id" like "Europe-Budapest-tz" which maps to a file "<id>.json".
    """
    data = json.loads(timezones_json.read_text(encoding="utf-8"))
    ids: set[str] = set()
    for _tz, entries in data.items():
        for entry in entries:
            geo_id = entry.get("id")
            if geo_id:
                ids.add(geo_id)
    return sorted(ids)


def _geojson_dir_complete(geojson_dir: Path, expected_ids: list[str]) -> tuple[bool, list[str]]:
    """Check if all expected '<id>.json' files exist under geojson_dir.

    Returns (is_complete, missing_ids).
    """
    missing: list[str] = []
    for geo_id in expected_ids:
        if not (geojson_dir / f"{geo_id}.json").exists():
            missing.append(geo_id)
    return (len(missing) == 0, missing)


def _fetch_latest_input_data_zip_url() -> str:  # pragma: no cover
    """Scrape the releases page for the 'input-data.zip' asset URL.

    Uses a lightweight regex to find the first matching asset link.
    """
    releases_url = "https://github.com/evansiroky/timezone-boundary-builder/releases"
    req = urllib.request.Request(releases_url, headers={"User-Agent": "pyumann-tz4d/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    # Match either absolute or relative hrefs
    m = re.search(
        r'href=["\'](?P<href>(?:https://github\.com)?'
        r"/evansiroky/timezone-boundary-builder/releases/download/[^/]+/input-data\\.zip)"
        r'["\']',
        html,
    )
    if not m:
        raise RuntimeError("Could not find input-data.zip link on releases page")
    href = m.group("href")
    if href.startswith("/evansiroky/"):
        href = "https://github.com" + href
    return href


def _download_bytes(url: str) -> bytes:  # pragma: no cover
    req = urllib.request.Request(url, headers={"User-Agent": "pyumann-tz4d/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


# pylint: disable=too-many-locals,too-many-branches,too-many-statements
def download_geojson(
    verbose: bool = True,
) -> bool:  # pragma: no cover
    """Ensure timezone GeoJSON and mapping JSON files exist and are up-to-date.

    Behavior:
    - Detect latest input-data.zip URL on the releases page.
    - Compare with data/tz/tz.url (if exists). If different/missing, trigger update.
    - If any of the 3 JSONs (expectedZoneOverlaps.json, osmBoundarySources.json, timezones.json)
      are missing, trigger update.
    - If data/tz/geojson is missing or incomplete vs timezones.json ids, trigger update.

    When updating:
    - Download input-data.zip
    - Extract the 3 JSON files to data/tz
    - Extract all files under input-data/downloads/ to data/tz/geojson
    - Write tz.url with the used URL
    - Rebuild tz_index.pkl

    Returns True if an update was performed, False otherwise.
    """
    tz_data_dir = Path(project_root()) / "data" / "tz"
    tz_data_dir.mkdir(parents=True, exist_ok=True)
    geojson_dir = tz_data_dir / "geojson"
    geojson_dir.mkdir(parents=True, exist_ok=True)
    tz_url_file = tz_data_dir / "tz.url"
    expected_jsons = [
        tz_data_dir / "expectedZoneOverlaps.json",
        tz_data_dir / "osmBoundarySources.json",
        tz_data_dir / "timezones.json",
    ]

    # Try to get the latest URL
    try:
        latest_url = _fetch_latest_input_data_zip_url()
    except Exception as e:  # pylint: disable=broad-exception-caught
        # If we cannot reach GitHub but we already have complete data, allow continuing
        if verbose:
            print(f"Warning: could not fetch releases page: {e}", file=sys.stderr)
        latest_url = None

    # Determine if update is needed
    need_update = False

    # Check JSON presence
    missing_jsons = [p for p in expected_jsons if not p.exists()]
    if missing_jsons:
        need_update = True

    # If we have timezones.json, check geojson completeness
    if not need_update and (tz_data_dir / "timezones.json").exists():
        try:
            expected_ids = _expected_geojson_ids(tz_data_dir / "timezones.json")
            complete, missing = _geojson_dir_complete(geojson_dir, expected_ids)
            if not complete:
                need_update = True
                if verbose:
                    print(f"GeoJSON incomplete: missing {len(missing)} files", file=sys.stderr)
        except Exception as e:  # pylint: disable=broad-exception-caught
            need_update = True
            if verbose:
                print(f"Warning: could not verify geojson completeness: {e}", file=sys.stderr)

    # Compare stored URL
    if latest_url is not None:
        stored_url = tz_url_file.read_text(encoding="utf-8").strip() if tz_url_file.exists() else None
        if stored_url != latest_url:
            need_update = True

    if not need_update:
        # Be quiet on no-op; callers may print a single line.
        return False

    # Perform update
    if latest_url is None:
        raise RuntimeError("Cannot update timezone data: latest input-data.zip URL unavailable.")
    if verbose:
        print(f"Downloading timezone input-data.zip from {latest_url}...", file=sys.stderr)
    try:
        blob = _download_bytes(latest_url)
    except (URLError, HTTPError) as e:
        raise RuntimeError(f"Failed to download input-data.zip: {e}") from e

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        # Extract JSONs
        members = {name: name for name in zf.namelist()}

        def find_member(target: str) -> str | None:
            # target like 'input-data/expectedZoneOverlaps.json'
            for name in members:
                if name.endswith(target):
                    return name
            return None

        json_targets = [
            "input-data/expectedZoneOverlaps.json",
            "input-data/osmBoundarySources.json",
            "input-data/timezones.json",
        ]
        for tgt in json_targets:
            member = find_member(tgt)
            if not member:
                raise RuntimeError(f"Zip missing member: {tgt}")
            with zf.open(member) as src, open(tz_data_dir / Path(tgt).name, "wb") as dst:
                dst.write(src.read())

        # Extract downloads directory into geojson_dir
        downloads_prefix = None
        for name in zf.namelist():
            if name.endswith("input-data/downloads/") or name.endswith("input-data/downloads"):
                downloads_prefix = name.rstrip("/") + "/"
                break
        if downloads_prefix is None:
            # Try to find any path ending with '/downloads/'
            for name in zf.namelist():
                if "/downloads/" in name:
                    downloads_prefix = name.split("downloads/")[0] + "downloads/"
                    break
        if downloads_prefix is None:
            raise RuntimeError("Zip missing downloads directory")

        for name in zf.namelist():
            if not name.startswith(downloads_prefix):
                continue
            if name.endswith("/"):
                continue
            # Only extract json files
            if not name.lower().endswith(".json"):
                continue
            with zf.open(name) as src:
                out_path = geojson_dir / Path(name).name
                with open(out_path, "wb") as dst:
                    dst.write(src.read())

    # Write tz.url
    tz_url_file.write_text(latest_url + "\n", encoding="utf-8")

    # Rebuild pickle
    _build_and_save_pickle(tz_data_dir)

    if verbose:
        print("Timezone data updated.", file=sys.stderr)
    return True


@lru_cache(maxsize=1)
def _build_tz_index() -> tuple[index.Index, list[PreparedGeometry], list[str], list[BaseGeometry]]:
    """Build rtree index + prepared and raw geometries from GeoJSON data (cached).

    Automatically rebuilds pickle if source files are newer (makefile-style).
    Loads from pickle if available, otherwise builds from GeoJSON.

    Returns (rtree_index, list[PreparedGeometry], list[tz_name], list[Geometry]).
    """
    tz_data_dir = Path(project_root()) / "data" / "tz"
    geojson_dir = tz_data_dir / "geojson"
    timezones_json = tz_data_dir / "timezones.json"
    index_pkl = tz_data_dir / "tz_index.pkl"

    if not geojson_dir.exists():  # pragma: no cover
        geojson_dir.mkdir(parents=True, exist_ok=True)
    # If core files missing or incomplete, bootstrap/update first
    need_bootstrap = False
    if not timezones_json.exists():  # pragma: no cover
        need_bootstrap = True
    else:
        try:
            expected_ids = _expected_geojson_ids(timezones_json)
            complete, _missing = _geojson_dir_complete(geojson_dir, expected_ids)
            if not complete:  # pragma: no cover
                need_bootstrap = True
        except Exception:  # pragma: no cover  # pylint: disable=broad-exception-caught
            need_bootstrap = True
    if need_bootstrap:  # pragma: no cover
        download_geojson(verbose=True)

    # Check if pickle needs rebuild
    if _needs_rebuild(index_pkl, geojson_dir, timezones_json):  # pragma: no cover
        _build_and_save_pickle(tz_data_dir)

    # Load from pickle
    try:
        with open(index_pkl, "rb") as f:
            index_data = Munch(pickle.load(f))

        # Prepare geometries (can't pickle prepared geoms)
        geoms = [prep(geom) for geom in index_data.geoms]

        # Rebuild rtree index
        idx = index.Index()
        for i, bounds in enumerate(index_data.bounds):
            idx.insert(i, bounds)

        return idx, geoms, index_data.tz_names, index_data.geoms
    except Exception as e:  # pragma: no cover  # pylint: disable=broad-exception-caught
        raise RuntimeError(f"Failed to load timezone index from {index_pkl}: {e}") from e


def tz_from_coords(lat: float, lon: float, tolerance_lon_delta_deg: int | float = 7.5) -> str | None:
    """Return IANA timezone name from lat/lon using high-resolution polygons.

    Uses timezone-boundary-builder GeoJSON data in data/tz/geojson/.
    Fallback behavior when no polygon contains the point:
    - Prefer the nearest timezone whose centroid longitude is within ±7.5° (±30 minutes)
      of the given longitude (accounting for dateline wrap-around).
    - If none match that constraint, return the absolute nearest timezone by geometry distance.
    tolerance_lon_delta_deg=0 disables fallback.
    Returns None if no timezone can be determined.
    """
    try:
        idx, geoms_prep, tz_names, geoms_raw = _build_tz_index()
    except (ImportError, FileNotFoundError) as e:  # pragma: no cover
        raise RuntimeError(f"Cannot load timezone polygons: {e}") from e

    # GeoJSON uses (lon, lat) order
    pt = Point(lon, lat)

    # 1) Exact containment via prepared geoms and rtree candidates
    for i in idx.intersection((lon, lat, lon, lat)):
        if geoms_prep[i].contains(pt):
            return tz_names[i]

    if not tolerance_lon_delta_deg:
        return None

    # 2) No exact match. Choose nearest with longitude constraint first, else absolute nearest.
    def lon_delta_deg(a: float, b: float) -> float:
        """Minimal absolute longitude difference in degrees accounting for wrap-around."""
        d = abs(a - b)
        return 360.0 - d if d > 180.0 else d

    nearest_idx = None
    nearest_dist = float("inf")
    constrained_idx = None
    constrained_dist = float("inf")

    for i, geom in enumerate(geoms_raw):
        # Fast reject using bbox distance could be added, but N~400 is acceptable to scan
        dist = pt.distance(geom)
        if dist < nearest_dist:
            nearest_dist = dist
            nearest_idx = i

        # Check ±7.5° centroid-longitude constraint
        try:
            cen_lon = float(geom.centroid.x)
        except (ValueError, TypeError, AttributeError, GEOSException):  # pragma: no cover
            continue
        if lon_delta_deg(lon, cen_lon) <= 7.5 and dist < constrained_dist:
            constrained_dist = dist
            constrained_idx = i

    pick = constrained_idx if constrained_idx is not None else nearest_idx
    return tz_names[pick] if pick is not None else None


def local_time_from_timestamp(lat: float, lon: float, ts: float):
    """Return (tz_name, offset, local_dt) for given coords and UTC timestamp.

    ts is Unix timestamp in seconds since epoch (UTC).
    """
    tz_name = tz_from_coords(lat, lon)
    if not tz_name:
        return None, None, None
    dt_utc = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
    dt_local = dt_utc.astimezone(ZoneInfo(tz_name))
    return tz_name, dt_local.utcoffset(), dt_local


def tz_offset_from_tz_unaware_dt(lat: float, lon: float, dt_naive: dt.datetime) -> str | None:
    """Compute UTC offset for a naive local datetime at given coordinates.

    Rules:
    - Interpret dt_naive as local wall time in the timezone at lat/lon.
    - If the time is ambiguous (fall back), prefer the "new" timezone
      after the transition (fold=1, the later/standard offset in NH).
    - If the time is nonexistent (spring forward gap), use the offset
      of the "new" timezone after the transition (the later offset).

    Returns a timedelta offset, or None if timezone cannot be resolved.
    """
    tz_name = tz_from_coords(lat, lon)
    if not tz_name:
        return None
    tz = ZoneInfo(tz_name)

    # First, try to detect ambiguity (fall back). If ambiguous, choose fold=1.
    dt_fold0 = dt_naive.replace(tzinfo=tz, fold=0)
    dt_fold1 = dt_naive.replace(tzinfo=tz, fold=1)
    off0 = dt_fold0.utcoffset()
    off1 = dt_fold1.utcoffset()
    if off0 != off1:
        # Ambiguous local time: prefer the new tz (fold=1)
        return off1

    # Not ambiguous. Handle potential nonexistent time (spring forward gap).
    # Heuristic: if offsets differ within a +/- 2 hour window, we are near a
    # transition. Prefer the offset just after the local time by sampling +1h.
    off_here = dt_fold0.utcoffset()
    plus = (dt_naive + dt.timedelta(hours=1)).replace(tzinfo=tz).utcoffset()
    minus = (dt_naive - dt.timedelta(hours=1)).replace(tzinfo=tz).utcoffset()
    if plus != minus and plus is not None and minus is not None:
        # Prefer the "new" tz after the jump (post-transition offset)
        # For a spring-forward gap, this corresponds to `plus`.
        return plus  # pragma: no cover

    # Default: use the straightforward offset at this wall time
    return off_here


def parse_iso(ts: str) -> dt.datetime:
    """Parse ISO 8601 datetime string, handling trailing 'Z' for UTC."""
    # Handle trailing 'Z' (Zulu → UTC)
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return dt.datetime.fromisoformat(ts)


def main():
    """CLI entry point for timezone lookup and data download."""
    # Usage:
    #   python -m umann.geo.tz4d <lat> <lon> <datetime_iso>
    #   python -m umann.geo.tz4d            # triggers download/update if needed
    #   python -m umann.geo.tz4d --download # same as above
    if len(sys.argv) == 1 or (len(sys.argv) == 2 and sys.argv[1] in {"--download", "-d"}):  # pragma: no cover
        changed = download_geojson(verbose=True)
        print("Timezone data updated." if changed else "Timezone data already up-to-date.")
        sys.exit(0)

    lat, lon, dt_str = sys.argv[1:4]  # pragma: no cover
    lat = float(lat)  # pragma: no cover
    lon = float(lon)  # pragma: no cover
    dt_naive = parse_iso(dt_str)  # pragma: no cover
    offset = tz_offset_from_tz_unaware_dt(lat, lon, dt_naive)  # pragma: no cover
    tz_name = tz_from_coords(lat, lon)  # pragma: no cover
    print(f"Offset for {dt_str} at ({lat}, {lon}): {offset} ({tz_name})")  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    main()
