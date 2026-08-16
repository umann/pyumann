"""Database model utilities."""

import re
import string
import typing as t

from umann.utils.data_utils import return_as_type
from umann.utils.fs_utils import read_file
from umann.utils.log_utils import setup_package_logger
from umann.utils.sql_utils import remove_sql_comments, sort_sqls, split_sql_statements, sql_format

_logger = setup_package_logger()


def get_init_sqls(return_type: t.Type = list) -> list[str] | str:
    ret = sql_format(get_pragmas(return_type=list) + get_ddl(return_type=list) + get_init_data(return_type=list))
    return return_as_type(ret, return_type)


def get_pragmas(return_type: t.Type = list) -> list[str] | str:
    ret = """\
PRAGMA foreign_keys=ON;
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
PRAGMA temp_store=MEMORY;
"""
    return return_as_type(ret, return_type)


def get_ddl(return_type: t.Type = list) -> list[str] | str:
    """Return the list of SQL statements to initialize the database schema."""
    ret = get_ddl_str()
    # _logger.debug(f"0 {ret=}")
    ret = remove_sql_comments(ret)
    # _logger.debug(f"1 {ret=}")
    ret = split_sql_statements(ret)
    # _logger.debug(f"2 {ret=}")
    ret = sort_sqls(ret)
    # _logger.debug(f"3 {ret=}")
    ret = return_as_type(ret, return_type)
    # _logger.debug(f"4 {ret=}")
    return ret


def get_init_data(return_type: t.Type = list) -> list[str] | str:
    ret = split_sql_statements(
        f"""
INSERT OR IGNORE INTO vol (win, unx)
VALUES {", ".join(f"('{i}:', '/mnt/{i.lower()}')" for i in string.ascii_uppercase)};
"""
    )
    # INSERT OR IGNORE INTO engine (engine, data) VALUES
    #     ('google_vision', '{{"gui_url": "https://cloud.google.com/vision"}}')
    # ;
    return return_as_type(ret, return_type)


def get_ddl_str() -> str:
    """Return the SQL statements to initialize the database schema in one string"""
    ddl = read_file(__file__.removesuffix(".py") + "_ddl.sql")
    for sql_str in sql_format(split_sql_statements(ddl), return_type=list):
        # cspell:words chk_ts
        if match := re.search(r"CREATE TABLE (?:IF NOT EXISTS )?`?(\w+)`?.*\bchk_ts\b", sql_str):
            # breakpoint()
            ddl += f"\n{trigger_on_chk_ts(match[1])}"
    return ddl

    # -- DELETE FROM `file_attr` WHERE
    # --    `chk_ts` < CAST(strftime('%s', 'now') - (ABS(random() % 31) + 90) * 86400 AS INTEGER);
    # print(ddl_str)
    # sys.exit()

    # ddl_str = re.sub("^ *-- .*\n", "", ddl_str, flags=re.MULTILINE)
    # ddl_str = re.sub("^ */[*].*?[*]/", "", ddl_str, flags=re.MULTILINE | re.DOTALL)


def trigger_on_chk_ts(table: str) -> str:
    return f"""\

CREATE TRIGGER IF NOT EXISTS {table}_after_insert_set_chk_ts
AFTER INSERT ON `{table}`
FOR EACH ROW
BEGIN
    UPDATE `{table}` SET `chk_ts` = UNIXEPOCH('subsec') WHERE `id` = NEW.`id`;
END;

CREATE TRIGGER IF NOT EXISTS {table}_after_update_chk_ts
AFTER UPDATE ON `{table}`
FOR EACH ROW
WHEN NEW.chk_ts = OLD.chk_ts
BEGIN
    UPDATE `{table}` SET `chk_ts` = UNIXEPOCH('subsec') WHERE `id` = NEW.`id`;
END;"""


# if __name__ == "__main__":
#    print(sql_format(get_ddl()))
# print("\n".join(f"{single_line(remove_sql_comments(sql)).strip()};" for sql in filter(None, get_ddl_list())))

if __name__ == "__main__":
    # for idx, sql in enumerate(get_init_sqls()):
    # for idx, sql in enumerate(get_ddl()):
    #     print(f"-- -------- {idx}\n{sql};\n")

    SQL = """CREATE TABLE IF NOT EXISTS `keyword` (
    `id`      INTEGER PRIMARY KEY NOT NULL,
    `keyword` TEXT NOT NULL,  -- keyword/tag/label/subject
    `lang`    CHAR(2) NOT NULL DEFAULT 'hu',  -- ISO 639-1 language code
    `mid_id`  INTEGER REFERENCES `mid` (`id`) ON DELETE RESTRICT,
    UNIQUE (`keyword`, `lang`),
    CHECK (
        LENGTH(`keyword`) > 0 AND `keyword` NOT LIKE ' %' AND `keyword` NOT LIKE '% ' AND `keyword` NOT LIKE '%  %'
            AND `keyword` NOT GLOB '*[,;]*'
        AND lang GLOB '[a-z][a-z]'
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
CREATE INDEX IF NOT EXISTS `content_keyword-keyword_id` on content_keyword (`keyword_id`);"""

    sql_format(split_sql_statements(SQL))
    # print(sql_format(split_sql_statements(sql)))
