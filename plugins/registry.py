from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class PluginInfo:
    id: str
    name: str
    version: str
    description: str
    author: str
    path: Path
    icon: str
    menu_label: str
    url: str
    has_models: bool
    has_routes: bool
    enabled: bool = True


_plugins: dict[str, PluginInfo] = {}


def register_plugin(plugin: PluginInfo):
    _plugins[plugin.id] = plugin


def unregister_plugin(plugin_id: str):
    _plugins.pop(plugin_id, None)


def get_plugin(plugin_id: str) -> Optional[PluginInfo]:
    return _plugins.get(plugin_id)


def get_all_plugins() -> list[PluginInfo]:
    return list(_plugins.values())


def get_enabled_plugins() -> list[PluginInfo]:
    return [p for p in _plugins.values() if p.enabled]


def get_menu_items() -> list[dict]:
    """Return list of dicts for the sidebar template."""
    return [
        {
            "id": p.id,
            "url": p.url,
            "icon": p.icon,
            "label_key": p.menu_label,
        }
        for p in _plugins.values()
        if p.enabled
    ]
