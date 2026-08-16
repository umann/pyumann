"""Run Vulture via Python API and normalize output for stable diffs."""

from __future__ import annotations

import re
import subprocess
import sys
import typing as t

from vulture.config import InputError, make_config
from vulture.core import Vulture
from vulture.utils import ExitCode

WHITELIST_LINE_RE = re.compile(r"^(?P<name>.+?)\s+#\s+(?P<message>.+)\s+\((?P<path>.+)\)$")
PATH_LINE_RE = re.compile(r"^(?P<path>.*?):(?P<line>\d+)$")


def _git_python_files() -> list[str]:
    """Return tracked Python files from Git, preserving repository order."""
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return []
    return [line for line in result.stdout.splitlines() if line]


def _render_whitelist_sorted(items: t.Iterable[t.Any]) -> str:
    """Convert whitelist rows to ``path:line: message: name`` and sort by position."""
    rows: list[tuple[tuple[str, int], str]] = []
    for item in items:
        raw = item.get_whitelist_string()
        match = WHITELIST_LINE_RE.match(raw)
        if not match:
            rows.append((("", 0), raw))
            continue
        path_with_line = match.group("path")
        path_line_match = PATH_LINE_RE.match(path_with_line)
        if path_line_match:
            file_path = path_line_match.group("path")
            line_number = int(path_line_match.group("line"))
        else:
            file_path = path_with_line
            line_number = 0
        rendered = f"{path_with_line}: {match.group('message')}: {match.group('name')}"
        rows.append(((file_path.lower(), line_number), rendered))

    rows.sort(key=lambda item: item[0])
    return "".join(f"{line}\n" for _, line in rows)


def main(args: t.Sequence[str] | None = None) -> int:
    """Run Vulture and print normalized output while retaining Vulture exit codes."""
    argv = list(args) if args is not None else sys.argv[1:]
    if not argv:
        argv = _git_python_files()

    try:
        config = make_config(argv)
    except InputError as exc:
        sys.stderr.write(f"{exc}\n")
        return int(ExitCode.InvalidCmdlineArguments)

    vulture = Vulture(
        verbose=config["verbose"],
        ignore_names=config["ignore_names"],
        ignore_decorators=config["ignore_decorators"],
    )
    vulture.scavenge(config["paths"], exclude=config["exclude"])
    items = vulture.get_unused_code(
        min_confidence=config["min_confidence"],
        sort_by_size=config["sort_by_size"],
    )

    if config["make_whitelist"]:
        sys.stdout.write(_render_whitelist_sorted(items))
    else:
        for item in items:
            sys.stdout.write(f"{item.get_report(add_size=config['sort_by_size'])}\n")

    if items:
        return int(ExitCode.DeadCode)
    return int(vulture.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
