"""Default soul extraction plugin.

Default soul is the entire file:
- Start: Beginning of file
- End: End of file
"""

from umann.digest.soul import Soul, SoulPlugin


class DefaultPlugin(SoulPlugin):
    """Extract soul from Default files."""

    rank = 99  # Lowest priority

    @classmethod
    def can_handle(cls, soul: Soul) -> bool:  # pylint: disable=unused-argument
        """Check if file is Default."""

        return True  # Always return true with high rank (low priority) to let other plugins handle known formats first

    def handle(self) -> None:
        # breakpoint()
        """Extract Default soul as entire file."""
        self.soul.soulless = True
        # self.soul.offset = 0
        # self.soul.length = self.soul.size


# Auto-register plugin
Soul.register_plugin(DefaultPlugin)
