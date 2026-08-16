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
    CHECK (LENGTH(`dir`) > 0 AND `dir` LIKE '/%'  AND `dir` LIKE '%/' AND `dir` NOT LIKE '%\%')
);

/* basename without dir and ext >might be empty for e.g. .gitignore */
CREATE TABLE IF NOT EXISTS `bas` (
    `id`  INTEGER PRIMARY KEY NOT NULL,
    `bas` TEXT UNIQUE NOT NULL,
    CHECK (`bas` NOT GLOB '*[/\]*')
);

/* extension including dot, or empty string for no extension */
CREATE TABLE IF NOT EXISTS `ext` (
    `id`  INTEGER PRIMARY KEY NOT NULL,
    `ext` TEXT UNIQUE NOT NULL,
    /* Allow empty string or strings starting with '.' and containing no additional '.' or path separators */
    CHECK (
        `ext` = ''
        OR (
            SUBSTR(`ext`, 1, 1) = '.'
            AND INSTR(SUBSTR(`ext`, 2), '.') = 0
            AND INSTR(`ext`, '/') = 0
            -- AND INSTR(`ext`, '\\') = 0
        )
    )
);

CREATE TABLE IF NOT EXISTS `soul` (
    `id`       INTEGER PRIMARY KEY NOT NULL,
    `md5_soul` CHAR(32) UNIQUE,  -- see umann.digest.soul
    CHECK (`md5_soul` IS NULL OR (length(`md5_soul`) = 32 AND NOT `md5_soul` GLOB '*[^0-9a-f]*'))
);

CREATE TABLE IF NOT EXISTS `content` (
    `id`       INTEGER PRIMARY KEY NOT NULL,
    `md5`      CHAR(32) UNIQUE NOT NULL,
    `size`     UNSIGNED INTEGER NOT NULL,
    `soul_id`  INTEGER DEFAULT NULL REFERENCES `soul` (`id`) ON DELETE RESTRICT,
    CHECK (length(`md5`) = 32 AND NOT `md5` GLOB '*[^0-9a-f]*')
);

CREATE INDEX IF NOT EXISTS `content-md5` ON content (`md5`);
CREATE INDEX IF NOT EXISTS `content-size` ON content (`size`);
CREATE INDEX IF NOT EXISTS `content-soul_id` ON content (`soul_id`);

CREATE TABLE IF NOT EXISTS `engine` (
    `id`     INTEGER PRIMARY KEY NOT NULL,
    `engine` TEXT UNIQUE NOT NULL,
    `data`   TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS `engine-engine` on engine (`engine`);

CREATE TABLE IF NOT EXISTS `soul_error` (
    `id` INTEGER PRIMARY KEY NOT NULL,
    `content_id` INTEGER NOT NULL REFERENCES `content` (`id`) ON DELETE CASCADE,
    `message` TEXT NOT NULL,
    `traceback` TEXT,
    UNIQUE (`content_id`)
);
CREATE INDEX IF NOT EXISTS `soul_error-content_id` on soul_error (`content_id`);

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


CREATE INDEX IF NOT EXISTS `file-dir_id` on file (`dir_id`);
CREATE INDEX IF NOT EXISTS `file-bas_id` on file (`bas_id`);
CREATE INDEX IF NOT EXISTS `file-ext_id` on file (`ext_id`);
CREATE INDEX IF NOT EXISTS `file-content_id` on file (`content_id`);

-- Delete orphaned content records when the last referring file is deleted
CREATE TRIGGER IF NOT EXISTS file_after_delete_cleanup_content
AFTER DELETE ON file
FOR EACH ROW
BEGIN
    DELETE FROM content
    WHERE id = OLD.content_id
        AND NOT EXISTS (
            SELECT 1 FROM file WHERE file.content_id = content.id
        );
END;

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


CREATE TABLE IF NOT EXISTS file_metadata (
    `id`      INTEGER PRIMARY KEY NOT NULL,
    `cmd_id`  INTEGER NOT NULL REFERENCES `cmd` (`id`) ON DELETE RESTRICT,  -- e.g. 'exiftool -G1 -struct'
    `file_id` INTEGER NOT NULL REFERENCES `file` (`id`) ON DELETE CASCADE,
    `json`    TEXT NOT NULL, -- FS-specific (e.g System: for exiftool -G1) tags
    `chk_ts`  REAL NOT NULL DEFAULT (unixepoch()), -- unix timestamp of last check
    UNIQUE (`cmd_id`, `file_id`)
);

CREATE INDEX IF NOT EXISTS `file_metadata-file_id` ON `file_metadata` (`file_id`);
CREATE INDEX IF NOT EXISTS `file_metadata-chk_ts` ON `file_metadata` (`chk_ts`);
CREATE INDEX IF NOT EXISTS `file_metadata-cmd_id` ON `file_metadata` (`cmd_id`);


CREATE TABLE IF NOT EXISTS content_metadata (
    `id`         INTEGER PRIMARY KEY NOT NULL,
    `cmd_id`     INTEGER NOT NULL REFERENCES `cmd` (`id`) ON DELETE RESTRICT,
    `content_id` INTEGER NOT NULL REFERENCES `content` (`id`) ON DELETE CASCADE,
    `json`       TEXT NOT NULL,  -- all content-specific metadata, i.e. no FS-specific
                                 -- (e.g System: for exiftool -G1) tags
    `chk_ts`     REAL NOT NULL DEFAULT (unixepoch()), -- unix timestamp of last check
    UNIQUE (`cmd_id`, `content_id`)
);


CREATE INDEX IF NOT EXISTS `content_metadata-content_id` ON `content_metadata` (`content_id`);
CREATE INDEX IF NOT EXISTS `content_metadata-chk_ts` ON `content_metadata` (`chk_ts`);

/* Clean up old metadata entries with a random timeout between 90 and 120 days */
-- DELETE FROM `content_metadata` WHERE
--    `chk_ts` < CAST(strftime('%s', 'now') - (ABS(random() % 31) + 90) * 86400 AS REAL);

/* Exif metadata highlights.
Columns names with CamelCase are mapped from EXIF tags as-is. They are also in table content_metadata. */
CREATE TABLE IF NOT EXISTS `digest` (
    `id`                 INTEGER PRIMARY KEY NOT NULL,
    `content_id`         INTEGER NOT NULL UNIQUE REFERENCES `content` (`id`) ON DELETE CASCADE,
    `width`              INTEGER,  -- ImageWidth
    `height`             INTEGER,  -- ImageHeight
    `orientation`        TEXT,     -- Orientation
    `artist`             TEXT,     -- Creator of photo/video, performer of audio
    `title`              TEXT,     -- Caption-Abstract of image or title of audio/video
    `keywords`           TEXT,     -- ';'-separated with leading and trailing ';'
                                   -- same as in table keyword, here for easy searching
    `known_faces`        TEXT,     -- ';'-separated with leading and trailing ';' of face stating with capital letter
    `other_faces`        TEXT,     -- ';'-separated with leading and trailing ';'
    `rating`             TEXT,     -- Rating
    `tld`                TEXT,     -- 2-letter CountryCode
    `state`              TEXT,     -- State or Province (county in Hungary)
    `city`               TEXT,     -- City
    `location`           TEXT,     -- Sublocation/Location
    `date_time_original` TEXT,     -- DateTimeOriginal for video/photos; might be just Year for audio. Date sep is '-'
    `tz_offset`          CHAR(6),  -- OffsetTimeOriginal '-04:00', '+02:00' etc. NOT 'Z' but '+00:00'
    `lat`                REAL,     -- GPSLatitude
    `lon`                REAL,     -- GPSLongitude
    `pos_accuracy_m`     REAL,     -- GPSHPositioningError (in meters)
    `mime_type`          TEXT,     -- like image/jpeg, video/x-msvideo, video/quicktime, video/mp4, audio/mpeg
    `taken_ts`           REAL,     -- unix timestamp when photo was taken
    `duration_s`         REAL,     -- Duration for audio/video files (is seconds)
    `region`             TEXT,     -- Geo region info. NOTE: not an EXIF tag, but derived from Keywords
    `album`              TEXT,     -- album for music, film roll identifier for scanned images
    `track`              TEXT,     -- track number for music, frame number for scanned images
    `chk_ts`             REAL NOT NULL DEFAULT (unixepoch()), -- unix timestamp of last check
    CHECK (`lat` IS NULL OR (`lat` BETWEEN -90.0 AND 90.0)),
    CHECK (`lon` IS NULL OR (`lon` BETWEEN -180.0 AND 180.0))
    /*
    CHECK (
        CASE WHEN `mime_type` LIKE 'image/%' OR `mime_type` LIKE 'video/%' THEN 1 ELSE 0 END
        = CASE WHEN `width` IS NOT NULL AND `width` > 0 AND `height` IS NOT NULL AND `height` > 0 THEN 1 ELSE 0 END
    ),
    CHECK (
        CASE WHEN `mime_type` LIKE 'audio/%' OR `mime_type` LIKE 'video/%' THEN 1 ELSE 0 END
        = CASE WHEN `duration_s` IS NOT NULL AND `duration_s` >= 0 THEN 1 ELSE 0 END
    )
    */
);
CREATE INDEX IF NOT EXISTS `digest-width-height` on digest (`width`, `height`);
CREATE INDEX IF NOT EXISTS `digest-height` on digest (`height`);
CREATE INDEX IF NOT EXISTS `digest-orientation` on digest (`orientation`);
CREATE INDEX IF NOT EXISTS `digest-artist` on digest (`artist`);
CREATE INDEX IF NOT EXISTS `digest-title` on digest (`title`);
CREATE INDEX IF NOT EXISTS `digest-keywords` on digest (`keywords`);
CREATE INDEX IF NOT EXISTS `digest-rating` on digest (`rating`);
CREATE INDEX IF NOT EXISTS `digest-tld` on digest (`tld`);
CREATE INDEX IF NOT EXISTS `digest-state` on digest (`state`);
CREATE INDEX IF NOT EXISTS `digest-city` on digest (`city`);
CREATE INDEX IF NOT EXISTS `digest-location` on digest (`location`);
CREATE INDEX IF NOT EXISTS `digest-date_time_original` on digest (`date_time_original`);
CREATE INDEX IF NOT EXISTS `digest-tz_offset` on digest (`tz_offset`);
CREATE INDEX IF NOT EXISTS `digest-lat-lon` on digest (`lat`, `lon`);
-- CREATE INDEX IF NOT EXISTS `digest-pos_accuracy_m` on digest (`pos_accuracy_m`);
CREATE INDEX IF NOT EXISTS `digest-taken_ts` on digest (`taken_ts`);
CREATE INDEX IF NOT EXISTS `digest-duration_s` on digest (`duration_s`);
CREATE INDEX IF NOT EXISTS `digest-region` on digest (`region`);
CREATE INDEX IF NOT EXISTS `digest-chk_ts` on digest (`chk_ts`);

-- /* as seen in .picasa.ini */
-- CREATE TABLE IF NOT EXISTS `picasa_file_entry` (
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
-- CREATE INDEX IF NOT EXISTS `picasa_file_entry-crop` on picasa_file_entry (`crop`);
-- CREATE INDEX IF NOT EXISTS `picasa_file_entry-faces` on picasa_file_entry (`faces`);
-- CREATE INDEX IF NOT EXISTS `picasa_file_entry-filters` on picasa_file_entry (`filters`);
-- CREATE INDEX IF NOT EXISTS `picasa_file_entry-redo` on picasa_file_entry (`redo`);
-- CREATE INDEX IF NOT EXISTS `picasa_file_entry-rotate` on picasa_file_entry (`rotate`);
-- CREATE INDEX IF NOT EXISTS `picasa_file_entry-star` on picasa_file_entry (`star`);
-- CREATE INDEX IF NOT EXISTS `picasa_file_entry-chk_ts` on picasa_file_entry (`chk_ts`);
--
-- trigger_on_chk_ts('picasa_file_entry')

CREATE TABLE IF NOT EXISTS `mid` (
    `id`      INTEGER PRIMARY KEY NOT NULL,
    `mid`     TEXT UNIQUE NOT NULL, -- as seen in Google Knowledge Graph
    CHECK (LENGTH(`mid`) > 0 AND MID NOT LIKE '% %')
);

CREATE TABLE IF NOT EXISTS `keyword` (
    `id`      INTEGER PRIMARY KEY NOT NULL,
    `keyword` TEXT NOT NULL,  -- keyword/tag/label/subject
    `lang`    CHAR(2) NOT NULL DEFAULT 'hu',  -- ISO 639-1 language code
    `mid_id`  INTEGER REFERENCES `mid` (`id`) ON DELETE RESTRICT,
    UNIQUE (`keyword`, `lang`),
    CHECK (
        LENGTH(`keyword`) > 0 AND `keyword` NOT LIKE ' %' AND `keyword` NOT LIKE '% ' AND `keyword` NOT LIKE '%  %'
            AND `keyword` NOT GLOB '*[,;]*'
        -- AND lang GLOB '[a-z][a-z]'
    )
);

/*
CREATE TABLE IF NOT EXISTS `translate` (
    `id`      INTEGER PRIMARY KEY NOT NULL,
    `hu_keyword_id` INTEGER NOT NULL REFERENCES `keyword` (`id`) ON DELETE RESTRICT,
    `en_keyword_id` INTEGER NOT NULL REFERENCES `keyword` (`id`) ON DELETE RESTRICT,
    UNIQUE (`hu_keyword_id`, `en_keyword_id`)
);
CREATE INDEX IF NOT EXISTS `translate-hu_keyword_id` on translate (`hu_keyword_id`);
CREATE INDEX IF NOT EXISTS `translate-en_keyword_id` on translate (`en_keyword_id`);
*/

-- This is also in table content_metadata.
CREATE TABLE IF NOT EXISTS `content_keyword` (
    `id` INTEGER PRIMARY KEY NOT NULL,
    `content_id` INTEGER NOT NULL REFERENCES `content` (`id`) ON DELETE CASCADE,
    `keyword_id` INTEGER NOT NULL REFERENCES `keyword` (`id`) ON DELETE CASCADE,
    UNIQUE (`content_id`, `keyword_id`)
);
CREATE INDEX IF NOT EXISTS `content_keyword-keyword_id` on content_keyword (`keyword_id`);

CREATE TABLE IF NOT EXISTS `person` (
    `id`  INTEGER PRIMARY KEY NOT NULL,
    `hex` TEXT,  -- as seen in %APPDATA%\Local\Google\Picasa2\Contacts\contacts.xml
    -- If hex is NULL, (nick+namespace) uniqueness is enforced thru _hex_not_null
    `_hex_not_null` TEXT GENERATED ALWAYS AS (COALESCE(`hex`, '')) STORED,
    `emails`      TEXT,  -- comma separated email addresses from %APPDATA%\Local\Google\Picasa2\Contacts\contacts.xml
    `nick`        TEXT NOT NULL, -- Real Name or nickname of person
    `namespace`   TEXT, -- DEFAULT 'http://umann.hu/kornel/picasa/1.0/',
    -- Picasa allows same nick for different persons (contacts).
    -- Name can be modified in Picasa so different images with same hex might have different nicks.
    -- These will be stored as separate person records.
    -- If namespace is NULL, there is no uniqueness constraint neither on nick nor on hex nor on their
    -- combination.
    -- Not however if you have name only, get_id will always return the first match.
    UNIQUE (`hex`, `nick`, `namespace`),
    UNIQUE (`nick`, `_hex_not_null`, `namespace`),
    CHECK (`hex` IS NULL OR (length(`hex`) BETWEEN 1 AND 16 AND NOT `hex` GLOB '*[^0-9a-f]*'))
);

-- This is also in table content_metadata.
-- Could be called content_person but persons might appear as Creator in content, too
CREATE TABLE IF NOT EXISTS `face` (
    `id`    INTEGER PRIMARY KEY NOT NULL,
    `content_id` INTEGER NOT NULL REFERENCES `content` (`id`) ON DELETE RESTRICT,
    `person_id`  INTEGER REFERENCES `person` (`id`) ON DELETE RESTRICT,
    `rect64`     TEXT, -- as seen in .picasa.ini
    `X`          REAL, -- as seen in XMP-mwg-rs:RegionInfo.RegionList[].Area.H (left, percentage of width)
    `Y`          REAL, -- as seen in XMP-mwg-rs:RegionInfo.RegionList[].Area.V (upper, percentage of height)
    `W`          REAL, -- as seen in XMP-mwg-rs:RegionInfo.RegionList[].Area.W (width, percentage of width)
    `H`          REAL, -- as seen in XMP-mwg-rs:RegionInfo.RegionList[].Area.H (height, percentage of height)
    UNIQUE (`content_id`, `X`, `Y`, `W`, `H`),
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

CREATE INDEX IF NOT EXISTS `face-person_id` on face (`person_id`);
