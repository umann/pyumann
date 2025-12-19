"""PNG soul extraction plugin.

PNG soul consists of the IDAT (Image Data) chunks containing the
compressed image data. This excludes PNG metadata chunks.
"""

from umann.digest.soul import Soul, SoulError, SoulPlugin


class PNGPlugin(SoulPlugin):
    """Extract soul from PNG files."""

    SIGNATURE = b"\x89PNG\r\n\x1a\n"
    IDAT = b"IDAT"
    CRC_LENGTH = 4
    MAX_CHUNKS = 1000

    @classmethod
    def can_handle(cls, soul: Soul) -> bool:
        """Check if file is PNG."""
        if soul.file:
            return soul.file.suffix.lower() == ".png"
        # Check PNG signature
        return soul.content[:8] == cls.SIGNATURE

    def handle(self) -> None:
        """Extract PNG soul from IDAT chunks.

        PNG files consist of chunks with format:
        - 4 bytes: length (big-endian)
        - 4 bytes: chunk type
        - N bytes: chunk data
        - 4 bytes: CRC

        Soul is the contiguous sequence of IDAT chunks.
        """
        s = self.soul

        # Verify PNG signature
        s.pos_read(len(self.SIGNATURE), self.SIGNATURE)

        in_idat = False

        for _ in range(self.MAX_CHUNKS):
            offset_candidate = s.pos

            # Read chunk header (length + type)
            if s.pos + 8 > s.size:
                break  # End of file

            chunk_header = s.pos_read(8)
            chunk_length = int.from_bytes(chunk_header[:4], "big")
            chunk_type = chunk_header[4:8]

            if chunk_type == self.IDAT:
                # Found IDAT chunk
                if not in_idat:
                    # First IDAT - mark soul start
                    s.offset = offset_candidate
                    in_idat = True

                # Skip chunk data and CRC
                s.pos_add(chunk_length + self.CRC_LENGTH)

            elif in_idat:
                # No longer in IDAT chunks - soul is complete
                s.length = offset_candidate - s.offset
                return

            else:
                # Skip this non-IDAT chunk
                s.pos_add(chunk_length + self.CRC_LENGTH)

        # If we're still in IDAT at end of file
        if in_idat:
            s.length = s.size - s.offset
            return

        raise SoulError(f"No IDAT chunk found in first {self.MAX_CHUNKS} chunks")


# Auto-register plugin
Soul.register_plugin(PNGPlugin)
