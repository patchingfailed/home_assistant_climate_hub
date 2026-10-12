# Status

Updated 2026-10-12. The only place for project status.

## Now

Planning is done for the first round: requirements, architecture decisions and the UI flow are drafted. No integration
code exists yet.

## Next

1. **Clickable prototype** of the first setup, room and window flows in Home Assistant style, for UI review.
2. **DEV spike** for the native UI assumptions (`docs/ui_mockups.md` §7): sortable entity selector inside a subentry
   form and section, sections in subentry flows, menu step as preview, area selector filtered by device class, creating
   the hub entry with subentries in one step, device name translation with an `{area}` placeholder.
3. **Toolchain**: Python 3.14 venv, pinned `pytest-homeassistant-custom-component` for HA 2026.10, ruff target
   `py314`, CI (pytest, ruff, hassfest, HACS validation).
4. **Minimum HA version** as an ADR after the spike (at least 2025.9 for the sortable selector).
5. **Logic spec and pure logic modules** with table tests: psychrometrics (absolute humidity, dew point, humidity after
   ventilating), source resolution with offset learning, region fallback, window state, recommendation (A1–A6),
   shading (SH1).
6. Before the first deploy: remove old `climate_hub` entries and the old `custom_components/climate_hub` folder on DEV.

## Open decisions

- `docs/ui_mockups.md` §8, points 3 and 4: main-side options always show all four directions; entity list complete?
- Requirements Q5: defaults (maximum age 40 min, burst ventilation 10 min, humidity threshold 60 %, repair after 6 h).
- Requirements Q6: verify the sortable selector inside a subentry flow on DEV.
- U11: native UI vs. custom panel, decided after the DEV spike and the prototype review.

## Recently done

- 2026-10-12: project scaffolding (CLAUDE.md, deploy script, test conftest, Claude settings and skill);
  `docs/requirements.md`, `docs/architecture.md` (ADR-001 to ADR-006), `docs/ui_mockups.md`, this file.
  Verified on DEV: no (nothing built yet).
