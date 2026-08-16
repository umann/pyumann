"""Run Pylint and sort GCC-format diagnostics by source position."""

import re
import subprocess
import sys
import typing as t

GCC_DIAGNOSTIC_RE = re.compile(r"^(.*?):(\d+):(\d+):\s")
GCC_MESSAGE_TEMPLATE = "{path}:{line}:{column}: {msg_id}: {msg} ({symbol})"


def sort_gcc_output(output: str) -> str:
    """Return only GCC diagnostics sorted by filename, row, and column."""
    diagnostics: list[tuple[tuple[str, int, int], str]] = []

    for line in output.splitlines(keepends=True):
        match = GCC_DIAGNOSTIC_RE.match(line)
        if match:
            filename, row, column = match.groups()
            diagnostics.append(((filename, int(row), int(column)), line))

    diagnostics.sort(key=lambda item: item[0])
    return "".join(line for _, line in diagnostics)


def main(args: t.Sequence[str] | None = None) -> int:
    """Run Pylint in GCC mode, print sorted output, and retain its exit code."""
    command = [
        sys.executable,
        "-m",
        "pylint",
        "--score=n",
        "--reports=n",
        "--output-format=text",
        f"--msg-template={GCC_MESSAGE_TEMPLATE}",
        *(args if args is not None else sys.argv[1:]),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    sys.stdout.write(sort_gcc_output(result.stdout))
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
