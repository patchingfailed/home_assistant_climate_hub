"""Diagnostics: the full decision chain of a hub entry (integration §13)."""

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import ClimateHubConfigEntry
from .logic.codec import dump_comfort, dump_state


def _plain(value: Any) -> Any:
    """Recursively convert dataclasses, enums, datetimes and tuple keys to JSON."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return _plain(value.value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Mapping):
        return {
            "/".join(map(str, key)) if isinstance(key, tuple) else str(_plain(key)): (
                _plain(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [_plain(item) for item in value]
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ClimateHubConfigEntry
) -> dict[str, Any]:
    """Return options, model, engine state, last results and store bookkeeping."""
    coordinator = entry.runtime_data.coordinator
    result = coordinator.data
    return {
        "options": _plain(entry.options),
        "subentries": [
            {
                "id": sub.subentry_id,
                "type": sub.subentry_type,
                "title": sub.title,
                "data": _plain(sub.data),
            }
            for sub in entry.subentries.values()
        ],
        "model": _plain(coordinator.model),
        "state": dump_state(coordinator.state),
        "comfort": dump_comfort(coordinator.comfort),
        "results": None
        if result is None
        else {
            "rooms": _plain(result.rooms),
            "regions": _plain(result.regions),
            "windows": _plain(result.windows),
            "house": _plain(result.house),
        },
        "failures": _plain(result.failures) if result is not None else {},
        "forecast": _plain(coordinator.forecast),
        "store": {
            "seen": _plain(coordinator.seen),
            "area_sync": _plain(coordinator.area_sync),
            "device_areas": _plain(coordinator.device_areas),
        },
    }
