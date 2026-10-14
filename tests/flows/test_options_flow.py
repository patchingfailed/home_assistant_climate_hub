"""Hub options, screen S9 (docs/integration.md 9.6), through the flow manager."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.climate_hub.const import RELOAD_DELAY

from ..house import House
from .conftest import field, suggested

TIMING = {
    "max_age": 30,
    "burst_duration": 15,
    "humidity_threshold": 65,
    "repair_delay": 12,
}


@contextmanager
def count_reloads(hass: HomeAssistant) -> Iterator[Any]:
    """Patch the setup so that reloads can be counted (see test_setup.py)."""
    with patch(
        "custom_components.climate_hub.async_setup_entry", return_value=True
    ) as setup:
        yield setup


async def settle(hass: HomeAssistant) -> None:
    """Let the coalesced reload timer run out."""
    await hass.async_block_till_done()
    async_fire_time_changed(
        hass, dt_util.utcnow() + RELOAD_DELAY + timedelta(seconds=1)
    )
    await hass.async_block_till_done()


async def test_form_is_filled_from_the_options(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(hub.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert [str(k) for k in result["data_schema"].schema] == [
        "weather",
        "area_sync",
        "timing",
    ]
    assert suggested(result, "weather") == house.weather
    assert suggested(result, "area_sync") is True
    # Options the hub fixture lacks show the logic defaults
    assert {k: suggested(result, f"timing.{k}") for k in TIMING} == {
        "max_age": 40,
        "burst_duration": 10,
        "humidity_threshold": 60.0,
        "repair_delay": 6,
    }
    _, selector = field(result, "timing.max_age")
    assert selector.config["unit_of_measurement"] == "min"


async def test_saving_stores_flat_options_and_reloads_once(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(hub.entry_id)
    with count_reloads(hass) as setup:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                "weather": house.weather,
                "area_sync": False,
                "timing": {k: float(v) for k, v in TIMING.items()},
            },
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await settle(hass)
        assert setup.call_count == 1
    assert dict(hub.options) == {
        "weather": house.weather,
        "area_sync": False,
        "max_age": 30,
        "burst_duration": 15,
        "humidity_threshold": 65.0,
        "repair_delay": 12,
    }
    assert isinstance(hub.options["max_age"], int)
    assert isinstance(hub.options["humidity_threshold"], float)


async def test_clearing_the_weather_removes_the_option(
    hass: HomeAssistant, house: House, hub: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(hub.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"area_sync": True, "timing": TIMING}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "weather" not in hub.options
