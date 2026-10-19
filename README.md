<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="custom_components/climate_hub/brand/dark_logo@2x.png">
    <img alt="Climate Hub" src="custom_components/climate_hub/brand/logo@2x.png" width="420">
  </picture>
</p>

# Climate Hub

Climate Hub computes one temperature, humidity and pressure value per room and per outdoor side from sensors that you
rank, and takes the next sensor in the list when the top one stops reporting. From these values it recommends per room
whether to open or close the windows, and per window whether to close the cover.

The sensors of one area disagree: one sits next to a radiator, a thermostat reads 1 °C warm, another drops off the
network for hours. A dashboard or an automation that reads a single sensor inherits each of these faults.

## What it does

- Rooms: one room per Home Assistant area. Temperature, humidity and pressure come from a ranked list of sources. A
  source is valid when its value is numeric, its unit converts to the metric's unit and it reported within the maximum
  age (default 40 min). The first valid source in the list wins. When a lower-ranked source takes over, its learned
  deviation from the top source is subtracted, so the room value does not jump. Derived values per room: absolute
  humidity, dew point, difference to the outside, position in the comfort range and trend.
- Outdoor sides: up to four, one per compass direction, each tied to an outdoor area. A side without a valid source
  takes the mean of its adjacent sides, then the opposite side, then the weather entity (its values count as failed
  after 2 h).
- Windows: a window, a double leaf or a pass-through of two openings in a row, with the states `closed`, `ajar`,
  `tilted` and `open`. A window counts as ventilating from `tilted` by default. Each room gets a recommendation
  (`open`, `keep_open`, `close`, `keep_closed` or `none`) with a reason, computed from the room and outside values, the
  comfort range (default 20 to 24 °C), the humidity threshold (default 60 %) and the daily strategy from the forecast.
  Binary sensors warn when a window stays open longer than the burst ventilation time (default 10 min) while it works
  against the day's strategy, or while a heating or cooling device of the room is running.
- Cover recommendation: one sensor per window, `close`, `keep_closed`, `open`, `keep_open` or `none`, with a reason,
  from the sun position relative to the window, the cloud cover, the room temperature and the daily strategy. Climate
  Hub reads covers and moves nothing. Rules: [cover reasons](docs/reference.md#cover-reasons).
- Repairs: Home Assistant repairs report a source that has been invalid for the repair delay (default 6 h), a new
  sensor in the area of a room or outdoor side, and windows whose room was deleted.

English and German translations are included.

## Requirements

- Home Assistant 2026.10.0 or newer.
- Temperature sensors, and optionally humidity and pressure sensors, assigned to areas. An entity reaches an area
  through its device or directly. `climate` entities in the area count as temperature sources and, when they report
  it, as humidity sources.
- Optional: a weather entity that provides a forecast through `weather.get_forecasts` (hourly or daily). It feeds the
  daily strategy and the outside values when all sensors of an outdoor side fail. Without a forecast the Daily
  strategy sensor is `unknown`; without a weather entity the sensor does not exist.
- For the cover recommendation: the `sun` integration (`sun.sun`). Without it the cover recommendation is `none` with
  the reason `no_data`.
- Optional: the `recorder`. The window form uses it to pre-fill the state mapping of text sensors from the values of
  the last 14 days.

## Installation

### HACS (custom repository)

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/patchingfailed/home_assistant_climate_hub` as category **Integration**.
3. Install **Climate Hub** and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration → Climate Hub**.

### Manual

Copy `custom_components/climate_hub` into the `custom_components` folder of your Home Assistant configuration and
restart. Then continue with step 4 above.

## First setup

Only one Climate Hub entry exists per Home Assistant instance. The setup dialog creates it together with the rooms,
outdoor sides and windows you confirm. Nothing is created before the last step.

1. Open **Settings → Devices & services → Add integration → Climate Hub**. The dialog **Set up Climate Hub** counts what
   it found: areas with a climate sensor or thermostat, areas with a temperature sensor that could be outside, window
   and door contacts, and weather services.
   - **Weather service**: pre-filled with the first weather entity that supports a forecast. Optional.
   - **Keep areas up to date**: on by default. Climate Hub enters the room and outdoor side values as the temperature
     and humidity sensor of their areas, so area cards show the fused value. It clears a field only while the field
     still holds the entity Climate Hub wrote.

   Select **Submit**.
2. **Which areas are rooms?** lists the areas that have a temperature source, as "floor · area" (areas without a floor
   read "no floor"). An area on a floor whose name contains an outside word (Outside, Outdoor, Garden, Yard, Patio,
   Terrace, Balcony, or the German equivalents) is not pre-checked. Any other area is pre-checked when it has a
   `climate` entity or sits on a floor. Check the rooms and select **Submit**.
3. **House plan** has four sections: **North**, **East**, **South** and **West**.
   - **Outdoor area**: the outdoor area whose sensors measure that side. Leave it empty for a side without one, for
     example a wall on the neighbour's property. The weather entity then stands in.
   - **Rooms on this side**: the rooms whose windows face that way. A room belongs to one side only; the outside air
     of its recommendation comes from there. Leave out interior rooms: they get no main side, and their
     recommendation is `none` with the reason `no_side`.

   An outdoor area can serve one side only. Select **Submit**.
4. **Preview** shows what would be created, with live values: per room the current value, its source, the fallbacks
   ready and the entities that were not taken with a reason (for example a fridge sensor: "not a room value"); per
   outdoor side the value and its fallback chain; the weather service line; the windows added so far. Choose
   - **Create** to create everything,
   - **Add window (optional)** to add a window, see below,
   - **Change rooms** to return to step 2,
   - **Change house plan** to return to step 3.
5. Optional, repeatable: **Add window (optional)**. Windows are never guessed, because they depend on how the contacts
   are mounted.
   1. **Add window**: pick the **Room**.
   2. Pick the type: **Single window or door**, **Double leaf** or **Pass-through**.
   3. Fill in the form. A single window takes a **Contact**; a double leaf takes **Left leaf**, **Right leaf** and
      **Contact between the leaves (optional)**; a pass-through takes **Inner opening** and **Outer opening**. **Name**
      stays empty for a name based on the room. **Show all contacts** lists every contact in the house instead of
      those in the room's area and without an area. The section **Extra contacts** takes **Tilt detection** and
      **Handle contact** for a single window and **Handle contact** for a double leaf; a pass-through has none. The
      section **Cover** takes the **Cover** entity, and the section **Advanced** takes
      **Facing** (default "Like the room"), **Exact facing in degrees** and **Counts as ventilating from** (default
      "Tilted").
   4. A text sensor as contact opens **Assign states**: which text means **closed**, **ajar**, **tilted** and
      **open**. The fields are pre-filled from past values and common words.
   5. The window preview shows its state and the room's recommendation. Select **Save** to return to the setup
      preview, or **Change type**.
6. Select **Create**. The dialog ends with a hint where to change sources and add windows later.

### What the defaults mean

The setup writes these values into the hub options (see below for where to change them). The comfort range is not an
option; it lives in number entities. Ranges and all other fields: [settings](docs/reference.md#settings),
[writable numbers](docs/reference.md#writable-numbers).

| Setting | Default | Meaning |
|---|---|---|
| Maximum age of a measurement | 40 min | A reading older than this counts as failed; the next source takes over. A room or outdoor side can override it under **Advanced**. |
| Duration of burst ventilation | 10 min | Length of a burst for humidity. The cooling-down, heating-up and open-while-heating/cooling warnings fire only when a window stays open longer. After a burst, the next one waits 1 h. |
| Ventilate for humidity from | 60 % | From this room humidity the recommendation is to ventilate if the outside air holds less water vapour. It continues until the humidity is 5 points below the threshold. |
| Report an outage after | 6 h | A source must be invalid for this long before a repair appears. |
| Comfort temperature min / max | 20 °C / 24 °C | Number entities on the device Home climate. A room above the range is recommended to open while it is cooler outside, until the middle of the range (22 °C by default; on a `prevent_heat_up` day down to the comfort minimum); a room below it, while it is warmer outside. The minimum must stay below the maximum. |
| Threshold | 2 °C | Number entity on the same device. The forecast maximum above comfort maximum plus threshold makes the daily strategy `prevent_heat_up`; the forecast minimum below comfort minimum minus threshold makes it `prevent_cool_down`. |

## Adding and changing later

Everything set during the first setup stays editable.

- Add: on the integration page (**Settings → Devices & services → Climate Hub**), select **Add room**, **Add outdoor
  side** or **Add window** at the top. The same three entries are in ⋮ next to the Climate Hub entry.
  - **Add room** asks for the **Area**, then shows **Room: {area}** with the **Main side**, the **Temperature sources,
    most important first** (drag to reorder), and the sections **Humidity and pressure**, **Heating and cooling** and
    **Advanced**. Empty humidity and pressure lists follow the devices of the temperature sources. Heating and cooling
    devices are only read; their setpoint is compared with the room temperature. **Advanced** holds **Show individual
    readings** (on by default): with at least two sources it adds the Temperature spread and Humidity spread entities,
    which list the value of every source; switched off, both disappear. The preview before **Save** shows the current
    value and the fallbacks. Fields: [room form](docs/reference.md#room-form).
  - **Add outdoor side** asks for the **Direction** (only free directions are offered) and the **Outdoor area**, then
    shows the form with the sources and the sections **Humidity and pressure** and **Advanced**.
    Fields: [outdoor side form](docs/reference.md#outdoor-side-form).
  - **Add window** runs the window steps from the first setup. If the area is not a room yet, saving creates the room
    with suggested sources. Fields: [window form](docs/reference.md#window-form).
- Change or delete one item: the gear icon on its card opens **Reconfigure room**, **Reconfigure outdoor side** or
  **Reconfigure window**. ⋮ on the card offers **Rename** and **Delete**. Rename changes the title on the card and in
  repair texts; device and entity names stay. Deleting a room keeps its windows; they report their state and raise a
  repair that offers to recreate the room or delete the windows.
- Options: select the gear icon (**Configure**) next to the Climate Hub entry; **System options** in ⋮ is Home
  Assistant's own dialog, not these options. The dialog **Climate Hub – Options** holds **Weather
  service**, **Keep areas up to date** and, in the collapsed section **Times and thresholds**, the four values of the
  table above. If the chosen weather entity is unavailable or provides no forecast, a check step offers **Save
  anyway** or **Adjust**. All options: [hub options](docs/reference.md#hub-options),
  [settings](docs/reference.md#settings).
- House plan: open ⋮ next to the entry and choose **Reconfigure**. The form is the one from step 3 of the first setup,
  filled with the current state. If a side gets a new or different outdoor area, a preview with the suggested
  sources comes before **Save**.
- Comfort range and threshold: the number entities on the device Home climate, also usable in automations. See
  [writable numbers](docs/reference.md#writable-numbers).

Changes take effect without a restart: the integration reloads 1 s after the first change, and changes within that
second share one reload.

## What you get

Climate Hub creates one device per room, per outdoor side and per window, plus the hub device Home climate. Rooms
and outdoor sides are devices named Climate, placed in their area. Windows are devices named Window (a pass-through:
Passage), numbered from the second one in a room ("Window 2"), or the name you gave. If the area is not part of the
entity IDs (a Home Assistant setting), the device name carries it instead: "Kitchen climate". Entity IDs are
generated by Home Assistant from area, device and entity name and are not renamed by Climate Hub. Unique IDs derive
from the subentry, so renaming an area or a device does not break history.

| Device | Entities (English names) | Details |
|---|---|---|
| Room | Temperature, Humidity, Pressure, Absolute humidity, Dew point, Outside temperature, Outside humidity, Outside temperature difference, Outside humidity difference, Outside, Comfort range, Trend, Recommendation; with windows also Window, Window open since, Cooling down, Heating up; with windows and heating or cooling devices also Open while heating/cooling; with at least two sources and the switch Show individual readings on (the default) Temperature spread and Humidity spread; with heating or cooling devices Deviation from setpoint | [room entities](docs/reference.md#room-entities), [readings and setpoint](docs/reference.md#readings-and-setpoint) |
| Outdoor side | Temperature, Humidity, Pressure, Absolute humidity, Dew point | [outdoor side entities](docs/reference.md#outdoor-side-entities) |
| Window | State, Open since, Cover | [window entities](docs/reference.md#window-entities) |
| Hub | Comfort temperature min, Comfort temperature max, Threshold, Daily strategy (with a weather entity), Indoor average, Outdoor, and with at least one window Anywhere cooling down, Anywhere heating up, Anywhere cover to close (plus Anywhere open while heating/cooling with heating or cooling devices) | [hub entities](docs/reference.md#hub-entities) |

In a room, Humidity, Absolute humidity and Dew point exist only with a humidity source, Pressure only with a pressure
source. The outside entities of a room exist when at least one outdoor side or a weather entity is configured;
Outside humidity difference also needs a humidity source. An outdoor side always has all five entities. The Cover
sensor of a window is disabled by default and enabled when the window has a cover assigned.

Temperature spread and Humidity spread show how far a room's sources disagree: the highest minus the lowest valid
value, with the value of every source, before any correction, in the attribute `readings`. That helps in a room with
zones, such as bed and desk. A thermostat counts only when the room has fewer than two other sensors, because it
measures at the radiator. Deviation from setpoint is the room temperature minus the setpoint of the first heating or
cooling device in `heat`, `cool`, `heat_cool` or `auto` that reports a setpoint; negative means colder than the
setpoint, and with a setpoint range it is 0 inside the range.

Further reading: [object model](docs/reference.md#object-model), the attributes that show where a value came from
([provenance attributes](docs/reference.md#provenance-attributes)), and [diagnostics](docs/reference.md#diagnostics)
for the full decision chain of every value.

## Expected behaviour

- Sources are evaluated when one of them changes (at most one evaluation every 2 s) and every 60 s. Contact changes
  are debounced for 5 s.
- Offsets learn over about a day. A lower-ranked source gets a deviation from the top source while both are valid. It
  counts as learned after 1 h of paired readings, and the average settles with a time constant of 8 h. Learned
  offsets survive restarts. When the value switches down to a lower-ranked source, the correction starts at the last
  measured deviation (if that pair is younger than the maximum age) and moves to the learned one within 1 h. Until a
  source has 1 h of paired readings, the preview of the room and outdoor side forms says "deviation is being learned".
- Every measurement says where its value came from. `stage` is `primary` for the top source, `fallback` for a lower
  one and `none` when no source is valid; outside values add `neighbour`, `opposite` and `weather`. Depending on the
  stage, `source`, `reason` (for example `stale`) and `offset` are added. Details:
  [provenance attributes](docs/reference.md#provenance-attributes).
- A room without a main side has the recommendation `none` with the reason `no_side`. A room whose temperature or
  outside value is missing has `none` with `no_data`. All reasons:
  [recommendation reasons](docs/reference.md#recommendation-reasons).
- The Daily strategy is `unknown` while the weather entity provides no forecast. An hourly forecast needs at least 12
  entries in the next 24 h; a daily forecast needs an entry for today. The forecast is fetched at start, when the
  weather entity changes (at most every 15 min) and hourly. See [daily strategy](docs/reference.md#daily-strategy).
- The cover recommendation is advice. Climate Hub calls no cover service, and existing cover automations keep working.
  See [cover reasons](docs/reference.md#cover-reasons).
- Outage repairs appear after the repair delay (default 6 h), counted from the moment a source is first judged invalid.
  For a silent sensor that is the maximum age after its last report, so the repair appears after 40 min plus 6 h with
  the defaults. The repair disappears when the source delivers values again. The repair for a new sensor appears
  5 s after the registry change that brought it into the area (or after the first evaluation at start); the one for
  windows without a room at the reload after the room was deleted. See [repairs](docs/reference.md#repairs).
- After a change of the configuration, the Climate Hub entities are `unavailable` until the reload has finished and the
  first evaluation has run. Automations should tolerate that state for a short time.

## Troubleshooting

| Symptom | Cause | Remedy |
|---|---|---|
| Daily strategy is `unknown`; the setup preview says "but no forecast" | The weather entity provides no forecast service. This is the case for a weather entity mirrored from another Home Assistant instance. | Select a weather entity of an integration with a forecast under **Configure → Weather service**. The service can be tested in Developer tools with `weather.get_forecasts`. |
| Outside humidity or pressure is `unknown`, or a room value outside is missing | The values come from the weather entity (no outdoor sensor delivers them), and the weather entity is unavailable, lacks the attribute or has not updated for 2 h. | Check the state of the weather entity. Select another one under **Configure → Weather service**, or add a humidity or pressure source to the outdoor side. |
| A room uses its second source; `stage` is `fallback`, `reason` is `stale`; later a repair "Sensor for … not responding" | The top sensor reports only when its value changes. A steady value is older than the maximum age (40 min), so the source counts as failed. After the repair delay (6 h) the repair appears. | Raise **Maximum age of a measurement** for that room or outdoor side (section **Advanced**) or in the hub options, or put a source that reports regularly first. The repair clears itself. |
| A window shows `open` although it is closed | The contact has come off the frame or its magnet and keeps reporting `open`. Climate Hub never reads `unavailable` or `unknown` as closed, but it trusts a contact that reports `open`. | Fix or reattach the contact. Check the contact's own state in Developer tools. Remove it from the window with **Reconfigure window** if it is defective. |
| A sensor without a device is not suggested as a source | The suggestion skips entities without a device ("no device") and helper values when the area has other sources. Only an area without any other source gets them suggested, entities without a device first, then derived values. | Add the entity under **Temperature sources** by hand; the preview of **Add room** lists it under "Not taken" with its reason. |
| Texts show the old wording, or raw keys, after an update | Home Assistant reads translations at start and the browser caches the frontend texts. | Restart Home Assistant after the update, then reload the page without cache (Ctrl+F5) or clear the app cache. |
| The contact list of a window form is long, or the right contact is missing | A text sensor is offered only when its state or `options` contain a window word (closed, locked, ajar, tilted, tilt, open and the German words); binary sensors only with the device class window, door, opening or garage door. | Switch on **Show all contacts** to list every contact in the house, pick the contact, and map its texts in **Assign states**. |
| The Cover sensor of a window is missing | The entity is disabled by default for windows without a cover. | Assign a **Cover** to the window, or enable the entity in its settings. |
| The cover recommendation is `none` with `no_data` | `sun.sun` does not exist, the room has no temperature, or the window has no facing (Facing "Like the room" in a room without a main side). | Enable the `sun` integration; check the room's temperature sensor; give the room a main side or the window a **Facing**. |
| Setting Comfort temperature min or max fails | The minimum must stay below the maximum. | Change the other value first. |

## Limits

- One Climate Hub entry per Home Assistant instance.
- Four outdoor sides at most, one per compass direction and one outdoor area each. A room has one main side; windows
  that face another side take it from their own **Facing**.
- One comfort range for the whole house. There is no range per room.
- Climate Hub does not control anything: not heating or cooling devices, not covers, not windows. It reads them and
  recommends. It reads a setpoint and never sets one.
- A spread needs two valid values. With one of two sensors out it is `unknown`; it does not fall back to the
  thermostat. Deviation from setpoint uses the first device in the list that regulates and reports a setpoint; a second
  device's setpoint is shown in the attribute `devices` but does not count.
- Source labels in `readings` drop the area name and metric words, which are known in English and German only; a name
  in another language keeps its metric word.
- No energy model: no heat exchange or solar gain per window. Cover and window recommendations follow rules with the
  thresholds above.
- No heat index, humidex or similar comfort indices.
- Management uses Home Assistant's own dialogs. There is no custom panel.
- Not built: a mould-risk indicator, a CO2 or air-quality rule, a ventilation preference per outdoor side and a
  cross-ventilation hint.
- Sources are sensors with the device class temperature, humidity or pressure and `climate` entities. Contacts are
  binary sensors of the classes window, door, opening and garage door, or text sensors with a state mapping.

## Documentation

| For | Read |
|---|---|
| Setting up and using Climate Hub | this README, [reference](docs/reference.md) |
| Letting Claude work with an installed Climate Hub (entities, diagnosis, automations) | [agent skill](docs/agent/climate-hub/SKILL.md) |
| Development and review: what is built, how it is computed, why | [logic](docs/logic.md), [integration](docs/integration.md), [architecture decisions](docs/architecture.md), [requirements](docs/requirements.md), [UI mockups](docs/ui_mockups.md); status in [STATUS](docs/STATUS.md) |

## License

[MIT](LICENSE)

## Development and AI use

The project is developed together with an AI assistant (Claude by Anthropic). The ideas, requirements, design decisions
and every review are the maintainer's; the AI helps write and test the code. A change is specified before it is built,
covered by tests, and tried on a Home Assistant test instance before it is merged.

These checks run on every push to `main` and on every pull request:

- `ruff check` and `ruff format --check` on Python 3.14
- `pytest` on Python 3.14
- hassfest, Home Assistant's own validation of an integration
- the HACS action, which validates the repository for HACS

The hassfest and HACS checks also run daily at 03:00 UTC, because their rules change without a commit here. A tag
`v*` starts a workflow that compares the tag with the version in `manifest.json` and creates the GitHub release from
the tag message.

If you find a bug or something that looks wrong, please
[open an issue](https://github.com/patchingfailed/home_assistant_climate_hub/issues).
