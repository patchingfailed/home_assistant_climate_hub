"""Window flow (docs/integration.md 9.5, screens S8, S8a-c, S8d and the preview).

`WindowSteps` holds all steps and reaches the outside only through a few hooks, so the
first setup can use it too. `WindowSubentryFlow` is the subentry flow that implements
the hooks. The room step has its own ID `window_room`, so a host flow keeps its own
`user` and `reconfigure` steps.
"""

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import probatio
from homeassistant.config_entries import SOURCE_RECONFIGURE, ConfigSubentryFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    AreaSelector,
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    Selector,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from homeassistant.util import dt as dt_util

from ..const import SUBENTRY_REGION, SUBENTRY_ROOM, SUBENTRY_WINDOW
from ..logic import model as m
from ..logic.window import Level, suggest_text_mapping
from ..registry import entity_infos
from .common import (
    async_level_words,
    async_window_words,
    contact_choices,
    option_selector,
    subentry_by_area,
)
from .hub import new_room_item, new_subentry
from .preview import (
    PlanItem,
    PreviewRun,
    Texts,
    area_name,
    async_run_preview,
    async_texts,
    entity_name,
    window_markdown,
)

SECTION_EXTRA_CONTACTS = "extra_contacts"
SECTION_COVER = "cover"
SECTION_ADVANCED = "advanced"
SHOW_ALL = "show_all"

TYPES = (m.WINDOW_SINGLE, m.WINDOW_DOUBLE, m.WINDOW_PASS_THROUGH)
FACINGS = [m.FACING_ROOM, "n", "e", "s", "w"]
MIN_LEVELS = [m.MIN_LEVEL_AJAR, m.MIN_LEVEL_TILTED, m.MIN_LEVEL_OPEN]
LEVEL_FIELDS = tuple(level.name.lower() for level in Level)
HISTORY = timedelta(days=14)
_BINARY_PREFIX = "binary_sensor."

# Contact keys of each type, and those that must be set
CONTACTS = {
    m.WINDOW_SINGLE: (m.CONF_LEAF, m.CONF_TILT, m.CONF_HANDLE),
    m.WINDOW_DOUBLE: (m.CONF_LEAF_LEFT, m.CONF_LEAF_RIGHT, m.CONF_TILT, m.CONF_HANDLE),
    m.WINDOW_PASS_THROUGH: (m.CONF_INNER, m.CONF_OUTER),
}
REQUIRED = {
    m.WINDOW_SINGLE: (m.CONF_LEAF,),
    m.WINDOW_DOUBLE: (m.CONF_LEAF_LEFT, m.CONF_LEAF_RIGHT),
    m.WINDOW_PASS_THROUGH: (m.CONF_INNER, m.CONF_OUTER),
}
# Contacts of the section "extra_contacts"; the others are main fields
EXTRA_CONTACTS = {
    m.WINDOW_SINGLE: (m.CONF_TILT, m.CONF_HANDLE),
    m.WINDOW_DOUBLE: (m.CONF_HANDLE,),
    m.WINDOW_PASS_THROUGH: (),
}
_SECTIONS = (SECTION_EXTRA_CONTACTS, SECTION_COVER, SECTION_ADVANCED)


def step_id(window_type: str) -> str:
    return f"window_{window_type}"


@dataclass(slots=True)
class WindowDraft:
    """The window being added or edited; `values` are the flat form values."""

    type: str = ""
    values: dict[str, Any] = field(default_factory=dict)
    mappings: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    queue: list[str] = field(default_factory=list)  # text sensors still to map
    show_all: bool = False
    listed_for: str = ""  # the area the contact lists were built for


def flatten(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Form input to flat values (sections are UI only)."""
    flat: dict[str, Any] = {}
    for key, value in user_input.items():
        if key in _SECTIONS and isinstance(value, Mapping):
            flat.update(value)
        else:
            flat[key] = value
    return flat


def nest(window_type: str, values: Mapping[str, Any], show_all: bool) -> dict[str, Any]:
    """Flat values to suggested form values."""
    extra = EXTRA_CONTACTS[window_type]
    main = [k for k in CONTACTS[window_type] if k not in extra]
    suggestion: dict[str, Any] = {
        k: values[k]
        for k in (m.CONF_AREA, m.CONF_NAME, *main)
        if values.get(k) not in (None, "")
    }
    suggestion[SHOW_ALL] = show_all
    suggestion[SECTION_EXTRA_CONTACTS] = {k: values[k] for k in extra if values.get(k)}
    suggestion[SECTION_COVER] = {k: values[k] for k in (m.CONF_COVER,) if values.get(k)}
    suggestion[SECTION_ADVANCED] = {
        k: values[k]
        for k in (m.CONF_FACING, m.CONF_FACING_DEGREES, m.CONF_MIN_LEVEL)
        if values.get(k) is not None
    }
    return suggestion


def _is_text(entity_id: str) -> bool:
    return not entity_id.startswith(_BINARY_PREFIX)


# Known texts and words of a text sensor (S8d)


async def async_recorded_states(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Distinct recorded states of the last 14 days (only with a recorder)."""
    if "recorder" not in hass.config.components:
        return []
    from homeassistant.components.recorder import get_instance, history

    end = dt_util.utcnow()

    def query() -> Mapping[str, list[Any]]:
        return history.get_significant_states(
            hass,
            end - HISTORY,
            end,
            [entity_id],
            include_start_time_state=True,
            significant_changes_only=False,
            minimal_response=True,
            no_attributes=True,
        )

    found = await get_instance(hass).async_add_executor_job(query)
    return [
        item["state"] if isinstance(item, dict) else item.state
        for item in found.get(entity_id, ())
    ]


async def async_known_texts(hass: HomeAssistant, entity_id: str) -> list[str]:
    """The `options` attribute, the recorded states and the current state."""
    state = hass.states.get(entity_id)
    texts: list[Any] = [] if state is None else [*state.attributes.get("options", ())]
    texts.extend(await async_recorded_states(hass, entity_id))
    if state is not None:
        texts.append(state.state)
    return [
        text
        for text in dict.fromkeys(texts)
        if isinstance(text, str) and text not in ("", "unknown", "unavailable")
    ]


class WindowSteps:
    """All window steps; a host flow implements the `_window_*` hooks."""

    hass: HomeAssistant
    # Provided by the flow base class
    async_show_form: Any
    async_show_menu: Any
    add_suggested_values_to_schema: Any

    _window_draft: WindowDraft | None = None

    # Hooks

    def _window_room_selector(self) -> Selector:
        """The room field of the `window_room` step and of the type forms."""
        raise NotImplementedError

    def _window_room_problem(self, area_id: str) -> str | None:
        """Error key when the area cannot hold a window (`is_region`), else None."""
        raise NotImplementedError

    def _window_names_in(self, area_id: str) -> list[str]:
        """Names of the other windows in that room, for the numbering."""
        raise NotImplementedError

    def _window_has_room(self, area_id: str) -> bool:
        """Whether the area already is a room (else saving creates it)."""
        raise NotImplementedError

    async def _async_window_preview_run(
        self, data: Mapping[str, Any], extra: list[PlanItem]
    ) -> PreviewRun:
        """One engine run with the window and the rooms that would be created."""
        raise NotImplementedError

    async def _async_window_finish(self, data: dict[str, Any], title: str) -> Any:
        """Save the window (and its room, see `_window_new_room`)."""
        raise NotImplementedError

    # Draft

    @property
    def _draft(self) -> WindowDraft:
        if self._window_draft is None:
            self._window_draft = WindowDraft()
        return self._window_draft

    def _window_begin(self, area_id: str) -> None:
        """Add: a fresh draft for the room."""
        self._window_draft = WindowDraft(
            values={m.CONF_AREA: area_id}, listed_for=area_id
        )

    def _window_load(self, data: Mapping[str, Any]) -> None:
        """Edit: the stored data."""
        self._window_draft = WindowDraft(
            type=data[m.CONF_TYPE],
            values={k: v for k, v in data.items() if k != m.CONF_MAPPINGS},
            mappings=copy.deepcopy(dict(data.get(m.CONF_MAPPINGS, {}))),
            listed_for=data[m.CONF_AREA],
        )

    def _window_new_room(self, area_id: str) -> PlanItem:
        """The room that saving creates along, with suggested sources (U4)."""
        return new_room_item(self.hass, area_id)

    # Names and data

    def _window_name(self, texts: Texts) -> str:
        """The user's name, else the translated default numbered in the room."""
        draft = self._draft
        if given := str(draft.values.get(m.CONF_NAME) or "").strip():
            return given
        base = texts(
            "pass_through_name"
            if draft.type == m.WINDOW_PASS_THROUGH
            else "window_name"
        )
        taken = {n.casefold() for n in self._window_names_in(self._area)}
        name, number = base, 2
        while name.casefold() in taken:
            name, number = f"{base} {number}", number + 1
        return name

    @property
    def _area(self) -> str:
        return str(self._draft.values[m.CONF_AREA])

    def _window_data(self, texts: Texts) -> dict[str, Any]:
        """The data to save, exactly the keys of §3.2."""
        draft, values = self._draft, self._draft.values
        data: dict[str, Any] = {
            m.CONF_AREA: self._area,
            m.CONF_TYPE: draft.type,
            m.CONF_NAME: self._window_name(texts),
        }
        data.update({k: values[k] for k in CONTACTS[draft.type] if values.get(k)})
        if draft.mappings:
            data[m.CONF_MAPPINGS] = copy.deepcopy(draft.mappings)
        if values.get(m.CONF_COVER):
            data[m.CONF_COVER] = values[m.CONF_COVER]
        data[m.CONF_FACING] = values.get(m.CONF_FACING) or m.FACING_ROOM
        if values.get(m.CONF_FACING_DEGREES) is not None:
            data[m.CONF_FACING_DEGREES] = float(values[m.CONF_FACING_DEGREES])
        data[m.CONF_MIN_LEVEL] = values.get(m.CONF_MIN_LEVEL) or m.MIN_LEVEL_TILTED
        return data

    def _window_title(self, texts: Texts, data: Mapping[str, Any]) -> str:
        return texts(
            "window_title",
            area=area_name(self.hass, data[m.CONF_AREA]),
            name=data[m.CONF_NAME],
        )

    # Room (add)

    async def async_step_window_room(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        errors: dict[str, str] = {}
        placeholders = {"area": ""}
        if user_input is not None:
            area_id = user_input[m.CONF_AREA]
            if (problem := self._window_room_problem(area_id)) is None:
                self._window_begin(area_id)
                return await self.async_step_window_type()
            errors["base"] = problem
            placeholders["area"] = area_name(self.hass, area_id)
        return self.async_show_form(
            step_id="window_room",
            data_schema=probatio.Schema(
                {probatio.Required(m.CONF_AREA): self._window_room_selector()}
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    # Type (S8)

    async def async_step_window_type(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return self.async_show_menu(
            step_id="window_type",
            menu_options=[step_id(t) for t in TYPES],
            description_placeholders={"area": area_name(self.hass, self._area)},
        )

    async def async_step_window_single(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return await self._async_window_form(m.WINDOW_SINGLE, user_input)

    async def async_step_window_double(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return await self._async_window_form(m.WINDOW_DOUBLE, user_input)

    async def async_step_window_pass_through(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return await self._async_window_form(m.WINDOW_PASS_THROUGH, user_input)

    # Form (S8a-c)

    def _contact_selector(self, choices: list[str]) -> EntitySelector:
        return EntitySelector(EntitySelectorConfig(include_entities=choices))

    def _window_schema(
        self, window_type: str, words: frozenset[str] | None
    ) -> probatio.Schema:
        """`words`: text sensors must name a window position; None lists all."""
        draft, values = self._draft, self._draft.values
        infos = entity_infos(self.hass)
        chosen = [values[k] for k in CONTACTS[window_type] if values.get(k)]
        near = self._contact_selector(
            contact_choices(
                self.hass,
                infos,
                None if draft.show_all else draft.listed_for,
                chosen,
                words,
            )
        )
        everywhere = self._contact_selector(
            contact_choices(self.hass, infos, None, chosen, words)
        )
        extra = EXTRA_CONTACTS[window_type]
        fields: dict[Any, Any] = {
            probatio.Required(m.CONF_AREA): self._window_room_selector()
        }
        for key in CONTACTS[window_type]:
            if key in extra:
                continue
            fields[probatio.Optional(key)] = everywhere if key == m.CONF_OUTER else near
            if key == m.CONF_INNER:  # the toggle sits under the list it widens
                fields[probatio.Optional(SHOW_ALL, default=False)] = BooleanSelector()
        if window_type != m.WINDOW_PASS_THROUGH:
            fields[probatio.Optional(SHOW_ALL, default=False)] = BooleanSelector()
        fields[probatio.Optional(m.CONF_NAME)] = TextSelector()
        if extra:
            fields[probatio.Required(SECTION_EXTRA_CONTACTS)] = section(
                probatio.Schema({probatio.Optional(k): near for k in extra}),
                {"collapsed": not any(values.get(k) for k in extra)},
            )
        fields[probatio.Required(SECTION_COVER)] = section(
            probatio.Schema(
                {
                    probatio.Optional(m.CONF_COVER): EntitySelector(
                        EntitySelectorConfig(domain="cover")
                    )
                }
            ),
            {"collapsed": not values.get(m.CONF_COVER)},
        )
        fields[probatio.Required(SECTION_ADVANCED)] = section(
            probatio.Schema(
                {
                    probatio.Optional(
                        m.CONF_FACING, default=m.FACING_ROOM
                    ): option_selector(FACINGS, "facing"),
                    probatio.Optional(m.CONF_FACING_DEGREES): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=360,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="°",
                        )
                    ),
                    probatio.Optional(
                        m.CONF_MIN_LEVEL, default=m.MIN_LEVEL_TILTED
                    ): option_selector(MIN_LEVELS, "min_level"),
                }
            ),
            {
                "collapsed": (
                    values.get(m.CONF_FACING, m.FACING_ROOM) == m.FACING_ROOM
                    and values.get(m.CONF_FACING_DEGREES) is None
                    and values.get(m.CONF_MIN_LEVEL, m.MIN_LEVEL_TILTED)
                    == m.MIN_LEVEL_TILTED
                )
            },
        )
        return probatio.Schema(fields)

    async def _async_window_show(
        self,
        window_type: str,
        errors: dict[str, str] | None = None,
        placeholders: Mapping[str, str] | None = None,
    ) -> Any:
        draft = self._draft
        draft.type = window_type
        texts = await async_texts(self.hass)
        shown = (
            texts("shown_all")
            if draft.show_all
            else texts("shown_area", area=area_name(self.hass, draft.listed_for))
        )
        return self.async_show_form(
            step_id=step_id(window_type),
            data_schema=self.add_suggested_values_to_schema(
                self._window_schema(
                    window_type,
                    None if draft.show_all else await async_window_words(self.hass),
                ),
                nest(window_type, draft.values, draft.show_all),
            ),
            errors=errors or {},
            description_placeholders={
                "area": area_name(self.hass, draft.listed_for),
                "shown": shown,
                **(placeholders or {}),
            },
        )

    def _window_problem(
        self, window_type: str, values: Mapping[str, Any]
    ) -> str | None:
        if any(not values.get(k) for k in REQUIRED[window_type]):
            return "no_contact"
        chosen = [values[k] for k in CONTACTS[window_type] if values.get(k)]
        if len(set(chosen)) < len(chosen):
            return "same_contact"
        return None

    async def _async_window_form(
        self, window_type: str, user_input: dict[str, Any] | None
    ) -> Any:
        draft = self._draft
        if user_input is None:
            return await self._async_window_show(window_type)
        flat = flatten(user_input)
        show_all = bool(flat.pop(SHOW_ALL, False))
        draft.type, draft.values = window_type, flat
        area_id = flat[m.CONF_AREA]
        if (problem := self._window_room_problem(area_id)) is not None:
            return await self._async_window_show(
                window_type,
                {"base": problem},
                {"area": area_name(self.hass, area_id)},
            )
        if show_all != draft.show_all or area_id != draft.listed_for:
            # The lists depend on both; forms are not live, so the form opens again
            draft.show_all, draft.listed_for = show_all, area_id
            return await self._async_window_show(window_type)
        if (problem := self._window_problem(window_type, flat)) is not None:
            return await self._async_window_show(window_type, {"base": problem})
        contacts = [flat[k] for k in CONTACTS[window_type] if flat.get(k)]
        draft.mappings = {e: v for e, v in draft.mappings.items() if e in contacts}
        draft.queue = [e for e in contacts if _is_text(e)]
        return await self.async_step_window_mapping()

    # State mapping (S8d)

    async def async_step_window_mapping(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        draft = self._draft
        if user_input is not None:
            entity_id = draft.queue.pop(0)
            mapping = {k: list(v) for k, v in user_input.items() if v}
            if mapping:
                draft.mappings[entity_id] = mapping
            else:
                draft.mappings.pop(entity_id, None)
        if not draft.queue:
            return await self._async_window_preview()
        entity_id = draft.queue[0]
        known = await async_known_texts(self.hass, entity_id)
        if entity_id in draft.mappings:
            prefill = draft.mappings[entity_id]
        else:
            found = suggest_text_mapping(known, await async_level_words(self.hass))
            prefill = {
                level.name.lower(): [t for t in known if t in found[level]]
                for level in Level
            }
        picked = [t for texts_ in prefill.values() for t in texts_]
        options = list(dict.fromkeys([*known, *picked]))
        selector = SelectSelector(
            SelectSelectorConfig(
                options=options,
                multiple=True,
                custom_value=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
        return self.async_show_form(
            step_id="window_mapping",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema({probatio.Optional(f): selector for f in LEVEL_FIELDS}),
                {k: v for k, v in prefill.items() if v},
            ),
            description_placeholders={"sensor": entity_name(self.hass, entity_id)},
        )

    # Preview and save

    async def _async_window_preview(self) -> Any:
        texts = await async_texts(self.hass)
        data = self._window_data(texts)
        area_id = data[m.CONF_AREA]
        new_room = (
            None if self._window_has_room(area_id) else self._window_new_room(area_id)
        )
        run = await self._async_window_preview_run(
            data, [] if new_room is None else [new_room]
        )
        title = self._window_title(texts, data)
        named = bool(str(self._draft.values.get(m.CONF_NAME) or "").strip())
        return self.async_show_menu(
            step_id="window_preview",
            menu_options=["window_save", "window_adjust", "window_retype"],
            description_placeholders={
                "title": title,
                "preview": window_markdown(
                    self.hass,
                    texts,
                    run,
                    title=None if named else title,
                    new_room=new_room,
                ),
            },
        )

    async def async_step_window_preview(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return await self._async_window_preview()

    async def async_step_window_adjust(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return await self._async_window_show(self._draft.type)

    async def async_step_window_retype(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        return await self.async_step_window_type()

    async def async_step_window_save(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        texts = await async_texts(self.hass)
        data = self._window_data(texts)
        return await self._async_window_finish(data, self._window_title(texts, data))


class WindowSubentryFlow(WindowSteps, ConfigSubentryFlow):
    """Add (room, type, form, preview) and edit (form, preview) of one window."""

    @property
    def _own_id(self) -> str | None:
        if self.source != SOURCE_RECONFIGURE:
            return None
        return self._get_reconfigure_subentry().subentry_id

    # Hooks

    def _window_room_selector(self) -> AreaSelector:
        return AreaSelector()

    def _window_room_problem(self, area_id: str) -> str | None:
        if area_id in subentry_by_area(self._get_entry(), SUBENTRY_REGION):
            return "is_region"
        return None

    def _window_names_in(self, area_id: str) -> list[str]:
        return [
            sub.data[m.CONF_NAME]
            for sub in self._get_entry().subentries.values()
            if sub.subentry_type == SUBENTRY_WINDOW
            and sub.data[m.CONF_AREA] == area_id
            and sub.subentry_id != self._own_id
        ]

    def _window_has_room(self, area_id: str) -> bool:
        return area_id in subentry_by_area(self._get_entry(), SUBENTRY_ROOM)

    async def _async_window_preview_run(
        self, data: Mapping[str, Any], extra: list[PlanItem]
    ) -> PreviewRun:
        return await async_run_preview(
            self.hass,
            self._get_entry(),
            self._own_id,
            SUBENTRY_WINDOW,
            data,
            extra,
        )

    async def _async_window_finish(self, data: dict[str, Any], title: str) -> Any:
        entry = self._get_entry()
        if not self._window_has_room(data[m.CONF_AREA]):
            room = self._window_new_room(data[m.CONF_AREA])
            self.hass.config_entries.async_add_subentry(
                entry, new_subentry(self.hass, await async_texts(self.hass), room)
            )
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_and_abort(
                entry, self._get_reconfigure_subentry(), title=title, data=data
            )
        return self.async_create_entry(title=title, data=data)

    # Entry points

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
        """Add: starts with the room."""
        return await self.async_step_window_room(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Edit: the form of the stored type, with the stored data."""
        data = self._get_reconfigure_subentry().data
        self._window_load(data)
        return await self._async_window_form(data[m.CONF_TYPE], None)
