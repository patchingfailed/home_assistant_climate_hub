<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="custom_components/climate_hub/brand/dark_logo@2x.png">
    <img alt="Climate Hub" src="custom_components/climate_hub/brand/logo@2x.png" width="420">
  </picture>
</p>

# Climate Hub

Everything about your indoor climate in one place: Climate Hub merges all the temperature, humidity and pressure
sensors of a room, plus the readings from outside, into **one entity per room and per outdoor side**. When a sensor
drops out, that entity keeps delivering a trustworthy value instead of going `unavailable`. That makes it a stable
foundation for dashboards and downstream automations. On top of that, it tells you **when opening or closing a window
helps**.

The problem: some of your sensors sit next to a radiator, some report the fridge, some drop off the network for hours.
Climate Hub ranks them, falls back when one fails, and always says where a value came from.

## What it does

- **Rooms:** one temperature, humidity and pressure value per Home Assistant area from a ranked list of sources, with
  fallbacks. Each value reports its source and the fallback stage that produced it.
- **Outdoor sides:** the same per compass direction, falling back to neighbouring sides, the opposite side and finally
  your weather service.
- **Windows:** the window connects a room to the outside. It reports its opening state and whether opening or closing
  helps today, based on indoor and outdoor values, a comfort range and the weather forecast. An optional recommendation
  covers roller shutters; it is advisory and never touches your existing automations.
- **Repairs:** Home Assistant repairs tell you when a source has been out for too long, when a new sensor appeared in a
  room's area, or when a window lost its room.
- **Native UI:** setup and editing use Home Assistant's own config flow, subentries and areas. Suggestions are proposed
  and you confirm; nothing becomes a source silently.

English and German translations are included.

## Requirements

Home Assistant **2026.10.0** or newer.

## Installation

### HACS (custom repository)

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/patchingfailed/home_assistant_climate_hub` as category **Integration**.
3. Install **Climate Hub** and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration → Climate Hub**.

### Manual

Copy `custom_components/climate_hub` into the `custom_components` folder of your Home Assistant configuration and
restart.

## Documentation

The design documents live in [`docs/`](docs/): [requirements](docs/requirements.md),
[architecture decisions](docs/architecture.md), [UI mockups](docs/ui_mockups.md), [pure logic spec](docs/logic.md) and
[integration spec](docs/integration.md). Current status: [`docs/STATUS.md`](docs/STATUS.md).

## License

[MIT](LICENSE)

## Built with care and responsible AI use

This project is developed together with an AI assistant (Claude by Anthropic). The ideas, requirements, design
decisions and every review are the maintainer's; the AI helps write and test the code. The result is held to the same
bar as any other code in this repository: it is specified up front, covered by tests (several hundred, run on every
push), checked by linters and Home Assistant's own validation, and tried on a real Home Assistant instance before it
is merged. If you find a bug or something that looks wrong, please
[open an issue](https://github.com/patchingfailed/home_assistant_climate_hub/issues).
