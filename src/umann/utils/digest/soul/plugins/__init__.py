"""Soul extraction plugins for various file formats.

Plugins are automatically discovered and registered when this module is imported.
Each plugin file must call Soul.register_plugin() at module level.
"""

import importlib
from pathlib import Path

from umann.utils.fs_utils import project_root


def _discover_and_load_plugins():
    """Dynamically discover and import all plugin modules.

    This triggers the Soul.register_plugin() calls in each plugin file,
    registering them with the Soul class.
    """
    plugins_dir = Path(__file__).parent

    for plugin_file in plugins_dir.glob("[a-z]*.py"):  # skip __init__.py
        # Import the module to trigger plugin registration
        # e.g src/umann/digest/soul/plugins/jpg.py --> umann.digest.soul.plugins.jpg
        importlib.import_module(project_root(plugin_file, as_module=True))


# Auto-discover and load all plugins on module import
_discover_and_load_plugins()
