"""SQL utility functions for handling SQL statements, parameters, and formatting."""

import re
import sys
import typing as t
from functools import lru_cache

import sqlparse
from sqlparse.exceptions import SQLParseError

from umann.utils.data_utils import single_line
from umann.utils.log_utils import setup_package_logger

_logger = setup_package_logger()


def substitute_parameters_in_sql(sql: str, parameters: tuple | dict = ()):
    """Build SQL with parameters substituted for logging.

    Args:
        sql: SQL text whose placeholders should be substituted.
        parameters: Positional or named parameters to inject into the SQL for logging.

    Returns:
        The SQL string with any matching placeholders replaced by repr-formatted values.

    >>> substitute_parameters_in_sql("SELECT * FROM table WHERE id = ?", (42,))
    'SELECT * FROM table WHERE id = 42'
    >>> substitute_parameters_in_sql("SELECT * FROM table WHERE name = :name", {"name": "Alice"})
    "SELECT * FROM table WHERE name = 'Alice'"
    >>> substitute_parameters_in_sql(
    ...     "SELECT * FROM table WHERE name = :name AND age = :age",
    ...     {"name": "Alice", "age": 30},
    ... )
    "SELECT * FROM table WHERE name = 'Alice' AND age = 30"
    >>> substitute_parameters_in_sql(
    ...     "SELECT * FROM table WHERE name = :name AND age = :age",
    ...     {"name": "Alice"},
    ... )
    "SELECT * FROM table WHERE name = 'Alice' AND age = :age"
    >>> substitute_parameters_in_sql(
    ...     "SELECT * FROM table WHERE name = :name AND age = :age",
    ...     {"name": "Alice", "age": 30, "extra": "ignored"},
    ... )
    "SELECT * FROM table WHERE name = 'Alice' AND age = 30"

    """
    sql = remove_sql_comments(sql)
    try:
        if isinstance(parameters, dict):
            # Named parameters: replace :name with values
            sql_with_params = sql
            for key, value in parameters.items():
                sql_with_params = sql_with_params.replace(f":{key}", repr(value))
        else:
            # Positional parameters: replace ? with values using iterator to avoid re-replacing
            param_iter = iter(parameters)

            def replacer(match):
                try:
                    return repr(next(param_iter))
                except StopIteration:
                    return match.group(0)  # No more parameters, leave ? as-is

            sql_with_params = re.sub(r"\?", replacer, sql)
    except TypeError:
        # Fallback if substitution fails
        sql_with_params = f"{sql}\n-- Parameters: {parameters}"
    return sql_with_params


def remove_sql_comments(sql: str | list[str]) -> str:
    """Remove SQL comments from a SQL string.

    Args:
        sql: A SQL string or list of SQL strings to strip comments from.

    Returns:
        The SQL text with comments removed.

    >>> remove_sql_comments("SELECT * FROM table -- This is a comment\nWHERE id = 1;")
    'SELECT * FROM table \nWHERE id = 1;'
    >>> remove_sql_comments("SELECT * FROM table /* This is a\nmulti-line comment */ WHERE id = 1;")
    'SELECT * FROM table  WHERE id = 1;'
    >>> remove_sql_comments("SELECT * FROM table; -- Comment\n/* Multi-line\nComment */")
    'SELECT * FROM table;'
    >>> remove_sql_comments("-- Full line comment\nSELECT * FROM table;")
    'SELECT * FROM table;'
    """
    if isinstance(sql, list):
        return [remove_sql_comments(s) for s in sql]

    # sqlparse may raise on extremely large SQL (e.g. huge parameterized WHERE clauses).
    # In those cases we only need best-effort stripping for logging, so use a regex fallback.
    try:
        return sqlparse.format(sql, strip_comments=True)
    except SQLParseError:
        # Remove multi-line comments that occupy entire lines (without non-comment parts), including tailing newlines
        sql = re.sub(r"^ */\*.*?\*/ *\n", "", sql, flags=re.DOTALL | re.MULTILINE)
        sql = re.sub(r" +/\*.*?\*/ *", " ", sql, flags=re.DOTALL)  # Remove multi-line comments with space before
        sql = re.sub(r" */\*.*?\*/ +", " ", sql, flags=re.DOTALL)  # Remove multi-line comments with space after
        sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)  # Remove remaining multi-line comments
        # NOTE: -- must be prepended by a space to be a comment
        sql = re.sub(r"^ *--.*?$\n?", "", sql, flags=re.MULTILINE)  # Remove single-line comments full line
        sql = re.sub(r" +--.*?$", "", sql, flags=re.MULTILINE)  # Remove remaining single-line comments
        return sql
    # return sql


def backtick(columns) -> str:
    """Return column names wrapped in backticks for SQL statements.

    Args:
        columns: One column name or an iterable of column names.

    Returns:
        A comma-separated string of backtick-quoted column names.

    >>> backtick("column1")
    '`column1`'
    >>> backtick(["column1", "column2"])
    '`column1`, `column2`'
    """
    if isinstance(columns, str):
        columns = [columns]
    return ", ".join(f"`{c}`" for c in columns)


def placeholder_and_values(where: dict, action: t.Literal["insert", "update", "where"] = "where") -> tuple[str, tuple]:
    """Build SQL placeholders and the corresponding value tuple.

    Args:
        where: Mapping of column names to values.
        action: Placeholder style to generate for insert, update, or where clauses.

    Returns:
        A pair of the placeholder SQL fragment and the values tuple.
    """
    if action == "insert":
        placeholders = ", ".join(["?"] * len(where))
    else:  # update or where
        delimiter = ", " if action == "update" else " AND "
        placeholders = delimiter.join(f"{backtick(k)}=?" for k in where.keys())
    values = tuple(where.values())
    return placeholders, values


def _statement_table_name(
    stmt_type: t.Literal["CREATE_TABLE", "CREATE_INDEX", "CREATE_TRIGGER", "INSERT"],
    obj_name: str | None,
    sql_no_comments: str,
) -> str | None:
    """Infer the table name for a SQL statement from its text.

    Args:
        stmt_type: Normalized SQL statement type.
        obj_name: Parsed object name, when one was captured from the statement.
        sql_no_comments: SQL text with comments already removed.

    Returns:
        The referenced table name, or None when it cannot be inferred.

    >>> _statement_table_name("CREATE_TABLE", "my_table", "CREATE TABLE my_table (id INTEGER PRIMARY KEY);")
    'my_table'
    >>> _statement_table_name("CREATE_INDEX", "my_index", "CREATE INDEX my_index ON my_table (column1);")
    'my_table'
    >>> _statement_table_name(
    ...     "CREATE_TRIGGER",
    ...     "my_trigger",
    ...     "CREATE TRIGGER my_trigger AFTER INSERT ON my_table BEGIN ... END;",
    ... )
    'my_table'
    >>> _statement_table_name("INSERT", None, "INSERT INTO my_table (column1) VALUES ('value1');")
    'my_table'
    """
    if "TRIGGER" in stmt_type or "INDEX" in stmt_type:
        table_match = re.search(r'\bON\s+[`"]?(\w+)[`"]?', sql_no_comments, re.IGNORECASE)
        return table_match.group(1) if table_match else None
    if "TABLE" in stmt_type:
        return obj_name
    if "INSERT" in stmt_type:
        insert_match = re.search(r'\bINTO\s+[`"]?(\w+)[`"]?', sql_no_comments, re.IGNORECASE)
        return insert_match.group(1) if insert_match else None
    return None


def _statement_dependencies(stmt_type: str, table_name: str | None, sql_no_comments: str) -> set[str]:
    """Collect foreign-key dependencies for a CREATE TABLE statement.

    Args:
        stmt_type: Normalized SQL statement type.
        table_name: Table name associated with the statement, if known.
        sql_no_comments: SQL text with comments removed.

    Returns:
        A set of referenced table names in lowercase.
    """
    if "TABLE" not in stmt_type or not table_name:
        return set()
    references = re.findall(r'\bREFERENCES\s+[`"]?(\w+)[`"]?', sql_no_comments, re.IGNORECASE)
    return {ref.lower() for ref in references}


def _collect_sql_statements(sql_commands: t.Iterable[str]) -> tuple[list[dict[str, t.Any]], dict[str, set[str]]]:
    """Parse SQL text into structured statements and collect table dependencies.

    Args:
        sql_commands: SQL command strings to inspect.

    Returns:
        A pair of parsed statement records and a table dependency mapping.
    """
    statements = []
    table_dependencies = {}  # table_name -> set of tables it depends on

    for raw_sql in sql_commands:
        sql = raw_sql.strip()
        if not sql:
            continue

        sql_no_comments = remove_sql_comments(sql)
        match = re.match(
            r"^\s*(PRAGMA|INSERT(?:\s+OR\s+IGNORE)?|CREATE\s+(?:TABLE|INDEX|TRIGGER))"
            r'\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:[`"]?(\w+)[`"]?)?',
            sql_no_comments,
            re.IGNORECASE | re.DOTALL,
        )

        if not match:
            statements.append({"sql": sql, "type": "UNKNOWN", "name": None, "table": None})
            continue

        stmt_type = match.group(1).upper().replace(" ", "_")
        obj_name = match.group(2) if match.lastindex >= 2 else None
        table_name = _statement_table_name(stmt_type, obj_name, sql_no_comments)

        if "TABLE" in stmt_type and table_name:
            table_dependencies[table_name.lower()] = _statement_dependencies(stmt_type, table_name, sql_no_comments)

        statements.append({"sql": sql, "type": stmt_type, "name": obj_name, "table": table_name})

    return statements, table_dependencies


def _build_table_order(dependencies: dict[str, set[str]]) -> dict[str, int]:
    """Return a dict mapping table name to its order.

    Args:
        dependencies: Mapping of tables to the tables they depend on.

    Returns:
        A mapping where lower integer values should be created earlier.
    """
    order = {}
    visited = set()

    def visit(table: str) -> int:
        if table in visited:
            return order.get(table, 0)
        if table not in dependencies:
            order[table] = 0
            return 0

        visited.add(table)
        max_dep_order = -1
        for dep in dependencies[table]:
            if dep != table:
                max_dep_order = max(max_dep_order, visit(dep))

        order[table] = max_dep_order + 1
        return order[table]

    for table in dependencies:
        visit(table)

    return order


def _statement_sort_key(stmt: dict[str, t.Any], table_order: dict[str, int]) -> tuple[t.Any, ...]:
    """Build the tuple used to sort SQL statements in dependency-aware order.

    Args:
        stmt: Parsed statement metadata.
        table_order: Dependency-aware table ordering.

    Returns:
        A tuple suitable for sorting statements into execution order.
    """
    type_priority = {
        "PRAGMA": (0, 0),
        "CREATE_TABLE": (1, 0),
        "CREATE_INDEX": (1, 1),
        "CREATE_TRIGGER": (1, 2),
        "INSERT_OR_IGNORE": (2, 0),
        "INSERT": (2, 0),
        "UNKNOWN": (99, 0),
    }
    priority, sub_priority = type_priority.get(stmt["type"], (50, 0))
    table_name = (stmt["table"] or stmt["name"] or "").lower()
    obj_name = (stmt["name"] or "").lower()

    dep_order = (
        table_order.get(table_name, 999) if stmt["type"] in {"CREATE_TABLE", "CREATE_INDEX", "CREATE_TRIGGER"} else 0
    )
    return (priority, dep_order, table_name, sub_priority, obj_name)


def sort_sqls(sql_commands: t.Iterable[str]) -> list[str]:
    """Sort SQL statements to ensure tables are created before they are referenced.

    Args:
        sql_commands: SQL command strings to sort.

    Returns:
        The SQL commands in dependency-aware execution order.
    """
    statements, table_dependencies = _collect_sql_statements(sql_commands)
    table_order = _build_table_order(table_dependencies)
    sorted_stmts = sorted(statements, key=lambda stmt: _statement_sort_key(stmt, table_order))
    return [s["sql"] for s in sorted_stmts]


def _prepare_sql_commands(sql: str | t.Iterable[str], split: bool | None) -> list[str]:
    """Normalize input SQL into a list of command strings.

    Args:
        sql: A single SQL string or iterable of SQL strings.
        split: Whether to split strings into individual statements.

    Returns:
        A list of SQL command strings ready for formatting.
    """
    if isinstance(sql, str):
        sql = [sql]
        if split is None:
            split = True
    elif split is None:
        split = False

    sql_commands = []
    for sql0 in sql:
        if split:
            sql_commands.extend(split_sql_statements(sql0))
        else:
            sql_commands.append(sql0)
    return sql_commands


def _format_sql_command(
    sql1: str,
    *,
    keep_comments: bool,
    flatten: bool,
    remove_backticks: bool,
) -> str | None:
    """Apply formatting to a single SQL command.

    Args:
        sql1: SQL command text to format.
        keep_comments: Whether SQL comments should be preserved.
        flatten: Whether to collapse the SQL onto one line.
        remove_backticks: Whether to drop backticks from non-keyword identifiers.

    Returns:
        The formatted SQL command, or None if it becomes empty.
    """
    if not keep_comments:
        sql1 = remove_sql_comments(sql1)
    if not re.search(r"\S", sql1):
        return None
    if flatten:
        sql1 = single_line(sql1)
    if remove_backticks:

        def callback(m: re.Match) -> str:
            return m[0] if m[1].upper() in sqlite_keywords() else m[1]

        sql1 = re.sub(r"`([a-zA-Z]\w*)`", callback, sql1)
    return sql1


def sql_format(
    sql: str | t.Iterable[str],
    options: dict[str, t.Any] | None = None,
    **kwargs: t.Any,
) -> str | list[str]:
    """Format SQL string(s) by removing comments and extra whitespace.

    Args:
        sql: SQL string or iterable of SQL strings to format.
        options: Optional default formatting options.
        **kwargs: Per-call formatting option overrides.

    Returns:
        A formatted SQL string or list of strings, depending on return_type.
    """
    options = options or {}
    keep_comments = kwargs.pop("keep_comments", options.get("keep_comments", False))
    flatten = kwargs.pop("flatten", options.get("flatten", True))
    sort = kwargs.pop("sort", options.get("sort", True))
    remove_backticks = kwargs.pop("remove_backticks", options.get("remove_backticks", True))
    return_type = kwargs.pop("return_type", options.get("return_type", str))
    split = kwargs.pop("split", options.get("split", None))

    if kwargs:
        unexpected = ", ".join(sorted(kwargs))
        raise TypeError(f"Unexpected keyword argument(s): {unexpected}")

    sql_commands = _prepare_sql_commands(sql, split)
    ret = []
    for sql1 in sql_commands:
        formatted = _format_sql_command(
            sql1,
            keep_comments=keep_comments,
            flatten=flatten,
            remove_backticks=remove_backticks,
        )
        if formatted is not None:
            ret.append(formatted)
    if sort:
        ret = sort_sqls(ret)
    if return_type == str:
        return "\n".join(ret)
    return ret


def split_sql_statements(script: str) -> list[str]:
    """Split a SQL script into individual statements.

    Args:
        script: SQL script text that may contain multiple statements.

    Returns:
        A list of individual SQL statements.
    """
    return sqlparse.split(script)


@lru_cache
def sqlite_keywords() -> set[str]:
    """Return a set of SQLite reserved keywords.

    Returns:
        A cached set of uppercase SQLite reserved keywords.
    """
    return set(
        """
    ABORT
    ACTION
    ADD
    AFTER
    ALL
    ALTER
    ALWAYS
    ANALYZE
    AND
    AS
    ASC
    ATTACH
    AUTOINCREMENT
    BEFORE
    BEGIN
    BETWEEN
    BY
    CASCADE
    CASE
    CAST
    CHECK
    COLLATE
    COLUMN
    COMMIT
    CONFLICT
    CONSTRAINT
    CREATE
    CROSS
    CURRENT
    CURRENT_DATE
    CURRENT_TIME
    CURRENT_TIMESTAMP
    DATABASE
    DEFAULT
    DEFERRABLE
    DEFERRED
    DELETE
    DESC
    DETACH
    DISTINCT
    DO
    DROP
    EACH
    ELSE
    END
    ESCAPE
    EXCEPT
    EXCLUDE
    EXCLUSIVE
    EXISTS
    EXPLAIN
    FAIL
    FILTER
    FIRST
    FOLLOWING
    FOR
    FOREIGN
    FROM
    FULL
    GENERATED
    GLOB
    GROUP
    GROUPS
    HAVING
    IF
    IGNORE
    IMMEDIATE
    IN
    INDEX
    INDEXED
    INITIALLY
    INNER
    INSERT
    INSTEAD
    INTERSECT
    INTO
    IS
    ISNULL
    JOIN
    KEY
    LAST
    LEFT
    LIKE
    LIMIT
    MATCH
    MATERIALIZED
    NATURAL
    NO
    NOT
    NOTHING
    NOTNULL
    NULL
    NULLS
    OF
    OFFSET
    ON
    OR
    ORDER
    OTHERS
    OUTER
    OVER
    PARTITION
    PLAN
    PRAGMA
    PRECEDING
    PRIMARY
    QUERY
    RAISE
    RANGE
    RECURSIVE
    REFERENCES
    REGEXP
    REINDEX
    RELEASE
    RENAME
    REPLACE
    RESTRICT
    RETURNING
    RIGHT
    ROLLBACK
    ROW
    ROWS
    SAVEPOINT
    SELECT
    SET
    TABLE
    TEMP
    TEMPORARY
    THEN
    TIES
    TO
    TRANSACTION
    TRIGGER
    UNBOUNDED
    UNION
    UNIQUE
    UPDATE
    USING
    VACUUM
    VALUES
    VIEW
    VIRTUAL
    WHEN
    WHERE
    WINDOW
    WITH
    WITHOUT
""".split()
    )


PATH_ITEM_PART = r"(?:[\w\-\x20(),'.?*]|\[[\w\-\x20(),'.]*\])"
PATH_ITEM_NONEMPTY_RE0 = rf"(?:{PATH_ITEM_PART}+)"
PATH_ITEM_RE0_CAN_BE_EMPTY_NONGREEDY = rf"(?:{PATH_ITEM_PART})*?"
PATTERN = (
    rf"^(?P<vol>/mnt/[a-z?]|[A-Z?]:)?(?P<dir>/(?:{PATH_ITEM_NONEMPTY_RE0}/)*)"
    + rf"(?P<bas>{PATH_ITEM_RE0_CAN_BE_EMPTY_NONGREEDY})(?P<ext>(?:[.]{PATH_ITEM_RE0_CAN_BE_EMPTY_NONGREEDY})?)$"
)


def glob_to_where(wildcards: t.Iterable[str]) -> tuple[str, tuple[str, ...]]:
    """Convert glob patterns to SQL SELECT statement with WHERE clauses.

    Args:
        wildcards: Filesystem-like glob patterns to translate into SQL predicates.

    Returns:
        A pair containing the SQL WHERE clause and its bound parameter values.

    >>> glob_to_where(["/mnt/f/photos/20[01]?/*"])
    ('((vol.unx = ?) AND (dir.dir GLOB ?))', ('/mnt/f', '/photos/20[01]?/'))
    >>> glob_to_where(["/mnt/f/photos/20[01]?/*.jpg", "/mnt/d/scan/"])
    ('((vol.unx = ?) AND (dir.dir GLOB ?) AND (ext.ext = ?))\n  OR ((vol.unx = ?) AND (dir.dir = ?))',
     ('/mnt/f', '/photos/20[01]?/', '.jpg', '/mnt/d', '/scan/'))
    >>> glob_to_where([""])
    Traceback (most recent call last):
    ...
    ValueError: No match ...
    """
    # joins = [f"\n  JOIN {tbl} ON file.{tbl}_id = {tbl}.id" for tbl in ("vol", "dir", "bas", "ext")]
    ors = []
    binds = []
    for wildcard in wildcards:
        if match := re.search(PATTERN, wildcard):
            groupdict = match.groupdict()
            groupdict["vol"] = groupdict.get("vol") or ""
            if groupdict["bas"] == "" and groupdict["ext"] == "":
                groupdict.pop("bas")
                groupdict.pop("ext")
            ands = []
            for tbl, val in groupdict.items():
                if val == "*":
                    continue
                if tbl == "ext" and val == "":
                    continue
                col = tbl
                if tbl == "vol":
                    # Empty vol is valid on Unix paths like /home/... (stored in vol.unx).
                    col = "win" if re.search(r"^[A-Z?]:$", val) else "unx"
                # joins.add(f"\n  JOIN {tbl} ON file.{tbl}_id = {tbl}.id")
                op_ = "GLOB" if re.search(r"[*?\[\]]", val) else "="
                ands.append(f"({tbl}.{col} {op_} ?)")
                binds.append(val)
            ors.append("(" + " AND ".join(ands) + ")")
        else:
            raise ValueError(f"No match {PATTERN} for {wildcard}")
    where_clause = "\n  OR ".join(ors)

    return where_clause, tuple(binds)


if __name__ == "__main__":  # For manual testing
    res: tuple = glob_to_where(sys.argv[1:])
    print(res)
    print()
    readable_sql = substitute_parameters_in_sql(*res)
    print(readable_sql)
