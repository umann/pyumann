"""Default soul extraction plugin.

Default soul is the entire file:
- Start: Beginning of file
- End: End of file
"""

from umann.utils.digest.soul import Soul, SoulPlugin


class DefaultPlugin(SoulPlugin):
    """Extract soul from Default files."""

    SUPPORTED_EXTENSIONS = set()  # can_handle_ext always returns None but can_handle_content is always True

    rank = 99  # Lowest priority

    @classmethod
    def can_handle_content(cls, soul: Soul) -> bool:  # pylint: disable=unused-argument
        return True  # Always return true with high rank (low priority) to let other plugins handle known formats first

    def handle(self) -> None:
        """Extract Default soul as entire file."""
        self.soul.soulless = True


# Auto-register plugin
Soul.register_plugin(DefaultPlugin)
