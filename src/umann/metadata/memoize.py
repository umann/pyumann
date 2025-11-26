"""Module to persistently memoize file metadata using an SQLite database."""

import json
import os
import re
import sqlite3
import stat
import string
import sys
import typing as t
from contextlib import contextmanager, suppress
from functools import lru_cache

from munch import DefaultMunch, Munch

from umann.config import get_config

# from umann.metadata.picasa import is_file_for_picasa
from umann.utils.data_utils import dict_only_keys, get_multi, split_dict
from umann.utils.fs_utils import SLASHB, md5_file, urealpath, vol_type

# from umann.metadata.md5_sum import md5_sum
# from umann.metadata.soul import md5_soul
# from umann.metadata.mp3_metadata import get_mp3_metadata


class NotARegularFileError(OSError):
    """Exception raised when a given path is not a regular file."""


sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

PATH_RE0 = r"(?=/)(?P<dir>.*/)(?P<bas>[^/]+?)(?P<ext>(?:[.][^./]*)?)"
FULLPATH_PATTERN = dict(
    win=re.compile(rf"^(?P<vol>[A-Z]:){PATH_RE0}$"),
    unx=re.compile(rf"^(?P<vol>(?:/mnt/[a-z])?){PATH_RE0}$"),
)[vol_type()]


@lru_cache
def db_conn():
    def munch_factory(cursor: sqlite3.Cursor, row: t.Sequence[t.Any]) -> Munch:
        return Munch({col[0]: row[i] for i, col in enumerate(cursor.description)})

    connection = sqlite3.connect(get_config("memoize.db.path"))
    connection.row_factory = munch_factory
    # Access the attribute to satisfy static analysis (vulture) – sqlite3 uses it implicitly.
    _ = connection.row_factory  # noqa: F841
    return connection


@contextmanager
def get_cursor() -> t.Generator[sqlite3.Cursor, None, None]:
    """Yield a cursor wrapped in a transaction.

    - Commits when the with-block exits cleanly
    - Rolls back if an exception escapes the with-block
    - Always closes the cursor
    """
    connection = db_conn()
    cur = connection.cursor()
    try:
        yield cur
    except sqlite3.Error:
        # Ensure we don't persist partial writes on error
        connection.rollback()
        raise
    else:
        connection.commit()
    finally:
        try:
            cur.close()
        except sqlite3.Error:
            pass


# def single_line(string: str) -> str:
#     return re.sub(r" */[*].*?[*]/ *", " ", " ".join(string.split()).replace("( ", "(").replace(" )", ")"))


def trigger_on_chk_ts(table: str) -> str:
    return f"""\

CREATE TRIGGER IF NOT EXISTS {table}_after_insert_set_chk_ts
AFTER INSERT ON {table}
FOR EACH ROW
BEGIN
UPDATE {table} SET chk_ts = unixepoch('subsec') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS {table}_after_update_chk_ts
AFTER UPDATE ON {table}
FOR EACH ROW
WHEN NEW.chk_ts = OLD.chk_ts
BEGIN
    UPDATE {table} SET
        chk_ts = unixepoch()
    WHERE id = NEW.id;
END;"""


def init():
    sqls_str = rf"""
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=MEMORY;
PRAGMA temp_store=MEMORY;

/* Command: CLI with args before file name like exiftool -struct -G1 */
CREATE TABLE IF NOT EXISTS `cmd` (
    `id`  INTEGER PRIMARY KEY NOT NULL,
    `cmd` TEXT UNIQUE NOT NULL,
    CHECK (LENGTH(`cmd`) > 0)
);

/* Volume: mount point (unx) or drive (win) */
CREATE TABLE IF NOT EXISTS `vol` (
    `id`  INTEGER PRIMARY KEY NOT NULL,
    `unx` TEXT DEFAULT NULL,  -- e.g. /mnt/c (under Unix)
    `win` TEXT DEFAULT NULL,  -- e.g. C: (under Windows)
    CHECK (unx IS NOT NULL OR win IS NOT NULL)
    UNIQUE(unx),
    UNIQUE(win)
);

-- /* Auto-fill missing unx/win on insert */
-- CREATE TRIGGER IF NOT EXISTS vol_before_insert_autofill
-- AFTER INSERT ON vol
-- FOR EACH ROW
-- WHEN NEW.unx IS NULL OR NEW.win IS NULL
-- BEGIN
--     UPDATE vol SET
--         unx = CASE
--             WHEN NEW.unx IS NULL AND NEW.win GLOB '[A-Z]:' THEN '/mnt/' || LOWER(SUBSTR(NEW.win, 1, 1))
--             ELSE NEW.unx
--         END,
--         win = CASE
--             WHEN NEW.win IS NULL AND NEW.unx GLOB '/mnt/[a-z]' THEN UPPER(SUBSTR(NEW.unx, 6, 1)) || ':'
--             ELSE NEW.win
--         END
--     WHERE id = NEW.id;
-- END;

/* Directory: must start with / and end with / . Might be a single / */
CREATE TABLE IF NOT EXISTS `dir` (
    `id` INTEGER PRIMARY KEY NOT NULL,
    `dir`    TEXT UNIQUE NOT NULL,
    CHECK (LENGTH(`dir`) > 0 AND `dir` LIKE '/%'  AND `dir` LIKE '%/' AND `dir` NOT LIKE '%{SLASHB}%')
);

/* basename without dir and ext >might be empty for e.g. .gitignore */
CREATE TABLE IF NOT EXISTS `bas` (
    `id`  INTEGER PRIMARY KEY NOT NULL,
    `bas` TEXT UNIQUE NOT NULL,
    CHECK (`bas` NOT GLOB '*[/{SLASHB}]*')
);

/* extension including dot, or empty string for no extension */
CREATE TABLE IF NOT EXISTS `ext` (
    `id`  INTEGER PRIMARY KEY NOT NULL,
    `ext` TEXT UNIQUE NOT NULL,
    /* Allow empty string or strings starting with '.' and containing no additional '.' or path separators */
    CHECK (
        `ext` = ""
        OR (
            SUBSTR(`ext`, 1, 1) = "."
            AND INSTR(SUBSTR(`ext`, 2), ".") = 0
            AND INSTR(`ext`, "/") = 0
            AND INSTR(`ext`, "{SLASHB}") = 0
        )
    )
);

CREATE TABLE IF NOT EXISTS `content` (
    `id`       INTEGER PRIMARY KEY NOT NULL,
    `md5`      CHAR(32) UNIQUE NOT NULL,
    `size`     UNSIGNED INTEGER NOT NULL,
    `md5_soul` CHAR(32) DEFAULT NULL,  -- see umann.digest.soul
    CHECK (
        length(`md5`) = 32
        AND NOT `md5` GLOB '*[^0-9a-f]*'
        AND (
            `md5_soul` IS NULL
            OR (length(`md5_soul`) = 32 AND NOT `md5_soul` GLOB '*[^0-9a-f]*')
        )
    )
);

CREATE TABLE IF NOT EXISTS `file` (
    `id`      INTEGER PRIMARY KEY NOT NULL,
    `vol_id`  INTEGER NOT NULL REFERENCES `vol` (`id`) ON DELETE RESTRICT,
    `dir_id`  INTEGER NOT NULL REFERENCES `dir` (`id`) ON DELETE RESTRICT,
    `bas_id`  INTEGER NOT NULL REFERENCES `bas` (`id`) ON DELETE RESTRICT,
    `ext_id`  INTEGER NOT NULL REFERENCES `ext` (`id`) ON DELETE RESTRICT,
    `mtime`   REAL NOT NULL, -- unix timestamp. Note: under Windows with Perl, must handle DST bug. Py does this.
    `chk_ts`  REAL NOT NULL DEFAULT (unixepoch()), -- unix timestamp of last check
    `content_id`  INTEGER NOT NULL REFERENCES `content` (`id`) ON DELETE RESTRICT,
    `deleted` INTEGER NOT NULL DEFAULT 0,
    UNIQUE (`vol_id`, `dir_id`, `bas_id`, `ext_id`)
);

/* Ensure bas + ext is not empty string */
CREATE TRIGGER IF NOT EXISTS file_before_insert_check_bas_ext
BEFORE INSERT ON file
FOR EACH ROW
BEGIN
    SELECT CASE
        WHEN (SELECT bas FROM bas WHERE id = NEW.bas_id) || (SELECT ext FROM ext WHERE id = NEW.ext_id) = ''
        THEN RAISE(ABORT, 'bas + ext cannot be empty string')
    END;
END;

{trigger_on_chk_ts('file')}

CREATE INDEX IF NOT EXISTS `file-dir_id` on file (`dir_id`);
CREATE INDEX IF NOT EXISTS `file-bas_id` on file (`bas_id`);
CREATE INDEX IF NOT EXISTS `file-ext_id` on file (`ext_id`);
CREATE INDEX IF NOT EXISTS `file-content_id` on file (`content_id`);

CREATE TABLE IF NOT EXISTS file_metadata (
    `id`      INTEGER PRIMARY KEY NOT NULL,
    `cmd_id`  INTEGER NOT NULL REFERENCES `cmd` (`id`) ON DELETE RESTRICT,  -- e.g. "exiftool -G1 -struct"
    `file_id` INTEGER NOT NULL REFERENCES `file` (`id`) ON DELETE CASCADE,
    `json`    TEXT NOT NULL, -- FS-specific (e.g System: for exiftool -G1) tags
    `chk_ts`  REAL NOT NULL DEFAULT (unixepoch()), -- unix timestamp of last check
    UNIQUE (`cmd_id`, `file_id`)
);

{trigger_on_chk_ts('file')}

CREATE INDEX IF NOT EXISTS `file_metadata-cmd_id` ON `file_metadata` (`cmd_id`);
CREATE INDEX IF NOT EXISTS `file_metadata-file_id` ON `file_metadata` (`file_id`);
CREATE INDEX IF NOT EXISTS `file_metadata-chk_ts` ON `file_metadata` (`chk_ts`);

CREATE TABLE IF NOT EXISTS content_metadata (
    `id`         INTEGER PRIMARY KEY NOT NULL,
    `cmd_id`     INTEGER NOT NULL REFERENCES `cmd` (`id`) ON DELETE RESTRICT,  -- e.g. "exiftool -G1 -struct"
    `content_id` INTEGER NOT NULL REFERENCES `content` (`id`) ON DELETE CASCADE,
    `json`       TEXT NOT NULL,  -- all content-specific metadata, i.e. no FS-specific
                                -- (e.g System: for exiftool -G1) tags
    `chk_ts`     REAL NOT NULL DEFAULT (unixepoch()), -- unix timestamp of last check
    UNIQUE (`cmd_id`, `content_id`)
);

{trigger_on_chk_ts('file')}

CREATE INDEX IF NOT EXISTS `content_metadata-cmd_id` ON `content_metadata` (`cmd_id`);
CREATE INDEX IF NOT EXISTS `content_metadata-content_id` ON `content_metadata` (`content_id`);
CREATE INDEX IF NOT EXISTS `content_metadata-chk_ts` ON `content_metadata` (`chk_ts`);

/* Clean up old metadata entries with a random timeout between 90 and 120 days */
-- DELETE FROM `content_metadata` WHERE
--    `chk_ts` < CAST(strftime('%s', 'now') - (ABS(random() % 31) + 90) * 86400 AS REAL);

/* Exif metadata highlights.
Columns names with CamelCase are mapped from EXIF tags as-is. They are also in table content_metadata. */
CREATE TABLE IF NOT EXISTS `exif` (
    `id`                   INTEGER PRIMARY KEY NOT NULL,
    `content_id`           INTEGER NOT NULL REFERENCES `content` (`id`) ON DELETE CASCADE,
    `ImageWidth`           INTEGER NOT NULL,
    `ImageHeight`          INTEGER NOT NULL,
    `Orientation`          TEXT,
    `Creator`              TEXT,
    `Description`          TEXT,
    `Keywords`             TEXT,  -- comma-separated; same as in keyword, here for easy searching
    `Rating`               TEXT,
    `CountryCode`          TEXT,
    `State`                TEXT,
    `City`                 TEXT,
    `Location`             TEXT,
    `DateTimeOriginal`     TEXT,
    `OffsetTimeOriginal`   CHAR(6),
    `GPSLatitude`          REAL,
    `GPSLongitude`         REAL,
    `GPSHPositioningError` REAL,
--     `taken_ts`             INTEGER,  -- unix timestamp when photo was taken
--     `duration_sec`         REAL,
--     `region`               TEXT,  -- Geo region info. NOTE: not an exif tag, but derived from Keywords
    `chk_ts`  REAL NOT NULL DEFAULT (unixepoch()), -- unix timestamp of last check
    UNIQUE (`content_id`)  -- Do not allow the same content to have multiple exif entries
);
CREATE INDEX IF NOT EXISTS `exif-ImageWidth-ImageHeight` on exif (`ImageWidth`, `ImageHeight`);
CREATE INDEX IF NOT EXISTS `exif-Orientation` on exif (`Orientation`);
CREATE INDEX IF NOT EXISTS `exif-Creator` on exif (`Creator`);
CREATE INDEX IF NOT EXISTS `exif-Description` on exif (`Description`);
CREATE INDEX IF NOT EXISTS `exif-Keywords` on exif (`Keywords`);
CREATE INDEX IF NOT EXISTS `exif-Rating` on exif (`Rating`);
CREATE INDEX IF NOT EXISTS `exif-CountryCode` on exif (`CountryCode`);
CREATE INDEX IF NOT EXISTS `exif-State` on exif (`State`);
CREATE INDEX IF NOT EXISTS `exif-City` on exif (`City`);
CREATE INDEX IF NOT EXISTS `exif-Location` on exif (`Location`);
CREATE INDEX IF NOT EXISTS `exif-DateTimeOriginal` on exif (`DateTimeOriginal`);
CREATE INDEX IF NOT EXISTS `exif-OffsetTimeOriginal` on exif (`OffsetTimeOriginal`);
CREATE INDEX IF NOT EXISTS `exif-GPSLatitude-GPSLongitude` on exif (`GPSLatitude`, `GPSLongitude`);
CREATE INDEX IF NOT EXISTS `exif-GPSHPositioningError` on exif (`GPSHPositioningError`);
-- CREATE INDEX IF NOT EXISTS `exif-taken_ts` on exif (`taken_ts`);
-- CREATE INDEX IF NOT EXISTS `exif-duration_sec` on exif (`duration_sec`);
-- CREATE INDEX IF NOT EXISTS `exif-region` on exif (`region`);
CREATE INDEX IF NOT EXISTS `exif-chk_ts` on exif (`chk_ts`);

{trigger_on_chk_ts('file')}

-- /* as seen in .picasa.ini */
-- CREATE TABLE IF NOT EXISTS `picasa` (
--     `id`      INTEGER PRIMARY KEY NOT NULL,
--     `file_id` INTEGER NOT NULL REFERENCES `file` (`id`) ON DELETE CASCADE,
--     `crop`    TEXT,
--     `faces`   TEXT,
--     `filters` TEXT,
--     `redo`    TEXT,
--     `rotate`  TEXT,
--     `star`    TEXT,
--     `chk_ts`  REAL NOT NULL, -- unix timestamp of last check
--     `json`    TEXT,  -- all the fields (incl. above ones)
--     UNIQUE (`file_id`)
-- );
-- CREATE INDEX IF NOT EXISTS `picasa-crop` on picasa (`crop`);
-- CREATE INDEX IF NOT EXISTS `picasa-faces` on picasa (`faces`);
-- CREATE INDEX IF NOT EXISTS `picasa-filters` on picasa (`filters`);
-- CREATE INDEX IF NOT EXISTS `picasa-redo` on picasa (`redo`);
-- CREATE INDEX IF NOT EXISTS `picasa-rotate` on picasa (`rotate`);
-- CREATE INDEX IF NOT EXISTS `picasa-star` on picasa (`star`);
-- CREATE INDEX IF NOT EXISTS `picasa-chk_ts` on picasa (`chk_ts`);
--
-- {trigger_on_chk_ts('file')}

-- This is also in table content_metadata.
CREATE TABLE IF NOT EXISTS `keyword` (
    `id` INTEGER PRIMARY KEY NOT NULL,
    `content_id`     INTEGER NOT NULL REFERENCES `content` (`id`) ON DELETE CASCADE,
    `keyword`    TEXT NOT NULL,
    UNIQUE (`content_id`, `keyword`)
);
CREATE INDEX IF NOT EXISTS `keyword-keyword` on keyword (`keyword`);

CREATE TABLE IF NOT EXISTS `contact` (
    `id`  INTEGER PRIMARY KEY NOT NULL,
    `contact_hex` CHAR(16) UNIQUE,  -- as seen in %APPDATA%\Local\Google\Picasa2\Contacts\contacts.xml
    `emails`      TEXT, -- comma separated email addresses from %APPDATA%\Local\Google\Picasa2\Contacts\contacts.xml
    `nick`        TEXT NOT NULL UNIQUE, -- Real Name or nickname of person
    `namespace`   TEXT DEFAULT NULL, -- DEFAULT "http://umann.hu/kornel/picasa/1.0/",
    UNIQUE (`nick`, `namespace`),  -- Picasa allows same nick for different contacts, we do not

    CHECK (`contact_hex` IS NULL OR (length(`contact_hex`) BETWEEN 1 AND 16 AND NOT `contact_hex` GLOB '*[^0-9a-f]*'))
);
CREATE INDEX IF NOT EXISTS `contact-nick` on contact (`nick`);

-- This is also in table content_metadata.
CREATE TABLE IF NOT EXISTS `face` (
    `id`    INTEGER PRIMARY KEY NOT NULL,
    `content_id`     INTEGER NOT NULL REFERENCES `content` (`id`) ON DELETE RESTRICT,
    `contact_id` INTEGER REFERENCES `contact` (`id`) ON DELETE RESTRICT,
    -- `name`       TEXT, -- as seen in XMP-mwg-rs:RegionInfo.RegionList[].Name
    `rect64`     CHAR(16), -- as seen in .picasa.ini
    `X`          REAL, -- as seen in XMP-mwg-rs:RegionInfo.RegionList[].Area.H (left, percentage of width)
    `Y`          REAL, -- as seen in XMP-mwg-rs:RegionInfo.RegionList[].Area.V (upper, percentage of height)
    `W`          REAL, -- as seen in XMP-mwg-rs:RegionInfo.RegionList[].Area.W (width, percentage of width)
    `H`          REAL, -- as seen in XMP-mwg-rs:RegionInfo.RegionList[].Area.H (height, percentage of height)
    UNIQUE (`contact_id`, `content_id`, `rect64`),
    UNIQUE (`contact_id`, `content_id`, `X`, `Y`, `W`, `H`),
    -- UNIQUE (`name`, `content_id`, `rect64`),
    -- UNIQUE (`name`, `content_id`, `X`, `Y`, `W`, `H`),
    UNIQUE (`content_id`, `rect64`),
    CHECK (
        `rect64` IS NULL OR ((length(`rect64`) BETWEEN 1 AND 16) AND NOT `rect64` GLOB '*[^0-9a-f]*')
        AND (
            (`X` IS NULL AND `Y` IS NULL AND `W` IS NULL AND `H` IS NULL)
            OR (X BETWEEN 0 AND 1 AND Y BETWEEN 0 AND 1 AND W BETWEEN 0 AND 1 AND H BETWEEN 0 AND 1)
        )
        AND (`rect64` IS NOT NULL OR `X` IS NOT NULL)
        /* AND (`contact_id` IS NOT NULL OR `name` IS NOT NULL) */
   )
);

INSERT OR IGNORE INTO vol (win, unx)
    VALUES {', '.join(f'("{i}:", "/mnt/{i.lower()}")' for i in string.ascii_uppercase)};
"""

    # -- DELETE FROM `file_attr` WHERE
    # --    `chk_ts` < CAST(strftime('%s', 'now') - (ABS(random() % 31) + 90) * 86400 AS INTEGER);
    # print(sqls_str)
    # sys.exit()

    # sqls_str = re.sub("^ *-- .*\n", "", sqls_str, flags=re.MULTILINE)
    # sqls_str = re.sub("^ */[*].*?[*]/", "", sqls_str, flags=re.MULTILINE | re.DOTALL)

    sqls = re.split(r"; *\n(?!END)", sqls_str.strip(" \n;"))
    with get_cursor() as cursor:
        for sql in sqls:
            # print(f"--- Executing SQL ---\n{sql.strip()}\n--- End SQL ---")
            execute(cursor, sql)


def flat1(data) -> str | None:
    if isinstance(data, (list, tuple)):
        data = data[0] if data else None
    return data


def flat_more(data) -> str | None:
    if isinstance(data, (list, tuple)):
        data = ", ".join(data) if data else None
    return data


# pylint: disable=too-many-arguments
def get_file_rec(
    fname: str,
    /,
    *,
    func: t.Callable[[str], dict[str, t.Any]] = lambda f: {},
    cmd: str = "",
    fstat=None,
    strict: bool = False,
    on_nonexistent: t.Any = FileNotFoundError,
) -> Munch:
    """Get or create file record in memoization database.

    :param str fname: _description_
    :param _type_ func: _description_, defaults to lambdaf:{}
    :param str cmd: _description_, defaults to ""
    :param _type_ fstat: _description_, defaults to None
    :param bool strict: _description_, defaults to False
    :param t.Any on_nonexistent: _description_, defaults to FileNotFoundError
    :raises NotARegularFileError: _description_
    :raises on_nonexistent: _description_
    :return Munch: _description_
    """

    @lru_cache()
    def _md5_file(fname: str) -> str:
        return md5_file(fname)

    with suppress(FileNotFoundError):
        fstat = fstat or os.stat(fname)
        if not stat.S_ISREG(fstat.st_mode):
            raise NotARegularFileError(f"Not a regular file: {fname}")
    size, mtime = (fstat.st_size, fstat.st_mtime) if fstat else (None, None)

    with get_cursor() as cursor:
        parameters = _get_file_parameters(cursor, cmd, fname)
        if (res := _get_file_rec(cursor, fname, parameters)) is not None:
            if (
                res.size == size
                and res.mtime == mtime
                and (not strict or res.md5 == _md5_file(fname))
                and not res.deleted
            ):
                metadata = {}
                for key in ["file_metadata_json", "content_metadata_json"]:
                    metadata.update(json.loads(res.get(key) or "{}"))
                return metadata
        else:
            res = DefaultMunch()

        res.update(parameters)
        res.fname = fname
        res.func = func

        # return _postprocess_file_rec(cursor, fname, res, size, mtime, func, on_nonexistent)
        _set_file_deleted(cursor, res)  # deletes file record if there is res.file_id

        if res.content_id:
            # delete if no more file refers to this content
            if not select1(cursor, "file", ["id"], dict(content_id=res.content_id)):
                delete1(cursor, "content", dict(id=res.content_id))

        if size is None:
            if isinstance(on_nonexistent, Exception):
                raise on_nonexistent(f"File not found: {res.fname}")
            return on_nonexistent

        res.content_id = res.content_id or get_id(
            cursor, "content", uniq=dict(md5=_md5_file(res.fname)), add=dict(size=size, md5_soul=None)
        )

        if not res.file_id:
            res.update(
                {"vol_id": get_id(cursor, "vol", {vol_type(): parameters.vol})}
                | {f"{tbl}_id": get_id(cursor, tbl, {tbl: parameters[tbl]}) for tbl in ["dir", "bas", "ext"]},
            )

        res.file_id = get_id(
            cursor,
            "file",
            dict_only_keys(res, ["vol_id", "dir_id", "bas_id", "ext_id"]),
            dict(
                content_id=res.content_id,
                mtime=mtime,
                deleted=0,
                # chk_ts=chk_ts,
            ),
        )

        return _handle_metadata(cursor, res)


def _handle_metadata(cursor: sqlite3.Cursor, res: Munch) -> Munch | None:
    if not has_metadata_ext(res.fname):
        return None
    metadata = res.func(res.fname)  # e.g. get_exiftool(res.fname)
    res.file_metadata, res.content_metadata = split_dict(
        metadata, lambda x: not x.split(":")[0] in ("System", "Exiftool", "SourceFile")
    )
    _handle_content_metadata(cursor, res)
    _handle_file_metadata(cursor, res)
    return metadata or None


def _handle_content_metadata(cursor: sqlite3.Cursor, res: Munch) -> None:
    has_kw = has_face = res.ext in get_config("picasa.exts", {})
    if has_kw:
        delete1(cursor, "keyword", where=dict(content_id=res.content_id))
    if has_face:
        delete1(cursor, "face", where=dict(content_id=res.content_id))

    if not res.content_metadata:
        delete1(
            cursor,
            "content_metadata",
            where=dict(cmd_id=res.cmd_id, content_id=res.content_id),
        )
        delete1(cursor, "exif", where=dict(content_id=res.content_id))
        return
    upsert1(
        cursor,
        "content_metadata",
        add=dict(json=json.dumps(res.content_metadata, ensure_ascii=False)),  # , chk_ts=chk_ts),
        uniq=dict(cmd_id=res.cmd_id, content_id=res.content_id),
    )
    upsert1(
        cursor,
        "exif",
        add=metadata_to_exif_highlights(res.content_metadata),  # | dict(chk_ts=chk_ts),
        uniq=dict(content_id=res.content_id),
    )
    if has_kw:
        # MWG:Keywords prefers XMP over IPTC and handles encoding properly
        if keywords_raw := res.content_metadata.get("MWG:Keywords", res.content_metadata.get("XMP-dc:Subject")):
            if not isinstance(keywords_raw, list):  # we use exiftool with -struct so should be list
                keywords_raw = keywords_raw.split(",")
            keywords = [kw.strip() for kw in keywords_raw if kw.strip()]
            insert(cursor, "keyword", [dict(content_id=res.content_id, keyword=kw) for kw in keywords])
    if has_face and (faces := get_multi(res.content_metadata, "XMP-mwg-rs:RegionInfo.RegionList", default=None)):
        # items: list[dict[str, t.Any]] = []
        # TODO: use insert instead of insert1 in loop
        for face in faces:
            contact_id = None
            if nick := face.get("Name"):
                contact_id = get_id(
                    cursor,
                    "contact",
                    dict(
                        nick=nick,
                        namespace=flat1(
                            get_multi(
                                face,
                                "Extensions.XMP-Umann:FaceNamespace",
                                get_config("picasa.namespace", default=None),
                            )
                        ),
                    ),
                    dict(
                        emails="",
                        contact_hex=flat1(get_multi(face, "Extensions.XMP-Umann:FaceID", default=None)),
                    ),
                )
            insert1(
                cursor,
                "face",
                dict(
                    content_id=res.content_id,
                    contact_id=contact_id,
                    # name=nick,
                    rect64=flat1(get_multi(face, "Extensions.XMP-Umann:FaceRect64", default=None)),
                    X=get_multi(face, "Area.H", default=None),
                    Y=get_multi(face, "Area.Y", default=None),
                    W=get_multi(face, "Area.W", default=None),
                    H=get_multi(face, "Area.H", default=None),
                ),
            )


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


def _get_file_parameters(cursor: sqlite3.Cursor, cmd: str, fname: str) -> Munch:
    if match := FULLPATH_PATTERN.search(abs_path := urealpath(fname)):
        # vol, dir, bas, ext
        return Munch(match.groupdict() | dict(cmd_id=get_id_cached(cursor, "cmd", cmd=cmd)))
    raise ValueError(f"Cannot parse volume, dir, bas, ext from fname={fname!r} (abs_path={abs_path!r})")


def _get_file_rec(cursor: sqlite3.Cursor, fname: str, parameters: Munch[str, str]) -> Munch | None:

    if has_metadata_ext(fname):
        select_metadata = """,
file_metadata.json as file_metadata_json,
file_metadata.id as file_metadata_id,
content_metadata.json as content_metadata_json,
content_metadata.id as content_metadata_id"""
        join_metadata = """\
LEFT JOIN file_metadata    ON
    file_metadata.file_id = file.id AND file_metadata.cmd_id = :cmd_id
LEFT JOIN content_metadata ON
    content_metadata.content_id = content.id AND content_metadata.cmd_id = :cmd_id"""
    else:
        select_metadata = ""
        join_metadata = ""

    # def _md5_soul_file(fname: str) -> str:
    #     return md5_soul(fname)

    execute(
        cursor,
        f"""\
SELECT
    file.id as file_id,
    file.mtime,
    file.deleted,
    dir.id as dir_id,
    bas.id as bas_id,
    content.id as content_id,
    content.size,
    content.md5,
    content.md5_soul{select_metadata}
FROM file
    JOIN vol          ON vol.id = file.vol_id
    JOIN dir          ON dir.id = file.dir_id
    JOIN bas          ON bas.id = file.bas_id
    JOIN ext          ON ext.id = file.ext_id
    LEFT JOIN content ON content.id = file.content_id
{join_metadata}
WHERE
    vol.`{vol_type()}` = :vol
    AND dir.dir = :dir
    AND bas.bas = :bas
    AND ext.ext = :ext""",
        parameters,
    )
    return cursor.fetchone()


def _set_file_deleted(cursor: sqlite3.Cursor, res: Munch, cleanup: bool = False):
    if not res.file_id:
        return
    # delete1(cursor, "file", dict(id=res.file_id))
    update1(cursor, "file", add=dict(deleted=1), where=dict(id=res.file_id))
    if cleanup:
        # Check if there are any other files referencing the same bas, ext, content
        tbls = ["dir", "content"]
        if res.bas not in {".picasa"}:  # skip bas cleanup chk for .picasa files, there's a lot of them
            tbls.append("bas")
        for tbl in tbls:
            execute(cursor, f"SELECT file.id FROM file JOIN {tbl} ON {tbl}.id = file.{tbl}_id LIMIT 1")
            if cursor.fetchone() is None:
                delete1(cursor, tbl, dict(id=res[f"{tbl}_id"]))


def metadata_to_exif_highlights(metadata: dict[str, t.Any]) -> dict[str, t.Any]:
    """Convert a metadata dict as returned by exiftool to a flat dict with EXIF tag names as keys.

    Args:
        metadata: Metadata dict as returned by exiftool

    Returns:
        Flat dict with EXIF tag names as keys
    """

    keywords_str = flat_more(metadata.get("MWG:Keywords"))
    creator = flat_more(metadata.get("MWG:Creator", "")).strip() or None
    return dict(
        ImageWidth=metadata.get("File:ImageWidth"),
        ImageHeight=metadata.get("File:ImageHeight"),
        Orientation=metadata.get("IFD0.Orientation"),
        Creator=creator,
        Description=metadata.get("MWG:Description"),
        Keywords=keywords_str,
        Rating=metadata.get("MWG:Rating"),
        CountryCode=metadata.get("XMP-iptcCore.CountryCode"),
        State=metadata.get("MWG:State"),
        City=metadata.get("MWG:City"),
        Location=metadata.get("MWG:Location"),
        DateTimeOriginal=metadata.get("ExifIFD.DateTimeOriginal"),
        OffsetTimeOriginal=metadata.get("EXIF.OffsetTimeOriginal"),
        GPSLatitude=metadata.get("EXIF.GPSLatitude"),
        GPSLongitude=metadata.get("EXIF.GPSLongitude"),
        GPSHPositioningError=metadata.get("XMP-exif.GPSHPositioningError"),
    )


@lru_cache
def get_id_cached(cursor: sqlite3.Cursor, table: str, **uniq) -> int:
    """
    Upsert a dictionary into a SQLite table and return PK id without option to add extra column values

    :param cursor: SQLite cursor object
    :param str table: Name of the table to insert into
    :param dict uniq: keys are column names and values are WHERE to search for/insert
    :return int: PK id value
    """
    return get_id(cursor, table, uniq)


def get_id(
    cursor, table: str, uniq: dict, add: dict | None = None, return_whether_chg: bool = False
) -> int | tuple[int, bool]:
    """
    Upsert a dictionary into a SQLite table and return PK id

    :param cursor: SQLite cursor object
    :param str table: Name of the table to insert into
    :param dict uniq: keys are column names and values are WHERE to search for/insert
    :param dict|None add: additional values to set, defaults to None
    :param bool return_whether_chg: whether to return if a change (insert or update) happened, defaults to False
    :return int | tuple[int,bool]: PK id value or (PK id value, whether_chg) if return_whether_chg is True
    """
    add = add or {}

    pk_ = "id"
    if res := select1(cursor, table, [pk_, *add.keys()], uniq):
        id_ = res.pop(pk_)
        if whether_chg := res != add:
            update1(cursor, table, add, uniq)
    else:
        id_ = insert1(cursor, table, {**uniq, **add})
        whether_chg = True
    return (id_, whether_chg) if return_whether_chg else id_


def select1(cursor: sqlite3.Cursor, table, columns, where) -> dict | None:
    placeholders, values = placeholder_and_values(where)
    sql = f"SELECT {backtick(columns)} FROM `{table}` WHERE {placeholders}"
    execute(cursor, sql, values)
    return cursor.fetchone() or None


def update1(cursor: sqlite3.Cursor, table, add, where, debug: bool = False):
    s_placeholders, s_values = placeholder_and_values(add, "update")
    w_placeholders, w_values = placeholder_and_values(where)
    sql = f"UPDATE {backtick(table)} SET {s_placeholders} WHERE {w_placeholders}"
    if debug:
        print(f"UPDATE {table} SET {add} WHERE {where} sql", file=sys.stderr)
    execute(cursor, sql, s_values + w_values)


def delete1(cursor: sqlite3.Cursor, table, where, debug: bool = False):
    placeholders, values = placeholder_and_values(where)
    sql = f"DELETE FROM {backtick(table)} WHERE {placeholders}"
    if debug:
        print(sql, values, file=sys.stderr)
    execute(cursor, sql, values)


def upsert1(cursor: sqlite3.Cursor, table: str, add: dict, uniq: dict, debug: bool = False) -> int:
    """Upsert a row and return its primary key id.

    Args:
        cursor: SQLite cursor
        table: Table name
        add: Columns to insert or update
        uniq: Unique constraint columns (used for ON CONFLICT)
        debug: Enable debug output

    Returns:
        Primary key id of the inserted or updated row
    """
    placeholders_insert, values_insert = placeholder_and_values(add | uniq, "insert")
    placeholders_conflict, values_conflict = placeholder_and_values(add, "update")

    sql = f"""\
INSERT INTO {backtick(table)} ({backtick((add | uniq).keys())})
VALUES ({placeholders_insert})
ON CONFLICT({backtick(uniq.keys())}) DO UPDATE SET {placeholders_conflict}
RETURNING id\
"""
    if debug:
        print("UPSERT", add, uniq, file=sys.stderr)
        print(sql, values_insert + values_conflict, file=sys.stderr)

    execute(cursor, sql, values_insert + values_conflict)
    return cursor.fetchone()["id"]


def insert1(cursor: sqlite3.Cursor, table: str, add: dict, ignore: bool = False, debug: bool = False) -> int:
    placeholders, values = placeholder_and_values(add, "insert")
    command = "INSERT OR IGNORE" if ignore else "INSERT"
    if debug:
        print(command, add, file=sys.stderr)
    sql = f"{command} INTO {backtick(table)} ({backtick(add.keys())}) values ({placeholders})"
    execute(cursor, sql, values)
    return cursor.lastrowid


def insert(cursor: sqlite3.Cursor, table: str, add: list[dict], ignore: bool = False, debug: bool = False) -> int:
    if not add:
        return None
    values = tuple(v for d in add for v in d.values())
    command = "INSERT OR IGNORE" if ignore else "INSERT"
    if debug:
        print(command, add, file=sys.stderr)
    sql = (
        f"{command} INTO {backtick(table)} ({backtick(add[0].keys())})"
        + f" values {', '.join(['(' + ', '.join(['?'] * len(add[0])) + ')'] * len(add))}"
    )
    execute(cursor, sql, values)
    return cursor.lastrowid


def execute(cursor: sqlite3.Cursor, sql: str, parameters: tuple | dict = ()):
    try:
        return cursor.execute(sql, parameters)
    except sqlite3.Error as e:
        # Show SQL with parameters substituted for easier debugging
        try:
            if isinstance(parameters, dict):
                # Named parameters: replace :name with values
                sql_with_params = sql
                for key, value in parameters.items():
                    sql_with_params = sql_with_params.replace(f":{key}", repr(value))
            else:
                # Positional parameters: replace ? with values
                sql_with_params = sql
                for value in parameters:
                    sql_with_params = sql_with_params.replace("?", repr(value), 1)
        except TypeError as e2:
            # Fallback if substitution fails
            sql_with_params = f"{sql}\n-- Parameters: {parameters}"
            raise sqlite3.Warning(f"{e!r}\n>>>\n{sql_with_params.strip()}\n<<<") from e2

        raise sqlite3.Warning(f"{e!r}\n>>>\n{sql_with_params.strip()}\n<<<") from e


def backtick(columns) -> str:
    if isinstance(columns, str):
        columns = [columns]
    return ", ".join(f"`{c}`" for c in columns)


def placeholder_and_values(where: dict, action: t.Literal["insert", "update", "where"] = "where") -> tuple[str, tuple]:
    if action == "insert":
        placeholders = ", ".join(["?"] * len(where))
    else:  # update or where
        delimiter = ", " if action == "update" else " AND "
        placeholders = delimiter.join(f"{backtick(k)}=?" for k in where.keys())
    values = tuple(where.values())
    return placeholders, values


# def get_memoized(fname, attr, function, stat=None):
#     """With stat, a 2nd call to os.stat can be saved if provided by caller"""
#     with get_cursor() as cursor:
#         file_rec = get_file_rec(cursor, fname, attr, stat)
#         if file_rec.blb is not None:
#             return decode(file_rec.blb)
#         value = function(fname)
#         if isinstance(value, dict):
#             value = {k: v for k, v in value.items() if v is not None and v != ""}
#         insert1(
#             cursor,
#             "content_metadata",
#             {"file_id": file_rec.file_id, "attr": attr, "blb": encode(value), "chk_ts": int(time.time())},
#         )
#         return value


# def encode(obj):
#     return re.sub(
#         r"(?:\n[.][.][.])?\n$", "", yaml.dump(obj, default_flow_style=True, width=1_000)
#     )  # pickle.dumps(obj)


# def decode(BLOB):
#     return yaml.safe_load(BLOB)  # pickle.loads(BLOB)


init()


# -- LEFT JOIN bas as pbas on pbas.bas = '.picasa'
# -- LEFT JOIN ext as pext on pext.ext = '.ini'
# -- LEFT JOIN file as pfile ON
# --    pfile.vol_id = file.vol_id AND pfile.dir_id = file.dir_id
# --    AND pfile.bas_id = pbas.id AND pfile.ext_id = pext.id
