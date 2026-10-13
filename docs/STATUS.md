# Status

Updated 2026-10-13. The only place for project status.

## Now

UI mockups are approved (2026-10-13). The clickable prototype (private Claude artifact „Climate Hub
Prototyp", example data) shows the approved state. No integration code exists yet.

## Next

1. **DEV spike** on a throwaway branch for `docs/ui_mockups.md` §7 (12 items, incl. the area prefix in entity IDs).
   DEV is clean (no old `climate_hub` entries, entities, devices or folder; checked 2026-10-13). The DEV token comes
   from the repo's gitignored `.env` (`HA_TOKEN`), used by `deploy.ps1` and `ha.py`; verified against the DEV API.
2. **Minimum HA version** as an ADR after the spike (at least 2025.10 for menu option descriptions).
3. **Logic spec and pure logic modules** with table tests: psychrometrics (absolute humidity, dew point, humidity after
   ventilating), source resolution with offset learning, region fallback, window state (incl. the W12 table),
   recommendation (A1–A6, A12), shading (SH1).
4. **CI**: pytest, ruff, hassfest, HACS validation.

## Open decisions

- ADR-005 naming may change if Home Assistant prefixes the area to new entity IDs (spike item 6).
- U11: native UI vs. custom panel, decided after the DEV spike.

## Recently done

- 2026-10-13: mockups approved after the second prototype review (entity list, defaults Q5, S8d, optional windows
  step, heating/cooling, repairs). Window names default to „{Bereich} Fenster"; the double leaf's shared contact is a main
  field. Verified on DEV: no.

- 2026-10-13: first prototype review folded in. Requirements R5, R6, R14, R15, A12, W0, W11, W12 (truth table) and U1;
  mockups S4, S5, S6, S8, S11 and §6–§8. Prototype republished. Verified on DEV: no.
- 2026-10-13: mockups v2. Checked the native flow capabilities against core and frontend source (§2.4, §7).
  Room and region creation now start with the area. Window contacts are filtered by type only (U6 exception), and the
  window name is optional. Main side always offers four directions. New S8d text-sensor mapping (W2). Fixed leftover
  examples in the project skill. Clickable prototype built and published for review. Verified on DEV: no.
- 2026-10-13: toolchain. Python 3.14.7, `.venv`, `requirements_test.txt` (`pytest-homeassistant-custom-component`
  0.13.372 = HA 2026.10.1, ruff 0.17.0), ruff target `py314`, local `scripts/deploy.config.ps1`. HA 2026.10 imports
  `fcntl` at test startup, so `win_compat.py` stubs it on Windows (`-p win_compat`). `python -m pytest` starts (0 tests),
  ruff green. Note: the Python installer asks for UAC even with `--scope user`.
- 2026-10-12: project scaffolding (CLAUDE.md, deploy script, test conftest, Claude settings and skill);
  `docs/requirements.md`, `docs/architecture.md` (ADR-001 to ADR-006), `docs/ui_mockups.md`, this file.
  Verified on DEV: no (nothing built yet).
