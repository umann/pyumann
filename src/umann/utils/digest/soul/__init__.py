"""Soul - Extract metadata-free content ("soul") from media files.

The "soul" is the net image/video/audio stream without metadata.
By hashing the soul, you can compare if two files differ only in metadata.
"""

import hashlib
import traceback
import typing as t
from abc import ABC, abstractmethod
from pathlib import Path

import yaml
from munch import Munch


class SoulError(Exception):
    """Base exception for Soul operations."""


class NoHandlerError(SoulError):
    """No plugin can handle this file."""


# pylint: disable=too-many-instance-attributes
class Soul:
    """Extract and hash the metadata-free content from media files.

    The "soul" is the core media data without metadata (EXIF, ID3, etc).
    This allows comparing files to see if they differ only in metadata.

    Usage:
        # Get MD5 hash of soul
        md5 = Soul("image.jpg").compute().result()

        # Get the soul bytes themselves
        soul_bytes = Soul("image.jpg").compute().result("soul")

        # Get multiple fields
        offset, length = Soul("video.avi").compute().result(["offset", "length"])
    """

    # Registry of plugin classes
    _plugins: list[type["SoulPlugin"]] = []

    # Supported media file extensions (populated by plugins)
    _supported_extensions: set[str] = set()

    # File size limits
    # BUFFER_SIZE = 2**20  # 1 MB
    # MEMORY_LIMIT = 2**30  # 1 GB

    SIMPLE_FIELDS = {"offset", "length", "content", "size", "soul_error"}

    def __init__(
        self,
        file: str | Path | None = None,
        content: bytes | None = None,
        hasher: t.Callable[[bytes], str] | None = None,
    ):
        """Initialize Soul extractor.

        Args:
            file: Path to media file (mutually exclusive with content)
            content: File content as bytes (mutually exclusive with file)
            hasher: Hash function, default is hashlib.md5().hexdigest()

        Raises:
            ValueError: If both or neither file/content specified
        """
        if (file is None) == (content is None):
            raise ValueError("Exactly one of 'file' or 'content' must be specified")

        self.file = Path(file) if file else None
        self._content = content
        self._hasher = hasher or (lambda b: hashlib.md5(b).hexdigest())

        # Result fields populated by plugins
        self.offset: int | None = None  # Where soul starts
        self.length: int | None = None  # How long soul is
        self._soul: bytes | None = None  # Cached soul bytes
        self._pos: int = 0  # Current read position
        self.soulless: bool = False  # If True, file has no soul (e.g. text files)
        self.soul_error: Munch[t.Literal["message", "traceback"], str] | None = None

    @classmethod
    def register_plugin(cls, plugin: type["SoulPlugin"]):
        """Register a plugin class for handling specific file types."""
        if plugin not in cls._plugins:
            cls._plugins.append(plugin)
            # Register plugin's supported extensions
            if hasattr(plugin, "SUPPORTED_EXTENSIONS"):
                cls._supported_extensions.update(plugin.SUPPORTED_EXTENSIONS)

    @property
    def size(self) -> int:
        """Get file size in bytes."""
        if self._content is not None:
            return len(self._content)
        return self.file.stat().st_size

    @property
    def content(self) -> bytes:
        """Get entire file content as bytes."""
        if self._content is None:
            # Prevent reading huge files into memory (> 2GB)
            if self.size > 2 * 1024 * 1024 * 1024:

                raise SoulError(f"{self.file=} too large to read into memory: {self.size} bytes")
            self._content = self.file.read_bytes()
        return self._content

    @content.setter
    def content(self, value: bytes) -> None:
        """Set file content as bytes."""
        self._content = value

    @property
    def pos(self) -> int:
        """Current read position."""
        return self._pos

    def pos_set(self, position: int) -> int:
        """Set read position and return previous position."""
        if position > self.size:
            raise SoulError(f"Position {position} beyond end of file (size {self.size})")
        prev = self._pos
        self._pos = position
        return prev

    def pos_add(self, delta: int) -> int:
        """Add to position and return previous position."""
        return self.pos_set(self._pos + delta)

    def pos_read(self, length: int, expected: bytes | None = None) -> bytes:
        """Read bytes at current position and advance position.

        Args:
            length: Number of bytes to read
            expected: If provided, verify read bytes match this

        Returns:
            Bytes read

        Raises:
            SoulError: If expected mismatch or read past end
        """
        if self._pos + length > self.size:
            raise SoulError(f"Unexpected end of file at pos {self._pos} " f"reading {length} bytes (size {self.size})")

        data = self.content[self._pos : self._pos + length]
        self._pos += length

        if expected is not None and data != expected:
            raise SoulError(f"Expected {expected!r}, got {data!r} at pos {self._pos - length}")

        return data

    def pos_find(self, needle: bytes) -> int | None:
        """Find bytes starting from current position.

        Returns:
            Position of first occurrence, or None if not found
        """
        idx = self.content.find(needle, self._pos)
        return idx if idx >= 0 else None

    def subcontent(self, offset: int | None = None, length: int | None = None) -> bytes:
        """Extract substring from content.

        Args:
            offset: Start position (defaults to self.offset)
            length: Length to extract (defaults to self.length)

        Returns:
            Extracted bytes
        """
        offset = offset if offset is not None else self.offset
        length = length if length is not None else self.length

        if offset is None or length is None:
            raise SoulError("offset and length must be set")

        if offset + length > self.size:
            raise SoulError(f"Unexpected end of file: offset {offset} + length {length} " f"> size {self.size}")

        return self.content[offset : offset + length]

    def find_plugin(self) -> type["SoulPlugin"]:
        """Find appropriate plugin for this file.

        Returns:
            Plugin class that can handle this file

        Raises:
            NoHandlerError: If no plugin can handle the file
        """
        for plugin_class in sorted(self._plugins, key=lambda cls: cls.rank):
            if plugin_class.can_handle(self):
                return plugin_class

        raise NoHandlerError(f"No plugin can handle {self.file or 'content'}")

    def _reset_result_state(self, *, soulless: bool) -> "Soul":
        """Reset runtime state for the current soul extraction."""
        self.soulless = soulless
        self.offset = None
        self.length = None
        self._soul = None
        return self

    def _is_unsupported_file(self) -> bool:
        """Return True when the file type is not supported by any registered plugin."""
        return bool(self.file and self.file.suffix.lower() not in self._supported_extensions)

    def compute(self) -> "Soul":
        """Compute soul offset and length using appropriate plugin.

        Returns:
            Self for method chaining
        """
        if self._is_unsupported_file():
            return self._reset_result_state(soulless=True)

        try:
            plugin_class = self.find_plugin()
            plugin = plugin_class(self)
            plugin.handle()
        except (SoulError, MemoryError) as e:
            error_msg = (
                str(e) if not isinstance(e, MemoryError) else f"Out of memory processing file ({self.size} bytes)"
            )
            self.soul_error = Munch(message=error_msg, traceback=traceback.format_exc())
            return self._reset_result_state(soulless=True)

        if self.soulless:
            return self._reset_result_state(soulless=True)

        return self

    def _populate_simple_results(self, results: dict[str, t.Any], fields: tuple[str, ...]) -> None:
        """Populate simple scalar fields from the Soul instance."""
        for field in self.SIMPLE_FIELDS:
            if field in fields:
                results[field] = getattr(self, field)

    def _populate_soul_results(self, results: dict[str, t.Any], fields: tuple[str, ...]) -> None:
        """Populate soul-related results when requested."""
        if "soul" not in fields and "md5_soul" not in fields:
            return

        if self.soulless:
            results["soul"] = None
            return

        if self._soul is None:
            self._soul = self.subcontent()
        results["soul"] = self._soul

    def _populate_md5_results(self, results: dict[str, t.Any], fields: tuple[str, ...]) -> None:
        """Populate md5-related results when requested."""
        if "md5_soul" not in fields and "md5" not in fields:
            return

        if "md5_soul" in fields:
            results["md5_soul"] = None if self.soulless else self._hasher(self._soul or self.subcontent())

        if "md5" in fields:
            # Use streaming MD5 for files to avoid loading entire file into memory
            if self.file:
                from umann.utils.fs_utils import md5_file  # pylint: disable=import-outside-toplevel

                results["md5"] = md5_file(str(self.file))
            else:
                results["md5"] = self._hasher(self.content)

    def result(self, *fields: str | list[str]) -> t.Any:
        """Get result fields.

        Args:
            fields: Field names to retrieve. Options:
                - "offset": Start position of soul
                - "length": Length of soul
                - "soul": Soul bytes
                - "md5_soul": MD5 hash of soul (default if no fields specified)
                - "content": Entire file content
                - "md5": MD5 hash of entire file
                - "size": File size

        Returns:
            Single value if one field, tuple if multiple fields

        Examples:
            >>> Soul("img.jpg").compute().result()  # Returns md5_soul
            '10c9e17c0ac4e1ab75807823cb567168'

            >>> Soul("img.jpg").compute().result("offset", "length")
            (89, 35)
        """
        normalized_fields = tuple(fields) if fields else ("md5_soul",)
        if self.length is None and self.offset is not None:
            self.length = self.size - self.offset

        results: dict[str, t.Any] = {}
        self._populate_simple_results(results, normalized_fields)
        self._populate_soul_results(results, normalized_fields)
        self._populate_md5_results(results, normalized_fields)

        if len(normalized_fields) == 1:
            return results[normalized_fields[0]]
        return tuple(results[f] for f in normalized_fields)


class SoulPlugin(ABC):
    """Base class for Soul extraction plugins.

    Each plugin handles a specific file format (JPG, MP3, etc).
    """

    SUPPORTED_EXTENSIONS = set()  # Set of file extensions this plugin can handle
    rank = 1  # Default priority. Lower rank = higher priority. Used in can_handle selection.
    # The Default plugin should have the lowest priority to allow other plugins to handle known formats.

    def __init__(self, soul: Soul):
        """Initialize plugin with Soul instance."""
        self.soul = soul

    # Attribute name "SUPPORTED_EXTENSIONS" doesn't conform to snake_case naming style
    # pylint: disable=invalid-name  # TODO
    @classmethod
    def can_handle(cls, soul: Soul) -> bool | None:
        if (ret := cls.can_handle_ext(soul)) is not None:
            return ret
        return cls.can_handle_content(soul)

    @classmethod
    def can_handle_ext(cls, soul: Soul) -> bool | None:
        if soul.file:
            return soul.file.suffix.lower() in cls.SUPPORTED_EXTENSIONS
        return None

    @classmethod
    @abstractmethod
    def can_handle_content(cls, soul: Soul) -> bool:
        """Check if this plugin can handle the given file.

        Args:
            soul: Soul instance to check

        Returns:
            True if this plugin can handle the file
        """

    @abstractmethod
    def handle(self) -> None:
        """Extract soul offset and length from file.

        Must set self.soul.offset and self.soul.length.
        """


def extract_soul(file: str | Path, *fields: str) -> t.Any:
    """Convenience function to extract soul data from file.

    Args:
        file: Path to media file
        fields: Result fields to return (default: md5_soul)

    Returns:
        Result value(s)

    Examples:
        >>> soul("image.jpg")
        '10c9e17c0ac4e1ab75807823cb567168'

        >>> soul("video.avi", "offset", "length")
        (1024, 50000)
    """
    ret = Soul(file).compute()
    # breakpoint()
    ret = ret.result(*fields)
    return ret


def md5_soul(file: str | Path) -> str:
    """Convenience function to extract md5_soul valuefrom file.

    Args:
        file: Path to media file

    Returns:
        Result value(s)

    Examples:
        >>> md5_soul("image.jpg")
        '10c9e17c0ac4e1ab75807823cb567168'
    """
    return Soul(file).compute().result("md5_soul")
