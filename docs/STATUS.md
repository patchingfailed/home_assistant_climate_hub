# Status

Updated 2026-10-16. The only place for project status.

## Now

All three milestones are built, verified on DEV by Felix and merged into `main`: M1 (rooms and outdoor sides), M2
(windows) and M3 (repairs: source outages, new sources, windows without a room; merged 2026-10-16). PROD runs since
2026-10-16. 750 tests green on `fix/audit-findings`. Plan and build order: `docs/integration.md`.

Branches (CLAUDE.md rule 14): `main` is the current line and pushed. `fix/audit-findings` holds the fixes and doc
updates from the 2026-10-16 repo audit until merged. `spike/native-ui` stays local as a reference and is never merged.
The repository is public (Felix's go, 2026-10-16).

## Next

1. **Audit fixes**: Felix's click review of `fix/audit-findings` on DEV (any reconfigure ends in „Die Änderungen sind
   gespeichert.", interior rooms show „keine Außenseite", room absolute humidity and dew point show source and stage,
   form titles „Raum: …" / „Außenseite: …" / „Climate Hub – Optionen", help texts under every field), then merge,
   then PROD with Felix's go.
2. **User documentation** in the README (entities, recommendation values, repairs, options, limitations): paused by
   Felix on 2026-10-16; outline first when picked up.
3. **Audit leftovers** (small): an entity-level test for the R13 attribute; `any_cover_to_close` always carries
   `windows`, even when empty (decide: keep or drop when empty).
4. **PROD follow-up**: watch the first days (values, repairs, log). Optional idea: a hint for a contact that stays
   `open` for days (not built; needs a requirement and a mockup first, rule 8).

DEV notes: DEV has one weather entity with a forecast service (met.no); its other weather entities are mirrors
without one, so the daily strategy stays unknown with them. The `*_klima_*` entities without attributes on DEV are
mirrors of another instance (`remote_homeassistant`), not Climate Hub's. DEV's
mirrored sensors update only when their value changes, so a steady one turns stale after `max_age` and, after the
repair delay, raises a real outage issue; that is DEV's mirror, not a bug. Outage tests: a state-only sensor set via
`POST /api/states` (owned by no integration, so nothing overwrites it), first in a room's list, then `unavailable`;
the repair delay goes down to 1 h in S9. New-source tests: move a mirrored sensor into a room's area; one that was in
the area when the room was last saved counts as seen and raises nothing.

## Open decisions

- Scope guard from the review: no energy-exchange model (requirements §7); the cover recommendation is advisory and
  leaves existing cover automations untouched.

## Recently done

- 2026-10-16: audit leftovers decided with Felix and built on `fix/audit-findings` (two Sonnet implementers, reviewed
  and committed per topic). W10: the open-since hint after a restart uses only contacts that report a non-closed
  level (a leaf closed later no longer moves the start forward). N7: the threshold check was unreachable (Home
  Assistant validates `number.set_value` against the range, min 0.5) and is gone with its translation. Form titles
  as in the mockups: „Raum: {area}", „Außenseite: {direction}" (translated direction), „Climate Hub – Optionen". U8:
  70 fields per language had no help text; all have one now (Felix waived the mockup round, rule 8), and a test fails
  on a field without one. Review find: the worker's „Alle Kontakte zeigen" text said „aus anderen Räumen", but the
  switch also lifts the window-word filter for text sensors; reworded to „alle Kontakte im Haus". DEV: deployed with
  restart, titles checked through the flow API (forms opened and discarded, nothing saved), texts served, log clean.
  Verified on DEV: yes (API); click review pending.

- 2026-10-16: repo audit (three Sonnet researchers: requirements traceability, specs and ADRs against code, UI and
  repo rules) and its fixes on `fix/audit-findings` (three Sonnet implementers, reviewed and committed per topic).
  Result: 66 of 86 requirement IDs and all 12 scenarios built and tested, 10 deferred by design, none built by
  accident; the docs lagged the code mostly at interface level. Fixed: abort reasons had no translations, so every
  reconfigure showed the raw `reconfigure_successful` (frontend falls back to the key); the 60 s tick could evaluate
  before HA had started (I14), now the interval is set in the first run; interior rooms showed `no_data`, now
  `no_side` („keine Außenseite"); room absolute humidity and dew point had no E6 attributes, now those of the weaker
  input without `offset`; default words gain verriegelt, abgeschlossen, locked; dead `dismissed` parameter and a
  test-only helper removed. Decided with Felix: A2 keeps warming a cold room on heat-up days (requirement sentence
  fixed), W8 says `unknown`. New tests: A2, W8 entity state, U5 `reorder`, I14 tick, abort translations. Docs brought
  to the built state (requirements markers for deferred IDs, interface sketches, plan-phrased text, mockup deviations,
  §7/§8 of the mockups collapsed, ADR updates); a location name and a reference to an earlier iteration removed from
  tracked files (they stay in the git history). DEV: deployed with restart, translations served in de and en, the
  three interior rooms show `no_side`, the kitchen's derived values show the temperature fallback, first evaluation
  after the start, log clean. Verified on DEV: yes (API); click review pending.

- 2026-10-16: PROD first run (Felix's go, HA 2026.10.1). Only `custom_components/climate_hub` copied with
  `deploy.ps1 -Instance Prod` (restart by hand: no PROD token in the shell), area sync left on (PROD does not use area
  sensors). Felix set up rooms and areas through the flow: went well. The one report, a window shown open, was a
  detached shared contact that kept saying `open`, not a logic bug; no code change. Verified on DEV: yes (before the
  deploy); verified on PROD: first run, no findings.

- 2026-10-16: CI merged into `main` (PR 1, branch deleted); on `main` CI and Validate are green, HACS included (it reads
  the default branch, so it failed on the PR). Brand images from Felix in `custom_components/climate_hub/brand/`
  (icon, logo, dark logo, each plus @2x; source SVG in `docs/assets/icon.svg`), logo on top of the README, `ignore:
  brands` removed from `validate.yml`. Deployed to DEV with restart: the brands API serves icon, @2x, logo and
  dark logo (200, sizes match), log clean, Felix sees the icons. First release tag `v0.1.0` (manifest version).
  Verified on DEV: yes.

- 2026-10-16: CI on `build/ci`: `ci.yml` (ruff check and format, pytest on Python 3.14) and `validate.yml` (hassfest,
  HACS action, daily cron; `brands` ignored until the icon exists), `hacs.json` (minimum 2026.10.0), manifest
  `issue_tracker` and sorted keys, README with the problem statement and the AI disclosure, MIT license. `win_compat`
  needs no change on Linux. Publish check (tree and 68 commits): no IPs, tokens or hosts; the repository went public.
  Found: a workflow on a branch needs a pull request to run (push trigger is `main` only); the HACS job needs a
  checkout. Verified on DEV: not applicable (no integration code changed).

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
