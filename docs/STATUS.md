# Status

Updated 2026-10-16. The only place for project status.

## Now

All three milestones are built, verified on DEV by Felix and merged into `main`: M1 (rooms and outdoor sides), M2
(windows) and M3 (repairs: source outages, new sources, windows without a room; merged 2026-10-16). 738 tests green.
Plan and build order: `docs/integration.md`.

Branches (CLAUDE.md rule 14): `main` is the current line; the M3 commits are not pushed yet (push is Felix's call).
`spike/native-ui` stays local as a reference and is never merged.

## Next

1. **CI**: pytest, ruff, hassfest, HACS validation; `hacs.json` with `"homeassistant": "2026.10.0"` (ADR-008).
2. **PROD trial**, area sync off for the first run, only with Felix's explicit go.

DEV notes: the only real weather entity on DEV is `weather.forecast_home` (met.no); `weather.openweathermap` and
`weather.mannheim` are mirrors without a forecast service, so the daily strategy stays unknown with them. DEV's
mirrored sensors update only when their value changes, so a steady one turns stale after `max_age` and, after the
repair delay, raises a real outage issue; that is DEV's mirror, not a bug. Outage tests: a state-only sensor set via
`POST /api/states` (owned by no integration, so nothing overwrites it), first in a room's list, then `unavailable`;
the repair delay goes down to 1 h in S9. New-source tests: move a mirrored sensor into a room's area; one that was in
the area when the room was last saved counts as seen and raises nothing.

## Open decisions

- None. Scope guard from the review: no energy-exchange model (requirements §7); the cover recommendation is advisory and
  leaves existing cover automations untouched.

## Recently done

- 2026-10-16: M3 built on `build/m3-repairs` (steps 18 and 19 by a Sonnet implementer, each reviewed and committed
  separately) and verified on DEV. `issues.py`: outage issues after each evaluation with three texts (correction,
  fallback only, no replacement), kept while their object fails; new-source issues (R14) from the pre-fill rules
  including the R6 last resort, minus the seen set; windows without a room (W11) at setup. `repairs.py`: new sensor
  as a menu „Als Quelle aufnehmen" / „Nicht aufnehmen" (Felix's click review; the bare confirm had no „no"), and
  windows without a room with „Raum wieder anlegen" (S6 preview) or „Fenster löschen" (confirm). Decided with Felix:
  DEV test without MQTT, R14 follows the pre-fill exactly, repair delay minimum stays 1 h. Found and fixed: the
  fingerprint hashed `MappingProxyType` by its `str()` (key-order dependent), so a fix would have swallowed other
  open issues; the seen set missed mirrored sensors at start-up (their device class only arrives with the state), so
  it now records every sensor and climate entity of the area; the outage text showed the deviation (+0,8 °C) instead
  of the applied correction (−0,8 °C). DEV smoke test through the API (R14 raise and fix with the second issue
  surviving, W11 with room delete, recreate, same entity IDs), then Felix's click review: R14 dialog and its new
  menu, W11, outage with its text and its disappearance on recovery. Test setup removed afterwards (repair delay
  back to 6 h); five mirrored sensors stay in the areas they belong to. The room Küche, deleted for the W11 review,
  was recreated through the fix flow with four suggested sources; no issue open. M3 merged into `main`;
  `build/m3-repairs` deleted. Verified on DEV: yes.

- 2026-10-16: M2 click review on DEV by Felix: passed. Before it, every window path ran through the flow API on DEV
  (single, double leaf with two text sensors and S8d pre-filled from recorder history, bath text sensor with handle,
  pass-through) and the S9 check step appeared for the mirrored weather. Rooms without a main side show no
  recommendation (`no_side`, M1 behaviour); the window preview says so. M2 merged into `main`; `build/m2-windows`
  deleted. Verified on DEV: yes.

- 2026-10-16: M2 steps 14–16a built (Sonnet implementers, each reviewed and committed separately): window devices
  and entities, room window entities, hub any-flags, cover enable rule (I6); window subentry flow S8–S8d with preview
  and room creation (mixin `WindowSteps`); the window loop and windows part in the first setup; weather status line
  in S4 and check step in S9 (adds the daily variant „Vorhersage täglich"). DEV smoke test through the flow API: a
  kitchen window created, preview as in the mockup, entity IDs as in mockups §6, log clean. Found on DEV: 150+ text
  sensors (SSIDs, app versions) offered as contacts; text contacts now need a window word in state or options, „Alle
  Kontakte zeigen" lists all (Felix agreed). `deploy.ps1 -Logs` reads the log through the Supervisor proxy. Success
  text says „⋮ beim Eintrag Climate Hub" (the entry's real title) instead of the mockup's „Hausklima". Verified on
  DEV: partly (flow API; click review pending).

- 2026-10-15: M1 click review on DEV by Felix: rooms good. Outdoor humidity and pressure were unknown because the chosen
  weather entity was a dead mirror; with a working one the weather stage fills them. Mirrored weather entities cannot
  deliver forecasts, which led to the agreed weather status line (S4) and check step (S9). M1 merged into `main` and
  pushed; `build/m1-rooms` deleted. Verified on DEV: yes.

- 2026-10-14: M1 step 12 (hub flow S1–S4, options S9, house plan S10 with preview) built; stand-ins removed; 643
  tests green. M1 deployed to DEV (spike entry and files removed). DEV showed a real gap: its mirrored sensors have no
  device, so R6 offered no room and the first setup was a dead end. Fixed with an R6 last resort (device-less, then
  derived values when an area has nothing better; Felix agreed). Verified on DEV: partly (S1/S2 through the flow API;
  UI click review pending).

- 2026-10-14: M1 steps 1–11 built on `build/m1-rooms` (Sonnet implementers, each reviewed and committed separately):
  package skeleton with coalesced reload, shared test fixture house, pure `logic/model.py` and `logic/engine.py` (whole
  data flow incl. windows and covers), codec and `Store`, registry and model building, snapshot and forecast fetch,
  coordinator (I14 start, contact re-check, forecast kept on fetch errors, tick independent of entity listeners),
  devices and entities for rooms, regions and hub, diagnostics, area sync, room and region subentry flows with live
  previews. 601 tests green, ruff clean. Area sync leaves a field alone once the user changed it (R11 amended).
  Translation values must be strip-clean for hassfest; `tests/test_translations.py` guards it. Verified on DEV: no.

- 2026-10-14: integration spec and build plan drafted (`docs/integration.md`): pure engine `logic/engine.py`,
  snapshot, coordinator (60 s tick, 2 s debounce, contact re-check, forecast at start, on weather change and hourly),
  `Store` schema and codec, devices and entity table with unique IDs, flows mapped to step IDs and data keys, repairs,
  area sync, translations (`common` for word lists, the only free section hassfest accepts), diagnostics, tests, and
  20 build steps in three milestones. Felix approved I1–I11; folded into ADR-009 (new), ADR-002 (house settings in
  options), R11 (regions too, clear only own values), R14 ("seen" set), H2 (reject min ≥ max), SH2 (enable cover
  entity), mockups S1 text and §6. Sun from `sun.sun` (Felix). Verified on DEV: no (docs only).

- 2026-10-14: ADR-008, minimum Home Assistant 2026.10.0 (Felix agreed). Researched with sources: subentries 2025.3,
  `reorder` 2025.8 (ADR-004 and Q6 said 2025.9, corrected), menu option descriptions 2025.10, area prefix in entity
  IDs 2026.6, `entity_id_parts` 2026.8, `probatio` 2026.9. Since 2026.8 a device may sit in one subentry only (fits
  S5). N6 and Q6 closed. Verified on DEV: no (docs only).

- 2026-10-13: branches folded into `main` (fast-forward, nothing lost) and `main` pushed; GitHub's default branch
  is `main`, `planning/kickoff` and `build/logic-modules` are deleted locally and on GitHub. Branch rule as CLAUDE.md rule 14 (Felix agreed).

- 2026-10-13: pure logic built (`docs/logic.md` §3–§12): `const`, `psychro`, `sources`, `outdoor`, `comfort`,
  `strategy`, `window`, `recommendation`, `cover`, `prefill`, `house`, every table case a pytest case (393 tests in
  about 6 s, no `hass` fixture), plus a purity test (no `homeassistant` import, no clock read). Build refinements
  folded into the spec: strategy takes the observed outdoor value as a number, `outages` takes candidate statuses,
  "implausible" needs every leaf known, S8d default words come from translations, `no_room` only on the cover, the
  cover's open-window guard applies after the hold (review find: a held `close` could have locked someone out),
  S2 proposes only areas with a pre-fillable temperature, bias table row 5 coverage corrected. Line length stays
  ruff's 88. Verified on DEV: no (pure logic, nothing to deploy).

- 2026-10-13: logic spec approved. D15 (forecast bias A14, weather offset per side O5) and D16 (cover recommendation
  with heat and cold barrier, SH1/SH2) folded into the requirements; mockups §6 rename „Beschattung" to „Rollladen"
  (`sensor.<area>_fenster_rollladen`) and „Irgendwo beschatten" to „Irgendwo Rollladen schließen". Verified on DEV:
  no (spec only).

- 2026-10-13: first review of the logic spec. D1–D12 and D14 approved and folded into the requirements; R13 becomes an
  attribute (mockups §6). From the review: D15 (forecast bias and weather offset per side) and D16 (cover
  recommendation with heat and cold barrier) added to the spec. Verified on DEV: no (spec only).
- 2026-10-13: logic spec drafted (`docs/logic.md`): ten pure modules with interfaces and table cases, reference
  values computed (psychrometrics, offset learning, fallback means). Proposes D1–D14, among them a glide for offsets at
  the fallback switch, a binary recommendation with goals, a humidity guard against humid summer air, and a 24 h
  forecast horizon. Verified on DEV: no (spec only).
- 2026-10-13: U11 closed, native UI (ADR-001 confirmed). R3: humidity and pressure follow the temperature devices;
  without such devices the list is pre-filled from the area. Drag-sorting confirmed on DEV.
- 2026-10-13: second click review on DEV folded into the mockups. Copy rule (no first person). S8d with one field per
  position. Windows start with the room; contacts filtered with „Alle Kontakte zeigen". S2/S3 use computed lists,
  S2 pre-selects by floors and thermostats. S5 shows the real card layout. Verified on DEV: yes (spike, UI).

- 2026-10-13: ADR-007, device names without the area (accepted by Felix); E3 and the mockups follow it. First click
  review on DEV showed stale translations from the browser cache (the server serves the new ones).
- 2026-10-13: native-UI spike on DEV (HA 2026.10.1). 11 of 12 mechanisms work at API and source level; the area
  doubles in entity IDs when the device name contains it. Pitfalls added to the project skill; `deploy.ps1 -Restart`
  now waits until HA runs again. Spike tests green (7), ruff clean. Verified on DEV: yes (API level; UI look pending).
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
