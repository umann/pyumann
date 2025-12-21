"""ISO Base Media File Format (ISOBMFF) base plugin.

Base class for file formats using ISO BMFF structure (MP4, MOV, etc.).
"""

import struct

from umann.digest.soul import SoulError, SoulPlugin


class IsoBmffPluginBase(SoulPlugin):
    """Base plugin for ISO Base Media File Format files.

    ISO BMFF is used by MP4, MOV, M4V, M4A and other formats.
    Files are structured as a sequence of atoms (boxes):
    - 4 bytes: size (big-endian uint32)
    - 4 bytes: type (four-character code)
    - size-8 bytes: data

    Special cases:
    - size == 1: Extended size in next 8 bytes (uint64)
    - size == 0: Atom extends to end of file
    """

    def handle(self) -> None:
        """Extract soul from mdat atom.

        The mdat (movie data) atom contains the actual media payload.
        """
        s = self.soul

        # Find mdat atom
        while s.pos < s.size - 8:
            atom_start = s.pos

            # Read atom header
            atom_size = struct.unpack(">I", s.pos_read(4))[0]
            atom_type = s.pos_read(4)

            # Handle extended size
            if atom_size == 1:
                if s.pos + 8 > s.size:
                    raise SoulError("Truncated extended size atom")
                atom_size = struct.unpack(">Q", s.pos_read(8))[0]
                header_size = 16
            else:
                header_size = 8

            # Handle size == 0 (atom extends to EOF)
            if atom_size == 0:
                atom_size = s.size - atom_start

            # Check if this is the mdat atom
            if atom_type == b"mdat":
                # Soul starts after the atom header
                s.offset = s.pos
                # Soul length is atom size minus header
                s.length = atom_size - header_size

                # Verify we don't exceed file bounds
                if s.offset + s.length > s.size:
                    raise SoulError(f"mdat atom extends beyond file: {s.offset + s.length} > {s.size}")

                return

            # Skip to next atom
            next_pos = atom_start + atom_size
            if next_pos <= atom_start or next_pos > s.size:
                # Invalid atom size or would go backwards/beyond EOF
                break

            s.pos_set(next_pos)

        raise SoulError("No mdat atom found in ISO BMFF file")
