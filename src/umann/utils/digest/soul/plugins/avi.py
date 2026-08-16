"""AVI soul extraction plugin.

AVI soul is the movie data in the LIST/movi chunk.
This excludes AVI headers and metadata.
"""

import struct

from umann.utils.digest.soul import Soul, SoulError, SoulPlugin


class AVIPlugin(SoulPlugin):
    """Extract soul from AVI files."""

    SUPPORTED_EXTENSIONS = {".avi"}
    RIFF_HEADER_SIZE = 12

    @classmethod
    def can_handle_content(cls, soul: Soul) -> bool:
        """Check if file is AVI."""
        if soul.file:
            return soul.file.suffix.lower() == ".avi"
        # Check RIFF/AVI header
        return soul.content[:4] == b"RIFF" and soul.content[8:12] == b"AVI "

    def handle(self) -> None:
        """Extract AVI soul from LIST/movi chunk.

        AVI files use RIFF format with structure:
        - "RIFF" + size (4 bytes) + "AVI "
        - Chunks: "LIST" + size (4 bytes) + type (4 bytes)

        Following Perl implementation logic:
        - offset = position just before the 4-byte chunk type (after LIST + size)
        - length = RIFF chunk size field value (includes the 4-byte type + data)
        """
        s = self.soul

        # Read and verify main RIFF header
        riff_id, riff_size, avi_type = self._read_riff_header()

        if riff_id != b"RIFF":
            raise SoulError(f"Expected RIFF header, got {riff_id!r}")

        if riff_size + 8 > s.size:
            raise SoulError("Truncated RIFF file")

        if avi_type != b"AVI ":
            raise SoulError(f"Expected AVI type, got {avi_type!r}")

        # Find LIST/movi chunk
        while s.pos < s.size - 12:
            # chunk_pos = s.pos
            chunk_type, chunk_length, chunk_id = self._read_riff_header()

            if chunk_type == b"LIST" and chunk_id == b"movi":
                # Found the movie data!
                # offset = position before chunk_id (newpos - 4 in Perl)
                # The newpos in Perl is after reading the full 12-byte header,
                # but then it subtracts 4 to point before the chunk_id
                s.offset = s.pos - 4  # Position before the 4-byte chunk_id
                s.length = chunk_length  # RIFF size field (includes chunk_id + data)
                return

            # Skip to next chunk
            # We've read the 12-byte header, now skip the remaining data
            # chunk_length includes the 4-byte chunk_id we already read
            s.pos_add(chunk_length - 4)

        raise SoulError("No LIST/movi chunk found in file")

    def _read_riff_header(self) -> tuple[bytes, int, bytes]:
        """Read RIFF chunk/header (12 bytes).

        Reads the standard RIFF structure:
        - 4 bytes: chunk type (e.g., "RIFF", "LIST")
        - 4 bytes: size (little-endian uint32)
        - 4 bytes: chunk ID/subtype (e.g., "AVI ", "movi")

        Returns:
            (chunk_type, size, chunk_id) tuple

        Note: This matches Perl's riff_params_fh which returns (type, length, id, newpos)
        where newpos = pos + 12 (after reading the header).
        """
        s = self.soul

        if s.pos + self.RIFF_HEADER_SIZE > s.size:
            raise SoulError(f"Not enough data for RIFF header at pos {s.pos}")

        # Read 12 bytes: Type(4) + Size(4) + ID(4)
        header = s.pos_read(self.RIFF_HEADER_SIZE)

        chunk_type = header[0:4]
        chunk_size = struct.unpack("<I", header[4:8])[0]  # Little-endian uint32
        chunk_id = header[8:12]

        return chunk_type, chunk_size, chunk_id


# Auto-register plugin
Soul.register_plugin(AVIPlugin)
