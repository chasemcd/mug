# Dimension 1 — P2P Transport & Authority

| Field | Value |
| --- | --- |
| Audit date | 2026-07-19 |
| Sources | `mug/server/static/js/webrtc_manager.js` (1032 lines), `mug/server/static/js/pyodide_multiplayer_game.js` (8062 lines), `mug/server/pyodide_game_coordinator.py` (881 lines), `mug/utils/webrtc.py`, `mug/server/app.py` P2P/pyodide handlers |
| Contracts mapped | API-06, API-07, API-09, API-10, API-16 (all rev 0.2) |

## 1. Mechanism map

### 1.1 Signaling flow (server-relayed, SocketIO)

- Single socket event `webrtc_signal` for offer/answer/ICE. Client → server: `{game_id, target_player_id, type, payload}` (`webrtc_manager.js:814-821`); server handler `app.py:1631-1655` delegates to `PyodideGameCoordinator.handle_webrtc_signal` (`pyodide_game_coordinator.py:499-570`), which does a reverse socket→player lookup for the sender and relays `{type, from_player_id, game_id, payload}` to the target's socket room, *without inspecting the SDP/ICE payload*. Target-player lookup tolerates str/int ID mismatch via ad-hoc conversion (`pyodide_game_coordinator.py:530-540`).
- Client receive path: `WebRTCManager._handleSignal` (`webrtc_manager.js:687-722`) filters on `game_id` and self-echo, then dispatches offer/answer/ice-candidate.
- **Role assignment is deterministic**: lower player ID is the initiator/offerer (`webrtc_manager.js:226-255`, comparison handles numeric and string IDs at `265-275`). Same rule is reused for ICE-restart offers (`webrtc_manager.js:529`).
- ICE candidates arriving before the remote description are **buffered** and flushed after `setRemoteDescription` (`webrtc_manager.js:774-806`); a null candidate is treated as end-of-candidates (`775-778`).
- ICE servers: two Google STUN servers always; four metered.ca TURN URLs (UDP/TCP 80, UDP 443, TURNS 443) added only if TURN credentials exist (`webrtc_manager.js:384-418`). Credentials flow: env vars/`configure_webrtc()` → `ExperimentConfig` (`mug/utils/webrtc.py:9-51`) → `PyodideGameState.turn_username/credential/force_turn_relay` (`pyodide_game_coordinator.py:52-54,146-148`) → sent to clients inside `pyodide_game_ready.turn_config` **only when username present** (`pyodide_game_coordinator.py:252-256`) → `WebRTCManager` options (`pyodide_multiplayer_game.js:5484-5492`). `forceRelay` sets `iceTransportPolicy:'relay'` (`webrtc_manager.js:287-290`). Note: TURN credentials are sent to the browser in cleartext payload.
- A **separate probe signaling namespace** exists for latency matchmaking: `probe_ready`/`probe_signal`/`probe_result` (`app.py:1663-1718`), deliberately distinct event names to avoid collision with game signaling.

### 1.2 Game setup / seed / peer identity

- Server-side game creation: `GameManager` calls `PYODIDE_COORDINATOR.create_game()` (`game_manager.py:223`) which draws a **server-generated 32-bit RNG seed** per game (`pyodide_game_coordinator.py:134`).
- `add_player` emits `pyodide_player_assigned` to that socket with `{player_id, game_id, game_seed, num_players}` (`pyodide_game_coordinator.py:195-218`); client stores it and seeds a JS-side multiplayer RNG (`pyodide_multiplayer_game.js:1250-1260`).
- When all expected players joined, coordinator marks the game active, transitions the ServerGame to `PLAYING`, and emits `pyodide_game_ready` to the room with `{players, player_subjects, turn_config, scene_metadata}` (`pyodide_game_coordinator.py:223-268`).
- Client builds a **deterministic playerID↔index mapping by sorting player IDs** (used by the binary protocol's uint16 player field) (`pyodide_multiplayer_game.js:1270-1277`), stores subject mapping, configures monitors/timeouts from `scene_metadata` (`1288-1325`), and initiates P2P **only for exactly 2 human players** (`1334-1368`); more than 2 players falls back to SocketIO relay only.
- Python-side determinism: `initialize()` validates the env exposes `get_state`/`set_state` (`validateStateSync`, `1634-1683`; absence disables all hashing/rollback/resync), and seeds `np.random` + `random` with the game seed (`1685-1700`); every `reset()` re-seeds both and resets the JS RNG (`1754-1758`), and calls `env.reset(seed=...)` (`1763`).

### 1.3 Data channel configuration

- One DataChannel named `'game'`, created by the initiator with `ordered: false, maxRetransmits: 0` — unreliable, unordered, UDP-like; "GGPO handles loss" (`webrtc_manager.js:237-241`). `binaryType='arraybuffer'` (`652-653`).
- Loss is compensated by **input redundancy**: each input packet carries the last N inputs (redundancy 3 by default in `P2PInputSender`, `pyodide_multiplayer_game.js:839-851`, but instantiated with **10** at `5508-5513`); duplicates are dropped on receipt (`storeRemoteInput` duplicate check, `4110-4114`).
- Send-side congestion guard: skip P2P send if `dataChannel.bufferedAmount > 16384` bytes and fall back to SocketIO for that input (`833-891`, `2042-2056`).

### 1.4 Authority model: no host — symmetric deterministic replicas (GGPO)

- Explicitly "Symmetric P2P architecture (no host)" (`pyodide_multiplayer_game.js:8`), "All players are symmetric peers — no host/client distinction" (`pyodide_game_coordinator.py:172`). **Both peers step their own Pyodide env every frame**; there is no authoritative env anywhere for P2P play. The server coordinator never steps an env; it holds only metadata (seed, membership, a frame counter field that in practice never advances).
- The only asymmetric tie-breakers:
  - WebRTC initiator = lower player ID (`webrtc_manager.js:231`).
  - Desync resync direction: **lower player ID defers to higher** — lower requests state from higher (`_shouldRequestStateResync`, `pyodide_multiplayer_game.js:4049-4055`, and `app.py:2507-2515` comment). (This flow is dormant; see 1.7.)
- Per-tick loop: a **Web Worker timer** (throttling-exempt) drives ticks at scene FPS (`GameTimerWorker`, `78-172`; `_initTimerWorker`/`_handleWorkerTick`, `5778-5890`). Each `step()` (`1974-2368`):
  1. drains queued network inputs synchronously (`_processQueuedInputs`, `7174-7199` — race-free w.r.t. rollback),
  2. stores the local action into the input buffer at `frame + INPUT_DELAY` (`storeLocalInput`, `4190-4212`; `INPUT_DELAY` default 0, configurable via `GymScene.input_delay`, `mug/scenes/gym_scene.py:154,822`),
  3. sends the input P2P-first with SocketIO fallback (`2037-2056`),
  4. executes any pending rollback *before* stepping (`2063-2073`),
  5. updates `confirmedFrame` and exchanges confirmed-state hashes (`2077-2080`),
  6. builds actions for **all** human seats from the GGPO buffer (true GGPO: local player also delayed) with prediction fill (`2084-2122`; prediction = `previous_submitted_action` or default action, `getPredictedAction` `4220-4230`),
  7. snapshots env+RNG state every `snapshot_interval` frames **before** stepping (`2150-2155`, `saveStateSnapshot` `4298-4375` captures `env.get_state()`, numpy MT19937 state, Python `random` state, JS `cumulative_rewards`, `step_num`),
  8. steps the env in Pyodide (`stepWithActions`, `2485-2580`), records frame data into a **speculative buffer** (`2221-2234`, gated on episode-end sync so both peers export identical frame counts), increments `frameNumber`, prunes buffers.

### 1.5 Per-tick action exchange protocol (encoding, sizes, cadence)

- **Primary transport**: custom hand-rolled **binary DataView protocol** over the DataChannel — *not* msgpack, *not* JSON. Message types (`pyodide_multiplayer_game.js:322-333`):

| Type | Byte | Size | Purpose |
|---|---|---|---|
| INPUT | 0x01 | 9 + 5·n bytes (n≤15) | player uint16, currentFrame uint32, n inputs of (frame uint32, action **uint8**) (`353-399`) |
| PING/PONG | 0x02/0x03 | 9 | RTT, float64 timestamp echo (`409-429`), 500 ms cadence (`7583-7601`) |
| KEEPALIVE | 0x04 | — | presence only (`7061-7063`) |
| EPISODE_END | 0x05 | 9 | frame + episode uint32 (`442-465`) |
| EPISODE_READY | 0x06 | 13 | episode uint32 + 8-char md5 state hash (`479-510`) |
| STATE_HASH | 0x07 | 13 | frame uint32 + 8 bytes (16 hex chars of truncated SHA-256) (`524-556`) |
| VALIDATION_PING/PONG | 0x10/0x11 | 9 | validation handshake (`566-587`) |
| INPUT_REQUEST/RESPONSE | 0x12/0x13 | 9 / 5+5·n | missing-input recovery for fast-forward (`601-676`) |
| FOCUS_STATE | 0x14 | 6 | focused bit + frame uint32 (`690-711`) |

  All multi-byte fields big-endian. Actions constrained to uint8 (0–255) on this wire.
- **Fallback transport**: SocketIO event `pyodide_player_action` `{game_id, player_id, action, frame_number, timestamp, sync_epoch}` (`_sendViaSocketIO`, `6994-7004`) → server `app.py:1795-1835` → coordinator `receive_action` (`pyodide_game_coordinator.py:274-346`) which **relays immediately to every other player** as `pyodide_other_player_action` (action-queue approach, no per-frame barrier, no timeout wait despite `action_timeout=5.0` existing at `:96`), while collecting inter-action-delay diagnostics (`306-325`, `_log_game_diagnostics` `455-497`). In fallback mode the action can be any JSON value (no uint8 constraint). Client queues received SocketIO inputs identically to P2P ones (`1372-1400`).
- Cadence: one input send per tick (per frame at scene FPS); each packet redundantly carries the last ≤10 inputs.
- **msgpack** is used only on the client→server evidence path, not P2P: episode data export `msgpack.encode(episodeData)` → `emit_episode_data` (`pyodide_multiplayer_game.js:3711`, also `index.js:1662`, `phaser_gym_graphics.js:237`) → `msgpack.unpackb` server-side (`app.py:1126,1185`).

### 1.6 Rollback, confirmation, hashing

- Late confirmed input differing from what was actually executed on a predicted frame ⇒ `pendingRollbackFrame` (min of pending) (`storeRemoteInput`, `4096-4184`); rollback executes at next frame start (`performRollback`, `4493-4819`): restore best snapshot ≤ target (`findBestSnapshot` `4380-4388`; `loadStateSnapshot` restores env + both RNG states + JS rewards/step_num with restore verification, `4394-4480`), then **replays all frames in a single Python batch** (no event-loop yields — the core race-prevention design, `4684-4755`), refreshing on-interval snapshots and re-accumulating rewards inside the batch, re-storing corrected frame data, re-marking still-missing frames as predicted (`4629-4635`). Post-rollback render is re-pulled with tween smoothing flags (`rollback_smoothing_duration` default 100 ms) (`2303-2358`). Guards: `rollbackInProgress` prevents nested rollbacks and input processing during replay (`4127-4130`, `7175-7178`); hashes/pending peer hashes/outbound hash queue invalidated from target frame (`4511-4529`).
- **Confirmed-frame machinery**: `confirmedFrame` = highest consecutive frame with all human inputs (`_updateConfirmedFrame`, `2748-2784`); confirmed frames get a hash **computed from the stored snapshot for that frame, not live state** (`_computeAndStoreConfirmedHash`, `2916-2963`) using SHA-256 truncated to 16 hex chars over `json.dumps(sort_keys, separators)` of the state with **floats normalized to 10 decimal places** (`_computeHashFromState`, `2972-3001`; same algorithm in `computeQuickStateHash`, `3174-3213`).
- Hash exchange is **asynchronous over the DataChannel** (`_exchangePendingHashes` drains a queue, re-queues on buffer-full, holds during rollback and while disconnected, `3031-3061`); peer hashes buffered until local catch-up (`_handleStateHash`, `3068-3084`); comparison on whichever side completes second (`_attemptHashComparison`, `3092-3115`). Match ⇒ `verifiedFrame` high-water mark (`3122-3128`). **Mismatch ⇒ log + record a `desyncEvent` (with optional full state dump) only — no automatic correction** (`_handleDesync`, `3137-3172`).
- Speculative vs canonical data: frame data lands in `speculativeFrameData` and is **promoted** to `frameDataBuffer` with `wasSpeculative: true` once ≤ `confirmedFrame` (`_promoteConfirmedFrames`, `2791-2808`); at episode end, an input-confirmation wait (`_waitForInputConfirmation`, default 500 ms, scene-configurable `input_confirmation_timeout_ms`, `2819-2865`) runs before forced boundary promotion capped at the synced termination frame (`_promoteRemainingAtBoundary`, `2877-2907`).
- **Episode boundary sync**: episode end broadcast + agreement, `syncedTerminationFrame = min(local, remote)` guarantees identical export row counts (`_broadcastEpisodeEnd` `7254-7295` with 2 s timeout fallback; `_updateSyncedTerminationFrame` `7376-7410`; `_checkEpisodeSyncAndReset` `7297-7337` — completes only after input confirmation, clears sync state *after* export). Episode start: after reset, an 8-char **md5** hash of initial state is exchanged via EPISODE_READY with 3×500 ms retries and echo-ack (`reset()` `1859-1881`, `_broadcastEpisodeReady` `7452-7502`, `_handleEpisodeReady` `7412-7450`); start-hash mismatch is **logged and ignored** ("continue anyway", `7524-7527`); 5 s start-sync timeout proceeds anyway (`waitForP2PEpisodeStart`, `7551-7581`).

### 1.7 Server-relayed state sync (dormant) and dead server code

- `p2p_state_sync` (hash broadcast via server), `p2p_state_request`, `p2p_state_response` relays exist (`app.py:2464-2578`) and client handlers exist (`pyodide_multiplayer_game.js:1404-1527`, `_applyP2PState` `4061-4088` sets env state, clears GGPO state), with the lower-defers-to-higher tie-breaker — but the only broadcaster, `broadcastSymmetricStateSync()` (`2641-2664`), has **zero call sites**; step() explicitly notes "State hash recording and P2P sync broadcasts disabled" (`2209-2212`). So the automatic resync path is dormant; the live verification layer is the DataChannel confirmed-hash exchange, which detects but does not repair.
- **Broken/dead server handlers**: `pyodide_state_hash` and `pyodide_send_full_state` (`app.py:2581-2649`) call `PYODIDE_COORDINATOR.receive_state_hash` / `.receive_full_state`, which **do not exist** on the coordinator — invoking these events would raise AttributeError. The client also emits `p2p_connection_type` (`5618-5623`) for which **no server handler exists** (silently dropped). Docstrings in `app.py:2657` ("If host disconnects, elect new host") and `pyodide_hud_update` "host broadcasts HUD" (`2439-2461`) are legacy of an abandoned host-based design.

### 1.8 Validation handshake

- Gate: game loop does not start until `p2pReadyGate` resolves; timeout 15 s (`1118-1129`).
- On DataChannel open, state machine `idle → connecting → validating → validated | failed` (`1131-1143`, `_startValidation` `5923-5946`): each peer sends VALIDATION_PING (after 100 ms settle), responds with PONG; validation complete when *ping sent + pong received + peer's ping seen* (bidirectional flow proven) (`_checkValidationComplete`, `6150-6157`).
- Success: emit `p2p_validation_success` (`6159-6180`); server records per-player (`record_validation_success`, `pyodide_game_coordinator.py:667-691`; a server-side 10 s validation timeout field exists but is never enforced) and when count ≥ expected emits `p2p_validation_complete` to the room (`app.py:2074-2096`), which resolves the ready gate on both clients (`1531-1534`). Status UI relayed via `p2p_validation_status` (`app.py:1920-1934`).
- Failure (client validation timeout 15 s, or ready-gate timeout without validated state, `1344-1360`, `_onValidationTimeout` `6182-6194`): emit `p2p_validation_failed` → server (`app.py:2099-2161`) notifies all sockets with **`p2p_validation_repool`**, removes the game from coordinator and GameManager **without** GAME_ENDED transition, and resets participants to IDLE so both players re-enter the waitroom for a new partner. If validation is disabled, timeout instead degrades to SocketIO-relay play (`1354-1358`).

## 2. Failure semantics

### 2.1 Disconnect detection (client)

- ICE `disconnected` ⇒ 500 ms grace (`disconnectGracePeriodMs`, `webrtc_manager.js:191`, `589-623`) then `onConnectionLost`; ICE `failed` ⇒ immediate `onConnectionLost` + ICE-restart attempt (`336-348`); unexpected DataChannel close while ICE connected ⇒ `onConnectionLost` (`664-675`). Parallel 5 s disconnect timeout triggers ICE restart (`563-571`). Max 3 ICE restarts (`186,515-519`); restart offer created only by the deterministic initiator (`528-537`). Recovery to connected/completed with prior restart attempts or disconnected flag ⇒ `onConnectionRestored` (`355-366`).
- SocketIO layer is deliberately slow to declare disconnect (ping 8 s / timeout 30 s ⇒ ~38 s) because "multiplayer games already have P2P disconnect detection at 500ms" (`app.py:186-199`).

### 2.2 Bilateral pause & reconnection

- Client `_onP2PConnectionLost` (skipped if scene exited/paused/done): records disconnection event, emits `p2p_connection_lost {game_id, player_id, frame_number}`, and pauses locally immediately (`6202-6232`).
- Server `handle_p2p_connection_lost` (`app.py:2167-2198`) → `coordinator.handle_connection_lost` (`pyodide_game_coordinator.py:731-778`): adds reporter to `reconnection_lost_players`; infers `disconnected_player_id` as **the other player** (2-player assumption, `756-762`); first report starts reconnection (`'pause'`) ⇒ server emits `p2p_pause {pause_frame, detecting_player}` to the whole room via SocketIO (works while P2P is down); later reports return `'already_pausing'`.
- Client `_handleServerPause` (`6272-6291`) pauses (`_pauseForReconnection`, `6238-6266`: sets `isPaused`, pauses ContinuousMonitor, shows overlay, attempts ICE restart) and starts the **client-side reconnection timeout** (default 30 000 ms, overridden by `scene_metadata.reconnection_timeout_ms`, `1294-1298`; the coordinator's own `reconnection_timeout_s: 5.0` field at `pyodide_game_coordinator.py:68` is *never used to enforce anything* — timeout authority is client-side). While paused, `step()` and worker ticks are no-ops (`2001-2004`, `5810-5813`).
- **Success**: DataChannel reopen or ICE recovery ⇒ `_onP2PReconnectionSuccess` (`6836-6869`) logs attempt {duration, outcome, attempts}, emits `p2p_reconnection_success`; server `handle_reconnection_success` (`pyodide_game_coordinator.py:780-828`) waits until `lost ⊆ recovered`, accumulates `total_pause_duration_ms`, resets reconnection state, returns `'resume'` ⇒ server emits `p2p_resume` to room ⇒ `_handleServerResume` (`6875-6905`) clears timeout **first**, unpauses, resumes monitoring. Game state (frames, inputs, env) is untouched across the pause — play resumes from the pause frame; no state re-sync is performed on resume.
- **Timeout**: client `_onReconnectionTimeout` (`6317-6344`) records outcome `'timeout'`, emits `p2p_reconnection_timeout`; server (`app.py:2222-2295`) fetches `disconnected_player_id`, reads `handle_reconnection_timeout` data `{total_pause_duration_ms, lost_players, recovered_players}` (`830-855`), archives a session snapshot + termination reason `partner_disconnected` to the admin aggregator, emits **`p2p_game_ended {reason:'reconnection_timeout', reconnection_data, disconnected_player_id}`** to the room, removes the game from coordinator and GameManager.
- Client `_handleReconnectionGameEnd` (`6355-6439`): sets `state="done"`, `partnerDisconnectedTerminal=true` (which makes `isDone()` return **false** so the scene never advances — the overlay is terminal, `3777-3788`), records `sessionPartialInfo {terminationReason:'partner_disconnected', terminationFrame, disconnectedPlayerId, reconnectionData}`, **exports metrics before showing the overlay** (`emitMultiplayerMetrics`), emits `participant_terminal_state` (server marks GAME_ENDED and subject processed, `app.py:2023-2071`), shows a full-page overlay with an optional client-generated UUID completion code emitted via `waitroom_timeout_completion` (`6448-6526`; note `this.socket` at `6462` is likely undefined — the class uses global `socket` elsewhere, so that emit silently no-ops). Special case `reason:'scene_completed'` just closes P2P gracefully (`6363-6371`).
- **Data preserved on timeout path**: full cumulative validation/metrics JSON (per player + server-side aggregation), reconnection event log, pause durations; **lost**: the tail of the in-progress episode's frame data is *not* exported as episode CSV (`_emitEpisodeDataFromBuffer` only runs via `signalEpisodeComplete`, which this path does not call — only the metrics JSON captures the partial session).

### 2.3 Socket disconnect of a peer (`on_disconnect`, `app.py:2652-2800`)

- Grace: if the subject is inside the Pyodide **loading** window, session is preserved and no cleanup/notification happens (`2678-2687`, `is_client_in_loading_grace` `app.py:144-154`).
- Otherwise session state saved for reconnect; if the socket maps to a coordinator game, a termination record with reason `partner_disconnected` is archived (if active), then `remove_player(notify_others=is_active)` (`pyodide_game_coordinator.py:388-453`): removes the player; if others remain and notify is on, **the game is deleted immediately and each remaining socket gets `p2p_game_ended {reason:'partner_disconnected', disconnected_player_id}`** — i.e., a *server-observed* socket drop ends the game at once with **no reconnection window** (the 30 s pause flow only applies to P2P-layer drops where both sockets stay up). GameManager waitroom state also cleaned (`remove_subject_quietly`, `app.py:2775-2797`).

### 2.4 Mid-game exclusion & partner exclusion

- Client-side ContinuousMonitor (ping/tab-hidden thresholds; checks every 30 frames, `2248-2275`) ⇒ `_handleMidGameExclusion` (`3839-…`): stops loop, shows exclusion UI, emits `mid_game_exclusion` → server (`app.py:1838-1917`) archives termination (reason `sustained_ping`/`tab_hidden`) and calls `handle_player_exclusion` (`pyodide_game_coordinator.py:572-643`): partner sockets get `partner_excluded` (neutral message) **and `trigger_data_export {is_partial:true, termination_reason:'partner_exclusion', termination_frame}`**, 0.1 s eventlet sleep for delivery, then game deleted. Partner client handles `partner_excluded` (stop loop, close P2P, `1538-1565`) and `trigger_data_export` (mark partial, `emitMultiplayerMetrics`, then request redirect, `1569-1586`). Researcher-defined continuous callbacks run server-side, failing open (`_execute_exclusion_callback`, `app.py:2298-2436`).
- Focus-loss timeout (client-side, configurable `focus_loss_timeout_ms`): `_handleFocusLossTimeout` (`6532-6591`) ends the game terminally for the away player (no completion code), exports metrics, and emits `p2p_game_ended {reason:'focus_loss_timeout'}` **from client to server** — but no server handler exists for inbound `p2p_game_ended`, so the partner is actually ended via the P2P disconnect path when this client closes its connection.

### 2.5 Background/focus degradation

- Backgrounded tab: Worker keeps ticking, frames don't advance; partner inputs are buffered in `FocusManager` (`7128-7136`); partner keeps playing, predicting the backgrounded player as defaultAction. On refocus, **fast-forward** (`_performFastForward`, `4830-5162`): inject buffered inputs, request missing ones via INPUT_REQUEST/RESPONSE (3 s timeout, `_requestMissingInputs` `6066-6097`), batch-step up to 1000 frames in one Python call, cap at episode boundary, mark all as confirmed, then send **catch-up defaultAction inputs** for the missed frames so the partner can confirm its predictions (`5106-5124`), then re-check episode end (`5126-5161`). Inputs arriving while waiting-for-partner-focus at episode boundaries are **discarded**, not buffered (`7141-7146`). Optional `pause_on_partner_background` pauses the focused player too (`6124-6133`).
- Per-round health check: `reset()` blocks up to 10 s for a usable connection before each episode (`_waitForHealthyConnection`, `1846-1857`, `6914-6975`), erroring out if `reconnectionState.state === 'terminated'`.
- P2P degradation (latency > 300 ms or critical status) flips a sticky `p2pFallbackTriggered` flag (SocketIO thereafter, `_checkP2PHealth` `8040-8061`; also on DC close/failure `5547-5571`). Fallback is one-way — the runtime never returns to P2P sends after the flag is set.

## 3. What reaches the server vs stays peer-local

**Server-visible during play**
- All WebRTC signaling payloads (SDP/ICE relayed in cleartext through `webrtc_signal`).
- Every input sent via the SocketIO fallback path (`pyodide_player_action`), including frame numbers and timestamps — but **none** of the inputs sent over the DataChannel.
- `p2p_validation_status/success/failed`, `p2p_connection_lost/reconnection_success/reconnection_timeout` lifecycle events.
- `p2p_health_report` every 2 s: `{connection_type, latency_ms, status, episode}` → AdminAggregator only (`_reportP2PHealth` `5633-5675`; `app.py:1937-1954`).
- HUD text via `pyodide_hud_update`→`pyodide_hud_sync` broadcast (`app.py:2439-2461`).
- Per-episode evidence: `emit_episode_data` (msgpack; actions, rewards, terminateds, truncateds, flattened infos, per-frame `isFocused`, `wasSpeculative` flags, rollbackEvents, timestamps, player_subjects) with **ack + 5×2 s retry** (`3696-3769`), saved as `data/{experiment}/{scene}/{subject}_ep{n}.csv` (`app.py:1148-1210`); scene-end `emit_remote_game_data` (`app.py:1109-1145`).
- Scene-end / termination evidence: `emit_multiplayer_metrics` — the full `exportMultiplayerMetrics()` object (connection type/health, input delivery counts and P2P ratio, **all confirmed hashes across episodes, all verified actions, all desync events, all rollbacks**, sessionStatus/partial info, latency telemetry samples, focus-loss telemetry) saved per subject as `{subject}_multiplayer_metrics.json`, and once both players submit, a server-computed **aggregated cross-player comparison** (`{game_id}_aggregated_metrics.json`: per-frame hash/action match tables, first-mismatch frames, fullySynced flag) (`7816-7935`; `app.py:1213-1272`, `_create_aggregated_metrics` `1302-1441`).
- `multiplayer_game_complete` on normal completion (archives session + transitions participants to GAME_ENDED, `app.py:1957-2021`); `participant_terminal_state`; `client_console_log` for the admin dashboard.

**Peer-local only (never reaches the server)**
- P2P-delivered per-frame inputs in real time (only the post-hoc verified-action export captures them), raw input redundancy packets, ping/pong RTT frames, state-hash exchange messages, episode end/ready packets, focus-state packets, input request/response recovery traffic.
- State snapshots, RNG states, speculative frame data, rollback replay internals, desync state dumps (exported metrics include only a `hasStateDump` boolean, not the dump itself, `7740`, `7888`).
- `p2p_connection_type` is emitted but dropped server-side (no handler).

## 4. Contract mapping (0.2)

### api-07 (ExecutionMode P2P; per-replica writer; snapshot contract; EnvFactory)

| Runtime mechanism | Status | Notes |
|---|---|---|
| Symmetric deterministic replicas, one writer per replica | **PARITY** | Matches "P2P has one writer per deterministic replica". |
| Declared snapshot hooks (`snapshot()/restore()/state_hash()`) | **IMPROVE** | Runtime *probes* `get_state`/`set_state` at load and silently degrades (hashing, rollback, resync all disabled). Contract makes capabilities declared, not assumed. Migration: decide whether `p2p` mode without snapshot hooks is even legal. |
| Env creation via `EnvFactory` qualified name | **IMPROVE** | Runtime uses `environment_initialization_code` exec-strings and an implicit module-level `env`. Contract explicitly replaces this (R-17). |
| Identical normalized transition shape across modes | **GAP (runtime side)** | P2P-only fields (`wasSpeculative`, speculative→canonical promotion provenance, synced termination frame) must be representable in the normalized shape or API-10's experienced stream, else they're lost. |
| Input delay, finality barrier, reconciliation authority | **GAP (contract side)** | api-07 review-record leaves these open (A07-O02). The runtime has concrete answers the contracts don't yet model: `INPUT_DELAY` applied to *both* local and remote seats; finality = `confirmedFrame` (all-inputs-received) then `verifiedFrame` (hash-agreed); reconciliation tie-break = lower-ID-defers-to-higher; episode boundary finality = `min(localEndFrame, remoteEndFrame)`; input-confirmation wait before export. These must be captured by A07-O02 or they will be reinvented. |
| Snapshot cadence/rollback replay as batch, RNG state as part of snapshot | **GAP** | Runtime snapshot additionally captures **numpy + Python `random` global RNG state and JS-side rewards/step_num**. If the contract's env snapshot doesn't subsume RNG/global state, deterministic P2P replay breaks for envs that draw from global RNGs. Must be made explicit in the Phase-1 snapshot codec (A07-O01). |
| Bot/AI seat determinism | **GAP** | Runtime replays bots from *recorded* actions with an acknowledged TODO; fast-forward predicts bots as last-action. Rollback authority for agent decisions undefined in contracts. |
| Rollback smoothing via object identity + tween | **PARITY** | Explicitly preserved by api-07. |

### api-06 (Interaction/Group, matchmaking, leases)

| Runtime mechanism | Status | Notes |
|---|---|---|
| Coordinator game = interaction-ish record | **PARITY** (shape), **IMPROVE** (identity) | `PyodideGameState` conflates channel, group, matchmaking, and reconnection state in one dataclass; api-06 splits them. |
| Validation-failure re-pool | **PARITY** / **GAP** | The *game-level* validation repool is a second, post-match rejection path the ticket lifecycle should also represent — the contract names only the probe stage; post-formation dissolution back to `forming` isn't described. |
| Socket-ID as connection identity | **IMPROVE** | api-06 `ConnectionLease` + fencing is strictly stronger: today a duplicate tab/socket is not fenced at all in the coordinator. |
| Mid-game disconnect policy | **PARITY (partial)** | Runtime implements grace/pause, abort, continue-partial, compensate. *Substitute* has no runtime counterpart. |
| Group persistence/reunion | **GAP (both)** | Contract deliberately better; migration must build reunion from scratch under the shared-Group model. |
| 2-player hard limit for P2P | **GAP (contract silence)** | Runtime P2P requires exactly 2; coordinator disconnect inference assumes 2. Contract doesn't state that `ExecutionMode.P2P` is N=2-only; either constrain or plan mesh/star topology. |

### api-09 (client boundary, transport, input)

| Runtime mechanism | Status | Notes |
|---|---|---|
| `input_delay` on the input scheme | **PARITY** | |
| Typed action space on the wire | **IMPROVE** | Runtime P2P wire packs actions as uint8; SocketIO path takes arbitrary values; str/int key coercions everywhere. Migration: binary codec must carry env action-space values, not uint8. |
| No-input fill | **PARITY** | Note runtime's *prediction* uses the same policy — contract should state that prediction fill and no-input fill are the same declared value, else cross-client determinism of predictions breaks. |
| Idempotent realtime commands, acks | **IMPROVE** | Runtime has ack+retry only for `emit_episode_data`; every P2P lifecycle event is fire-and-forget. |
| `mugGlobals` in payloads | **IMPROVE** | Runtime ships `window.mugGlobals` inside episode payloads; retired by R-13. |
| WebRTC signaling relay, TURN provisioning | **GAP** | Nothing in any 0.2 contract models the signaling relay channel, ICE/TURN credential distribution, DataChannel reliability config, or the probe namespace. Uncontracted wire-tier surface a P2P rewrite must have. TURN credential exposure (cleartext to browser) needs a short-lived-credential story. |
| Per-seat delivery | **PARITY/IMPROVE** | Per-seat hidden-information rules cannot be enforced in P2P replicas (each peer has full state). Nothing states that **hidden-information designs are incompatible with `ExecutionMode.P2P`** — worth an explicit rule. |

### api-10 (canonical vs experienced evidence)

| Runtime mechanism | Status | Notes |
|---|---|---|
| Speculative→canonical promotion; `wasSpeculative` flags | **PARITY (conceptually), IMPROVE (formally)** | Today the **experienced** stream is discarded (predicted frames are overwritten during replay; only rollbackEvents metadata survives). Migration: capture both streams. |
| Dual-perspective upload + server aggregation | **PARITY** / **GAP** | When only one player ever submits, pending metrics are never aggregated and never flushed/marked partial; on hash disagreement the aggregate records it but nothing is quarantined. |
| Producer epoch/sequence, digests, immutability | **IMPROVE** | Runtime files are mutable JSON/CSV; `syncEpoch` exists vestigially. |
| Ack ≠ receipt | **IMPROVE** | Episode-data ack conflates transport ack with durable-save confirmation. |

### api-16 (deterministic replay, state_hash)

| Runtime mechanism | Status | Notes |
|---|---|---|
| Confirmed-frame SHA-256 state hash chain, float-normalized | **PARITY (mechanism), GAP (spec)** | Runtime hash = SHA-256/16-hex over sorted-key compact JSON with floats rounded to 1e-10; a second md5/8-char algorithm exists for episode-start checks. A rewrite must standardize one canonical `state_hash()`. |
| Verified actions + hashes exported for offline verification | **PARITY** | Exactly the raw material `run.verify()` needs. |
| Replay capability declaration | **IMPROVE** | Runtime silently downgrades; api-16 requires declared capability levels. |
| Rollback events as replay metadata | **GAP (contract)** | Nothing yet models **speculation/rollback lineage inside a run** (needed to reconstruct the experienced stream). |
| Snapshot+RNG capture for mid-run determinism | **GAP** | As api-07: global-RNG capture is required in practice. |

## 5. Intricacies register

**Determinism & ordering**
1. Deterministic initiator/answerer: lower player ID (numeric compare when both numeric, else localeCompare) — used for both initial offer and ICE-restart offers. Answerer never creates a DataChannel.
2. Deterministic player-index mapping via sorted player IDs (binary protocol identity).
3. Desync-resync tie-break: lower ID requests state from higher (string compare — subtly different from the connection-role comparator).
4. `min(local, remote)` synced termination frame ⇒ identical export row counts across peers; frame storage suppressed beyond it; export filters `frame < terminationFrame`; fast-forward and boundary promotion cap at the same boundary.
5. One shared server seed drives `env.reset(seed)`, `np.random`, Python `random`, and the JS AI RNG, re-seeded identically on every episode reset.
6. Snapshot semantics: snapshot[N] = state *before* stepping frame N; rollback replay runs as **one synchronous Python batch**; on-interval snapshots are refreshed inside the replay.
7. Confirmed hashes are computed **from the frame's snapshot, never live state**.
8. Prediction fill uses the same configured policy as no-input fill; `lastConfirmedActions` is updated in three places and must stay consistent across clients.
9. Frames re-predicted during replay are re-added to `predictedFrames` so a later real input still triggers a corrective rollback.
10. `pendingRollbackFrame` takes the **min** across multiple late inputs in one tick and is cleared at frame start before input drain.

**Race handling & buffering**
11. All network inputs are queued and drained only at frame start, never applied mid-await; queues are held during rollback.
12. ICE candidate buffering until remote description set.
13. Hash exchange deferred while rollback in progress and while the channel is congested/closed (re-queue at head on failed send); hash comparison skipped during rollback.
14. `isProcessingTick` guard prevents overlapping async tick processing; fast-forward blocks the tick loop while running.
15. Input redundancy (last ≤10 inputs per packet) + duplicate-drop is the loss-recovery story; INPUT_REQUEST/RESPONSE is the explicit recovery for long gaps.
16. Send-buffer congestion threshold (16 KiB) triggers per-input SocketIO fallback without flipping the sticky global fallback flag.
17. Server emits are collected under the coordinator lock but **emitted outside it** to avoid eventlet deadlock.

**Episode lifecycle**
18. Episode end requires bilateral agreement with a 2 s timeout fallback; state cleared only **after** export so `syncedTerminationFrame` survives through export.
19. Episode start: EPISODE_READY with hash, 3 retries at 500 ms, echo-ack on receipt; 5 s timeout proceeds anyway relying on seed determinism.
20. Input-confirmation wait at episode end before promoting speculative data — prevents cross-client export divergence under packet loss.
21. Action queues, GGPO state, pressed-key buffers are cleared at specific points (start of reset, after countdown, on waiting-overlay show/hide).
22. The WebRTC connection **persists across episodes**; closed only on scene exit/terminal states.

**Failure/timing constants (all load-bearing)**
23. 500 ms ICE-disconnect grace; 5 s disconnect→ICE-restart; 3 max ICE restarts; 15 s ready gate; 15 s validation timeout; 100 ms validation settle; 30 s (configurable) reconnection timeout — client-enforced; 2 s episode-end sync timeout; 5 s episode-start timeout; 10 s per-round health wait; 10 s focus-wait at episode transition; 2 s health-report cadence; 500 ms ping cadence; 1000-frame fast-forward cap; SocketIO 8/30 ping tuned *because* P2P detection exists.
24. Reconnection resume requires `lost ⊆ recovered` server-side; resume clears the client timeout *before* unpausing to avoid a timeout/resume race.
25. Terminal-state precedence: focus-loss overlay wins over partner-disconnect overlay; both set flags that make `isDone()` false so the scene can never auto-advance past the overlay.
26. Validation-failure repool must **not** transition participants to GAME_ENDED (must reset to IDLE) or they can never re-queue.
27. `scene_completed` game-end reason is a graceful no-overlay P2P close.
28. Server-observed socket drop ends the game immediately (no 30 s window); only P2P-layer drops get the pause/reconnect window — **two distinct disconnect regimes**.
29. Loading-grace: disconnects during Pyodide load do not tear down the game/session.
30. Fast-forward marks all fast-forwarded frames confirmed and sends defaultAction catch-up inputs so the partner's predictions get confirmed rather than triggering rollbacks; `isFocused` per-frame per-player is recorded through all three paths.
31. Metrics export happens **before** terminal overlays are shown on every failure path (data-first ordering).
32. **Do-not-port defects**: dead `pyodide_state_hash`/`pyodide_send_full_state` handlers calling nonexistent coordinator methods; unhandled `p2p_connection_type` emit; undefined `this.socket` silently dropping the completion-code emit; dormant `p2p_state_sync` resync layer with no broadcaster; coordinator `reconnection_timeout_s`/`p2p_validation_timeout_s`/`action_timeout` fields never enforced; str-vs-numeric ID comparison inconsistency between connection-role and resync tie-breakers.
