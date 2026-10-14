"""Diagnostics: structure, E6 candidates, JSON safety, before first evaluation."""

import json
from typing import Any

from homeassistant.core import HomeAssistant

from custom_components.climate_hub.diagnostics import (
    async_get_config_entry_diagnostics,
)
from tests.house import House
from tests.integration.test_coordinator import _entry


async def _setup(hass: HomeAssistant, house: House) -> Any:
    entry = _entry(house)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_structure(hass: HomeAssistant, house: House) -> None:
    entry = await _setup(hass, house)
    await entry.runtime_data.coordinator.async_refresh()
    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert set(diag) == {
        "options",
        "subentries",
        "model",
        "state",
        "comfort",
        "results",
        "failures",
        "forecast",
        "store",
    }
    assert {s["id"] for s in diag["subentries"]} == {
        "r_living",
        "r_bedroom",
        "g_garden",
        "w_living",
    }
    assert set(diag["results"]) == {"rooms", "regions", "windows", "house"}
    assert set(diag["results"]["rooms"]) == {"r_living", "r_bedroom"}
    assert set(diag["store"]) == {"seen", "area_sync", "device_areas"}

    candidates = diag["results"]["rooms"]["r_living"]["temperature"]["candidates"]
    assert {c["entity_id"] for c in candidates} >= {
        house.living_temp,
        house.living_air_temp,
    }
    for candidate in candidates:
        assert {"entity_id", "status", "value", "offset", "learned"} <= set(candidate)

    json.dumps(diag)


async def test_before_first_evaluation(hass: HomeAssistant, house: House) -> None:
    entry = await _setup(hass, house)
    entry.runtime_data.coordinator.data = None
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["results"] is None
    assert diag["failures"] == {}
    json.dumps(diag)
