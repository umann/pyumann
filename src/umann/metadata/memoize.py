# pylint: disable=too-many-lines
"""Module to persistently memoize file metadata using an SQLite database."""

import importlib
import json
import os
import re
import sqlite3
import sys
import typing as t
from pathlib import Path

import yaml
from munch import Munch

from umann.config import get_config
from umann.platform import vol_type
from umann.utils.data_utils import (
    batch_iter,
    deep_split,
    dict_only_keys,
    flat1,
    flat_more,
    get_multi,
    locale_sorted,
    split_dict,
    uniq_keep_order,
)
from umann.utils.db_utils import (
    db_conn,
    delete1,
    execute,
    get_id,
    get_id_cached,
    insert,
    insert1,
    insert_ignore_cached,
    transaction,
    upsert1,
)
from umann.utils.digest import extract_soul
from umann.utils.fs_utils import iter_files, project_root
from umann.utils.log_utils import setup_package_logger
from umann.utils.sql_utils import glob_to_where

# DB_VERSION = 5

_logger = setup_package_logger()

# Use transaction as get_cursor for backward compatibility
get_cursor = transaction


sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


# from umann.utils.db_utils import transaction as get_cursor


def get_file_rec_multi(
    wildcards: t.Iterable[str],
    /,
    *,
    func: t.Callable[[str], dict[str, t.Any]] = lambda f: {},
    cmd: str = "",
    # strict: bool = False,
    with_cleanup: bool = True,
) -> dict[str, Munch]:

    with get_cursor(db_conn()) as cursor:
        cursor.execute("DROP TABLE IF EXISTS _import")
        cursor.execute(
            """CREATE TEMPORARY TABLE _import(
            vol TEXT NOT NULL,
            dir TEXT NOT NULL,
            bas TEXT,
            ext TEXT,
            vol_id INTEGER,
            dir_id INTEGER,
            bas_id INTEGER,
            ext_id INTEGER,
            size INTEGER,
            mtime REAL,
            done INTEGER NOT NULL DEFAULT 0
        )"""
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS temp._import_ids ON _import (vol_id, dir_id, bas_id, ext_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS temp._import_done ON _import (done)")

        cmd_id = get_id(cursor, "cmd", dict(cmd=cmd))

    _logger.debug("iter_files start")
    batch_file_attrs = list(
        iter_files(
            wildcards,
            gitignore=(
                None if len(wildcards) == 1 and wildcards[0].startswith("/mnt/f") else project_root(".metadata_ignore")
            ),
        )
    )
    _logger.debug("iter_files end")
    results: dict[str, Munch] = {}
    if batch_file_attrs:  # paranoia
        with get_cursor(db_conn()) as cursor:
            results: dict[str, Munch] = {}
            # if batch_file_attrs := list(chain.from_iterable(iter_files(f) for f in fnames)):
            _logger.debug(
                f"Inserting {len(batch_file_attrs)} file attrs into temporary table `_import`, {batch_file_attrs[0]=}"
            )

            # cursor.execute("PRAGMA synchronous=OFF")
            cursor.executemany(
                "INSERT INTO _import (vol, dir, bas, ext, size, mtime) VALUES (?, ?, ?, ?, ?, ?)",
                (tuple(f.values()) for f in batch_file_attrs),
                # map(lambda f: (f.vol, f.dir, f.bas, f.ext, f.size, f.mtime), all_file_attrs)
            )
            insert_ignore_cached(cursor, "vol", vol_type(), (f.vol for f in batch_file_attrs))
            # set_vol = set((f.vol,) for f in batch_file_attrs)
            # _logger.debug(f"Upserting {len(set_vol)} records into table `vol`")
            # cursor.executemany(f"INSERT OR IGNORE INTO vol ({vol_type()}) VALUES (?)", set_vol)

            for tbl in ["dir", "bas", "ext"]:
                insert_ignore_cached(cursor, tbl, tbl, (f[tbl] for f in batch_file_attrs))
                # set_tbl = set((f[tbl],) for f in batch_file_attrs)
                # _logger.debug(f"Upserting {len(set_tbl)} records into table `{tbl}`")
                # cursor.executemany(f"INSERT OR IGNORE INTO {tbl} ({tbl}) VALUES (?)", set_tbl)

            # Update _import with IDs for faster joins
            cursor.execute(f"UPDATE _import SET vol_id = (SELECT id FROM vol WHERE vol.`{vol_type()}` = _import.vol)")
            cursor.execute("UPDATE _import SET dir_id = (SELECT id FROM dir WHERE dir.dir = _import.dir)")
            cursor.execute("UPDATE _import SET bas_id = (SELECT id FROM bas WHERE bas.bas = _import.bas)")
            cursor.execute("UPDATE _import SET ext_id = (SELECT id FROM ext WHERE ext.ext = _import.ext)")

            execute(
                cursor,
                f"""
                SELECT
                    vol.`{vol_type()}` as vol,
                    dir.dir,
                    bas.bas,
                    ext.ext,
                    imp.vol_id,
                    imp.dir_id,
                    imp.bas_id,
                    imp.ext_id,
                    imp.size,
                    imp.mtime,
                    file.id as file_id,
                    -- file.deleted
                    -- imp.size IS NOT NULL and imp.mtime IS NOT NULL as exists,
                    file.mtime == imp.mtime AND content.size == imp.size as up_to_date,
                    file_metadata.json as file_metadata_json,
                    -- file_metadata.id as file_metadata_id,
                    content_metadata.json as content_metadata_json
                    -- content_metadata.id as content_metadata_id
                FROM _import AS imp
                JOIN vol ON vol.id = imp.vol_id
                JOIN dir ON dir.id = imp.dir_id
                JOIN bas ON bas.id = imp.bas_id
                JOIN ext ON ext.id = imp.ext_id
                LEFT JOIN file ON
                    file.vol_id = imp.vol_id AND
                    file.dir_id = imp.dir_id AND
                    file.bas_id = imp.bas_id AND
                    file.ext_id = imp.ext_id
                LEFT JOIN content ON content.id = file.content_id
                LEFT JOIN file_metadata ON
                    file_metadata.file_id = file.id AND file_metadata.cmd_id = :cmd_id
                LEFT JOIN content_metadata ON
                    content_metadata.content_id = content.id AND content_metadata.cmd_id = :cmd_id
                WHERE not done
                    """,
                dict(cmd_id=cmd_id),
            )

            for row in cursor.fetchall():
                fname = f"{row.vol}{row.dir}{row.bas}{row.ext}"
                if row.up_to_date:  # and not row.get("deleted", 0):
                    metadata = {}
                    for key in ["file_metadata_json", "content_metadata_json"]:
                        metadata.update(json.loads(row.get(key) or "{}"))
                    results[fname] = metadata
                else:
                    res = Munch(row)
                    res.update(dict(func=func, fname=fname, cmd_id=cmd_id))
                    try:
                        res.md5, res.md5_soul, res.soul_error = extract_soul(
                            res.fname, "md5", "md5_soul", "soul_error"
                        )
                    except Exception as e:  # pylint: disable=broad-except  # TODO
                        _logger.error(f"Error calculating soul/md5 for {res.fname}: {e}")
                        continue

                    if res.md5_soul:
                        res.soul_id = get_id(cursor, "soul", uniq=dict(md5_soul=res.md5_soul))
                    else:
                        res.soul_id = None
                    res.content_id, res.content_chg = get_id(
                        cursor,
                        "content",
                        uniq=dict(md5=res.md5),
                        add=dict(size=res.size, soul_id=res.soul_id),
                        return_whether_chg=True,
                    )
                    if res.soul_error:
                        insert1(
                            cursor, "soul_error", add=dict(content_id=res.content_id, **res.soul_error), ignore=True
                        )
                    res.file_id = get_id(
                        cursor,
                        "file",
                        dict_only_keys(res, ["vol_id", "dir_id", "bas_id", "ext_id"]),
                        dict(content_id=res.content_id, mtime=res.mtime, deleted=0),
                        existing_id=res.file_id,
                    )

                    results[fname] = _handle_metadata(cursor, res, fname)
            # if nonexistent := {i for i in set(fnames) - set(results.keys()) if not os.path.exists(i)}:
            #     delete_nonexistent(cursor, nonexistent)
            execute(cursor, "UPDATE `_import` SET done = 1")
            # execute(cursor, "DROP TABLE _import")
            # dropped_tmp = True

    if with_cleanup:
        cleanup(wildcards)
        # if cannot_cleanup := [i for i in fnames if not re.search(DIR_PATTERN, urealpath(i))]:
        # raise ValueError(f"Cannot cleanup non-absolute paths: {cannot_cleanup}")

    return results


def cleanup(wildcards: t.Iterable[str]) -> dict[str, Munch]:
    """Cleanup file metadata cache in batches to avoid SQLite expression limits."""
    wildcards = list(wildcards)
    _logger.debug(f"Cleaning up for {len(wildcards)} wildcards")
    batch_size = 200

    with get_cursor(db_conn()) as cursor:
        for batch in batch_iter(wildcards, batch_size=batch_size):
            where_clause, sql_attrs = glob_to_where(batch)

            execute(
                cursor,
                f"""\
                SELECT
                    file.id,
                    vol.`{vol_type()}` as vol,
                    dir.dir,
                    bas.bas,
                    ext.ext
                FROM file
                JOIN vol ON vol.id = file.vol_id
                JOIN dir ON dir.id = file.dir_id
                JOIN bas ON bas.id = file.bas_id
                JOIN ext ON ext.id = file.ext_id
                LEFT JOIN _import AS imp ON
                    vol.`{vol_type()}` = imp.vol
                    AND dir.dir = imp.dir
                    AND bas.bas = imp.bas
                    AND ext.ext = imp.ext
                WHERE
                    {where_clause}
                    AND NOT file.deleted
                    AND NOT imp.done
                    -- WTF AND imp.vol IS NULL
                """,
                sql_attrs,
            )
            for row in cursor.fetchall():
                _logger.info(f"Cleaning up file id={row.id} {row.vol=} {row.dir=} {row.bas=} {row.ext=}")
                # _set_file_deleted(cursor, Munch(row))


# pylint: disable=too-many-arguments, too-many-locals
def get_file_rec(
    fname: str,
    /,
    *,
    func: t.Callable[[str], dict[str, t.Any]] = lambda f: {},
    cmd: str = "",
    # fstat=None,
    # strict: bool = False,
    # on_nonexistent: t.Any = FileNotFoundError,
) -> Munch:
    """Get or create file record in memoization database.

    :param fname: File name
    :param func:function to call on file
    :param cmd: CLI equivalent of func (to be used in cache key)

    :return metadata dict or on_nonexistent value
    """

    return get_file_rec_multi([fname], func=func, cmd=cmd)[fname]


def _handle_metadata(cursor: sqlite3.Cursor, res: Munch, fname: str) -> Munch | None:
    _logger.debug(f"{res.fname=} {res=}")
    engine = None
    if has_metadata_ext(res.fname):
        engine = res.func.__module__.split(".")[-1]
    else:
        res.func = None
    try:
        for sidecar in get_config("sidecars", []):
            if Path(res.fname).match(sidecar["fnmatch"]):
                assert not res.func, f"Multiple sidecar engines match {res.fname}: {engine} and {sidecar['engine']}"
                engine = sidecar["engine"]
                module = importlib.import_module(f"umann.metadata.{engine}")
                res.func = getattr(module, f"get_{engine}_metadata")

        if not res.func:
            return None
        metadata = res.func(res.fname)  # e.g. get_exiftool(res.fname)
    except Exception as e:  # pylint: disable=broad-except  # TODO
        _logger.error(f"Error getting metadata for {fname} with {engine=}: {e!r}")
        metadata = {"Error": type(e).__name__ + ": " + str(e)}
    # metadata.update({"Umann:md5": res.md5, "Umann:md5_soul": res.md5_soul})
    res.file_metadata, res.content_metadata = split_dict(
        metadata, lambda key_val: key_val[0].split(":")[0] in {"System", "ExifTool", "SourceFile"}
    )
    _handle_content_metadata(cursor, res)
    _handle_file_metadata(cursor, res)
    return metadata or None


# pylint: disable=too-many-branches  # TODO
def _handle_content_metadata(cursor: sqlite3.Cursor, res: Munch) -> None:
    if res.content_chg is False:
        return
    has_kw = has_face = res.ext in get_config("picasa.exts", {})
    if res.content_chg:
        if has_kw:
            delete1(cursor, "content_keyword", where=dict(content_id=res.content_id))
        if has_face:
            delete1(cursor, "face", where=dict(content_id=res.content_id))
    if not res.content_metadata:
        if res.content_chg:
            delete1(
                cursor,
                "content_metadata",
                where=dict(cmd_id=res.cmd_id, content_id=res.content_id),
            )
            delete1(cursor, "digest", where=dict(content_id=res.content_id))
        return
    upsert1(
        cursor,
        "content_metadata",
        add=dict(json=json.dumps(res.content_metadata, ensure_ascii=False)),  # , chk_ts=chk_ts),
        uniq=dict(cmd_id=res.cmd_id, content_id=res.content_id),
    )
    try:
        upsert1(
            cursor,
            "digest",
            add=metadata_to_digest(res.content_metadata),  # | dict(chk_ts=chk_ts),
            uniq=dict(content_id=res.content_id),
        )
    except Exception as e:  # sqlite3.IntegrityError
        _logger.error(f"DIGEST ERROR {res.fname=} {e!r}\n{yaml.dump(res.content_metadata)}")
        raise
    if has_kw:
        # MWG:Keywords prefers XMP over IPTC and handles encoding properly
        if keywords := get_keywords_list(res.content_metadata):
            content_keyword_items: list[dict] = []
            for keyword in keywords:
                keyword_id = get_id_cached(cursor, "keyword", keyword=keyword)
                content_keyword_items.append(dict(content_id=res.content_id, keyword_id=keyword_id))
            insert(cursor, "content_keyword", content_keyword_items, ignore=True)
    if has_face and (faces := get_multi(res.content_metadata, "XMP-mwg-rs:RegionInfo.RegionList", default=None)):
        items: list[dict[str, t.Any]] = []
        # TODO: use insert instead of insert1 in loop
        for face in faces:
            person_id = None
            try:
                if nick := face.get("Name"):
                    person_id = get_id_cached(
                        cursor,
                        "person",
                        **dict(
                            nick=nick,
                            namespace=flat1(
                                get_multi(
                                    face,
                                    "Extensions.XMP-Umann:FaceNamespace",
                                    get_config("picasa.namespace", default=None),
                                )
                            ),
                            hex=flat1(get_multi(face, "Extensions.XMP-Umann:FaceID", default=None)),
                        ),
                        # dict(
                        #     emails="",
                        # ),
                    )
            except Exception as e:  # sqlite3.IntegrityError  # pylint: disable=broad-except  # TODO
                _logger.error(f"FACE ERROR 1 {res.fname=} {e!r} {face=}\n{yaml.dump(faces)}")
            items.append(
                dict(
                    content_id=res.content_id,
                    person_id=person_id,
                    # name=nick,
                    rect64=flat1(get_multi(face, "Extensions.XMP-Umann:FaceRect64", default=None)),
                    X=flat1(get_multi(face, "Area.H", default=None)),
                    Y=flat1(get_multi(face, "Area.Y", default=None)),
                    W=flat1(get_multi(face, "Area.W", default=None)),
                    H=flat1(get_multi(face, "Area.H", default=None)),
                )
            )
        try:
            insert(cursor, "face", items)
        except Exception as e:  # sqlite3.IntegrityError  # pylint: disable=broad-except  # TODO
            _logger.error(f"FACE ERROR 2 {res.fname=} {e!r}\n{yaml.dump(faces)}")


def _handle_file_metadata(cursor: sqlite3.Cursor, res: Munch) -> None:
    if res.file_metadata:
        upsert1(
            cursor,
            "file_metadata",
            add=dict(json=json.dumps(res.file_metadata, ensure_ascii=False)),  # , chk_ts=chk_ts),
            uniq=dict(cmd_id=res.cmd_id, file_id=res.file_id),
        )
    else:
        delete1(
            cursor,
            "file_metadata",
            where=dict(cmd_id=res.cmd_id, file_id=res.file_id),
        )


def has_metadata_ext(fname: str) -> bool:
    return os.path.splitext(fname)[1] in get_config("metadata.exts", {})


def get_duration_s(metadata: dict[str, t.Any]) -> float | None:
    """Get duration in seconds from metadata dict.

    Args:
        metadata: Metadata dict as returned by exiftool (or whatever)
    """
    for key in ("Composite:Duration", "Track1:Duration", "QuickTime:Duration"):
        if ret := metadata.get(key):
            ret = ret.removesuffix(" (approx)").strip()
            ret = ret.removesuffix(" s").strip()
            if match := re.match(r"^(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)$", ret):
                hours = int(match.group(1) or "0")
                minutes = int(match.group(2) or "0")
                seconds = float(match.group(3) or "0")
                return hours * 3600 + minutes * 60 + seconds
    return None


def get_artist(metadata: dict[str, t.Any]) -> str | None:
    """Get artist from metadata dict.

    Args:
        metadata: Metadata dict as returned by exiftool (or whatever)
    """
    return (
        flat_more(metadata.get("MWG:Creator"))
        or metadata.get("ID3v2_3:Artist")
        or metadata.get("ID3v1:Artist")
        or None
    )


def get_title(metadata: dict[str, t.Any]) -> str | None:
    return metadata.get("MWG:Description") or metadata.get("ID3v2_3:Title") or metadata.get("ID3v1:Title") or None


def get_album(metadata: dict[str, t.Any]) -> str | None:
    return metadata.get("ID3v2_3:Album") or metadata.get("ID3v1:Album") or None


def get_track(metadata: dict[str, t.Any]) -> str | None:
    ret = metadata.get("ID3v2_3:Track") or metadata.get("ID3v1:Track")
    return str(ret) if ret is not None and ret != "" else None


def get_keywords_list(metadata: dict[str, t.Any]) -> list[str]:
    for tag in ("MWG:Keywords", "XMP-dc:Subject", "ID3v2_3:Comments", "ID3v1:Comments"):
        if keywords := deep_split(metadata.get(tag)):
            return keywords
    return []


def get_rating(metadata: dict[str, t.Any]) -> str:
    """Get popularity from metadata dict."""
    ret = metadata.get("MWG:Rating")
    if ret is not None and ret != "":
        return str(ret)
    return get_popularity(metadata) or None


def get_popularity(metadata: dict[str, t.Any]) -> str:
    """Get popularity from metadata dict.

    Looking for rating=(integer) in ID3v2_3:Popularimeter
    Winamp uses 0 .. 255. I use 0 .. 10 scale. So convert as follows:
    multiples or 25 in this range are divided 25
    Other integers are zero-padded to 3 digits.
    Other values are returns as-is

    >>> get_popularity({"ID3v2_3:Popularimeter": "Rating=125"})
    '5'
    >>> get_popularity({"ID3v2_3:Popularimeter": "rating@winamp.com Rating=250 Count=0"})
    '10'
    >>> get_popularity({"ID3v2_3:Popularimeter": "Rating=17"})
    '17'
    >>> get_popularity({"ID3v2_3:Popularimeter": "Rating=300"})
    '300'
    >>> get_popularity({"ID3v2_3:Popularimeter": "SomeOtherValue"})
    'SomeOtherValue'
    """
    ret = metadata.get("ID3v2_3:Popularimeter")
    if match := re.match(r"Rating\s*=\s*(\d+)(?!\d)", str(ret or ""), flags=re.IGNORECASE):
        ret = int(match.group(1))
        if 0 <= ret <= 250 and ret % 25 == 0:
            return str(int(ret / 25))
        return f"{ret:0>3}"
    return ret


def get_date_time_original(metadata: dict[str, t.Any]) -> str | None:
    """Get DateTimeOriginal from metadata dict.

    Args:
        metadata: Metadata dict as returned by exiftool (or whatever)
    """
    return metadata.get("ExifIFD.DateTimeOriginal") or metadata.get("ID3v1:Year") or None


def get_width(metadata: dict[str, t.Any]) -> int | None:
    """Get width from metadata dict.

    Args:
        metadata: Metadata dict as returned by exiftool (or whatever)
    """
    for key in ("File:ImageWidth", "EXIF:ImageWidth", "Track1:ImageHeight"):
        width = metadata.get(key)
        if width is not None:
            return int(width)
    if match := re.match(r"^(\d+)\D+(\d+)$", str(metadata.get("Composite:ImageSize") or "")):
        return int(match[1])
    return None


def get_height(metadata: dict[str, t.Any]) -> int | None:
    """Get height from metadata dict.

    Args:
        metadata: Metadata dict as returned by exiftool (or whatever)
    """
    for key in ("File:ImageHeight", "EXIF:ImageHeight", "Track1:ImageHeight"):
        height = metadata.get(key)
        if height is not None:
            return int(height)
    if match := re.match(r"^(\d+)\D+(\d+)$", str(metadata.get("Composite:ImageSize") or "")):
        return int(match[2])
    return None


def join_for_digest(strings: list[str]) -> str:
    """Join list of strings into a single string for digest calculation.

    Args:
        strings: List of strings

    Returns:
        Joined string by single semicolon without spaces, with leading and trailing semicolons
    >>> join_for_digest(['apple', 'banana', 'cherry'])
    ';apple;banana;cherry;'
    >>> join_for_digest(['apple'])
    ';apple;'
    >>> join_for_digest([])
    ';'
    >>> join_for_digest(None)
    ';'
    """
    joiner = ";"
    return joiner + "".join(f"{s}{joiner}" for s in strings or [])


def get_face_names(metadata: dict[str, t.Any]) -> list[str]:
    """Get list of known faces from metadata dict.

    Args:
        metadata: Metadata dict as returned by exiftool (or whatever)
    """
    return locale_sorted(
        set(
            face.get("Name")
            for face in get_multi(metadata, "XMP-mwg-rs:RegionInfo.RegionList", default=[])
            if face.get("Name")
        )
    )


def get_known_face_names(metadata: dict[str, t.Any]) -> list[str]:
    """Get list of known faces from metadata dict.

    Args:
        metadata: Metadata dict as returned by exiftool (or whatever)
    """
    return [f for f in uniq_keep_order(get_face_names(metadata)) if f[0].isupper()]


def get_other_face_names(metadata: dict[str, t.Any]) -> list[str]:
    """Get list of other faces from metadata dict.

    Args:
        metadata: Metadata dict as returned by exiftool (or whatever)
    """
    return [f for f in uniq_keep_order(get_face_names(metadata)) if not f[0].isupper()]


def metadata_to_digest(metadata: dict[str, t.Any]) -> dict[str, t.Any]:
    """Convert metadata for table `digest`.

    Args:
        metadata: Metadata dict as returned by exiftool (or whatever)

    Returns:
        Flat dict with table `digest` column names as keys
    """
    return dict(
        width=get_width(metadata),
        height=get_height(metadata),
        orientation=metadata.get("IFD0.Orientation"),
        artist=get_artist(metadata),
        title=get_title(metadata),
        keywords=join_for_digest(get_keywords_list(metadata)),
        known_faces=join_for_digest(get_known_face_names(metadata)),
        other_faces=join_for_digest(get_other_face_names(metadata)),
        album=get_album(metadata),
        track=get_track(metadata),
        rating=get_rating(metadata),
        tld=metadata.get("XMP-iptcCore.CountryCode"),
        state=metadata.get("MWG:State"),
        city=metadata.get("MWG:City"),
        location=metadata.get("MWG:Location"),
        date_time_original=get_date_time_original(metadata),
        tz_offset=metadata.get("EXIF.OffsetTimeOriginal"),
        lat=metadata.get("EXIF.GPSLatitude"),
        lon=metadata.get("EXIF.GPSLongitude"),
        pos_accuracy_m=metadata.get("XMP-exif.GPSHPositioningError"),
        mime_type=metadata.get("File:MIMEType"),
        duration_s=get_duration_s(metadata),
    )
