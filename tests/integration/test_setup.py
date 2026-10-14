"""Setup, unload and the coalesced reload (docs/integration.md §6.1, I2)."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.climate_hub.const import (
    DOMAIN,
    RELOAD_DELAY,
    SUBENTRY_REGION,
    SUBENTRY_ROOM,
    SUBENTRY_WINDOW,
)

SUBENTRIES = [
    ConfigSubentryData(
        subentry_type=SUBENTRY_ROOM,
        subentry_id="room1",
        unique_id="room_living_room",
        title="Living room",
        data={
            "area": "living_room",
            "side": "s",
            "temperature": ["sensor.living_room_temperature"],
            "humidity": [],
            "pressure": [],
            "climate_devices": [],
        },
    ),
    ConfigSubentryData(
        subentry_type=SUBENTRY_REGION,
        subentry_id="region1",
        unique_id="region_n",
        title="North",
        data={
            "area": "street",
            "direction": "n",
            "temperature": ["sensor.north_temperature"],
            "humidity": [],
            "pressure": [],
        },
    ),
    ConfigSubentryData(
        subentry_type=SUBENTRY_WINDOW,
        subentry_id="window1",
        title="Living room window",
        data={
            "area": "living_room",
            "type": "single",
            "name": "Window",
            "leaf": "binary_sensor.living_room_window",
            "facing": "room",
            "min_level": "tilted",
        },
    ),
]


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Climate Hub",
        options={},
        subentries_data=SUBENTRIES,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _touch_three_times(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    for title in ("a", "b", "c"):
        assert hass.config_entries.async_update_subentry(
            entry, entry.subentries["room1"], title=title
        )


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_burst_gives_one_reload(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    with patch(
        "custom_components.climate_hub.async_setup_entry", return_value=True
    ) as setup:
        _touch_three_times(hass, entry)
        await hass.async_block_till_done()
        assert setup.call_count == 0

        async_fire_time_changed(
            hass, dt_util.utcnow() + RELOAD_DELAY + timedelta(seconds=1)
        )
        await hass.async_block_till_done()
        assert setup.call_count == 1

        # The timer is spent: nothing further happens.
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=30))
        await hass.async_block_till_done()
        assert setup.call_count == 1


async def test_unload_cancels_pending_reload(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    _touch_three_times(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    with patch(
        "custom_components.climate_hub.async_setup_entry", return_value=True
    ) as setup:
        async_fire_time_changed(
            hass, dt_util.utcnow() + RELOAD_DELAY + timedelta(seconds=1)
        )
        await hass.async_block_till_done()
        assert setup.call_count == 0
    assert entry.state is ConfigEntryState.NOT_LOADED
