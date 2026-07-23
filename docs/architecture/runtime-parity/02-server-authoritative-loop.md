# Dimension 2 — Server-Authoritative Game Execution

| Field | Value |
| --- | --- |
| Audit date | 2026-07-19 |
| Sources | `mug/server/game_manager.py`, `mug/server/remote_game.py`, `mug/server/app.py` handlers, `mug/server/participant_state.py`, `mug/server/thread_safe_collections.py`, `mug/rendering/{surface,types}.py`, client `mug/server/static/js/{index.js, phaser_gym_graphics.js, ui_utils.js}` |
| Contracts mapped | API-06, API-07, API-09, API-12 (all rev 0.2) |

## 1. Mechanism map

### 1.1 Game creation, seat assignment, start

- **Join entry point**: `join_game` handler at `app.py:627-770`. Serialized per-subject via `with SUBJECTS[subject_id]:` (app.py:644). Checks `ParticipantStateTracker.can_join_waitroom` (app.py:680-696; tracker in `participant_state.py:48-133` with IDLE/IN_WAITROOM/IN_GAME/GAME_ENDED transitions at participant_state.py:34-45), runs stale-state validation `validate_subject_state` (game_manager.py:132-179), cleans stale entries with `remove_subject_quietly` (app.py:726-742), then calls `GameManager.add_subject_to_game` (app.py:750).
- **Matchmaking**: `add_subject_to_game` → `_add_to_fifo_queue` (game_manager.py:274-298, 411-480) under `waiting_games_lock`. No match → `_add_to_waitroom` (game_manager.py:482-534), which emits `waiting_room` to the joiner's socket. Optional P2P RTT probe path defers game creation.
- **Game object creation**: `_create_game` (game_manager.py:181-243) builds a `ServerGame(scene, game_id=uuid4)`. `ServerGame.__init__` (remote_game.py:167-227) seeds human slots from `scene.policy_mapping` (Human → `AvailableSlot` sentinel, bots recorded separately, remote_game.py:193-198) and holds `status` (`GameStatus` Inactive/Active/Reset/Done, remote_game.py:32-37) plus `SessionState` (WAITING→MATCHED→VALIDATING→PLAYING→ENDED with a validated transition table, remote_game.py:19-29, 234-262).
- **Seat assignment — two inconsistent paths**: match path assigns slots in order `available_slots[i]` (game_manager.py:986-999, 1023); probe/group path picks `random.choice(available_human_agent_ids)` (game_manager.py:326). `human_players` maps env agent_id → subject_id (remote_game.py:317-337).
- **Start**: `_start_game_with_countdown` (game_manager.py:1245-1265) — 3 s `match_found_countdown` broadcast for multiplayer — then `start_game` (game_manager.py:1267-1362): player-count safety validation, participant transitions to IN_GAME, **server-auth env pre-build to harvest asset specs** — `game._build_env()` then `scene.assets_to_preload = game.env.surface.get_asset_specs()` (1312-1317; this mutates the *shared scene object*), broadcast of `start_game` `{scene_metadata, game_id}`, optional per-subject `update_game_page_text` from `scene.game_page_html_fn(game, subject_id)` (1332-1350), transition to PLAYING and `socketio.start_background_task(self.run_server_game, game)`.
- **Client side of start** (index.js:846-916): sets `window.currentGameId`, `window.serverAuthoritative`, `window.serverAuthInputDelay = scene_metadata.input_delay || 0`, builds Phaser at `scene_metadata.fps` with `forceSetTimeOut`, enables the key listener with `scene_metadata.input_mode`.

### 1.2 Tick/step loop

- **Driver**: a single eventlet background task per game, `run_server_game` → `_run_server_game_inner` (game_manager.py:1364-1496). The **server drives ticks**; the client is a pure render sink.
- **Cadence**: `step_interval = 1.0 / scene.fps`; loop body is `lock → callbacks → game.step() → render broadcast → eventlet.sleep(step_interval)` (game_manager.py:1421-1442). Sleep is *after* step+render with no fixed-timestep accumulator, so actual tick rate is slightly below `fps` and drifts with env/render cost.
- **Action collection — two ingestion paths**:
  - `player_action` handler (app.py:1721-1764): server-auth path. Client sends **raw key name**; server maps `scene.action_mapping[key]` and calls `game.enqueue_action(agent_id, action)`. Agent id found by reverse lookup of `human_players`. The handler scans **all** GAME_MANAGERS by subject and never validates the client-sent `game_id` beyond non-null (app.py:1733-1740).
  - `send_pressed_keys` handler (app.py:842-872) → `process_pressed_keys` (game_manager.py:1525-1570): empty key list enqueues `scene.default_action`; multi-key lists reduced to one key or a composite tuple (`generate_composite_action`, game_manager.py:1572-1600); first mapped key wins. This is the legacy polling model — **no server-side code ever emits `request_pressed_keys`** (verified by grep), so in server-auth mode this path is vestigial except single-keystroke double-sends.
- **Pending-action model**: `pending_actions` is a plain dict, last-write-wins per agent (`enqueue_action` remote_game.py:525-527), consumed and **cleared every step** (remote_game.py:462, 500). Missing human action falls back per `action_population_method`: `PreviousSubmittedAction` → `prev_actions.get(agent_id, default_action)`, else `default_action` (remote_game.py:460-475).
- **Pressed-keys vs discrete on the client** (ui_utils.js:32-79): `single_keystroke` keydown emits both `send_pressed_keys` and (server-auth) `player_action`. `pressed_keys` mode is **edge-triggered in server-auth**: `player_action` fires once per keydown (repeat suppressed); **keyup only mutates local state — the server is never told about key release** (ui_utils.js:70-78).
- **Input delay**: client-side queue in `ui_utils.js:25-30, 94-137`. Queued with `emitAtFrame = frameCounter + delay` and drained once per **client render frame** from `processRendering`. Delay is measured in client render frames, not server ticks.
- **Bot/automated seats**: policies loaded server-side in `_load_policies` (remote_game.py:352-386). `_get_bot_action` (remote_game.py:395-427): heuristics call `compute_action(self.env, agent_id)` **with the live env object**; Random samples the action space; ONNX-style policies go through `scene.policy_inference_fn(agent_id, policy, self.observation)`; fallback is `scene.default_action`. Bots are queried **synchronously inside `step()` on every tick** (remote_game.py:477) — `scene.frame_skip` is **ignored** by the server loop.

### 1.3 Observation/render delivery

- **Server render**: `render_server_game` (game_manager.py:1602-1631). The env is built with `env_config["render_mode"] = "mug"` (remote_game.py:339-350), so `env.render()` returns the wire dict from `Surface.commit().to_dict()` = `{"game_state_objects": [...], "removed": [...]}` (`mug/rendering/types.py:55-60`).
- **Event + payload**: single **broadcast** to the socket room: `emit("server_render_state", {render_state, step, episode, rewards, cumulative_rewards, hud_text}, room=game_id)` (game_manager.py:1620-1631). Plain JSON over Socket.IO — no msgpack, no digest, no per-seat variant. Raw env observations are never sent to clients; only draw commands are.
- **Surface delta compression** (`mug/rendering/surface.py`): persistent objects (require explicit `id`, surface.py:93-94) retransmit only when their wire dict changes (`commit()` surface.py:359-393); ephemeral objects are sent every commit; `remove(id)` produces the `removed` list; `reset()` clears the delta cache to force full retransmit. Wire conversion `_to_wire` (surface.py:114-178): pixel→relative 0–1 coordinates unless `relative=True` (radius normalized by `max(w,h)`), sprite `w/h` aliased to `width/height`, output keys `uuid`, `object_type`, `depth`, `tween` (bool = tween_duration present), `tween_duration`, `permanent`.
- **Client consumption**: `server_render_state` handler buffers the packet; in server-auth mode `processRendering` consumes **exactly one buffered state per Phaser frame** (phaser_gym_graphics.js:773-780) — no catch-up draining (unlike the P2P drain-up-to-5) — so if the server outpaces the client, buffer and latency grow without bound until a reset flush.
- **Draw**: `drawState` (phaser_gym_graphics.js:817-908): explicit removals destroy persistent objects; non-`permanent` objects absent from the current frame are destroyed; add/update by `uuid`. Object vocabulary handled by JS: `sprite, animation(no-op), line, circle, rect/rectangle, polygon, text` — **`arc` and `ellipse`, which the Python Surface can emit (surface.py:313-357), are unhandled**. Position updates use `_applyPositionTween` (1315-1345): same-target tween allowed to finish, changed-target tween restarted from interpolated position, snap suppressed while tweening. An image-frame fallback renders `game_image_binary` as a JPEG blob texture.
- **HUD**: single string from `scene.hud_text_fn(game)` computed once per frame and **broadcast identically to all players**. Per-player HTML exists only at start via `game_page_html_fn`.

### 1.4 Episode boundaries, reset flow, multi-episode sequencing

- `ServerGame.step` aggregates `terminated`/`truncated` with `all(...)` for dict returns (remote_game.py:503-511), enforces `scene.max_steps` truncation, then sets `status = Reset` if `episode_num < scene.num_episodes` else `Done` (517-521). `reset()` increments `episode_num` (first episode = 1), zeroes `episode_rewards`, `tick_num`, `prev_actions`, `pending_actions`.
- **Reset flow** (game_manager.py:1445-1477): `on_episode_end` callback → `eventlet.sleep(scene.reset_freeze_s)` → broadcast `game_reset {timeout, config}` → **block on `game.reset_event.wait()`** (1463) until every player acks with `reset_complete`. Client keeps the Phaser instance alive (P2P destroys/recreates it). Per-subject `eventlet.event.Event`s are re-armed for the next episode.
- **End**: loop exits on Done/Inactive → `tear_down()` (env.close), `on_game_end` callback, broadcast `end_game {}`, `cleanup_game`.

## 2. Failure semantics

- **Disconnect routing**: socket `disconnect` handler (app.py:2652-2880). Engine-level detection is slow by config: `ping_interval=8, ping_timeout=30`, i.e. up to ~38 s before `disconnect` fires for a silent drop.
- **Server-auth disconnect branch** (`leave_game`, game_manager.py:1112-1128): the player is **not removed**. `document_focus_status[subject] = False`, an `eventlet.spawn_after(reconnection_timeout_ms/1000, _permanent_drop)` timer starts (default 5000 ms), and the loop keeps stepping their seat with fallback actions. Contrast: P2P-mode active games broadcast `end_game` and tear down.
- **Permanent drop** (`_permanent_drop`, game_manager.py:1768-1791): removes `subject_games`/`subject_rooms` (blocking future rejoin) but **leaves the seat in `human_players`** — the game continues on default actions forever. `reset_events[game_id][subject]` is *not* cleaned, and `game.reset_event.wait()` has **no timeout** (game_manager.py:1463), so a multi-episode game whose player was dropped mid-episode **stalls permanently at the next episode boundary**.
- **Rejoin flow**: on socket reconnect, the client emits `rejoin_server_auth` if `window.serverAuthoritative && window.currentGameId` (both in-memory, so a **page refresh cannot rejoin**). `rejoin_server_auth_game` (game_manager.py:1793-1830) requires status Active/Reset, cancels the drop timer, rejoins the room, replies `rejoin_success {game_id, scene_metadata}`. What does **not** restore: no keyframe/state snapshot (Surface's delta cache is per-game, so persistent objects committed pre-disconnect are never retransmitted — tolerable only because the client's Phaser objectMap survived), no `input_delay` re-arm, no missed `game_reset`/`end_game` replay.
- **Loop crash**: `run_server_game` catches everything, broadcasts `end_game {error, traceback}` to the room (full traceback disclosed to participants) and `cleanup_game`.
- **Teardown**: `cleanup_game` (game_manager.py:1633-1686) is idempotent: SessionState→ENDED, participants→GAME_ENDED, pairing-group recording, `game.tear_down()`, `_remove_game`.
- **Orphan handling**: no periodic sweeper; orphans healed lazily on next join. A server-auth game whose every player permanently dropped keeps stepping until `num_episodes` completes.

## 3. Concurrency

- **Model**: eventlet green threads over Flask-SocketIO. No `monkey_patch()` call and no explicit `async_mode` — auto-selected (eventlet). Single process; all state in-process dicts.
- **Locks**: per-game `threading.Lock` `game.lock` held around reset/step and leave/remove; `waiting_games_lock` serializes matchmaking; `ThreadSafeDict`/`ThreadSafeSet` wrap individual ops (iteration and check-then-act are *not* atomic); per-subject `SUBJECTS[subject_id]` locks in join/leave handlers.
- **Action-ingestion vs stepping race**: `enqueue_action` writes `pending_actions` **without taking `game.lock`**, while `step()` reads it at the top and clears it at the bottom of the locked section. Safe only under the cooperative-scheduling assumption; if the env yields (IO/sleep) mid-step, an action enqueued mid-step is silently destroyed by the clear.
- **Reset synchronization**: barrier of per-subject events + one game-level event; no timeout, no handling for membership changes between arm and wait.

## 4. Contract mapping (0.2)

### api-07

| Contract element | Legacy mechanism | Verdict |
| --- | --- | --- |
| `ExecutionMode.SERVER` (typed) | Boolean `scene.server_authoritative` + scattered getattr checks | **GAP** — untyped flag, no `snapshot_contract`/`writer` record |
| `EnvFactory` | `scene.env_creator(**env_config)` with injected `render_mode="mug"` | **PARITY on "factory, never instance"**; **GAP** on compile-time recording (no qualified name, no args record, no importability check) |
| `RenderPacket` per-seat with `seat_key`/`frame_number`/`render_digest`/`keyframe` | `Surface.commit()` dict **broadcast to the whole room** | **GAP** — no per-seat derivation (D09-4 unimplementable today), no frame_number inside the packet, no `keyframe` (root cause of the rejoin-resync hole), no digest. Delta compression + `removed` semantics are **PARITY** |
| `SurfaceCommand` vocabulary | Python emits `rect/circle/line/polygon/text/sprite/arc/ellipse`; wire uses `uuid`/`permanent`/`tween`; JS renders only 6 of 8 ops | **PARITY** on core ops and tween/persistence semantics; **GAP**: naming drift (`sprite`→`image`, `uuid`→`id`, `permanent`→`persistent`), `arc`/`ellipse` dead-end, no typed-param enforcement or `extras=` channel, `_updateLine` is a stub |
| `GameTransition` (normalized per-frame evidence) | Nothing — server loop records no per-step evidence; capture is left to `scene.callback` hooks | **GAP** — entire normalized-transition contract is new work for SERVER mode |
| `EpisodeBoundary` | `GameStatus.Reset/Done` + ephemeral broadcasts | **GAP** — no episode_id, no state_hash, boundary is not a record |
| Declared hooks | Absent; per-seat observation shaping does not exist in the server path | **GAP** |
| "One writer per env instance" | Single green-thread loop owns env under `game.lock` | **PARITY** |

### api-09

| Contract element | Legacy mechanism | Verdict |
| --- | --- | --- |
| `InputMode.PRESSED_KEYS` (held keys drive every frame) | Server-auth is **edge-triggered**: one `player_action` per keydown, keyup never reaches the server | **GAP** — with `PreviousSubmittedAction` a released key repeats forever; with `DefaultAction` a held key fires once |
| `InputMode.SINGLE_KEYSTROKE` | keydown → `player_action`, mapped server-side, one action per press | **PARITY** |
| Bindings map to env action space; typed `on_no_input` | `scene.action_mapping[key] → raw env action`; `default_action` + `action_population_method` | **PARITY** in effect; **IMPROVE** — untyped dict; composite-key tuples have no contract counterpart, and server/client composite algorithms differ |
| `input_delay` | Client-side queue in render frames | **PARITY** concept; **GAP** — unit is client render frames not ticks, not restored on rejoin |
| `SeatDelivery` (per-seat, broadcast rejected) | Room broadcast of one packet | **GAP** — delivery model is the opposite of the contract |
| Input routed only to bound seat | Reverse lookup before enqueue | **PARITY** in effect; client-supplied `game_id` unauthenticated |

### api-06

| Contract element | Legacy mechanism | Verdict |
| --- | --- | --- |
| `Interaction` lifecycle | `ServerGame` + `SessionState` machine + `ParticipantStateTracker` | **PARITY** in spirit; **GAP** — no interaction record, no multi-channel |
| `ConnectionLease` | `spawn_after` drop timers + `is_connected` flags, in-memory only | **GAP** — lease behavior implicit; restart loses everything |
| Matchmaking | FIFO default; two-stage RTT probe with failed-pair memory | **PARITY** |
| Total cast | `start_game` refuses to start with unfilled seats | **PARITY** (runtime check, not typed record) |

### api-12

| Contract element | Legacy mechanism | Verdict |
| --- | --- | --- |
| Non-blocking scheduler | Bot inference **synchronous inside the tick** — a slow policy stalls every player's frame | **GAP** |
| Mandatory typed fallback | `default_action` fallback in `_get_bot_action`; `previous_submitted_action` for humans only | **PARITY** for `default-action`; **GAP** — untyped, not mandatory, `repeat-last` unavailable for bots |
| `decides_every` on the policy | `scene.frame_skip` scene-global, honored by the browser bot path, **ignored by the server loop** | **GAP** — cadence misplaced and inconsistently enforced across modes |

## 5. Intricacies register

1. **Edge-triggered pressed-keys in server-auth**: key release invisible to the server; a parity plan must define held-key streaming per api-09 rather than replicate this.
2. **Last-write-wins, cleared-per-tick action slot**: at most one human action consumed per tick; two keypresses inside one tick interval collapse to the latest; an action landing during an env-internal yield is destroyed by the clear.
3. **Client-frame-denominated input delay**: drains in `processRendering`, so delay scales with the client's achieved fps; not re-armed after rejoin.
4. **Exactly-one-state-per-frame server-auth rendering with no catch-up**: server-faster-than-client accumulates unbounded buffer/latency; only `game_reset` and end/rejoin-fail flush it.
5. **Delta compression without keyframes**: persistent objects transmit once per game, not per client — late joiners/rejoiners depend on the client-side Phaser objectMap surviving; page refresh = permanent state loss + no rejoin. The contract's `keyframe` flag exists precisely to fix this.
6. **Ephemeral-object lifecycle**: non-`permanent` objects auto-destroyed when absent from the incoming frame; `permanent` objects require the explicit `removed` list. `Surface.reset()` is the manual "keyframe" used at episode starts.
7. **Tween continuity rules**: same-target tweens not restarted; changed-target tweens restart from interpolated position; positional snap suppressed while tweening. Sprites floor pixel positions while circles/polygons don't.
8. **Wire-format aliases**: `sprite` (not `image`), `uuid` (not `id`), `permanent` (not `persistent`), sprite `w/h → width/height`, `tween` bool derived from `tween_duration != None`. Coordinates normalized 0–1 server-side, radius by `max(w,h)`.
9. **`arc`/`ellipse` emit but never render**; `_updateLine` is a no-op.
10. **Reset barrier can deadlock**: `game.reset_event.wait()` has no timeout and `_permanent_drop` doesn't clean `reset_events` — a dropped player stalls every multi-episode server-auth game at the next boundary. Fix, don't preserve.
11. **Server-auth disconnect keeps the seat alive on fallback actions** — the game never pauses; after `_permanent_drop` the seat plays `default_action` to the end.
12. **Bot cadence and privilege**: bots act every server tick (`frame_skip` ignored); heuristic policies receive the *live env object* (full-state access).
13. **Env pre-build mutates shared scene state**: `scene.assets_to_preload = env.surface.get_asset_specs()` writes to the scene object shared by all concurrent games. Fix, don't preserve.
14. **Envelope metadata**: `step`, `episode`, per-agent `rewards` and `cumulative_rewards` ride every render packet — HUDs and analytics depend on this cadence.
15. **max_steps truncation server-side mirrors the client-side check**; `episode_num` is 1-based after first reset and drives Reset-vs-Done.
16. **Empty `pressed_keys` list actively enqueues default_action** — in the polling model, "no keys" overwrites a previously queued action.
17. **Trust boundaries as-built**: `player_action.game_id` unvalidated; crash tracebacks broadcast to participants; identity from the socket→subject mapping.
18. **Disconnect detection latency**: ping 8 s/timeout 30 s means the 5 s `reconnection_timeout_ms` starts only after up-to-38 s of engine-level grace.
19. **Seat-assignment nondeterminism**: `random.choice` in one path vs ordered in the other — matters for condition-balancing and replays.
20. **`GameStatus` vs `SessionState` are orthogonal state machines**; cleanup keys off both.
