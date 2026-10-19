# Status

Updated 2026-10-19. The only place for project status.

## Now

All three milestones are built, verified on DEV by Felix and merged into `main`: M1 (rooms and outdoor sides), M2
(windows) and M3 (repairs: source outages, new sources, windows without a room; merged 2026-10-16). PROD runs since
2026-10-16 (0.1.0, copied by hand); release 0.2.0 with the audit fixes is published but not yet on PROD. 759 tests
green. Plan and build order: `docs/integration.md`.

Branches (CLAUDE.md rule 14): `main` is the current line. `docs/documentation` is open for the documentation package
(local, WP0 done, WP1 drafted, WP3 built); it merges into `main` after Felix's README walkthrough.
`spike/native-ui` stays local as a reference and is never merged. The repository is public (Felix's go, 2026-10-16).

## Next

1. **PROD to HACS** (Felix, on PROD): HA backup; HACS → ⋮ → custom repositories → this repository, type
   Integration; download v0.2.0; restart. Same folder, so entry, unique IDs and history stay. From then on PROD only
   gets releases; `deploy.ps1 -Instance Prod` stays as an emergency path (Felix, 2026-10-16).
2. **Documentation package**, planned with Felix on 2026-10-18 (section below). WP0 done; WP1 drafted, verified
   against the code, entry points corrected from Felix's screenshot; WP3 (agent skill) built on the same branch at
   Felix's request, because he wants to use it on PROD now. Continue here:
   1. DEV is prepared: server language switched from `de` to `en` (2026-10-19, Felix's go) so that device names and
      entity IDs come out English; floors First floor and Outside. After the walkthrough, switch the server language
      back to `de` (Settings → System → General, or WebSocket `config/core/update` with `language`).
   2. Felix deletes the DEV entry, sets his profile language to English and follows the README from "First setup"
      word by word, noting every deviation, missing hint or guess; takes the screenshots from the shot list on the
      way (kept outside the repository; Felix has it); then adds a room, an outdoor side and a window along "Adding
      and changing later".
   3. Claude checks the images for private details (rule 13), embeds them with absolute `raw.githubusercontent.com`
      URLs on `main`, folds in Felix's deviations, runs `tests/test_docs.py`, then merges `docs/documentation` into
      `main` after Felix has looked (push is a separate go). The merge carries WP3 as well; WP2 follows on a new
      branch.
3. **Audit leftovers** (small): an entity-level test for the R13 attribute; `any_cover_to_close` always carries
   `windows`, even when empty (decide: keep or drop when empty). Found during WP1: the reason `ok` is translated but
   never written (dead entry, rule 4; `tests/test_docs.py` requires it in the reference while it exists); the `plan`
   and `reconfigure` step descriptions say "Simply leave out …" (banned word; change when the text is touched anyway);
   diagnostics redact nothing (no secrets in them; the reference says so; proposal: keep). Found during WP3 (decide):
   **Add window** in an area that is not a room creates the room with the suggested sources even when there are none,
   so a room with an empty temperature list exists (DEV's living room), while the room form requires at least one
   source; `any_cover_to_close` counts every window, also windows without a cover whose `cover` sensor is disabled
   (the skill documents the current behaviour).
4. **PROD follow-up**: watch the first days (values, repairs, log). Optional idea: a hint for a contact that stays
   `open` for days (not built; needs a requirement and a mockup first, rule 8).

DEV notes: since 2026-10-18 DEV runs 0.2.0, and its areas and its outdoor floor carry English names (area IDs unchanged)
for the README walkthrough; since 2026-10-19 the six indoor areas sit on a floor "First floor", the outdoor areas on
"Outside". DEV's server language is English (`en`) for the walkthrough; normally German (`de`). DEV has one weather
entity with a forecast service (met.no); its other weather entities are mirrors without one, so the daily strategy stays
unknown with them. The `*_klima_*` entities without attributes on DEV are mirrors of another instance
(`remote_homeassistant`), not Climate Hub's. DEV's mirrored sensors update only when their value changes, so a steady
one turns stale after `max_age` and, after the repair delay, raises a real outage issue; that is DEV's mirror, not a
bug. Outage tests: a state-only sensor set via `POST /api/states` (owned by no integration, so nothing overwrites it),
first in a room's list, then `unavailable`; the repair delay goes down to 1 h in S9. New-source tests: move a mirrored
sensor into a room's area; one that was in the area when the room was last saved counts as seen and raises nothing.

## Documentation package (planned 2026-10-18)

Three readers, three places. Every work package starts with an outline that Felix approves, is written from the code
(the audit found the specs lagging at interface level) and is checked fact by fact against the code by a verifier.
Order WP0 → WP1 → WP3 → WP2; Sonnet workers draft, the main session reviews. WP0 and WP1 on `docs/documentation`,
merged into `main` after WP1 so that the README HACS shows is reworked early and the branch stays short; WP3 and WP2
on a new branch (Felix, 2026-10-18).

| Reader | Question | Place |
|---|---|---|
| Home Assistant user | How do I get it running, what do I see afterwards, is that normal? | `README.md` (HACS shows it), `docs/reference.md` |
| Developer, reviewer, new dev session | What is built, how is it computed, and why? | `docs/logic.md`, `docs/integration.md`, reworked in place |
| Claude working with an installed Climate Hub | Which entities, what do the values mean, what may I change, how do I diagnose? | `docs/agent/climate-hub/SKILL.md` |

Decided with Felix:
- The technical documentation stays in the design set: `logic.md` and `integration.md` become the description of the
  built system instead of a new file next to them. File names, section numbers and the D/I IDs stay, because about 80
  code and test docstrings cite them.
- The agent context is for Claude outside Home Assistant (Claude Code or claude.ai with access to an instance), in
  skill format. No prompt for Home Assistant's own Assist.
- Screenshots: Felix takes them from a shot list that WP1 delivers; no automation for now.
- A docs guard test (WP1).

**WP0 Writing rules.** Done: the "Docs" section in CLAUDE.md is the reference for every session and worker. The
README's documentation section is the map of the readers, one row per reader once its document exists (WP1 adds
`docs/reference.md`, WP3 the skill).

**WP1 User.** README: what it does (sober rewrite of the pitch and of the "Built with care …" heading); requirements
(HA 2026.10, sensors assigned to areas, optional weather entity with a forecast); first setup as click steps along
S1–S4 and what the defaults mean; adding rooms, sides and windows later; expected behaviour (offsets learn over about
24 h, fallback stage in the attributes, `none` with `no_side` without a main side, daily strategy unknown without a
forecast-capable weather entity, the cover recommendation moves nothing, repairs only after the repair delay, entities
briefly unavailable after a configuration change); troubleshooting table (symptom → cause → remedy, from cases seen on
DEV and PROD); limits (requirements §7). `docs/reference.md`: every entity with raw states and English label, every
reason, attributes, options with defaults, repairs, diagnostics. Source of truth: `en.json`, the entity classes,
mockups §6. English only (rule 12). `tests/test_docs.py`: every entity key and every enum state and reason in
`en.json` appears in `docs/reference.md` and in the skill. Shot list for Felix (screen, state, crop, English UI);
before an image is committed, check it for private details (rule 13: device names, user in the sidebar, URL bar), and
check that images render in HACS' info view (relative paths may not; then absolute URLs). Done when the verifier
passed and someone set up Climate Hub on DEV using only the README, every step as written.

**WP3 Agent context.** Done 2026-10-19: `docs/agent/climate-hub/SKILL.md` (450 lines, most of it tables; the planned
150–250 counted prose). A copy lives in Felix's user skills (`~/.claude/skills/climate-hub/`); it is a copy, so it
needs a refresh when the skill changes. Still open: whether the repository should also be installable as a Claude Code
plugin.

**WP2 Technical documentation.** Rework `logic.md` and `integration.md` from build specs into the description of the
built system. Each section: what happens, how (formula or Mermaid flow), constants with values, why (ADR, requirement,
D/I ID), where in code and tests. Mermaid flows at least for one evaluation (8 steps), a room value with fallback and
offset learning, the outdoor fallback chain, window state, recommendation, cover. Removed: build order (§15 in both;
the CLAUDE.md layout line follows), approval and review history. The §0 decision tables dissolve into each section's
rationale; the IDs stay as anchors. Representative table cases stay as worked examples (the psychrometric reference
values in full); the complete cases live in the tests. Done when the verifier checked every number, formula and
threshold against the code, the reference values are recomputed with the code, Mermaid renders on GitHub, Felix read
two sections (dew point, recommendation) and could follow them, and no link or section reference is dead.

## Open decisions

- Scope guard from the review: no energy-exchange model (requirements §7); the cover recommendation is advisory and
  leaves existing cover automations untouched.

## Recently done

- 2026-10-19: WP3, the agent skill (Felix asked for it to work on PROD; the planned WP3 paragraph served as the
  outline). Drafted by a Sonnet worker; Claude added the diagnostics REST route and a health-check recipe. Verifier
  against code and the Home Assistant source: 4 wrong (among them `reason` and `offset` on outdoor side sensors, which
  appear only at `none` and `weather`, and the diagnostics wrapper `data`) and 6 imprecise statements, all fixed.
  Field test: a fresh Sonnet session with only the skill and read access to DEV solved the five planned tasks plus a
  health check, rendered both templates on DEV, and listed 17 gaps (mapping room names through areas, a registry
  reader, the offset glide, how far to trust a value, health-check rows for empty source lists, sides without
  humidity sources and long-open windows, the night range with both values); all folded in. Spot checks of its
  answers against DEV matched; the skill's registry snippet ran against DEV and found the 117 entities. The reference
  now names the diagnostics wrapper too. 759 tests green. Verified on DEV: yes (read-only field test).

- 2026-10-18: WP1 follow-up. Felix's screenshot of the integration page corrected the README entry points: the add
  buttons sit at the top of the page (and in ⋮ of the entry), the options open with the gear icon (⋮ → System options
  is Home Assistant's own dialog), a subentry card's gear opens its reconfigure form and its ⋮ offers Rename and
  Delete (Rename changes only the card title and repair texts). DEV prepared for the walkthrough: 0.2.0 deployed with
  restart, entry loaded, log clean; areas and the outdoor floor renamed to English through the WebSocket API. Found: device names
  follow the server language, not the profile language (pitfall added to the project skill). Verified on DEV: partly
  (deploy and load; README walkthrough pending).

- 2026-10-18: WP1 drafted (outline approved by Felix). README rewritten (sober intro, requirements, first setup as
  click steps, defaults, adding later, what you get, expected behaviour, troubleshooting from real cases, limits,
  "Development and AI use"); new `docs/reference.md` (every entity, state, reason, attribute, setting, repair,
  diagnostics); new `tests/test_docs.py` (en.json keys, states and reasons in the reference; banned words read from
  CLAUDE.md; relative links and anchors). Two Sonnet drafters, two Sonnet verifiers (about 580 statements checked
  against code): README 8 wrong or imprecise plus 4 minor, reference 3 wrong and 5 imprecise, all fixed. Among them:
  the room pre-check rule (an outside-word floor beats a climate entity), the reload timer (1 s after the first
  change), the cover hold (15 min dwell of the current wish, not of the new one) and the `new_source` check (start
  and 5 s after a registry change, not every evaluation). Code facts that the specs state differently, for WP2:
  offsets use an 8 h time constant, not a 24 h window; the Daily strategy entity does not exist without a weather
  entity. 756 tests green. Verified on DEV: no (Felix's README walkthrough pending).

- 2026-10-18: WP0 of the documentation package. "Docs" section in CLAUDE.md with the writing rules; beyond the plan:
  present tense for what is built, one name per concept, prose wrapped at 120. Decided with Felix: bold only for UI
  labels in click steps (Home Assistant docs convention); the rules cover UI strings only when they are added or
  changed anyway, no sweep of existing ones; merge after WP1. README documentation section rebuilt as the reader map.
  Verified on DEV: not applicable (docs only).

- 2026-10-18: documentation package planned with Felix (section above): three readers, writing rules, the technical
  documentation reworks the specs in place, agent context as a Claude skill, screenshots by Felix from a shot list,
  docs guard test. Branch `docs/documentation` opened. Verified on DEV: not applicable (plan only).

- 2026-10-16: release 0.2.0 (Felix's go). Version 0.2.0 rather than 1.x: 0.x bumps the minor for new and changed
  behaviour (the interior-room reason changes from `no_data` to `no_side`); 1.0 waits for a quiet PROD. New
  `.github/workflows/release.yml`: a `v*` tag creates the GitHub release, after checking the tag against the manifest
  version, with the annotated tag's message as notes (`gh` is not installed locally; release steps in CLAUDE.md).
  `main` pushed, CI and Validate green on both commits, tag `v0.2.0` pushed, release workflow green, release is the
  latest. Decided with Felix: PROD moves to HACS. Verified on DEV: not applicable (release only; the code is the one
  Felix clicked through).

- 2026-10-16: audit leftovers decided with Felix and built on `fix/audit-findings` (two Sonnet implementers, reviewed
  and committed per topic). W10: the open-since hint after a restart uses only contacts that report a non-closed
  level (a leaf closed later no longer moves the start forward). N7: the threshold check was unreachable (Home
  Assistant validates `number.set_value` against the range, min 0.5) and is gone with its translation. Form titles
  as in the mockups: „Raum: {area}", „Außenseite: {direction}" (translated direction), „Climate Hub – Optionen". U8:
  70 fields per language had no help text; all have one now (Felix waived the mockup round, rule 8), and a test fails
  on a field without one. Review find: the worker's „Alle Kontakte zeigen" text said „aus anderen Räumen", but the
  switch also lifts the window-word filter for text sensors; reworded to „alle Kontakte im Haus". DEV: deployed with
  restart, titles checked through the flow API (forms opened and discarded, nothing saved), texts served, log clean.
  Felix's click review of the whole branch on DEV: passed; `fix/audit-findings` merged into `main` (fast-forward)
  and deleted. Verified on DEV: yes.

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
