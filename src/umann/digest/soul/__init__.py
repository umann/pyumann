"""Soul - Extract metadata-free content ("soul") from media files.

The "soul" is the net image/video/audio stream without metadata.
By hashing the soul, you can compare if two files differ only in metadata.
"""

import hashlib
import typing as t
from abc import ABC, abstractmethod
from pathlib import Path

import yaml


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

    # File size limits
    # BUFFER_SIZE = 2**20  # 1 MB
    # MEMORY_LIMIT = 2**30  # 1 GB

    SIMPLE_FIELDS = {"offset", "length", "content", "size"}

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

    @classmethod
    def register_plugin(cls, plugin: type["SoulPlugin"]):
        """Register a plugin class for handling specific file types."""
        if plugin not in cls._plugins:
            cls._plugins.append(plugin)

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

    def compute(self) -> "Soul":
        """Compute soul offset and length using appropriate plugin.

        Returns:
            Self for method chaining
        """
        plugin_class = self.find_plugin()
        plugin = plugin_class(self)
        plugin.handle()
        # breakpoint()
        return self

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
        if not fields:
            fields = ("md5_soul",)

        # Ensure length is set
        if self.length is None and self.offset is not None:
            self.length = self.size - self.offset

        # Build results dict
        results = {}

        # Simple fields
        for field in self.SIMPLE_FIELDS:
            if field in fields:
                results[field] = getattr(self, field)

        # Computed fields
        if "soul" in fields or "md5_soul" in fields:
            if self.soulless:
                results["soul"] = None
            else:
                if self._soul is None:
                    self._soul = self.subcontent()
                results["soul"] = self._soul

        if "md5_soul" in fields:
            results["md5_soul"] = None if self.soulless else self._hasher(self._soul or self.subcontent())

        if "md5" in fields:
            results["md5"] = self._hasher(self.content)

        # Return single value or tuple
        if len(fields) == 1:
            return results[fields[0]]
        return tuple(results[f] for f in fields)


class SoulPlugin(ABC):
    """Base class for Soul extraction plugins.

    Each plugin handles a specific file format (JPG, MP3, etc).
    """

    rank = 1  # Default priority. Lower rank = higher priority. Used in can_handle selection.
    # The Default plugin should have the lowest priority to allow other plugins to handle known formats.

    def __init__(self, soul: Soul):
        """Initialize plugin with Soul instance."""
        self.soul = soul

    @classmethod
    @abstractmethod
    def can_handle(cls, soul: Soul) -> bool:
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
