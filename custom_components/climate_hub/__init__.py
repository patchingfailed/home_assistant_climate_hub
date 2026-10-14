"""The Climate Hub integration."""

from homeassistant.const import Platform
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import RELOAD_DELAY
from .coordinator import ClimateHubConfigEntry, ClimateHubCoordinator, ClimateHubData
from .registry import build_model
from .store import ClimateHubStore

PLATFORMS: list[Platform] = []


async def async_setup_entry(hass: HomeAssistant, entry: ClimateHubConfigEntry) -> bool:
    """Set up the hub entry."""
    store = ClimateHubStore(hass, entry.entry_id)
    model = build_model(hass, entry)
    coordinator = ClimateHubCoordinator(
        hass, entry, model, store, await store.async_load(model)
    )
    entry.runtime_data = ClimateHubData(coordinator, store)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    pending: CALLBACK_TYPE | None = None

    @callback
    def _reload(_now: object) -> None:
        nonlocal pending
        pending = None
        hass.config_entries.async_schedule_reload(entry.entry_id)

    async def _config_changed(
        _hass: HomeAssistant, _entry: ClimateHubConfigEntry
    ) -> None:
        """Coalesce a burst of configuration changes into one reload (I2)."""
        nonlocal pending
        if pending is None:
            pending = async_call_later(hass, RELOAD_DELAY, _reload)

    @callback
    def _cancel_pending() -> None:
        if pending is not None:
            pending()

    entry.async_on_unload(entry.add_update_listener(_config_changed))
    entry.async_on_unload(_cancel_pending)
    await coordinator.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ClimateHubConfigEntry) -> bool:
    """Unload the hub entry; the coordinator saves the Store on shutdown."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ClimateHubConfigEntry) -> None:
    """Delete the hub's Store."""
    await ClimateHubStore(hass, entry.entry_id).async_remove()
