"""Fix flows of the fixable repair issues (integration §10.2, §10.3)."""

from typing import Any

from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntry, ConfigEntryState, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, SUBENTRY_ROOM, SUBENTRY_WINDOW
from .flows.common import subentry_by_area
from .flows.hub import new_room_item, new_subentry
from .flows.preview import area_name, async_run_preview, async_texts, room_markdown
from .issues import NEW_SOURCE_PREFIX, WINDOWS_PREFIX
from .logic import model as m
from .logic.prefill import follow_devices
from .logic.sources import Metric
from .registry import entity_infos
from .store import SeenEntry, fingerprint

ABORT_GONE = "gone"
ABORT_NO_TEMPERATURE = "no_room_temperature"
ABORT_DECLINED = "declined"
_FOLLOWED = ((Metric.HUMIDITY, m.CONF_HUMIDITY), (Metric.PRESSURE, m.CONF_PRESSURE))


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None
) -> RepairsFlow:
    """The fix flow of an issue, chosen by its ID prefix."""
    if issue_id.startswith(NEW_SOURCE_PREFIX):
        return NewSourceFlow()
    if issue_id.startswith(WINDOWS_PREFIX):
        return WindowsWithoutRoomFlow()
    raise ValueError(f"Issue {issue_id} has no fix flow")


class NewSourceFlow(RepairsFlow):
    """Append the new sensor to the object's sources, or decline it (R14)."""

    def _placeholders(self) -> dict[str, str] | None:
        issue = ir.async_get(self.hass).async_get_issue(DOMAIN, self.issue_id)
        return None if issue is None else issue.translation_placeholders

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["add", "decline"],
            description_placeholders=self._placeholders(),
        )

    async def async_step_decline(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Ignore the issue, as Home Assistant's own "Ignore" does; it stays listed."""
        placeholders = self._placeholders()
        ir.async_ignore_issue(self.hass, DOMAIN, self.issue_id, True)
        return self.async_abort(
            reason=ABORT_DECLINED, description_placeholders=placeholders
        )

    async def async_step_add(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        assert self.data is not None
        entry = self.hass.config_entries.async_get_entry(str(self.data["entry_id"]))
        entity_id = str(self.data["entity_id"])
        subentry = (
            None
            if entry is None
            else entry.subentries.get(str(self.data["subentry_id"]))
        )
        if (
            entry is None
            or subentry is None
            or entity_id in subentry.data.get(m.CONF_TEMPERATURE, ())
        ):
            return self.async_abort(reason=ABORT_GONE)
        new_data = self._new_data(subentry, entity_id)
        if entry.state is ConfigEntryState.LOADED:
            await self._async_keep_seen(entry, subentry, new_data, entity_id)
        self.hass.config_entries.async_update_subentry(entry, subentry, data=new_data)
        return self.async_create_entry(data={})

    def _new_data(self, subentry: ConfigSubentry, entity_id: str) -> dict[str, Any]:
        new_data = dict(subentry.data)
        new_data[m.CONF_TEMPERATURE] = [*subentry.data[m.CONF_TEMPERATURE], entity_id]
        infos = entity_infos(self.hass)
        for metric, key in _FOLLOWED:
            listed = list(subentry.data.get(key) or [])
            if not listed:
                continue  # empty means follow (R3)
            listed.extend(
                i for i in follow_devices([entity_id], infos, metric) if i not in listed
            )
            new_data[key] = listed
        return new_data

    async def _async_keep_seen(
        self,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        new_data: dict[str, Any],
        entity_id: str,
    ) -> None:
        """A fix is no review of the whole form: only its entity becomes seen (I4)."""
        coordinator = entry.runtime_data.coordinator
        old = coordinator.seen.get(subentry.subentry_id)
        coordinator.seen[subentry.subentry_id] = SeenEntry(
            fingerprint(new_data), (*(old.entities if old else ()), entity_id)
        )
        await coordinator.store.async_save(coordinator.store_data())


class WindowsWithoutRoomFlow(RepairsFlow):
    """Recreate the room or delete the windows of an area without a room (W11)."""

    def _state(self) -> tuple[ConfigEntry, str, list[ConfigSubentry]] | None:
        """The entry, the area and its window subentries; None when nothing is left."""
        assert self.data is not None
        entry = self.hass.config_entries.async_get_entry(str(self.data["entry_id"]))
        area_id = str(self.data["area_id"])
        if entry is None or area_id in subentry_by_area(entry, SUBENTRY_ROOM):
            return None
        windows = [
            sub
            for sub in entry.subentries.values()
            if sub.subentry_type == SUBENTRY_WINDOW and sub.data[m.CONF_AREA] == area_id
        ]
        return (entry, area_id, windows) if windows else None

    async def _placeholders(self, area_id: str, windows: list[ConfigSubentry]) -> dict:
        texts = await async_texts(self.hass)
        return {
            "area": area_name(self.hass, area_id),
            "windows": texts.join_and(sorted(sub.title for sub in windows)),
        }

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        if (state := self._state()) is None:
            return self.async_abort(reason=ABORT_GONE)
        _, area_id, windows = state
        return self.async_show_menu(
            step_id="init",
            menu_options=["recreate_room", "delete_windows"],
            description_placeholders=await self._placeholders(area_id, windows),
        )

    async def async_step_recreate_room(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        if (state := self._state()) is None:
            return self.async_abort(reason=ABORT_GONE)
        entry, area_id, _ = state
        texts = await async_texts(self.hass)
        item = new_room_item(self.hass, area_id)
        if not item.data.get(m.CONF_TEMPERATURE):
            # The issue stays open, so "Delete the windows" is still there next time
            return self.async_abort(
                reason=ABORT_NO_TEMPERATURE,
                description_placeholders={"area": area_name(self.hass, area_id)},
            )
        if user_input is None:
            run = await async_run_preview(
                self.hass, entry, None, item.subentry_type, item.data
            )
            return self.async_show_form(
                step_id="recreate_room",
                description_placeholders={
                    "area": area_name(self.hass, area_id),
                    "preview": room_markdown(
                        self.hass, texts, run, item.data, item.not_taken
                    ),
                },
            )
        self.hass.config_entries.async_add_subentry(
            entry, new_subentry(self.hass, texts, item)
        )
        return self.async_create_entry(data={})

    async def async_step_delete_windows(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        if (state := self._state()) is None:
            return self.async_abort(reason=ABORT_GONE)
        entry, area_id, windows = state
        if user_input is None:
            return self.async_show_form(
                step_id="delete_windows",
                description_placeholders=await self._placeholders(area_id, windows),
            )
        for sub in windows:
            self.hass.config_entries.async_remove_subentry(entry, sub.subentry_id)
        return self.async_create_entry(data={})
