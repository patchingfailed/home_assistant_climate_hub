"""The Store wrapper (docs/integration.md §7)."""

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.climate_hub.const import STORE_SAVE_DELAY, store_key
from custom_components.climate_hub.logic.engine import Comfort, EngineState
from custom_components.climate_hub.store import (
    ClimateHubStore,
    SeenEntry,
    StoreData,
    fingerprint,
)
from tests.logic.test_codec import _model, _state

ENTRY_ID = "entry1"
KEY = store_key(ENTRY_ID)


def _data() -> StoreData:
    return StoreData(
        engine=_state(),
        comfort=Comfort(19.0, 25.5, 3.0),
        seen={
            "r1": SeenEntry("abc", ("sensor.a", "sensor.b")),
            "g1": SeenEntry("def", ()),
            "gone": SeenEntry("zzz", ("sensor.c",)),
        },
        area_sync={"living_room": {"temperature": "sensor.a", "humidity": "sensor.b"}},
        device_areas={"r1": "living_room", "gone": "kitchen"},
    )


def _pruned() -> StoreData:
    data = _data()
    del data.seen["gone"]
    del data.device_areas["gone"]
    return data


async def test_empty_store_gives_defaults(hass: HomeAssistant) -> None:
    data = await ClimateHubStore(hass, ENTRY_ID).async_load(_model())
    assert data == StoreData(EngineState.empty(), Comfort(20.0, 24.0, 2.0))


async def test_save_and_reload_into_new_store(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    await ClimateHubStore(hass, ENTRY_ID).async_save(_data())
    assert hass_storage[KEY]["version"] == 1
    assert hass_storage[KEY]["minor_version"] == 1

    loaded = await ClimateHubStore(hass, ENTRY_ID).async_load(_model())

    assert loaded == _pruned()


async def test_load_prunes_seen_and_device_areas_not_area_sync(
    hass: HomeAssistant,
) -> None:
    store = ClimateHubStore(hass, ENTRY_ID)
    await store.async_save(_data())

    loaded = await ClimateHubStore(hass, ENTRY_ID).async_load(
        _model(rooms=("r2",), regions=("g1",), windows=())
    )

    assert set(loaded.seen) == {"g1"}
    assert loaded.device_areas == {}
    assert loaded.area_sync == _data().area_sync
    assert set(loaded.engine.rooms) == {"r2"}


async def test_delayed_save_writes_after_the_delay(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    store = ClimateHubStore(hass, ENTRY_ID)
    current = _data()
    store.schedule_save(lambda: current)
    assert KEY not in hass_storage

    async_fire_time_changed(
        hass, dt_util.utcnow() + STORE_SAVE_DELAY - timedelta(seconds=5)
    )
    await hass.async_block_till_done()
    assert KEY not in hass_storage

    current.comfort = Comfort(18.0, 26.0, 1.5)  # the provider runs at write time
    async_fire_time_changed(
        hass, dt_util.utcnow() + STORE_SAVE_DELAY + timedelta(seconds=5)
    )
    await hass.async_block_till_done()

    assert hass_storage[KEY]["data"]["comfort"] == {
        "min": 18.0,
        "max": 26.0,
        "threshold": 1.5,
    }


async def test_remove_deletes_the_data(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    store = ClimateHubStore(hass, ENTRY_ID)
    await store.async_save(_data())
    assert KEY in hass_storage

    await store.async_remove()

    assert KEY not in hass_storage
    assert await ClimateHubStore(hass, ENTRY_ID).async_load(_model()) == StoreData(
        EngineState.empty(), Comfort(20.0, 24.0, 2.0)
    )


async def test_garbage_in_the_file_starts_fresh(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    hass_storage[KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": KEY,
        "data": {"engine": 5, "comfort": [], "seen": {"r1": {}}, "device_areas": 3},
    }

    data = await ClimateHubStore(hass, ENTRY_ID).async_load(_model())

    assert data == StoreData(EngineState.empty(), Comfort(20.0, 24.0, 2.0))


def test_fingerprint_is_stable_and_order_independent() -> None:
    a = fingerprint({"area": "x", "temperature": ["sensor.a"], "n": 1})
    b = fingerprint({"n": 1, "temperature": ["sensor.a"], "area": "x"})
    assert a == b
    assert a != fingerprint({"area": "x", "temperature": ["sensor.b"], "n": 1})
