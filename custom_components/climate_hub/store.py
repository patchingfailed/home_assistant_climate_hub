"""Persistence of the hub's state in one Home Assistant `Store` (integration §7)."""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    LOGGER,
    STORE_MINOR_VERSION,
    STORE_SAVE_DELAY,
    STORE_VERSION,
    store_key,
)
from .logic.codec import dump_comfort, dump_state, load_comfort, load_state
from .logic.engine import Comfort, EngineState
from .logic.model import HouseModel


@dataclass(frozen=True, slots=True)
class SeenEntry:
    """Pre-fillable entities in the area when the subentry was last saved (I4)."""

    fingerprint: str
    entities: tuple[str, ...]


@dataclass(slots=True)
class StoreData:
    engine: EngineState
    comfort: Comfort
    seen: dict[str, SeenEntry] = field(default_factory=dict)
    area_sync: dict[str, dict[str, str]] = field(default_factory=dict)
    device_areas: dict[str, str] = field(default_factory=dict)


def fingerprint(data: Mapping[str, Any]) -> str:
    """Return a stable hash of subentry data.

    A plain dict first: `json.dumps` would hash a `MappingProxyType` by its `str()`,
    which depends on key order.
    """
    text = json.dumps(dict(data), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _dump(data: StoreData) -> dict[str, Any]:
    return {
        "engine": dump_state(data.engine),
        "comfort": dump_comfort(data.comfort),
        "seen": {
            subentry_id: {
                "fingerprint": entry.fingerprint,
                "entities": list(entry.entities),
            }
            for subentry_id, entry in data.seen.items()
        },
        "area_sync": data.area_sync,
        "device_areas": data.device_areas,
    }


def _load_seen(raw: Any, known: set[str]) -> dict[str, SeenEntry]:
    seen: dict[str, SeenEntry] = {}
    if not isinstance(raw, Mapping):
        return seen
    for subentry_id, entry in raw.items():
        if subentry_id not in known:
            continue
        try:
            entities = entry["entities"]
            if isinstance(entities, str) or not all(
                isinstance(e, str) for e in entities
            ):
                raise TypeError("entity list expected")
            if not isinstance(entry["fingerprint"], str):
                raise TypeError("string expected")
            seen[subentry_id] = SeenEntry(entry["fingerprint"], tuple(entities))
        except KeyError, TypeError:
            LOGGER.debug("Stored seen entry %s dropped", subentry_id)
    return seen


def _load_area_sync(raw: Any) -> dict[str, dict[str, str]]:
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(area_id): {
            str(field_name): entity_id
            for field_name, entity_id in fields.items()
            if isinstance(entity_id, str)
        }
        for area_id, fields in raw.items()
        if isinstance(fields, Mapping)
    }


def _load_device_areas(raw: Any, known: set[str]) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    return {
        subentry_id: area_id
        for subentry_id, area_id in raw.items()
        if subentry_id in known and isinstance(area_id, str)
    }


class ClimateHubStore:
    """One `Store` per hub entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORE_VERSION,
            store_key(entry_id),
            minor_version=STORE_MINOR_VERSION,
        )

    async def async_load(self, model: HouseModel) -> StoreData:
        """Load and prune to the subentries the model has; garbage starts fresh."""
        raw = await self._store.async_load()
        if not isinstance(raw, Mapping):
            raw = {}
        known = {*model.rooms, *model.regions, *model.windows}
        return StoreData(
            engine=load_state(raw.get("engine"), model),
            comfort=load_comfort(raw.get("comfort")),
            seen=_load_seen(raw.get("seen"), known),
            area_sync=_load_area_sync(raw.get("area_sync")),
            device_areas=_load_device_areas(raw.get("device_areas"), known),
        )

    async def async_load_area_sync(self) -> dict[str, dict[str, str]]:
        """Only the area-sync records, for removal when no model exists."""
        raw = await self._store.async_load()
        return _load_area_sync(
            raw.get("area_sync") if isinstance(raw, Mapping) else None
        )

    def schedule_save(self, provider: Callable[[], StoreData]) -> None:
        """Save after `STORE_SAVE_DELAY`; the provider runs when the write is due."""
        self._store.async_delay_save(
            lambda: _dump(provider()), STORE_SAVE_DELAY.total_seconds()
        )

    async def async_save(self, data: StoreData) -> None:
        """Save at once."""
        await self._store.async_save(_dump(data))

    async def async_remove(self) -> None:
        """Delete the stored file."""
        await self._store.async_remove()
