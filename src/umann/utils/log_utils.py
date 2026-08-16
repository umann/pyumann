"""Logging utilities for the umann package."""

import logging
import os
import shlex
import sys
from datetime import datetime
from functools import lru_cache
from typing import Optional


class SkipUtilityModulesFilter(logging.Filter):  # pylint: disable=too-few-public-methods
    """Filter that updates log records to skip utility module frames and show the real caller."""

    def __init__(self):
        super().__init__()
        self._utility_modules = {"sql_utils", "log_utils", "data_utils", "db_utils", "fs_utils"}

    def filter(self, record: logging.LogRecord) -> bool:
        """Update record to show the real caller, skipping utility modules."""
        try:
            # Walk back through the stack to find the real caller
            frame = sys._getframe()  # pylint: disable=protected-access
            skip_modules = self._utility_modules | {"logging"}

            while frame:
                module_name = frame.f_globals.get("__name__", "")
                # Skip frames from utility modules and logging internals
                if not any(skip in module_name for skip in skip_modules):
                    # Found the real caller - update record
                    record.pathname = frame.f_code.co_filename
                    record.lineno = frame.f_lineno  # noqa
                    record.funcName = frame.f_code.co_name  # noqa
                    # Update filename for consistency
                    record.filename = os.path.basename(record.pathname)
                    break
                frame = frame.f_back
        except Exception:  # pylint: disable=broad-except  # TODO
            pass  # Keep original record values if stack walking fails

        return True  # Always pass the record through


class ProjectRootFormatter(logging.Formatter):
    """Formatter that adds project-root-relative file path to the log record."""

    def __init__(self, fmt: str | None = None, datefmt: str | None = None):
        super().__init__(fmt, datefmt)
        try:
            # Lazy import to avoid circular dependency
            from umann.utils.fs_utils import project_root  # pylint: disable=import-outside-toplevel

            self._root = project_root()
        except Exception:  # pylint: disable=broad-except  # TODO
            self._root = None
        self._path_cache: dict[str, str] = {}

    def format(self, record: logging.LogRecord) -> str:
        # Calculate relative path
        try:
            if self._root:
                rel = self._path_cache.get(record.pathname)
                if rel is None:
                    rel = os.path.relpath(record.pathname, self._root)
                    self._path_cache[record.pathname] = rel
                record.file_name_relative_to_project_root = rel  # noqa
            else:
                record.file_name_relative_to_project_root = record.filename  # noqa
        except Exception:  # pylint: disable=broad-except  # TODO
            record.file_name_relative_to_project_root = record.filename  # noqa

        # Ensure we always return a string
        try:
            result = super().format(record)
            return result if result is not None else record.getMessage()
        except Exception:  # pylint: disable=broad-except  # TODO
            # Fallback to basic formatting if something goes wrong
            return f"{record.levelname}: {record.getMessage()}"


def setup_module_logger(
    module_name: str, log_dir: str = "logs", level: int = logging.DEBUG, formatter: Optional[logging.Formatter] = None
) -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    process_id = os.getpid()
    log_file = os.path.join(log_dir, f"{module_name}_{timestamp}-{process_id}.log")
    logger = logging.getLogger(module_name)
    logger.setLevel(level)
    if not logger.handlers:
        # Add filter to skip utility modules
        logger.addFilter(SkipUtilityModulesFilter())

        handler = logging.FileHandler(log_file)
        handler.setLevel(level)
        # Project-relative file path, function and line number
        formatter = formatter or ProjectRootFormatter(
            "%(asctime)s  %(levelname)s %(file_name_relative_to_project_root)s:%(lineno)d %(funcName)s() %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


@lru_cache
def setup_package_logger(
    package_name: str = "umann",
    log_dir: str = "logs",
    level: int = logging.DEBUG,
) -> logging.Logger:
    """Setup package logger. Returns the same logger instance on subsequent calls."""
    logger = setup_module_logger(package_name, log_dir, level, formatter=None)
    logger.info(f"Command line: {shlex.join(sys.argv)}")
    return logger
