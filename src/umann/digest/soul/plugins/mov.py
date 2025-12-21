"""MOV (QuickTime) soul extraction plugin.

MOV soul is the movie data in the mdat (movie data) atom.
This excludes MOV metadata and container structure.

MOV files use the same ISO base media format as MP4.
"""

from umann.digest.soul import Soul

from ._isobmff import IsoBmffPluginBase


class MOVPlugin(IsoBmffPluginBase):
    """Extract soul from MOV (QuickTime) files."""

    @classmethod
    def can_handle(cls, soul: Soul) -> bool:
        """Check if file is MOV/QuickTime."""
        if soul.file:
            suffix = soul.file.suffix.lower()
            if suffix in (".mov", ".qt"):
                return True

        # Check for QuickTime-specific ftyp brands or moov/mdat atoms
        if soul.size >= 8:
            atom_type = soul.content[4:8]
            # QuickTime files may start with ftyp, moov, mdat, or wide
            if atom_type in (b"ftyp", b"moov", b"mdat", b"wide", b"free"):
                return True

        return False


# Auto-register plugin
Soul.register_plugin(MOVPlugin)
