"""MP3 soul extraction plugin.

MP3 soul is the compressed audio data between:
- Start: After ID3v2 header(s)
- End: Before ID3v1 trailer (if present)

This excludes ID3 metadata tags.
"""

from umann.digest.soul import Soul, SoulError, SoulPlugin


class MP3Plugin(SoulPlugin):
    """Extract soul from MP3 files."""

    MP3_FRAME_SYNC = b"\xff\xfb"
    ID3V1_SIZE = 128

    @classmethod
    def can_handle(cls, soul: Soul) -> bool:
        """Check if file is MP3."""
        if soul.file:
            return soul.file.suffix.lower() == ".mp3"
        # Check for ID3 or MP3 frame sync
        return soul.content[:3] == b"ID3" or soul.content[:2] == cls.MP3_FRAME_SYNC

    def handle(self) -> None:
        """Extract MP3 soul by skipping ID3v2 headers and ID3v1 trailer."""
        s = self.soul

        # Skip ID3v2 headers (can be multiple)
        while s.pos + 3 <= s.size and s.content[s.pos : s.pos + 3] == b"ID3":
            s.pos_add(3)  # Skip "ID3"

            # Read version (2 bytes) and flags (1 byte)
            s.pos_read(3)

            # Read syncsafe size (4 bytes)
            size_bytes = s.pos_read(4)
            size = self._unsync_safe(size_bytes)

            if size is None:
                raise SoulError(f"Invalid ID3v2 size at pos {s.pos - 4}")

            # Skip the ID3v2 tag data
            s.pos_add(size)

        # Soul starts after ID3v2 headers
        s.offset = s.pos

        # Verify MP3 frame sync
        s.pos_read(2, self.MP3_FRAME_SYNC)

        # Calculate length (rest of file minus potential ID3v1 trailer)
        s.length = s.size - s.offset

        # Check for ID3v1 trailer at end
        if s.size >= self.ID3V1_SIZE:
            # Check last 128 bytes for "TAG" marker
            tag_pos = s.size - self.ID3V1_SIZE
            if s.content[tag_pos : tag_pos + 3] == b"TAG":
                s.length -= self.ID3V1_SIZE

    @staticmethod
    def _unsync_safe(data: bytes) -> int | None:
        """Convert ID3v2 syncsafe integer to normal integer.

        Syncsafe integers use only 7 bits per byte (MSB is always 0).

        Args:
            data: 4 bytes representing syncsafe int32

        Returns:
            Decoded integer, or None if invalid (any MSB set)
        """
        val = int.from_bytes(data, "big")

        # Check that high bit of each byte is 0
        if val & 0x80808080:
            return None

        # Decode: combine 7-bit chunks
        return (val & 0x0000007F) | ((val & 0x00007F00) >> 1) | ((val & 0x007F0000) >> 2) | ((val & 0x7F000000) >> 3)


# Auto-register plugin
Soul.register_plugin(MP3Plugin)
