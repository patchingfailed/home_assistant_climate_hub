<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/patchingfailed/home_assistant_climate_hub/main/custom_components/climate_hub/brand/dark_logo@2x.png">
    <img alt="Climate Hub" src="https://raw.githubusercontent.com/patchingfailed/home_assistant_climate_hub/main/custom_components/climate_hub/brand/logo@2x.png" width="420">
  </picture>
</p>

# Climate Hub

Climate Hub turns the temperature, humidity and pressure sensors you rank into one temperature, one humidity and one
pressure value per room and per outdoor side. When the top sensor stops reporting, it takes the next one in the list.
From these values it recommends per room whether to open or close the windows, and per window whether to close the
cover.

Sensors in the same room rarely agree. A thermostat on the radiator reads 1 °C warm, and a wireless sensor drops off
the network for hours. A dashboard or an automation that reads a single sensor inherits these faults.

## What it does

- Each Home Assistant area can become a room. Its temperature, humidity and pressure come from a list of sources that
  you rank. Climate Hub uses the first valid source: its value is a number, its unit converts, and it is no older than
  the maximum age (40 min by default). When a lower-ranked source takes over, Climate Hub subtracts that source's
  learned deviation from the top source, so the room value does not jump. Each room also gets absolute humidity, dew
  point, the difference to the outside, its position in the comfort range and a trend.
- There are up to four outdoor sides, one per compass direction, each with its own outdoor area. A side without a
  valid source takes the mean of its neighbouring sides, then the opposite side, then the weather entity, whose values
  count as failed after 2 h.
- A window can be a single window, a double leaf or a pass-through of two openings in a row, with the states `closed`,
  `ajar`, `tilted` and `open`. By default it counts as ventilating from `tilted` on. Each room gets a recommendation
  (`open`, `keep_open`, `close`, `keep_closed` or `none`) with a reason. It comes from the room and outside values, the
  comfort range (20 to 24 °C by default), the humidity threshold (60 % by default) and the daily strategy from the
  forecast. Binary sensors warn when a window stays open longer than the burst ventilation time (10 min by default)
  while that works against the day's strategy, or while a heating or cooling device in the room is running.
- Each window gets a cover recommendation, `close`, `keep_closed`, `open`, `keep_open` or `none`, with a reason. It
  looks at the sun position relative to the window, the cloud cover, the room temperature and the daily strategy.
  Climate Hub reads covers and never moves them. The rules are under [cover reasons](docs/reference.md#cover-reasons).
- Home Assistant repairs report a source that has been invalid for the repair delay (6 h by default), a new sensor in
  the area of a room or outdoor side, and windows whose room was deleted.

The integration comes with English and German translations.

## Requirements

- Home Assistant 2026.10.0 or newer.
- Temperature sensors assigned to areas, and humidity and pressure sensors if you have them. An entity belongs to an
  area through its device or directly. `climate` entities in the area count as temperature sources, and as humidity
  sources when they report humidity.
- For outdoor values, one area per side of the house that has an outdoor sensor; see
  [Areas for the outside](#areas-for-the-outside).
- Optional: a weather entity that provides a forecast through `weather.get_forecasts` (hourly or daily). It feeds the
  daily strategy, and the outside values when none of the outdoor sides has a value. Without a forecast the Daily
  strategy sensor is `unknown`, and without a weather entity it does not exist.
- For the cover recommendation, the `sun` integration (`sun.sun`). Without it the cover recommendation is `none` with
  the reason `no_data`.
- Optional: the `recorder`. The window form uses it to pre-fill the state mapping of a text sensor from its values of
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

There is one Climate Hub entry per Home Assistant instance. The setup dialog creates it together with the rooms,
outdoor sides and windows you confirm, and it creates nothing before the last step.

### Areas for the outside

Climate Hub finds sensors through their Home Assistant area, outdoor sensors included. Home Assistant has no concept
of a side of the house, so Climate Hub uses areas for that too: an outdoor side is an area that holds the outdoor
sensors of one side. Before you start, create one area for each side where an outdoor sensor hangs, for example
"Garden" for the south side and "Street" for the north side. Assign the outdoor temperature sensor to it, through its
device or directly, together with any humidity or pressure sensor on that side.

Put these areas on a floor whose name contains an outside word, such as "Outside". Step 2 then leaves them
unchecked, so they do not become rooms, and step 3 offers them as outdoor areas. Step 3 lists only areas that are
not rooms and have a temperature sensor. A side without an outdoor area takes its values from the neighbouring
sides, then from the opposite side, then from the weather entity.

### Steps

1. Open **Settings → Devices & services → Add integration → Climate Hub**. The dialog **Set up Climate Hub** shows what
   it found: areas with a climate sensor or thermostat, areas with a temperature sensor that could be outside, window
   and door contacts, and weather services.
   - **Weather service** is optional and pre-filled with the first weather entity that supports a forecast.
   - **Keep areas up to date** is on by default. Climate Hub then enters the room and outdoor side values as the
     temperature and humidity sensor of their areas, so area cards show the combined value. It clears such a field
     only while the field still holds the entity Climate Hub wrote.

   Select **Submit**.

   ![Dialog Set up Climate Hub: counts of what was found, weather service, area sync switch](https://raw.githubusercontent.com/patchingfailed/home_assistant_climate_hub/main/docs/assets/screenshots/setup-start.png)
2. **Which areas are rooms?** lists every area with a temperature source as "floor · area", or "no floor" for an area
   that is on no floor. Areas on a floor whose name contains an outside word (Outside, Outdoor, Garden, Yard, Patio,
   Terrace, Balcony, or the German equivalents) start unchecked. Any other area starts checked if it has a `climate`
   entity or sits on a floor. Check the rooms, leave the outdoor areas unchecked because they become outdoor sides in
   step 3, and select **Submit**.

   ![Dialog Which areas are rooms?: rooms on the first floor checked, outdoor areas unchecked](https://raw.githubusercontent.com/patchingfailed/home_assistant_climate_hub/main/docs/assets/screenshots/setup-rooms.png)
3. **House plan** has one section per direction: **North**, **East**, **South** and **West**.
   - **Outdoor area** is the area whose sensors measure that side (see
     [Areas for the outside](#areas-for-the-outside)). Leave it empty if that side has no outdoor sensor, for example a
     wall facing the neighbour's property. Rooms on that side then take the values of the neighbouring sides, then the
     opposite side, then the weather entity.
   - **Rooms on this side** are the rooms whose windows face that way. A room belongs to one side only, and its
     recommendation uses the outside air of that side. Leave interior rooms out. They get no main side, and their
     recommendation is `none` with the reason `no_side`.

   Each outdoor area can serve one side only. Select **Submit**.

   ![Dialog House plan: per direction an outdoor area and the rooms on that side](https://raw.githubusercontent.com/patchingfailed/home_assistant_climate_hub/main/docs/assets/screenshots/setup-plan.png)
4. **Preview** shows what would be created, with live values. For each room you see the current value, its source,
   the fallbacks and the entities that were not taken, each with a reason (a fridge sensor, for example, is "not a
   room value"). For each outdoor side you see the value and its fallback chain, followed by the weather service and
   the windows added so far. Then choose one of these:
   - **Create** creates everything.
   - **Add window (optional)** adds a window, see step 5.
   - **Change rooms** goes back to step 2.
   - **Change house plan** goes back to step 3.

   ![Dialog Preview: rooms with value, source, fallbacks and a sensor not taken; outdoor sides with their fallback chain; the menu](https://raw.githubusercontent.com/patchingfailed/home_assistant_climate_hub/main/docs/assets/screenshots/setup-preview.png)
5. To add windows, choose **Add window (optional)**, once per window. Climate Hub never guesses windows, because they
   depend on how the contacts are mounted.
   1. **Add window** asks for the **Room**.
   2. Pick the type: **Single window or door**, **Double leaf** or **Pass-through**.

      ![Dialog Add window: the three window types with their descriptions](https://raw.githubusercontent.com/patchingfailed/home_assistant_climate_hub/main/docs/assets/screenshots/window-type.png)
   3. Fill in the form. A single window needs a **Contact**. A double leaf needs **Left leaf** and **Right leaf**, and
      if there is one, **Contact between the leaves (optional)**. A pass-through needs **Inner opening** and **Outer
      opening**. Leave **Name** empty to get a name based on the room. **Show all contacts** lists every contact in
      the house instead of only those in the room's area and those without an area. In the section **Extra
      contacts**, a single window takes **Tilt detection** and **Handle contact**, and a double leaf takes **Handle
      contact**; a pass-through has no extra contacts. The section **Cover** takes the **Cover** entity. The section
      **Advanced** holds **Facing** (default "Like the room"), **Exact facing in degrees** and **Counts as ventilating
      from** (default "Tilted").
   4. If the contact is a text sensor, **Assign states** asks which text means **closed**, **ajar**, **tilted** and
      **open**. The fields are pre-filled from past values and common words.
   5. The window preview shows the window's state and the room's recommendation. Select **Save** to return to the
      setup preview, or **Change type**.
6. Select **Create**. The last dialog says where to change sources and add windows later.

### What the defaults mean

The setup writes these values into the hub options; the next section shows where to change them. The comfort range and
the threshold are number entities on the device Home climate, not hub options. Ranges and all other fields are in the
reference under [settings](docs/reference.md#settings) and [writable numbers](docs/reference.md#writable-numbers).

| Setting | Default | Meaning |
|---|---|---|
| Maximum age of a measurement | 40 min | A reading older than this counts as failed, and the next source takes over. A room or outdoor side can override it under **Advanced**. |
| Duration of burst ventilation | 10 min | Length of a burst for humidity. The cooling-down, heating-up and open-while-heating/cooling warnings fire only when a window stays open longer. After a burst, the next one waits 1 h. |
| Ventilate for humidity from | 60 % | From this room humidity on, the recommendation is to ventilate if the outside air holds less water vapour. It continues until the humidity is 5 points below the threshold. |
| Report an outage after | 6 h | A source must be invalid for this long before a repair appears. |
| Comfort temperature min / max | 20 °C / 24 °C | A room above the range gets the advice to open while it is cooler outside, until the middle of the range (22 °C by default; on a `prevent_heat_up` day down to the comfort minimum). A room below the range gets it while it is warmer outside. The minimum must stay below the maximum. |
| Threshold | 2 °C | A forecast maximum above the comfort maximum plus the threshold makes the daily strategy `prevent_heat_up`; a forecast minimum below the comfort minimum minus the threshold makes it `prevent_cool_down`. |

## Adding and changing later

Everything set during the first setup can be changed later.

- To add a room, an outdoor side or a window, open the integration page (**Settings → Devices & services → Climate
  Hub**) and select **Add room**, **Add outdoor side** or **Add window** at the top. The same entries are in ⋮ next
  to the Climate Hub entry.
  - **Add room** asks for the **Area** and then shows **Room: {area}**. The form has the **Main side**, the
    **Temperature sources, most important first** (drag to reorder) and the sections **Humidity and pressure**,
    **Heating and cooling** and **Advanced**. Leave the humidity and pressure lists empty to use the matching sensors
    of the devices that provide the temperature sources. Heating and cooling devices are only read; Climate Hub
    compares their setpoint with the room temperature. Under **Advanced**, **Show individual readings** is on by
    default. With at least two sources it adds the entities Temperature spread and Humidity spread, which list the
    value of every source; switching it off removes both. The preview before **Save** shows the current value and the
    fallbacks. The reference lists every field of the [room form](docs/reference.md#room-form).

    ![Room form: area, main side, ranked temperature sources, sections Humidity and pressure, Heating and cooling, Advanced](https://raw.githubusercontent.com/patchingfailed/home_assistant_climate_hub/main/docs/assets/screenshots/room-form.png)
  - **Add outdoor side** asks for the **Direction**, offering only free ones, and the **Outdoor area**. The form then
    has the sources and the sections **Humidity and pressure** and **Advanced**. The reference lists every field of
    the [outdoor side form](docs/reference.md#outdoor-side-form).
  - **Add window** runs the same window steps as the first setup. If the area is not a room yet, saving creates the
    room with suggested sources. An area without a temperature sensor is refused, because it cannot become a room.
    The reference lists every field of the [window form](docs/reference.md#window-form).
- To change one item, select the gear icon on its card. It opens **Reconfigure room**, **Reconfigure outdoor side** or
  **Reconfigure window**. ⋮ on the card offers **Rename** and **Delete**. Renaming changes the title on the card and
  in repair texts, while device and entity names stay as they are. When you delete a room, its windows remain: they
  keep reporting their state and raise a repair that offers to recreate the room or delete the windows.
- The options open with the gear icon (**Configure**) next to the Climate Hub entry. **System options** in ⋮ is Home
  Assistant's own dialog and holds none of these settings. **Climate Hub – Options** has **Weather service**, **Keep
  areas up to date** and, in the collapsed section **Times and thresholds**, the four values from the table above. If
  the chosen weather entity is unavailable or has no forecast, a check step offers **Save anyway** or **Adjust**. The
  reference lists the [hub options](docs/reference.md#hub-options) and all other
  [settings](docs/reference.md#settings).
- To change the house plan, open ⋮ next to the entry and choose **Reconfigure**. You get the form from step 3, filled
  with the current state. If a side gets a new or different outdoor area, a preview with the suggested sources comes
  before **Save**.
- The comfort range and the threshold are number entities on the device Home climate, so automations can change them
  as well; see [writable numbers](docs/reference.md#writable-numbers).

Changes take effect without a restart. The integration reloads 1 s after the first change, and further changes within
that second share the same reload.

## What you get

Climate Hub creates a device for each room, outdoor side and window, plus the hub device Home climate. Room and
outdoor side devices are named Climate and placed in their area. Window devices are named Window and numbered from the
second window in a room ("Window 2"); a pass-through is named Passage, and a name you gave takes precedence. If your
Home Assistant leaves the area out of entity IDs (a setting), the device name includes it instead, as in "Kitchen
climate". Home Assistant generates the entity IDs from area, device and entity name, and Climate Hub never renames
them. Unique IDs come from the subentry, so renaming an area or a device keeps the history.

![Integration page: add buttons at the top, the hub device Home climate, one card per room and outdoor side](https://raw.githubusercontent.com/patchingfailed/home_assistant_climate_hub/main/docs/assets/screenshots/integration-page.png)

| Device | Entities (English names) | Details |
|---|---|---|
| Room | Temperature, Humidity, Pressure, Absolute humidity, Dew point, Outside temperature, Outside humidity, Outside temperature difference, Outside humidity difference, Outside, Comfort range, Trend, Recommendation; with windows also Window, Window open since, Cooling down, Heating up; with windows and heating or cooling devices also Open while heating/cooling; with at least two sources and the switch Show individual readings on (the default) Temperature spread and Humidity spread; with heating or cooling devices Deviation from setpoint | [room entities](docs/reference.md#room-entities), [readings and setpoint](docs/reference.md#readings-and-setpoint) |
| Outdoor side | Temperature, Humidity, Pressure, Absolute humidity, Dew point | [outdoor side entities](docs/reference.md#outdoor-side-entities) |
| Window | State, Open since, Cover | [window entities](docs/reference.md#window-entities) |
| Hub | Comfort temperature min, Comfort temperature max, Threshold, Daily strategy (with a weather entity), Indoor average, Outdoor, and with at least one window Anywhere cooling down, Anywhere heating up, Anywhere cover to close (plus Anywhere open while heating/cooling with heating or cooling devices) | [hub entities](docs/reference.md#hub-entities) |

A room has Humidity, Absolute humidity and Dew point only with a humidity source, and Pressure only with a pressure
source. Its outside entities exist once at least one outdoor side or a weather entity is configured; Outside humidity
difference also needs a humidity source. An outdoor side always has all five entities. A window's Cover sensor is
disabled by default and gets enabled when you assign a cover to the window.

![Sensors of a room device: measurements, outside values, comfort range, recommendation, trend, spread and deviation from setpoint](https://raw.githubusercontent.com/patchingfailed/home_assistant_climate_hub/main/docs/assets/screenshots/room-sensors.png)

Temperature spread and Humidity spread show how far a room's sources disagree. The state is the highest minus the
lowest valid value, and the attribute `readings` lists each source's own value before any correction. This helps in
a room with zones, such as bed and desk. A thermostat counts only when the room has fewer than two other sensors,
because it measures at the radiator. Deviation from setpoint is the room temperature minus the setpoint of the first
heating or cooling device in `heat`, `cool`, `heat_cool` or `auto` that reports a setpoint. A negative value means
colder than the setpoint, and with a setpoint range the value is 0 inside the range.

![Details of Temperature spread: the attribute Readings with the value of each source](https://raw.githubusercontent.com/patchingfailed/home_assistant_climate_hub/main/docs/assets/screenshots/room-readings.png)

The reference also explains the [object model](docs/reference.md#object-model), the
[provenance attributes](docs/reference.md#provenance-attributes) that show where a value came from, and the
[diagnostics](docs/reference.md#diagnostics), which contain the full decision chain of every value.

## Expected behaviour

- Climate Hub evaluates the sources when one of them changes, at most once every 2 s, and every 60 s. Contact changes
  are debounced for 5 s.
- Offsets take about a day to settle. While a lower-ranked source and the top source are both valid, Climate Hub learns
  their deviation. This offset counts as learned after 1 h of paired readings, settles with a time constant of 8 h and
  survives restarts. When the value switches down to a lower-ranked source, the correction starts at the last measured
  deviation, if that pair is younger than the maximum age, and moves to the learned value within 1 h. Until a source has
  1 h of paired readings, the preview in the room and outdoor side forms says "deviation is being learned".
- Each measurement carries attributes that say where its value came from. `stage` is `primary` for the top source,
  `fallback` for a lower one and `none` when no source is valid; outside values can also be `neighbour`, `opposite`
  or `weather`. Depending on the stage, `source`, `reason` (for example `stale`) and `offset` appear as well. The
  reference describes them under [provenance attributes](docs/reference.md#provenance-attributes).
- A room without a main side has the recommendation `none` with the reason `no_side`. A room whose temperature or
  outside value is missing has `none` with `no_data`. The reference lists all
  [recommendation reasons](docs/reference.md#recommendation-reasons).
- The Daily strategy stays `unknown` while the weather entity provides no forecast. An hourly forecast needs at least
  12 entries in the next 24 h, a daily forecast an entry for today. Climate Hub fetches the forecast at start, when
  the weather entity changes (at most every 15 min) and every hour; see
  [daily strategy](docs/reference.md#daily-strategy).
- The cover recommendation is advice only. Climate Hub calls no cover service, and existing cover automations keep
  working; see [cover reasons](docs/reference.md#cover-reasons).
- An outage repair appears after the repair delay (6 h by default), counted from the moment a source is first judged
  invalid. A sensor that stops reporting is judged invalid once its last report is older than the maximum age, so
  with the defaults its repair appears after 40 min plus 6 h. The repair disappears when the source delivers values
  again. A repair for a new sensor appears 5 s after the registry change that brought the sensor into the area, or
  after the first evaluation at start. The repair for windows without a room appears at the reload after the room was
  deleted; see [repairs](docs/reference.md#repairs).
- After a configuration change, the Climate Hub entities are `unavailable` until the reload has finished and the first
  evaluation has run. Automations should tolerate that state for a short time.

## Troubleshooting

| Symptom | Cause | Remedy |
|---|---|---|
| Daily strategy is `unknown`; the setup preview says "but no forecast" | The weather entity provides no forecast service. This is the case for a weather entity mirrored from another Home Assistant instance. | Select a weather entity of an integration with a forecast under **Configure → Weather service**. You can test the service in Developer tools with `weather.get_forecasts`. |
| Outside humidity or pressure is `unknown`, or a room value outside is missing | The values come from the weather entity because no outdoor sensor delivers them, and the weather entity is unavailable, lacks the attribute or has not updated for 2 h. | Check the state of the weather entity. Select another one under **Configure → Weather service**, or add a humidity or pressure source to the outdoor side. |
| A room uses its second source; `stage` is `fallback`, `reason` is `stale`; later a repair "Sensor for … not responding" appears | The top sensor reports only when its value changes. A steady value gets older than the maximum age (40 min), so the source counts as failed, and after the repair delay (6 h) the repair appears. | Raise **Maximum age of a measurement** for that room or outdoor side (section **Advanced**) or in the hub options, or put a source that reports regularly first. The repair clears itself. |
| A window shows `open` although it is closed | The contact has come off the frame or its magnet and keeps reporting `open`. Climate Hub never reads `unavailable` or `unknown` as closed, but it trusts a contact that reports `open`. | Fix or reattach the contact, and check the contact's own state in Developer tools. If it is defective, remove it from the window with **Reconfigure window**. |
| A sensor without a device is not suggested as a source | When the area has other sources, the suggestion skips entities without a device ("no device") and helper values. Only an area without any other source gets them suggested, entities without a device first, then derived values. | Add the entity under **Temperature sources** by hand. The preview of **Add room** lists it under "Not taken" with its reason. |
| Texts show the old wording, or raw keys, after an update | Home Assistant reads translations at start, and the browser caches the frontend texts. | Restart Home Assistant after the update, then reload the page without cache (Ctrl+F5) or clear the app cache. |
| The contact list of a window form is long, or the right contact is missing | A text sensor is offered only when its state or `options` contain a window word (closed, locked, ajar, tilted, tilt, open and the German words). A binary sensor is offered only with the device class window, door, opening or garage door. | Switch on **Show all contacts** to list every contact in the house, pick the contact, and map its texts in **Assign states**. |
| The Cover sensor of a window is missing | The entity is disabled by default for windows without a cover. | Assign a **Cover** to the window, or enable the entity in its settings. |
| The cover recommendation is `none` with `no_data` | `sun.sun` does not exist, the room has no temperature, or the window has no facing (Facing "Like the room" in a room without a main side). | Enable the `sun` integration, check the room's temperature sensor, and give the room a main side or the window a **Facing**. |
| Setting Comfort temperature min or max fails | The minimum must stay below the maximum. | Change the other value first. |

## Limits

- One Climate Hub entry per Home Assistant instance.
- At most four outdoor sides, one per compass direction, each with one outdoor area. A room has one main side; a
  window that faces another side takes it from its own **Facing**.
- One comfort range for the whole house, none per room.
- Climate Hub controls nothing. It reads heating and cooling devices, covers and window contacts and only recommends.
  It reads setpoints and never sets one.
- A spread needs two valid values. If one of two sensors is out, the spread is `unknown` and does not fall back to
  the thermostat. Deviation from setpoint uses the first device in the list that regulates and reports a setpoint. A
  second device's setpoint appears in the attribute `devices` but does not count.
- Source labels in `readings` leave out the area name and metric words. Climate Hub knows metric words in English and
  German only, so a name in another language keeps its metric word.
- There is no energy model, so no heat exchange or solar gain per window. The cover and window recommendations follow
  rules with the thresholds above.
- No heat index, humidex or similar comfort indices.
- Setup and changes use Home Assistant's own dialogs; there is no custom panel.
- Not built yet: a mould-risk indicator, a CO2 or air-quality rule, a ventilation preference per outdoor side and a
  cross-ventilation hint.
- Sources are sensors with the device class temperature, humidity or pressure, and `climate` entities. Contacts are
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

Climate Hub is developed together with an AI assistant, Claude by Anthropic. The ideas, requirements and design
decisions come from the maintainer, who also reviews every change; the AI helps write and test the code. Each change
is specified before it is built, covered by tests, and tried on a Home Assistant test instance before it is merged.

These checks run on every push to `main` and on every pull request:

- `ruff check` and `ruff format --check` on Python 3.14
- `pytest` on Python 3.14
- hassfest, Home Assistant's own validation of an integration
- the HACS action, which validates the repository for HACS

Hassfest and the HACS check also run every day at 03:00 UTC, because their rules can change without a commit in this
repository. A tag `v*` starts a workflow that compares the tag with the version in `manifest.json` and creates the
GitHub release from the tag message.

If you find a bug or something that looks wrong, please
[open an issue](https://github.com/patchingfailed/home_assistant_climate_hub/issues).
