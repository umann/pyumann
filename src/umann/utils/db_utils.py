"""Database utility functions for SQLite."""

import sqlite3
import sys
import typing as t
from collections import defaultdict
from contextlib import contextmanager
from functools import lru_cache

from munch import Munch

from umann.config import get_config
from umann.db.model import get_init_sqls
from umann.utils.data_utils import NotSpecified, any_in, return_as_type, single_line
from umann.utils.log_utils import setup_package_logger
from umann.utils.sql_utils import backtick, placeholder_and_values, sql_format, substitute_parameters_in_sql

_logger = setup_package_logger()


def _initialize_connection(connection: sqlite3.Connection) -> None:
    """Initialize schema and connection pragmas on a newly opened database."""
    with transaction(connection) as cursor:
        for sql in get_init_sqls():
            execute(cursor, sql)


@lru_cache
def db_conn() -> sqlite3.Connection:
    """Open, initialize, and cache the configured database connection lazily."""

    def munch_factory(cursor: sqlite3.Cursor, row: t.Sequence[t.Any]) -> Munch:
        return Munch({col[0]: row[i] for i, col in enumerate(cursor.description)})

    connection = sqlite3.connect(get_config("memoize.db.path"))
    connection.row_factory = munch_factory
    # Access the attribute to satisfy static analysis (vulture) – sqlite3 uses it implicitly.
    _ = connection.row_factory  # noqa: F841
    # Enable foreign key constraints on every connection (not persistent across connections)
    connection.execute("PRAGMA foreign_keys=ON")
    _initialize_connection(connection)
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
    except (sqlite3.Error, MemoryError, KeyboardInterrupt):
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


@contextmanager
def transaction(connection: sqlite3.Connection) -> t.Generator[sqlite3.Cursor, None, None]:
    """Context manager for database transactions.

    Provides a cursor wrapped in automatic transaction management:
    - Commits when the with-block exits cleanly
    - Rolls back if an exception escapes the with-block
    - Always closes the cursor

    Args:
        connection: SQLite database connection

    Yields:
        sqlite3.Cursor: Database cursor

    Example:
        with transaction(db_conn()) as cursor:
            execute(cursor, "INSERT INTO table VALUES (?)")
    """
    cur = connection.cursor()
    try:
        yield cur
    except (sqlite3.Error, MemoryError, KeyboardInterrupt):
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


# pylint: disable=too-many-arguments, too-many-positional-arguments
def get_id(
    cursor,
    table: str,
    uniq: dict,
    add: dict | None = None,
    return_whether_chg: bool = False,
    existing_id: int | None | NotSpecified = NotSpecified,
) -> int | tuple[int, bool | None]:
    """
    Upsert a dictionary into a SQLite table and return PK id

    :param cursor: SQLite cursor object
    :param str table: Name of the table to insert into
    :param dict uniq: keys are column names and values are WHERE to search for/insert
    :param dict|None add: additional values to set, defaults to None
    :param bool return_whether_chg: whether to return if a change (insert or update) happened, defaults to False
    :return int | tuple[int,bool|None]: PK id value or (PK id value, whether_chg) if return_whether_chg is True
        whether_chg is None if new record
    """
    add = add or {}

    if existing_id is not NotSpecified:
        assert not return_whether_chg, "Cannot use existing_id with True return_whether_chg"
        if existing_id is not None:
            update1(cursor, table, add, uniq)
            return existing_id
        id_ = insert1(cursor, table, {**uniq, **add})
        return id_

    pk_ = "id"
    if res := select1(cursor, table, [pk_, *add.keys()], uniq):
        id_ = res.pop(pk_)
        whether_chg = res != add
        if whether_chg:
            update1(cursor, table, add, uniq)
    else:
        id_ = insert1(cursor, table, {**uniq, **add})
        whether_chg = None
    return (id_, whether_chg) if return_whether_chg else id_


_ID_CACHE: dict[str, dict[frozenset, int]] = defaultdict(dict)


def get_id_cached(cursor: sqlite3.Cursor, table: str, **uniq) -> int:
    """
    Upsert a dictionary into a SQLite table and return PK id without option to add extra column values

    :param cursor: SQLite cursor object
    :param str table: Name of the table to insert into
    :param dict uniq: keys are column names and values are WHERE to search for/insert
    :return int: PK id value
    """
    # Pre-load entire table into cache if not already loaded
    if table not in _ID_CACHE:
        cursor.execute(f"SELECT * FROM {table}")
        for row in cursor.fetchall():
            # row is a Munch object due to row_factory
            row_dict = {k: v for k, v in row.items() if k != "id"}
            cache_key = frozenset(row_dict.items())
            _ID_CACHE[table][cache_key] = row.id

    cache_key = frozenset(uniq.items())
    if cache_key in _ID_CACHE[table]:
        return _ID_CACHE[table][cache_key]

    id_ = get_id(cursor, table, uniq)
    _ID_CACHE[table][cache_key] = id_
    return id_


INSERT_IGNORE_CACHE = defaultdict(set)


def insert_ignore_cached(cursor, table, col, values):
    if (table, col) not in INSERT_IGNORE_CACHE:
        cursor.execute(f"SELECT `{col}` FROM `{table}`")
        existing_values = {row[col] for row in cursor.fetchall()}
        INSERT_IGNORE_CACHE[(table, col)].update(existing_values)
    if values_to_upsert := set(values) - INSERT_IGNORE_CACHE[(table, col)]:
        _logger.debug(f"Inserting {len(values_to_upsert)} records into table `{table}`")
        cursor.executemany(f"INSERT OR IGNORE INTO `{table}` (`{col}`) VALUES (?)", [(v,) for v in values_to_upsert])
        INSERT_IGNORE_CACHE[(table, col)].update(values_to_upsert)


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
    # Flatten values in a stable column order to avoid dict iteration mismatches
    columns = list(add[0].keys())
    values = tuple(d[col] for d in add for col in columns)
    command = "INSERT OR IGNORE" if ignore else "INSERT"
    if debug:
        print(command, add, file=sys.stderr)
    sql = (
        f"{command} INTO {backtick(table)} ({backtick(columns)})"
        + f" values {', '.join(['(' + ', '.join(['?'] * len(columns)) + ')'] * len(add))}"
    )
    execute(cursor, sql, values)
    return cursor.lastrowid


def execute(cursor: sqlite3.Cursor, sql: str, parameters: tuple | dict = ()):

    sql_with_params = sql
    if not any_in(["CREATE", "PRAGMA", "INSERT OR IGNORE INTO vol"], sql):
        # _logger.debug(f"Executing SQL: {sql} with parameters: {parameters}")
        sql_with_params = substitute_parameters_in_sql(sql, parameters)
        flat_sql = single_line(sql_with_params)
        # if "SELECT `id` FROM `cmd` WHERE `cmd`='exiftool -struct -G1'" not in sql_with_params:
        _logger.debug("SQL: %s", flat_sql)

    try:
        ret = cursor.execute(sql, parameters)
        # _logger.debug("SQL executed")
        return ret
    except sqlite3.Error as e:
        _logger.error("Error executing SQL: %s\n%s", e, sql_with_params.strip())
        raise sqlite3.Warning(f"{e!r}\n>>>\n{sql_with_params.strip()}\n<<<") from e


def get_schema(return_type: t.Type = list) -> list[str] | str:
    """Return the database schema as a string."""
    with get_cursor() as cursor:
        ret = [row["sql"] for row in cursor.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")]
    return return_as_type(ret, return_type)


if __name__ == "__main__":
    print(sql_format(get_schema()))
