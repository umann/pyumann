"""MP4 soul extraction plugin.

MP4 soul is the movie data in the mdat (movie data) atom.
This excludes MP4 metadata and container structure.
"""

import struct

from umann.digest.soul import Soul

from ._isobmff import IsoBmffPluginBase


class MP4Plugin(IsoBmffPluginBase):
    """Extract soul from MP4 files."""

    @classmethod
    def can_handle(cls, soul: Soul) -> bool:
        """Check if file is MP4/M4V/M4A."""
        if soul.file:
            suffix = soul.file.suffix.lower()
            if suffix in (".mp4", ".m4v", ".m4a"):
                return True

        # Check for ftyp atom at start (ISO base media file format)
        if soul.size >= 12:
            # Read first 12 bytes: size (4) + type (4) + major brand (4)
            atom_size = struct.unpack(">I", soul.content[:4])[0]
            atom_type = soul.content[4:8]
            major_brand = soul.content[8:12]

            # Accept only common MP4/M4V/M4A brands so that MOV ('qt  ') is left
            # to the dedicated MOV plugin
            mp4_brands = {b"isom", b"iso2", b"mp41", b"mp42", b"M4A ", b"M4V ", b"avc1"}
            return atom_type == b"ftyp" and major_brand in mp4_brands and 12 <= atom_size <= soul.size

        return False


# Auto-register plugin
Soul.register_plugin(MP4Plugin)
