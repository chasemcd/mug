# Dimension 6 — Scene/Flow Progression & Client-Server State Sync (mugGlobals)

| Field | Value |
| --- | --- |
| Audit date | 2026-07-19 |
| Sources | `mug/scenes/{stager,scene,static_scene,unity_scene}.py`, `mug/configurations/experiment_config.py`, `mug/server/app.py` flow handlers, `mug/server/static/js/{index.js,ui_utils.js,unity_utils.js}`, `examples/cogrid/html_pages/` |
| Contracts mapped | API-03, API-04, API-09 (R-13 bridge), API-17 (rev 0.2) |

## 1. Mechanism map

### 1.1 Experiment config → Stager → scene sequence

- `ExperimentConfig.experiment(...)` binds a single `Stager`; `run(config)` stores it as the module-global `GENERIC_STAGER` (`app.py:2882-2885`).
- `Stager.__init__` asserts the sequence starts with `StartScene` and ends with `EndScene` (`stager.py:28-34`). Tracks only `current_scene_index`/`current_scene`.
- **Per-participant instantiation**: `build_instance()` deep-copies the whole stager, calls `build()` on every scene/wrapper, flattens (`stager.py:43-57`).
- **Ordering/gating wrappers** (`scene.py:184-265`): `SceneWrapper.build()` unpacks recursively; `RandomizeOrder` shuffles **in both** `build()` and `unpack()` and optionally truncates to `keep_n` — uses the process-global `random` module, **no per-subject seed, outcome not recorded anywhere**; `RepeatScene.build()` multiplies the list.
- **Scene lifecycle**: `activate()` emits `activate_scene` with `scene_metadata` (a JSON-serializable dump of **all instance vars** + `scene_id`, `scene_type`, timestamp — `scene.py:95-107, 145-181`); `deactivate()` emits `terminate_scene`.
- `Stager.start()` activates index 0 and fires **every scene's `on_connect` hook** (Unity preload fires at experiment start, not scene entry). `advance()` deactivates, increments, activates; walking past the end just logs — index can grow beyond `len(scenes)`. `get_state()/set_state()` persist **only** `current_scene_index`; `set_state` would `IndexError` on an out-of-range saved index.

### 1.2 Subject registration and identity

- **subject_id is the URL path.** `GET /` mints a uuid4 and redirects to `/<subject_id>`; `GET /<subject_id>` accepts any string — identity is entirely client-controlled/guessable, no signature or expiry (`app.py:223-242`).
- Re-entry blocked only for IDs in `PROCESSED_SUBJECT_NAMES` — appended only in `leave_game`, never for purely-static experiments.
- New participant: fresh `build_instance()` + `ParticipantSession(subject_id, mug_globals={"subjectName": subject_id}, ...)`. Returning participant: a **new** `build_instance()` (re-running `RandomizeOrder` shuffles!) then `set_state()` restores only the index (`app.py:246-270`).
- The template injects `var mugGlobals = {"subjectName": subjectName};` at global scope (`index.html:345-346`).
- On socket connect the client emits `register_subject {subject_id, mugGlobals}`. Server handler (`app.py:289-428`): duplicate-connection guard (second socket while `is_connected` → `duplicate_session`); maps sid→subject; emits `server_session_id` (per-process random token — captured client-side but **never validated on any later event**) and `experiment_config`. Restored session: merge globals `{**client, **server}` (**server wins**), `session_restored`, `stager.resume()`. Fresh: `update(client_globals)` (**client wins**), `stager.start()`.

### 1.3 Scene advancement protocol

- **Always client-initiated**, payload only `{session_id}`: (1) `#advanceButton` click for static scenes; (2) gym-scene "Done!" countdown — `onGameDone` callback or 100 ms polling, with a **MessageChannel watchdog** that force-emits if `setTimeout` was throttled in a background tab (`index.js:1730-1852`); (3) Unity countdown after `all_episodes_done`.
- **Server-side validation: effectively none.** `advance_scene` (`app.py:517-624`) looks up the stager, resets the tracker, removes the player from any Pyodide game, and calls `stager.advance()` unconditionally. No session_id check, no required-response check, no idempotency key, no expected-scene check — **a duplicate emit advances twice** (skips a scene).
- After advancing: lazily instantiates a shared per-scene `GameManager` for GymScenes (first-mover creates it), saves session state, updates the group manager, exports metadata.
- **`request_current_scene`** re-emits `activate_scene` for the current scene — a race repair for `activate_scene` arriving before the loading gate resolves; can double-render a scene, wiping in-progress DOM input.
- **Client scene rendering** (`index.js:1345-1459`): `activate_scene` merges `window.mugGlobals` into the scene data and dispatches on `scene_type` string: EndScene → redirect button (optional `append_subject_id`); GymScene → start button + waitroom flow; UnityScene; else static (advanceButton enabled by default). `terminate_scene` → sync globals, scrape `element_ids`, emit `static_scene_data_emission`, clear DOM.

### 1.4 mugGlobals end-to-end

**Platform-written keys:** `subjectName` (identity, read throughout multiplayer code), `gymSceneCounter`, `unityEpisodeCounter`, `unityScore`.

**Sync protocol (client → server, whole-object, merge-on-server):**
- `register_subject` carries the full object on every (re)connect.
- `sync_globals` is emitted **only on scene termination** (despite a server docstring saying "periodically" — there is no interval). Server does `session.mug_globals.update(client_globals)` — last-writer-wins per key (`app.py:467-474`).
- Piggybacked on every data emission: `static_scene_data_emission`, `emit_remote_game_data`, `emit_episode_data`, multiplayer metrics.

**Server → client:** only at session restore — `session_restored.mugGlobals` (merged, server-wins) replaces `window.mugGlobals` wholesale. No mid-scene push, no cross-participant sharing; scoping strictly per subject in the in-memory session.

**Persistence:** in-memory only; snapshots dumped to `data/{experiment_id}/{scene_id}/{subject_id}_globals.json` with every data emission.

**Consumption paths:** (1) Pyodide env init — `mug_globals = dict(js.window.mugGlobals.object_entries())` preamble before the study's init code (env parametrization from earlier pages); (2) custom HTML reads/writes `window.mugGlobals` freely; (3) scene activation exposes it as `sceneData.globals`.

**Custom-HTML use patterns found in `examples/cogrid/html_pages/`:**
- `overcooked_demo_instructions.html:40-99` — defensive init; **client-side condition randomization**: `fixedControls`/`hiddenControls` from `generateRandomPair()` stored in globals for later scenes.
- `choice_cramped_room.html:77-198` — reads globals written by a previous scene; writes `partner_mode` and reward parameters; **gates the startButton** with a 100 ms interval that re-disables the button after the platform's own enable logic runs — a deliberate fight with `enableStartRefreshInterval` (`index.js:1856-1901`).
- The advance-gating idiom (custom JS enabling/disabling `#advanceButton`) is documented in `StaticScene`'s docstring and used by every built-in form scene (`TextBox`, `OptionBoxesWithScalesAndTextBox`, `ScalesAndTextBox`, `MultipleChoice` — the last creates hidden inputs holding stringified index lists `"[0,1]"` for scraping).

**Response capture:** not via globals — scenes declare `element_ids`; on `terminate_scene` the client scrapes those DOM elements by tag/type (`getData`, `index.js:1373-1413`) and emits `static_scene_data_emission`; the server writes a one-row CSV + globals JSON. Requiredness is enforced **only** by scene-injected JS disabling the advance button; the server never checks.

### 1.5 Entry/continuous callbacks

- **Entry screening**: experiment-level config shipped to the client; built-in checks run **client-side** (UAParser device/browser, median-ping wait). If `has_entry_callback`, client sends context via `execute_entry_callback`; server runs the researcher's callable and replies `entry_callback_result {exclude, message}`; **client fail-opens after 5 s** (`index.js:556-561`). Feeds the unified loading gate.
- **Continuous callback**: per-GymScene `continuous_exclusion_callback` + interval; client emits `execute_continuous_callback {ping, is_tab_hidden, tab_hidden_duration_ms, frame_number, episode_number}`; server replies `continuous_callback_result {exclude, warn, message}` asynchronously. Can exclude mid-game or warn.
- `client_callback` is a generic per-scene hook (`Scene.on_client_callback`, base = `pass`).

### 1.6 Unity scene integration basics

- `UnityScene`: WebGL build config, `num_episodes`, server-side `score_fn`, `preload_game` pushed via `on_connect` at stager start.
- `unityEpisodeEnd` → server increments `episodes_completed` **on the per-participant scene instance**, emits `unity_episode_end` + `update_unity_score`. Per-episode data saved through the static path with `scene_id = f"{scene_id}_{ep}"` and **an empty mugGlobals dict** (explicit TODO). Client advances after the final episode's countdown (no double-fire guard).

## 2. Failure semantics

- **Refresh mid-scene**: disconnect saves `{current_scene_index}` + globals. Reload rebuilds a **fresh** stager and restores only the index, so: (a) `RandomizeOrder`/`keep_n` **re-rolls — a resumed participant can land on a different scene at the same index**; (b) per-instance scene state (Unity `episodes_completed`, cumulative score) resets; (c) unsubmitted DOM input is lost. Stager state is saved only on advance/disconnect; a server crash loses everything.
- **Duplicate registration**: two-layered and leaky. `register_subject` rejects a second socket while connected — but the **HTTP route runs first**: if the participant has not yet advanced (`stager_state is None`), `user_index` takes the "new participant" branch and **overwrites both the stager and the session** — the second tab hijacks/resets the first tab's server state. After the first advance the check holds.
- **Advancement races**: server accepts any number of `advance_scene` events — double emission skips a scene. Client-side mitigations only (button disable, countdown `_started` guard; Unity has no guard). Advancing past the last scene repeatedly grows the index; a session saved in that state breaks restore.
- **Server restart**: new `SERVER_SESSION_ID`; the client-held token is never validated — stale clients restart as fresh participants at index 0.
- **Pyodide loading grace**: disconnects during WASM compile exempted from cleanup.

## 3. Contract mapping (0.2)

### 3.1 Flow / progression → API-04

| Legacy mechanism | 0.2 contract | Verdict |
|---|---|---|
| Stager scene list, `current_scene_index` | `VisitPlan` of `PlannedActivity{ordinal, status}` | **PARITY** (richer: per-activity status vs a single index) |
| `RandomizeOrder`/`RepeatScene`, unseeded global `random`, re-rolled on restore | `RandomizationOutcome` recorded once; recovery "loads the plan and never re-samples" (D05-1) | **IMPROVE** — directly fixes the resume-reshuffle defect |
| Client-side condition assignment in custom HTML (`generateRandomPair`) | Declarative `Treatment`/`Assign`, assignment vs exposure records, durable balance | **IMPROVE** + **migration GAP**: study authors currently randomize in JS; nothing in the bridge accepts client-asserted conditions (R-13 explicitly distrusts them) |
| `advance_scene` unvalidated, non-idempotent | API-09 idempotent commands + bridge `advance` op; **activity-advancement/completion state machines are explicitly listed as remaining API-04 work** | **GAP** (state machine undesigned) + **IMPROVE** (idempotency) |
| Stager state saved only on advance/disconnect, in-memory | Plan materialized & committed before participation | **IMPROVE** |
| `ParticipantSession.mug_globals` blob | Namespaced, optimistically versioned `StateDocument` per visit | **PARITY-with-IMPROVE** (versioning replaces last-write-wins) |

### 3.2 Identity / registration → API-03

| Legacy | 0.2 | Verdict |
|---|---|---|
| subject_id = guessable URL path; identity echoed by client everywhere; client-provided fallback on episode data | Opaque signed `LaunchTicket`; server derives identity from launch state, never client fields | **IMPROVE**. GAP to preserve: researcher-chosen subject IDs embedded in recruitment URLs and `EndScene.append_subject_id` completion-redirect — 0.2 must express "append pseudonymous ID to completion redirect" |
| Duplicate-tab rejection + pre-advance hijack hole | Stable return link resumes the same `Enrollment` | **PARITY intent**; two-live-tabs concurrency semantics not yet specified — **GAP** |
| `PROCESSED_SUBJECT_NAMES` completion block (partial, memory-only) | Enrollment/flow status | **GAP** (legacy behavior itself inconsistent; needs a deliberate rule) |

### 3.3 mugGlobals → API-09 R-13 bridge — per-use-pattern inventory

| # | Legacy use pattern | Bridge coverage | Verdict |
|---|---|---|---|
| 1 | Identity: `subjectName` seeded/read everywhere | Bridge **rejects** identity keys (reserved-key semantic rule) | **IMPROVE** — pages need a read-only pseudonymous handle if any legacy page requires one |
| 2 | Participant responses stored in globals, dumped to `_globals.json` | `mug.response.set` with durable receipts; auto-collected named controls (API-17) | **PARITY + IMPROVE** (legacy loses data if the tab dies pre-terminate) |
| 3 | Cross-scene state handoff (write in scene A, read in scene B) | `mug.state.set/get` on the visit's client-writable StateDocument namespace | **PARITY** |
| 4 | Env parametrization: Pyodide preamble feeding init code | **No bridge op reaches env init.** Per-occurrence parameters come from `PlannedActivity` parameters / inline treatment placement (R-15) | **GAP** — the rewrite needs a defined path from recorded state/assignments into env construction; the bridge alone does not cover this (and per R-13 must not, for condition values) |
| 5 | Advance gating via custom JS on `#advanceButton` | `ContentSpec.response_required` + receipt gating + bridge `advance` | **PARITY** for "response required"; **GAP** for **arbitrary** JS gating conditions (all-scales-touched, timed reveals) — no documented "set advance-enabled/blocked" affordance |
| 6 | Gating the **startButton/game join** (incl. the interval hack fighting the platform) | No bridge op for interaction-activity readiness | **GAP** — a real pattern the typed bridge does not yet name |
| 7 | Platform counters (`gymSceneCounter`, `unityEpisodeCounter`, `unityScore`) in the same mutable namespace as author data | Occurrence ordinals/status live in the VisitPlan; score is interaction telemetry | **IMPROVE** — must not be reintroduced as shared globals; verify nothing downstream reads them from exports |
| 8 | Whole-object sync, client-wins normally / server-wins on restore | Per-key `state.set` with optimistic `version` | **IMPROVE** — removes silent clobbering |
| 9 | Globals snapshot beside every CSV | Versioned StateDocument + evidence | **PARITY** (analysts keep per-scene state snapshots) — confirm export shape covers it |
| 10 | `sceneData.globals` merge into activation payload | `state.get` pull model | **PARITY** |
| 11 | Unity per-episode emission with empty globals | n/a (bug/TODO) | **IMPROVE by construction** |

### 3.4 Content & data emission → API-17

- Static `scene_body` HTML (literal or filepath, read at config time, shipped in metadata on every activation) → `Content` file/inline bodies pinned to the study version. **PARITY** with **IMPROVE**: a redeploy can't change consented text.
- Built-in form scenes → typed `Field` closed set. **PARITY** for types; **GAP**: legacy `MultipleChoice` multi-select encodes selections as a stringified index list in a hidden input — export-compat mapping needed.
- `element_ids` DOM scraping on terminate → auto-collected named controls + `response.set` with durable receipt **before** advancing. **IMPROVE** (legacy can advance before/without the emission ack; emission and advance are separate unordered events).
- `CompletionCodeScene` server-generated UUID → no direct 0.2 analog named; **GAP** to place (likely content + evidence receipt).

### 3.5 Callbacks / screening

Entry screening (client-side checks + server callback, fail-open timeout) and continuous callbacks have no dedicated Phase 0 contract home; they intersect API-09 (handshake capabilities) and API-04 (flow-based eligibility per ADR-0014). **GAP**: fail-open-vs-fail-closed policy, callback context schema, and mid-interaction exclusion flow need contract homes.

## 4. Intricacies register

1. **Resume re-randomization defect**: current behavior is *wrong* but analysts' existing data embodies it; D05-1's fix is a behavior change to document, not preserve.
2. **`scene_metadata` is a full `vars()` dump** — custom scene subclass attributes flow to the client for free, and study code relies on arbitrary metadata keys (e.g., `in_game_scene_body`). A typed ContentSpec must give authors an equivalent escape hatch or enumerate every key in use.
3. **Advance triggers are heterogeneous**: button click, game-done watchdog (the MessageChannel throttled-tab force-advance is load-bearing for unattended completions), Unity countdown.
4. **`request_current_scene` is a repair idiom** — the activate/gate race it patches must be impossible or explicitly handled in the new client shell.
5. **Server-wins on restore vs client-wins on sync**: restoration deliberately discards fresher client values so the pre-refresh state wins. StateDocument versioning must preserve "recovery restores committed state" semantics.
6. **Globals sync only at scene termination** — per-op bridge writes will produce much finer-grained state histories; don't mis-model legacy data.
7. **`sync_globals` before `static_scene_data_emission` ordering** relies on socket.io per-connection ordering; the CSV+globals pair is assumed atomic per scene.
8. **Custom HTML fights the shell** (interval hack re-disabling the start button) — the bridge must give pages an authoritative gate, or authors will recreate the hack.
9. **Per-scene `GameManager` instances are shared across participants and created lazily on first advance into the scene** — waitroom scoping is per scene_id.
10. **`stager.on_connect` runs for all scenes at start/resume** — Unity preload fires at experiment start.
11. **Empty mugGlobals in Unity per-episode saves** and per-episode pseudo-scene IDs (`{scene_id}_{ep}`) shape existing data directories.
12. **Element scraping type coercions**: checkbox→bool, radio→checked value, range→float, select→array, button→textContent, missing→null-with-warning. Export parity requires matching coercions.
13. **`EndScene` reached ≠ completed**: completion blocking and admin "session completion" fire in two different places — two different notions of "done".
14. **Duplicate-tab pre-advance hijack** — the 0.2 fix must decide which tab wins (legacy silently prefers the newest).
15. **Client-supplied `session_id` is vestigial** — do not port; the 0.2 handshake replaces it.
16. **Pyodide loading grace** — the new lifecycle needs an equivalent "client busy, not gone" state.
17. **`advance_scene` with missing subject raises** into the socket handler — define explicit error semantics.
18. **Overrun advance past EndScene** can persist an out-of-range index that breaks restore.
