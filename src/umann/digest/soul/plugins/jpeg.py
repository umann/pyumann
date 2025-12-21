"""JPEG soul extraction plugin.

JPEG soul is the compressed image data between:
- Start: FF DA (Start of Scan marker)
- End: FF D9 (End of Image marker)

This excludes EXIF, JFIF headers, and other metadata.
"""

from umann.digest.soul import Soul, SoulError, SoulPlugin


class JPEGPlugin(SoulPlugin):
    """Extract soul from JPEG files."""

    # JPEG markers
    SOI = b"\xff\xd8"  # Start of Image
    SOS = b"\xda"  # Start of Scan
    EOI = b"\xd9"  # End of Image
    FF = b"\xff"
    RST0 = b"\xd0"  # Restart markers D0-D7
    RST7 = b"\xd7"

    MAX_ITERATIONS = 1000

    @classmethod
    def can_handle(cls, soul: Soul) -> bool:
        """Check if file is JPEG."""
        if soul.file:
            return soul.file.suffix.lower() in (".jpg", ".jpeg")
        # Check magic bytes
        return soul.content[:2] == cls.SOI

    # pylint: disable=too-many-branches
    def handle(self) -> None:
        """Extract JPEG soul between SOS and EOI markers.

        Handles progressive JPEGs which may have multiple SOS markers.
        The soul starts at the first SOS marker (FF DA) and ends after EOI marker (FF D9).

        Following Perl implementation logic:
        - offset = position of first FF DA (SOS marker start)
        - length = from SOS to position after FF D9 (includes both markers)
        """
        s = self.soul

        # Verify JPEG header (FF D8)
        marker_bytes = s.pos_read(2)
        if marker_bytes != self.SOI:
            raise SoulError(f"Expected JPEG SOI marker, got {marker_bytes.hex()}")

        # Position is now at byte 2
        # Scan through JPEG structure
        for cnt in range(self.MAX_ITERATIONS):
            # Expect FF marker
            ff = s.pos_read(1)
            if ff != self.FF:
                raise SoulError(f"Iteration {cnt+1} at pos {s.pos-1:#x}: expected FF, got {ff.hex()}")

            marker = s.pos_read(1)
            marker_val = marker[0]  # Get byte value

            # Remember FIRST SOS position only (fixed Perl bug)
            if marker_val == self.SOS[0]:
                if s.offset is None:
                    s.offset = s.pos - 2  # Back to start of FF DA

            cnt2 = 0
            # Skip through markers: 00 (escaped FF), DA (SOS), D0-D7 (restart)
            # Perl: while (!$marker || $marker eq $START_OF_STREAM || ($marker >= 0xd0 && $marker <= 0xd7))
            while marker_val == 0x00 or marker_val == self.SOS[0] or (self.RST0[0] <= marker_val <= self.RST7[0]):
                cnt2 += 1
                oldpos = s.pos

                # Find next FF
                pos = s.pos_find(self.FF)
                if pos is None or pos < 0:
                    raise SoulError(f"Iteration {cnt+1}/{cnt2}: FF not found after pos {oldpos:#x}")

                s.pos_set(pos)
                ff = s.pos_read(1)
                if ff != self.FF:
                    raise SoulError(f"Iteration {cnt+1}/{cnt2} at pos {pos:#x}: expected FF, got {ff.hex()}")

                marker = s.pos_read(1)
                marker_val = marker[0]

            # Check for End of Image
            if marker_val == self.EOI[0]:
                if s.offset is None:
                    raise SoulError(f"Iteration {cnt+1}: Found EOI before any SOS")
                # Length includes from SOS start (FF DA) to after EOI (current position)
                s.length = s.pos - s.offset
                return

            # For other markers, skip their data segment
            # pos is now 2 bytes past the FF XX marker
            # Read 2-byte length (big-endian) which includes itself
            if s.pos + 2 > s.size:
                raise SoulError(f"Iteration {cnt+1} at pos {s.pos:#x}: beyond file size {s.size}")

            length_bytes = s.pos_read(2)
            segment_length = int.from_bytes(length_bytes, "big")
            if not segment_length:
                raise SoulError(f"Iteration {cnt+1} at pos {s.pos-2:#x}: invalid segment length")

            # Advance by segment_length (which includes the 2-byte length field itself)
            s.pos_add(segment_length - 2)  # -2 because we already read length

            if s.pos >= s.size:
                raise SoulError(f"Iteration {cnt+1} at pos {s.pos:#x}: reached/exceeded file size {s.size}")

        raise SoulError(f"Exceeded {self.MAX_ITERATIONS} iterations")


# Auto-register plugin
Soul.register_plugin(JPEGPlugin)
