"""Plugin auto-discovery and loader.

On import, scans the plugins/ directory and registers all PlatformPlugin subclasses.
Access via: get_plugin(plugin_id) or list_plugins()
"""

from __future__ import annotations
import importlib
import inspect
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.platform.plugin_base import PlatformPlugin

logger = logging.getLogger("platform.plugins")

_registry: dict[str, "PlatformPlugin"] = {}
_loaded = False


def _discover_plugins() -> None:
    """Scan plugins/ directory and register all PlatformPlugin subclasses.

    Uses duck-typing (checks for plugin_id, plugin_name, initialize) to avoid
    circular imports between plugins/__init__.py and plugin_base.py.
    """
    global _loaded
    if _loaded:
        return
    _loaded = True

    plugin_dir = os.path.dirname(__file__)
    if not os.path.isdir(plugin_dir):
        logger.warning("Plugin directory not found: %s", plugin_dir)
        return

    for fname in sorted(os.listdir(plugin_dir)):
        if fname.startswith("_") or fname == "__pycache__" or not fname.endswith(".py"):
            continue
        modname = fname[:-3]
        try:
            mod = importlib.import_module(f"src.platform.plugins.{modname}")
            for _name, cls in inspect.getmembers(mod, inspect.isclass):
                pid = getattr(cls, "plugin_id", None)
                pname = getattr(cls, "plugin_name", None)
                if pid and pname and hasattr(cls, "initialize"):
                    try:
                        inst = cls()
                        _registry[pid] = inst
                        logger.info("Loaded plugin: %s (%s)", pid, pname)
                    except Exception as e:
                        logger.warning("Failed to init plugin %s: %s", pname, e)
                        logger.debug("Init error detail", exc_info=True)
        except Exception as e:
            logger.debug("Skipping plugin %s: %s", fname, e)


def get_plugin(plugin_id: str) -> "PlatformPlugin | None":
    """Return a registered plugin by its plugin_id, or None."""
    _discover_plugins()
    return _registry.get(plugin_id)


def list_plugins() -> list["PlatformPlugin"]:
    """Return all registered plugin instances."""
    _discover_plugins()
    return list(_registry.values())


def reload_plugins() -> None:
    """Clear the registry and re-scan. Useful for hot-reload during development."""
    global _loaded
    _registry.clear()
    _loaded = False
    _discover_plugins()
