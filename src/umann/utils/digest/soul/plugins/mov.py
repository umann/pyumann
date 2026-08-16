"""MOV (QuickTime) soul extraction plugin.

MOV soul is the movie data in the mdat (movie data) atom.
This excludes MOV metadata and container structure.

MOV files use the same ISO base media format as MP4.
"""

from umann.utils.digest.soul import Soul

from ._isobmff import IsoBmffPluginBase


class MOVPlugin(IsoBmffPluginBase):
    """Extract soul from MOV (QuickTime) files."""

    SUPPORTED_EXTENSIONS = {".mov", ".qt"}

    @classmethod
    def can_handle_content(cls, soul: Soul) -> bool:
        """Check if file is MOV/QuickTime."""

        # Check for QuickTime-specific ftyp brands or moov/mdat atoms
        if soul.size >= 8:
            atom_type = soul.content[4:8]
            # QuickTime files may start with ftyp, moov, mdat, or wide
            if atom_type in (b"ftyp", b"moov", b"mdat", b"wide", b"free"):
                return True

        return False


# Auto-register plugin
Soul.register_plugin(MOVPlugin)
