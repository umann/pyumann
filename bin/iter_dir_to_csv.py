#!/usr/bin/env python3
"""
Iterate through directories and output file metadata as CSV.

Supports:
- Single files, directories, and glob patterns as arguments
- Optional --md5 flag to compute MD5 hashes
- Optional --fnmatch PATTERN flag to filter files by basename (like find -name)
- Optional --gitignore FILE to skip paths matching patterns
"""

import csv
import hashlib
import os
import sys
from fnmatch import fnmatch
from glob import glob


def load_gitignore(path: str) -> list[str]:
    """Load gitignore-style patterns from a file."""
    patterns: list[str] = []
    if not path:
        return patterns
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
    except OSError as e:
        print(f"{path}: {e}", file=sys.stderr)
    return patterns


def md5_file_hex(path: str) -> str:
    """Compute MD5 hash of a file and return as hex string."""
    try:
        hasher = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        return ""


def matches_filename_filter(path: str, pattern: str | None) -> bool:
    """Check if basename of path matches glob pattern."""
    if pattern is None:
        return True
    basename = os.path.basename(path)
    return bool(fnmatch(basename, pattern))


def gitignore_match(path: str, patterns: list[str]) -> bool:
    """Return True if path matches any ignore pattern (with optional negation)."""
    if not patterns:
        return False
    norm_path = path.replace("\\", "/")
    path_cmp = norm_path[:-1] if norm_path.endswith("/") else norm_path
    basename = os.path.basename(path_cmp)
    for raw in patterns:
        pattern = raw
        negate = False
        if pattern.startswith("!"):
            negate = True
            pattern = pattern[1:]
        pattern = pattern.rstrip("/")
        match = fnmatch(path_cmp, pattern) or fnmatch(basename, pattern)
        if match:
            return not negate
    return False


def dir_gitignore_match(path: str, patterns: list[str]) -> bool:
    """Return True if any parent directory of path matches ignore patterns."""
    if not patterns:
        return False
    norm_path = path.replace("\\", "/").rstrip("/")
    temp = norm_path
    while True:
        slash = temp.rfind("/")
        if slash == -1:
            return False
        temp = temp[:slash]
        if gitignore_match(temp, patterns):
            return True


def print_csv_row(writer: csv.writer, path: str, size: int, mtime: int, md5_hex: str = "") -> None:
    """Write a CSV row with file metadata."""
    if md5_hex:
        writer.writerow([path, size, mtime, md5_hex])
    else:
        writer.writerow([path, size, mtime])


def process_file(
    writer: csv.writer,
    path: str,
    enable_md5: bool = False,
    fnmatch_pattern: str | None = None,
    gitignore_patterns: list[str] | None = None,
) -> None:
    """Process a single file and write CSV row."""
    if gitignore_patterns and (
        gitignore_match(path, gitignore_patterns) or dir_gitignore_match(path, gitignore_patterns)
    ):
        return

    if not matches_filename_filter(path, fnmatch_pattern):
        return

    try:
        stat_result = os.stat(path)
        size = stat_result.st_size
        mtime = stat_result.st_mtime
        md5_hex = md5_file_hex(path) if enable_md5 else ""
        print_csv_row(writer, path, size, mtime, md5_hex)
    except OSError:
        # File not found or error accessing it
        md5_hex = "" if enable_md5 else ""
        print_csv_row(writer, path, -1, -1, md5_hex)


def process_directory(
    writer: csv.writer,
    path: str,
    enable_md5: bool = False,
    fnmatch_pattern: str | None = None,
    gitignore_patterns: list[str] | None = None,
) -> None:
    """Walk through directory and process all files."""
    if gitignore_patterns and (
        gitignore_match(path, gitignore_patterns) or dir_gitignore_match(path, gitignore_patterns)
    ):
        return

    for root, dirs, files in os.walk(path):
        if gitignore_patterns:
            pruned_dirs: list[str] = []
            for d in dirs:
                dirpath = os.path.join(root, d)
                if gitignore_match(dirpath, gitignore_patterns) or dir_gitignore_match(dirpath, gitignore_patterns):
                    continue
                pruned_dirs.append(d)
            dirs[:] = pruned_dirs
        for filename in files:
            filepath = os.path.join(root, filename)
            process_file(writer, filepath, enable_md5, fnmatch_pattern, gitignore_patterns)


def process_argument(
    writer: csv.writer,
    arg: str,
    enable_md5: bool = False,
    fnmatch_pattern: str | None = None,
    gitignore_patterns: list[str] | None = None,
) -> None:
    """Process an argument (file, directory, or glob pattern)."""
    # Check if argument contains glob metacharacters
    if any(c in arg for c in "*?[]"):
        # Expand glob pattern
        matches = glob(arg)
        if matches:
            for match in sorted(matches):
                if os.path.isfile(match):
                    process_file(writer, match, enable_md5, fnmatch_pattern, gitignore_patterns)
                elif os.path.isdir(match):
                    process_directory(writer, match, enable_md5, fnmatch_pattern, gitignore_patterns)
        else:
            # No matches from glob - treat as non-existent file
            md5_hex = "" if enable_md5 else ""
            print_csv_row(writer, arg, -1, -1, md5_hex)
    else:
        # Not a glob pattern - check if it's a file or directory
        if os.path.isfile(arg):
            process_file(writer, arg, enable_md5, fnmatch_pattern, gitignore_patterns)
        elif os.path.isdir(arg):
            process_directory(writer, arg, enable_md5, fnmatch_pattern, gitignore_patterns)
        else:
            # Non-existent path
            md5_hex = "" if enable_md5 else ""
            print_csv_row(writer, arg, -1, -1, md5_hex)


def main():
    """Main entry point."""
    import argparse  # pylint: disable=import-outside-toplevel

    parser = argparse.ArgumentParser(
        description="Output file metadata as CSV",
        prog="iter_dir_csv.py",
    )
    parser.add_argument(
        "--md5",
        action="store_true",
        help="Compute and include MD5 hash for each file",
    )
    parser.add_argument(
        "--fnmatch",
        metavar="PATTERN",
        help="Filter files by basename pattern (e.g., '*.jpg')",
    )
    parser.add_argument(
        "--gitignore",
        metavar="FILE",
        help="Path to gitignore-style patterns file",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="File, directory, or glob pattern to process",
    )

    args = parser.parse_args()

    # Create CSV writer for stdout
    writer = csv.writer(sys.stdout)

    gitignore_patterns = load_gitignore(args.gitignore) if args.gitignore else []

    # Process each path argument
    for path in args.paths:
        process_argument(
            writer,
            path,
            enable_md5=args.md5,
            fnmatch_pattern=args.fnmatch,
            gitignore_patterns=gitignore_patterns,
        )


if __name__ == "__main__":
    main()
