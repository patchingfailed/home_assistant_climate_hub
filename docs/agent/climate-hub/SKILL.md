---
name: climate-hub
description: Use when working with an installed Climate Hub (Home Assistant custom integration `climate_hub`) from outside Home Assistant, for example in Claude Code or claude.ai with access to an instance. Covers questions about Climate Hub values (room, outdoor side, hub), why it recommends opening or closing a window or a cover, window states, repairs and failing sources, a health check and suggestions to improve its configuration, and writing automations or dashboard templates that use Climate Hub entities.
---

# Climate Hub for agents

Climate Hub fuses user-ranked temperature, humidity and pressure sources into one value per room and per outdoor side,
and recommends when to open or close windows and covers. It reads devices and never controls any: not windows, not
covers, not heating or cooling. Raw states, keys and attributes are in backticks; UI labels are the English ones.

## Object model

- One hub config entry per instance, titled "Climate Hub". Its device "Home climate" (`entry_type` `service`) carries
  the hub entities.
- Subentries of that entry, one device each: `room` (room), `region` (UI: outdoor side) and `window` (window).
- A room belongs to one area and has an optional main side (North, East, South, West or None). An outdoor side is one
  compass direction with one outdoor area. A window belongs to one area and is linked to the room of that area.
- Device names: rooms and outdoor sides "Climate", windows their window name ("Window", "Window 2", a pass-through
  "Passage", or the name the user gave). When the area is not part of entity IDs (a Home Assistant setting), the area
  goes into the device name: "Kitchen climate", "Kitchen Window". A name the user set (`name_by_user`) wins.
- Device identifiers are `(climate_hub, <subentry_id>)`, for the hub `(climate_hub, <entry_id>)`. Entity unique IDs are
  `<subentry_id>_<translation_key>` and, for hub entities, `<entry_id>_<translation_key>`.

## Finding entities

Never find Climate Hub entities by an entity ID pattern. Home Assistant generates IDs in the server language, and with
or without the area depending on a setting. Use the registry, and map the user's room names to rooms through the area
of the device. Area names are user data and may be in another language than the request.

WebSocket route (long-lived token): `config/entity_registry/list`, `config/device_registry/list`,
`config/area_registry/list`, and `config_entries/subentries/list` (argument `entry_id`, admin only).

- Entity registry entries carry `entity_id`, `platform`, `translation_key`, `unique_id`, `device_id`,
  `config_entry_id`, `config_subentry_id` (null for hub entities), `disabled_by` and `area_id`. Keep entries with
  `platform == "climate_hub"` and identify each by `translation_key` (the keys in the tables below).
- Device entries carry `id`, `identifiers`, `name`, `name_by_user`, `area_id`, `config_entry_id`, `config_subentry_id`
  and `entry_type`. The area of a room, outdoor side or window is the `area_id` of its device.
- Subentry entries carry `subentry_id`, `subentry_type` (`room`, `region`, `window`), `title` and `unique_id`, no
  configuration data. The configuration is in the diagnostics (see "Diagnose a value").

A minimal reader (Python with aiohttp; `HA_URL` and `HA_TOKEN` from the environment):

```python
import asyncio, os, aiohttp

async def main():
    url = os.environ["HA_URL"].replace("http", "ws", 1) + "/api/websocket"
    async with aiohttp.ClientSession() as session, session.ws_connect(url) as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": os.environ["HA_TOKEN"]})
        await ws.receive_json()
        result = {}
        for i, cmd in enumerate(("entity", "device", "area"), start=1):
            await ws.send_json({"id": i, "type": f"config/{cmd}_registry/list"})
            result[cmd] = (await ws.receive_json())["result"]
    areas = {a["area_id"]: a["name"] for a in result["area"]}
    devices = {d["id"]: d for d in result["device"]}
    for e in result["entity"]:
        if e["platform"] == "climate_hub":
            d = devices.get(e["device_id"], {})
            print(areas.get(d.get("area_id")), d.get("name_by_user") or d.get("name"),
                  e["translation_key"], e["entity_id"], e["disabled_by"])

asyncio.run(main())
```

Template route, `POST /api/template` with `{"template": "..."}` (admin). `integration_entities('climate_hub')` lists the
entity IDs of the integration. Limits: it gives no `translation_key`, and it lists only entities that exist in the state
machine (a disabled entity is missing). On its result `device_id(entity_id)`, `device_entities(device_id)`,
`device_attr(device, 'name')`, `area_name(device_or_entity)`, `state_attr(entity_id, name)` and `state_translated`
(server language) work. Identify devices and entities this way:

| What | Test |
|---|---|
| Hub device | `device_attr(e, 'entry_type')` is `service` |
| Room device | has an enum sensor whose `options` attribute contains `within` (the `comfort` sensor) |
| Window device | has an enum sensor with `ajar` in `options` and no `comfort` sensor on the device |
| Outdoor side device | none of the above (it has no enum sensor) |
| `recommendation` | enum sensor of a room device with `keep_open` in `options` |
| `trend`, `window` | `options` contain `rising`, respectively `ajar`, on a room device |
| `comfort_min`, `comfort_max`, `threshold` | `number` entities on the hub; attribute `min` is 10, 15, respectively 0.5 (°C instance) |
| `strategy` | enum sensor on the hub with `prevent_heat_up` in `options` |
| `indoor_average`, `outdoor` | numeric hub sensors; `outdoor` has the attribute `stage`, `indoor_average` has `minimum` and no `stage` |
| `any_cover_to_close` | hub binary sensor with the attribute `windows` |
| `temperature_spread`, `humidity_spread` | room sensors with the attribute `readings`; `device_class` `temperature_delta`, respectively `humidity` |
| `setpoint_deviation` | room sensor with the attribute `devices` |

Not identifiable by template: the room sensors `temperature`, `dew_point` and `outside_temperature` (all device class
`temperature`), and the hub binary sensors `any_cooling_down`, `any_heating_up` and `any_open_while_conditioning`. Get
them from the registry route and let the user confirm them before they go into an automation.

Entities exist only when the configuration needs them, and are removed otherwise:

- `humidity`, `absolute_humidity`, `dew_point`: the room has a humidity source (its own list, or the devices of its
  temperature sources). `pressure`: the same for pressure.
- `outside_temperature`, `outside_humidity`, `temperature_difference`, `outside`: at least one outdoor side or a weather
  service exists. `humidity_difference` also needs a humidity source.
- `window`, `window_open_since`, `cooling_down`, `heating_up`: the room has a window. `open_while_conditioning`: also a
  heating or cooling device.
- `temperature_spread`, `humidity_spread`: at least 2 sources of that metric and the room switch **Show individual
  readings** on (default on; rooms saved before the switch existed count as on). `setpoint_deviation`: at least one
  heating or cooling device, independent of the switch.
- Hub: `strategy` needs a weather service; `indoor_average` a room; `outdoor` an outdoor side or a weather service;
  `any_cooling_down`, `any_heating_up` and `any_cover_to_close` a window; `any_open_while_conditioning` a room with a
  window and a heating or cooling device.
- Window `cover` is created for every window and disabled unless the window has a cover.

An entity is `unavailable` while the last evaluation produced no result for its object, and for a moment after every
configuration change.

## Entities per device

Numeric sensors have state class `measurement`.

Room device:

| `translation_key` | Unit or states | Attributes |
|---|---|---|
| `temperature`, `humidity`, `pressure` | °C, %, hPa | `source`, `stage`, `reason`, `offset` |
| `absolute_humidity`, `dew_point` | g/m³, °C | `source`, `stage`, `reason` |
| `outside_temperature`, `outside_humidity` | °C, % | `stage`, `regions`, `reason`, `offset` |
| `temperature_difference` | °C, outside minus inside | none |
| `humidity_difference` | g/m³, outside minus inside | `humidity_after_ventilating` |
| `outside` | `warmer`, `colder`, `similar` (outside against inside, band 0.5 °C) | none |
| `comfort` | `below`, `within`, `above` (room temperature against the comfort range) | none |
| `trend` | `rising`, `steady`, `falling` (from 0.5 K/h over 60 min); `unknown` until samples span 30 min | none |
| `recommendation` | `open`, `keep_open`, `close`, `keep_closed`, `none` | `reason` |
| `window` | `closed`, `ajar`, `tilted`, `open` (most open window of the room) | none |
| `window_open_since` | timestamp when the earliest ventilating window started | none |
| `cooling_down`, `heating_up`, `open_while_conditioning` | `on`, `off` | none |
| `temperature_spread` | °C, highest minus lowest valid source value | `readings` |
| `humidity_spread` | %, highest minus lowest valid source value | `readings` |
| `setpoint_deviation` | °C, room temperature minus setpoint; negative is colder | `device`, `setpoint`, `setpoint_low`, `setpoint_high`, `devices` |

Outdoor side device (always all five):

| `translation_key` | Unit | Attributes |
|---|---|---|
| `temperature`, `humidity`, `pressure` | °C, %, hPa | `source`, `stage`, `regions`, `reason`, `offset` |
| `absolute_humidity`, `dew_point` | g/m³, °C | `stage`, `regions`, `reason` |

Window device:

| `translation_key` | States | Attributes |
|---|---|---|
| `state` | `closed`, `ajar` (sash closed, handle turned), `tilted`, `open`; `unknown` without a usable contact | `open_leaves` (double leaf only): `none`, `left`, `right`, `both`, `unknown` |
| `open_since` | timestamp when the window reached its ventilating level ("Counts as ventilating from", default `tilted`) | none |
| `cover` | `close`, `keep_closed`, `open`, `keep_open`, `none` | `reason` |

Hub device ("Home climate"):

| `translation_key` | Unit or states | Attributes |
|---|---|---|
| `strategy` | `prevent_heat_up`, `prevent_cool_down`, `neutral`; `unknown` without a forecast | `forecast_max`, `forecast_min`, `corrected_max`, `corrected_min`, `bias_max`, `bias_min` (°C) |
| `indoor_average` | °C, mean of the room temperatures | `minimum`, `maximum` |
| `outdoor` | °C, mean of the outdoor side temperatures | `stage`, `minimum`, `maximum`, `per_region` (`n`, `e`, `s`, `w`) |
| `comfort_min`, `comfort_max`, `threshold` | number, °C | none |
| `any_cooling_down`, `any_heating_up`, `any_open_while_conditioning` | `on` if a room is on, `unknown` if none is on and one is unknown | none |
| `any_cover_to_close` | `on` if a window has cover advice `close` or `keep_closed` | `windows`: list of `entity_id`, `reason` |

The comfort range is one for the whole house. `cooling_down` and `heating_up` start only after a window has ventilated
longer than the burst duration (default 10 min). `trend` samples survive a restart. `any_cover_to_close` counts every
window, also windows without a cover, whose `cover` sensor is disabled.

## Provenance of a value

Every measurement says where it came from. An attribute without a value is not written.

| Attribute | Room `temperature`, `humidity`, `pressure` | Outdoor side sensors and a room's outside values |
|---|---|---|
| `source` | while a source of the list delivers | outdoor side: while its own sources deliver; room outside values: never |
| `stage` | `primary`, `fallback` or `none` | also `neighbour`, `opposite`, `weather` |
| `reason` | when `stage` is not `primary`: the status of the first source | only at `none`: `no_side`, `no_pair` or `no_data` |
| `offset` | at `fallback` | at `weather` |
| `regions` | not written | directions (`n`, `e`, `s`, `w`) averaged into the value; absent at `weather` and `none` |

An outdoor side at `fallback` therefore shows only `source` and `stage`; read its first source directly. Room
`absolute_humidity` and `dew_point` show the attributes of the weaker of their two inputs, without `offset`. The hub
`outdoor` has `stage` `primary` or `fallback` when outdoor sides deliver, `weather` or `none` otherwise.

| `stage` | Meaning |
|---|---|
| `primary` | The first source of the list delivers. |
| `fallback` | A lower-ranked source of the same list delivers, corrected by `offset`. |
| `neighbour` | Outside values: the own side has no value; the mean of the adjacent sides is used. |
| `opposite` | Outside values: neither own nor adjacent sides have a value; the opposite side is used. |
| `weather` | Outside values: no outdoor side has a value; the weather service is used, corrected by `offset`. |
| `none` | No stage delivers a value. Without `reason` on a room value: the source list is empty. |

| `reason` | Meaning |
|---|---|
| `unavailable`, `unknown` | The first source has that state (`unknown` also: no value). |
| `not_numeric` | The state of the first source is not a number. |
| `unit` | The unit cannot be converted (temperature to °C, pressure to hPa; humidity must be %). |
| `missing` | The first source does not exist in Home Assistant. |
| `stale` | The last report is older than `max_age` (default 40 min; a room or side can override it). |
| `no_side` | Outside value of a room without a main side. |
| `no_pair` | Outside absolute humidity or dew point: no stage has temperature and humidity from the same sides. |
| `no_data` | Outside temperature, humidity or pressure: no stage, weather service included, delivers. |
| `ok` | Defined for a working source, never written as an attribute value. |

How `offset` is learned: while the first source and a lower-ranked one both deliver, the deviation between them feeds a
moving average with a time constant of 8 h; it counts as learned after 1 h of paired readings. After a switch down to a
lower-ranked source, the applied `offset` starts at that source's last measured deviation (if it is younger than
`max_age`) and moves to the learned value within 1 h, so the room value does not jump.

How far to trust a value: `primary` is as good as the first sensor. `fallback` is as good as the correction: check the
candidate's `learned` flag in the diagnostics, and expect the glide during the first hour after a switch.
`neighbour` and `opposite` come from another side of the house (sun and wind differ). `weather` is the corrected
weather service, the coarsest stage. `none` is no value.

## Readings and setpoint

- `readings` (on both spreads): label → value of every source in rank order, before any offset; `null` while a source
  is not valid. It shows the sources side by side, which the room value with its single `source` does not.
- The spread uses only non-`climate` sources when the room has at least 2 of them configured (a thermostat measures
  at the radiator), otherwise all. Fewer than 2 valid values: `unknown`, so with one of two sensors out the spread
  stays empty.
- `setpoint_deviation` takes the first device of the room's list with `hvac_mode` `heat`, `cool`, `heat_cool` or
  `auto` and a setpoint. Single setpoint: room temperature minus setpoint (`setpoint`). Range (`setpoint_low`,
  `setpoint_high`; only when the device reports no single setpoint): 0 inside, else the distance to the nearer
  limit. `device` names that device; `devices` maps every device's label to its `mode`, setpoint(s) and `current`
  reading. `unknown` without such a device (for example all `off`) or without a room temperature. Climate Hub never
  sets a setpoint.
- Labels are the friendly name without the area's words and without metric words (English and German only); empty or
  duplicate labels come from the entity ID, then the full name, then the entity ID itself.
- `readings` and `devices` are not recorded; the states have long-term statistics.

## Recommendation and cover reasons

The `recommendation` state follows the wish and the window state: a wish for an open window gives `open`, or `keep_open`
while a window of the room ventilates; a wish for closed gives `keep_closed` when no window ventilates, otherwise
`close`. `reason` of `recommendation`, in the order the logic checks them:

| `reason` | When |
|---|---|
| `no_side` | The room has no main side; the recommendation is `none`. |
| `no_data` | The room temperature or the outside temperature has no value; `none`. |
| `comfort_range_invalid` | The comfort minimum is not below the maximum; `none`. |
| `cool_room` | Outside `colder` and the room is `above` the comfort range; open until the middle of the range. |
| `pre_cool` | As `cool_room` on a `prevent_heat_up` day; starts 0.5 °C above the comfort minimum, cools to the minimum. |
| `warm_room` | Outside `warmer` and the room is `below` the range; open until the middle of the range. |
| `dry_room` | Room humidity above the humidity threshold (default 60 %) and outside air drier by 1 g/m³ or more; open until the humidity is 5 points below the threshold. |
| `burst_dry` | As `dry_room`, but opening would harm the temperature; open for the burst duration only. |
| `burst_done` | The burst has passed and the room is still humid; closed. Next burst 1 h after the window closed. |
| `outside_humid` | A temperature goal exists, but ventilating would bring the room humidity to the threshold or above. |
| `outside_colder` | No wish to open; opening would cool the room too much (`prevent_cool_down` or room `below`). Wins over `in_range`. |
| `outside_warmer` | No wish to open; opening would heat the room too much (`prevent_heat_up` or room `above`). Wins over `in_range`. |
| `in_range` | No wish to open and the room is `within`. |
| `no_benefit` | No wish to open and no reason above applies. |

`reason` of the window `cover` sensor, first match wins; a switch between close and open waits until the current wish
has lasted 15 min, switches from or to "none" take effect at once:

| `reason` | When | Wish |
|---|---|---|
| `no_room` | The window has no room in its area. | none |
| `no_data` | No sun position or room temperature, or no facing (Facing "Like the room" in a room without a main side). | none |
| `insulate` | Night (sun below 0°), outside colder, and `prevent_cool_down` or room `below`. | close |
| `night` | Night, `insulate` does not apply. | none |
| `solar_gain` | Sun on the window and room `below`, or outside temperature below the comfort minimum. | open |
| `sun_heat` | Sun on the window and heat risk (`prevent_heat_up`, or within 0.5 °C of the comfort maximum). | close |
| `heat_barrier` | `prevent_heat_up`, outside `warmer`, solar warmth not welcome. | close |
| `no_heat_risk` | Sun on the window, no heat risk. | open |
| `no_sun` | Daytime, none of the above. | open |
| `window_open` | The wish would be close, but the window state is `open`. | none |

The `cover` state maps the wish to the cover position: a close wish gives `close` if the cover is not closed (closed
means position 50 % or lower), else `keep_closed`; an open wish gives `open` if the cover is closed or its position is
unknown, else `keep_open`. Sun on the window means at least 10° elevation, within 60° of the facing, cloud cover 70 % or
lower.

## What may be changed

Only the three hub `number` entities, with `number.set_value`: `comfort_min` (10 to 30 °C), `comfort_max` (15 to 35 °C)
and `threshold` (0.5 to 10 °C), all in steps of 0.5. A value that makes the minimum equal to or higher than the
maximum is rejected and the old value stays. When both move down, set the minimum first; when both move up, the maximum
first. The next evaluation uses the new value.

Everything else is configuration and goes through the Home Assistant UI. Tell the user where to click:

| Change | Where |
|---|---|
| Weather service, area sync, `max_age`, burst duration, humidity threshold, outage delay | **Settings → Devices & services → Climate Hub**, gear icon (**Configure**) next to the entry. Not **System options** in ⋮. |
| Add a room, outdoor side or window | Same page, **Add room**, **Add outdoor side**, **Add window** at the top. |
| Sources and their order, main side, cover, contacts, facing, **Show individual readings** (room, section **Advanced**) | The gear icon on the card of the room, outdoor side or window (**Reconfigure …**). |
| Rename or delete one item | ⋮ on its card. Deleting a room keeps its windows; a repair offers to recreate the room. |
| House plan (outdoor area and rooms per direction) | ⋮ next to the entry, **Reconfigure**. |

The entry reloads 1 s after the first change; no restart is needed. Do not edit `.storage` and do not call internal
APIs or config-entry endpoints to change the configuration.

## Rules

1. Never change unique IDs or entity IDs. Home Assistant would lose the history. Renaming an area or a device does not
   change them.
2. A recommendation is advice. Write no automation that moves a window or a cover unless the user asks for one.
3. Automations must tolerate `unavailable` and `unknown`. After a configuration change the entry reloads and its
   entities are `unavailable` until the first evaluation has run.
4. On a production instance, state the exact action (service, entity, value, or click path) and wait for the user's go
   before any write, `number.set_value` included.
5. State what Climate Hub does not do: no control of devices, one comfort range for the house, one entry per instance,
   at most four outdoor sides.

## Recipes

### Diagnose a value

1. Read the entity and its attributes. `stage` `primary` needs no further search.
2. Room value at `fallback`: `source` is the entity in use, `reason` says why the first source is out, `offset` is the
   correction. Outdoor side at `fallback`: no `reason` and no `offset`; read the first source of the side directly.
3. Read the first source: its state and `last_reported`. `stale` means `last_reported` is older than `max_age`;
   sensors that report only on change trigger this. Remedy: raise **Maximum age of a measurement** in the section
   **Advanced** of the room or side, or in the hub options, or put a source that reports regularly first.
4. `stage` `neighbour`, `opposite`, `weather` or `none` on a room's outside value: the room's outdoor side has failed
   or does not exist. Check the main side of the room (`no_side`) and the `stage` of that side's sensors.
5. A large `offset` means a lower-ranked source differs from the first by that amount. It is learned, not a fault.
   `readings` on the room's `temperature_spread` or `humidity_spread` shows every source's own value side by side
   (`null` = not valid), which tells which source is off.
6. Check Settings → Repairs. `outage`, `outage_fallback` and `outage_none` appear after the outage delay (default 6 h,
   counted from the moment a source is judged invalid; 40 min plus 6 h for a silent sensor). They are not fixable from
   the issue; check battery and connection. `new_source` offers a sensor of the area as a source. `windows_without_room`
   offers to recreate the room or delete its windows.
7. For the full chain read the diagnostics: `GET /api/diagnostics/config_entry/<entry_id>` (admin), or **Download
   diagnostics** in ⋮ of the entry. Home Assistant wraps them: `data` holds Climate Hub's keys `options`,
   `subentries` (`id`, `type`, `title`, `data` with the configuration), `model`, `state` (learned offsets, glide
   anchors, goals), `comfort`, `results`, `failures`, `forecast` and `store`; `issues` lists its repairs. In `results`
   each value lists its candidates with `entity_id`, `status`, `value`, `offset` (learned) and `learned`. The file is
   unredacted (entity IDs, names, measured values); do not post it publicly.

### Explain a recommendation

Read `recommendation` and its `reason`, then the inputs of that reason:

- `comfort` and the room `temperature` against `comfort_min` and `comfort_max`.
- `outside`, `temperature_difference` and `outside_temperature` with its `stage`.
- `strategy` of the hub, for `pre_cool`, `outside_colder` and `outside_warmer`.
- Room `humidity` against the humidity threshold; `humidity_difference` and its `humidity_after_ventilating`.
- `window`: a ventilating window turns `open` into `keep_open` and `keep_closed` into `close`.

`none` with `no_side`, `no_data` or `comfort_range_invalid` is a configuration or data problem, not advice. For a cover,
read the window `cover` state and `reason`, then the `sun.sun` elevation, `strategy` and the room `comfort`.

### Installation health check

Collect the entities from the registry and the diagnostics, then check. Each finding has a remedy:

| Finding | Remedy |
|---|---|
| Room value at `fallback` with a `reason` | The first source is out: check it (battery, connection). If it reports only on change, raise `max_age`; or reorder under the gear icon of the card (**Temperature sources**). |
| Outdoor side value at `fallback` | Same, but read the side's first source directly (no `reason` on the side). |
| Value at `none` with a `reason` | All sources failed: check them, or add one on the card. |
| Room value at `none` without a `reason` | The room has no sources (for example created by **Add window** in an area without a temperature sensor): add them under **Reconfigure room**. |
| Many `stale` readings | Raise `max_age` for the room or side, or in the hub options. |
| Room with `no_side` that has windows | It most likely lacks its main side: set **Main side** in **Reconfigure room** or in the house plan (⋮ → **Reconfigure**). Rooms without an outside wall keep None; ask the user. |
| Outside humidity or pressure at `weather` while the side's temperature is `primary` | The outdoor side has no humidity or pressure source: add them under **Humidity and pressure** on the side's card. |
| Outside values at `neighbour`, `opposite` or `weather` throughout | No outdoor side for that direction, or its sources failed. An outdoor side is a Home Assistant area: create one for that side, assign its outdoor sensor, then pick it in the house plan; or check the side's sources. |
| Room without a `humidity` entity | No humidity source, so no `dry_room` advice: add one under **Humidity and pressure** on the room's card. |
| Open repairs | Recipe "Diagnose a value". |
| Window `state` `unknown` | **Reconfigure window**: check the contact, assign its texts in **Assign states**. |
| Window open for days, or `cooling_down` / `heating_up` on for hours | Ask the user. A contact that came off its magnet keeps reporting `open`; check the contact entity itself. |
| `strategy` missing | Set **Weather service** under **Configure**. |
| `strategy` `unknown` | No forecast service, a failed fetch without an earlier forecast, an hourly forecast with fewer than 12 points in the next 24 h, or a daily one without today: choose another weather entity under **Configure**. |
| Large `temperature_spread` | `readings` shows which source differs. Either the room has zones (bed and desk) or a sensor sits at a radiator, a window or in the sun; ask the user, and reorder the sources if the first one is the outlier. |
| `setpoint_deviation` `unknown` in a room with heating or cooling devices | No device is in `heat`, `cool`, `heat_cool` or `auto` with a setpoint (normal while heating is off), or the room temperature is missing. |
| `cover` sensor disabled on a window with a cover | The user disabled it; enable it in the entity settings. |
| `any_cover_to_close` on because of windows without a cover | Expected: it counts every window. An automation can filter `windows` by enabled `cover` sensors. |

### List open windows

Per window, `state` is not `closed`, and `open_since` is the time it reached its ventilating level. Per room, `window`
is the most open window. Template for all windows (the `comfort` check separates window devices from room devices; the
device name alone is not unique, so the area is printed with it):

```jinja
{% for e in integration_entities('climate_hub') if 'ajar' in (state_attr(e, 'options') or []) %}
{%- set ns = namespace(room=false, since=none) %}
{%- for x in device_entities(device_id(e)) %}
{%- if 'within' in (state_attr(x, 'options') or []) %}{% set ns.room = true %}{% endif %}
{%- if state_attr(x, 'device_class') == 'timestamp' %}{% set ns.since = x %}{% endif %}
{%- endfor %}
{%- if not ns.room and states(e) not in ['closed', 'unavailable', 'unknown'] %}
{{ device_attr(e, 'name') }} ({{ area_name(e) }}): {{ states(e) }}, since {{ states(ns.since) if ns.since else '-' }}
{%- endif %}
{%- endfor %}
```

### Dashboard: every room

A Markdown card. It finds rooms by their `comfort` sensor, so a new room appears without editing the card. The states
come from `state_translated`, in the server language.

```yaml
type: markdown
content: |-
  | Room | Comfort | Trend | Window | Recommendation |
  |---|---|---|---|---|
  {%- for c in integration_entities('climate_hub') if 'within' in (state_attr(c, 'options') or []) %}
  {%- set ns = namespace(rec=none, trend=none, win=none) %}
  {%- for e in device_entities(device_id(c)) %}
  {%- set o = state_attr(e, 'options') or [] %}
  {%- if 'keep_open' in o %}{% set ns.rec = e %}
  {%- elif 'rising' in o %}{% set ns.trend = e %}
  {%- elif 'ajar' in o %}{% set ns.win = e %}
  {%- endif %}
  {%- endfor %}
  {{- '\n' }}| {{ area_name(c) }} | {{ state_translated(c) }} | {{ state_translated(ns.trend) if ns.trend else '-' }} |
  {{- ' ' ~ (state_translated(ns.win) if ns.win else '-') }} | {{ state_translated(ns.rec) if ns.rec else '-' }}
  {%- if ns.rec and state_attr(ns.rec, 'reason') %} ({{ state_attr(ns.rec, 'reason') }}){% endif %} |
  {%- endfor %}
```

Limit: the table has no temperature, because `temperature` cannot be told from `dew_point` by template. For a
temperature column take the entity IDs from the registry route and put them into an entities or tile card.

The individual readings of every room, from the `readings` attribute of each `temperature_spread` (rooms with the
switch off or with one source have none):

```yaml
type: markdown
content: |-
  {%- for e in integration_entities('climate_hub')
      if state_attr(e, 'device_class') == 'temperature_delta' and state_attr(e, 'readings') is not none %}
  **{{ area_name(e) }}** (spread {{ states(e) ~ ' °C' if is_number(states(e)) else states(e) }})
  {%- for label, value in state_attr(e, 'readings').items() %}
  - {{ label }}: {{ value ~ ' °C' if value is not none else 'no value' }}
  {%- endfor %}
  {% endfor %}
```

### Automations

Entity IDs in angle brackets are placeholders. Take the real ones from the registry and let the user confirm them.
Before an automation on a room's `recommendation`, check that the room can produce one: with `no_side`, an empty source
list or a temperature at `none` it stays `none`, and the automation would never fire.

Notify when a room should be ventilated to dry it. `not_from` keeps a reload (`unavailable` to `open`) from firing it:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.<room>_recommendation
    to: open
    not_from: [unavailable, unknown]
conditions:
  - condition: template
    value_template: "{{ state_attr(trigger.entity_id, 'reason') in ['dry_room', 'burst_dry'] }}"
actions:
  - action: notify.<notifier>
    data:
      message: "A window should be opened to dry the room."
```

Warn when a window stays open while heating or cooling, using the hub flag `any_open_while_conditioning` (Climate Hub
itself waits for the burst duration before it turns on):

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.<hub>_any_open_while_conditioning
    to: "on"
actions:
  - action: notify.<notifier>
    data:
      message: "A window is open while heating or cooling."
```

A night comfort range, 18 to 22 °C from 22:00. Both values move down, so the minimum goes first; the 06:00 automation
raises them again with the maximum first. If the day values change, keep them in two `input_number` helpers and use
their states as `value`.

```yaml
triggers:
  - trigger: time
    at: "22:00:00"
conditions:
  - condition: template
    value_template: "{{ states('number.<hub>_comfort_max') not in ['unavailable', 'unknown'] }}"
actions:
  - action: number.set_value
    target:
      entity_id: number.<hub>_comfort_min
    data:
      value: 18
  - action: number.set_value
    target:
      entity_id: number.<hub>_comfort_max
    data:
      value: 22
```

Offer such automations only when asked, and state the exact action before writing them to a production instance
(rule 4).
