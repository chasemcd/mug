# Dimension 5 — Matchmaking, Latency Probes, Connection Monitoring

| Field | Value |
| --- | --- |
| Audit date | 2026-07-19 |
| Sources | `mug/server/matchmaker.py`, `mug/server/player_pairing_manager.py`, `mug/server/probe_coordinator.py`, `mug/server/static/js/probe_connection.js`, `mug/server/static/js/continuous_monitor.js`, `mug/server/app.py` probe/waitroom handlers, `mug/server/match_logger.py` |
| Contracts mapped | API-05, API-06 (rev 0.2) |

## 1. Mechanism map

### 1.1 Waitroom entry → match, end to end

1. **Pre-waitroom latency gating (server RTT)**: client sends `ping` every 1 s with its current median latency and focus state (`index.js:606-612`); server replies `pong` carrying `max_latency`/`min_ping_measurements` and stores the client-reported `ping_ms` into `PARTICIPANT_SESSIONS[subject_id].current_rtt` (`app.py:888-905`). Client computes RTT itself, keeps last 20 measurements, uses the **median** (`index.js:367-387`). Start button withheld until `min_ping_measurements` exist; subject **excluded before the waitroom** if median > `max_latency` (`index.js:1874-1886`). Server-side RTT is *client self-reported*.
2. **Join**: start button emits `join_game` → validation → `game_manager.add_subject_to_game(subject_id)`.
3. **Match decision**: `_add_to_fifo_queue` (`game_manager.py:274-298, 411-480`) under `waiting_games_lock`. Builds `MatchCandidate`s for arriving + every waitroom entry, attaching `rtt_ms` and `GroupHistory` from the `PlayerGroupManager`. `group_size` = number of `Human` entries in `scene.policy_mapping`. Then `matchmaker.find_match(arriving, waiting, group_size)`.
4. **No match** → `_add_to_waitroom` (`game_manager.py:482-534`): emits `waiting_room` with `cur_num_players`, `players_needed`, `ms_remaining = scene.waitroom_timeout or 60000`, timeout message, `hide_lobby_count` — to the arriving socket only.
5. **Match, no probing** (`probe_coordinator is None` or `matchmaker.max_p2p_rtt_ms is None`) → `_create_game_for_match` (`game_manager.py:961-1067`): create game, seat all matched, remove from waitroom, join rooms, `SessionState.MATCHED`, log via `MatchAssignmentLogger`, 3 s `match_found_countdown`, `start_game` with strict player-count validation.
6. **Match, probing needed** → `_probe_and_create_game` (`game_manager.py:536-573`): arriving parked in the waitroom while iterative pair probing runs via `_start_next_probe`.
7. **Waitroom timeout is purely client-enforced.** The client counts down `ms_remaining` locally; at 0 it emits `leave_game`, shows the timeout message, permanently disables the start button (`index.js:963-994`). Server `leave_game` removes from waitroom/game and records a `waitroom_timeout` termination. The client can emit `waitroom_timeout_completion` with a generated completion code; server logs it and writes `data/{experiment_id}/completion_codes/{subject_id}.json`. The same event is reused with `reason: 'partner_disconnected_mid_game'`. The server-side `waitroom_timeouts` dict is set/cleared but never *enforced* — vestigial.
8. **Partner leaves pre-start**: `waiting_room_player_left` broadcast → remaining clients emit `leave_game`, lobby ends, start button disabled.

### 1.2 Matchmaker subclasses (`mug/server/matchmaker.py`)

- **ABC `Matchmaker`** (`matchmaker.py:60-166`): `find_match(arriving, waiting, group_size)` returns exactly-`group_size` list including arriving, or `None`; called under `waiting_games_lock`; must not mutate `waiting`. `max_p2p_rtt_ms` on the base class gates post-match probing; `should_reject_for_rtt` (`:92-108`) rejects when `measured > threshold` **and treats a failed measurement (None) as reject** ("reject for safety"). `rank_candidates` (`:110-135`) returns the ordered probe-candidate list (default: FIFO of all waiting).
- **`FIFOMatchmaker`** (`:169-222`): waits until `len(waiting)+1 >= group_size`, then `waiting[:group_size-1] + [arriving]` — strict arrival order, N-size capable.
- **`LatencyFIFOMatchmaker`** (`:225-348`): stage 1 pre-filter — `estimated_p2p_rtt = arriving.rtt_ms + candidate.rtt_ms` (sum of the two *server* RTTs) must be `<= max_server_rtt_ms`; **missing RTT on either side does NOT exclude** (`:276-282`). Then FIFO over the filtered list. Stage 2 (real P2P probe) applies only if `max_p2p_rtt_ms` also set — "cheap pre-filter / precise post-filter".
- **`GroupReunionMatchmaker`** (`:351-487`): forward reunion — if arriving's `previous_partners` gives `>= group_size-1` members in waiting, reunite; reverse reunion — a waiting member who lists arriving as previous partner, **only implemented for `group_size == 2`** (`:457-471`); then FIFO fallback if `fallback_to_fifo=True` (default), else wait.
- Scene config: `scene.matchmaking(matchmaker=...)` validated as a `Matchmaker` **instance**; default → `FIFOMatchmaker()`. Legacy `wait_for_known_group` warns and behaves as FIFO. Legacy `matchmaking_max_rtt` is **stored but never enforced** (TODO comments only).

### 1.3 Two-stage latency probing (WebRTC DataChannel, not socket)

- **Trigger**: match proposed AND `probe_coordinator` set AND `matchmaker.max_p2p_rtt_ms` set. `ProbeCoordinator` is global, constructed with TURN creds (`app.py:2906-2913`).
- **Pairing loop** `_start_next_probe` (`game_manager.py:651-729`): filters candidates still in waitroom, not in `_probing_subjects`, not in `_failed_probe_pairs`; takes the first; registers both in `_probing_subjects`; stores `_pending_matches[probe_session_id]`. **The probed/created match is always a pair** (`game_manager.py:721`).
- **Server probe session** (`probe_coordinator.py:61-124`): fresh socket lookup for both; if either missing → immediate `on_complete(None)`. Emits `probe_prepare` (peer subject id + TURN creds) to both. State machine `preparing → connecting → complete|failed`. `probe_timeout_s = 15.0` is declared **but never enforced** — no sweep, no timer.
- **Client**: `ProbeManager` (`index.js:18-118`) creates `ProbeConnection` (closing any existing probe) → `probe_ready`. At 2 readies the server emits `probe_start`. `ProbeConnection` wraps `WebRTCManager` with probe-specific signaling (`probe_signal` relayed by subject id); deterministic initiator = lower subject id; 10 s client-side connection timeout; relay not forced ("we want to find best path").
- **Measurement**: on DataChannel open, app-level ping-pong — 5 pings, 2 s per-ping timeout, 100 ms interval, **median of successful RTTs** (`probe_connection.js:234-277`). Result reported via `probe_result {rtt_ms, success}`. Both clients measure and report; **first `probe_result` wins**.
- **Verdict** `_on_probe_complete` (`game_manager.py:731-839`): reject → add pair to `_failed_probe_pairs`, try next candidate; on exhaustion `eventlet.spawn(_retry_matchmaking_for_waitroom)` which re-runs matchmaking treating each non-probing waitroom member as arriving, stopping after the first success. Accept → under lock, verify **all** matched still in waitroom (abort silently if not), remove from waitroom, create game, countdown-start.

### 1.4 Group reunion persistence (`PlayerGroupManager`)

- Groups are created **whenever a game is cleaned up** with >1 real subject: `cleanup_game` → `create_group(real_subjects, scene_id)` (`game_manager.py:1663-1676`) — including exclusion/abort paths, not only clean completions.
- `create_group` (`player_pairing_manager.py:65-106`): new uuid `group_id`; each subject **removed from any prior group first**; a prior group left with ≤1 member is deleted. The store holds only each subject's *most recent* group — no history chain, no TTL.
- `GroupHistory` handed to matchmakers is derived per-arrival: `previous_partners`, `source_scene_id`, `group_id`.
- **Disconnect wipes history**: every disconnect path calls `cleanup_subject(subject_id)`, removing the subject and dissolving groups down to ≤1 member — a transient disconnect between scenes destroys reunion capability for the *whole* group.

### 1.5 N-size support vs pair-only paths

- N-size supported: FIFO, latency pre-filter, forward reunion + FIFO fallback, game creation/slotting, `PlayerGroupManager`.
- Pair-only: **the entire P2P probe path** (probed match is always `[candidate, arriving]`; `ProbeCoordinator` strictly two-party; `ProbeManager` holds a single `activeProbe`); reverse reunion. For `group_size > 2` with `max_p2p_rtt_ms` set, a probe-accepted "match" is a pair and game creation fails `is_ready_to_start()` — **probing + N>2 is effectively broken, not merely unsupported**.

### 1.6 Continuous monitoring during play (`continuous_monitor.js`)

- Config from scene metadata (`gym_scene.py:193-215`): master flag `continuous_monitoring_enabled` (default False), `continuous_max_ping` (null disables), rolling window (5) / required consecutive violations (3), tab-hidden warn at 3 s / exclude at 10 s, custom messages, optional server-side callback + interval (30 frames).
- **What it measures**: (a) `window.currentPing` — the *client↔server socket median RTT* (not P2P RTT), recorded each frame; (b) tab visibility via `visibilitychange`.
- **Decision logic** (`continuous_monitor.js:131-312`): priority = custom-callback result > tab > ping; ping only checked while tab visible ("hidden tabs have stale measurements"). Ping: exclusion on N *consecutive* over-threshold measurements; single violation → warning, re-warnable after 5 s. Tab: warn 3 s, exclude 10 s; timers reset on foreground. `pause()`/`resume()`/`reset()` around episode transitions.
- **On degradation**: warning → overlay; exclusion → `_handleMidGameExclusion`: stop loop, exclusion UI, `mid_game_exclusion`, mark partial, export metrics, `leave_game` + redirect. Server records termination, notifies partner, `cleanup_game` — which **still records the group** for reunion.
- **Custom callback loop**: every N frames client sends `execute_continuous_callback {ping, is_tab_hidden, tab_hidden_duration_ms, frame_number, episode_number}`; server runs the researcher's callable and replies `continuous_callback_result {exclude, warn, message}`, consumed on the next check.
- Adjacent telemetry: `p2p_health_report` (→ admin dashboard) and `p2p_validation_status` relay take no enforcement action.

### 1.7 Assignment recording (`match_logger.py`)

`log_match` writes `{timestamp, scene_id, game_id, participants:[{subject_id, rtt_ms}], matchmaker_class}` to `data/{experiment_id}/match_logs/{scene_id}_matches.jsonl` plus an admin activity. `rtt_ms` is the **server RTT** at candidate build time; the **measured P2P probe RTT is never persisted** — it exists only in server logs.

## 2. Failure semantics

| Scenario | Behavior |
| --- | --- |
| Candidate has no socket at probe creation | Immediate `on_complete(None)` → treated as reject → pair **permanently poisoned** in `_failed_probe_pairs` even though nothing was measured. |
| Candidate disconnects mid-probe | Disconnect removes them from the waitroom but **not** from `_probing_subjects`/`_pending_matches`. Recovery relies on the *other* client's 10 s timeout → `probe_result success:false`. If **both** probe clients vanish, no result ever arrives: probe state leaks forever (server `probe_timeout_s` is dead code) and deferred probes against those subjects stall. |
| Probe times out / connection fails | `probe_result {rtt_ms: null, success: false}` → reject → next candidate → on exhaustion, background rematch sweep; participants stay in the waitroom under their client-side countdown. |
| Probe succeeds but a matched member left during probe | Verified under lock; aborts silently — **the surviving member is left in the waitroom with no rematch trigger** until another arrival or probe-exhaustion retry fires. |
| Partial group formation (seat add fails) | Game removed; subjects removed from waitroom are **not re-added**. |
| Waitroom timeout release | Client-driven: `leave_game`, completion code, permanent start-button disable. Server never proactively expires a waitroom member; a client whose timer JS dies waits forever. |
| Partner leaves waitroom | `waiting_room_player_left` → all remaining ejected, lobby destroyed. |
| Mid-game exclusion | Client-authoritative decision and report; server trusts it, terminates for everyone, partner gets disconnect overlay + completion code. |

## 3. Contract mapping (API-05 / API-06, rev 0.2)

| Legacy mechanism | Contract construct | Verdict |
| --- | --- | --- |
| `FIFOMatchmaker` arrival-order, N-size | `Match.FIFO` / ticket `fifo` | **PARITY** — direct. |
| `LatencyFIFOMatchmaker.max_server_rtt_ms` pre-filter | `MatchLatency.max_estimated_rtt` | **PARITY with a vocabulary caveat**: legacy semantic is a bound on the **sum of two per-participant server RTTs**, and missing RTT data passes the filter. Neither is captured by the schema — pin in prose/tests or it will be re-implemented as a per-ticket bound. |
| `max_p2p_rtt_ms` post-probe filter + rejection/re-pooling over `rank_candidates` | `MatchLatency.max_p2p_rtt` + ticket status `probing` | **PARITY in vocabulary, GAP in fidelity**: (a) legacy probing is **pair-only and breaks for N>2** while contract `size` goes to 64 — N-member probe semantics (pairwise mesh? sequential?) must be defined; (b) fail-closed on probe failure (None ⇒ reject) is uncontracted; (c) failed-pair memory and re-probe suppression have no ticket-level representation; (d) the two thresholds are independently optional — schema `anyOf` allows this, good. |
| Custom `Matchmaker` subclass (live instance) | `MatchCustom.matchmaker_ref` (versioned name) | **PARITY/IMPROVE** — contract records by name+version; preserve `max_p2p_rtt_ms`/`should_reject_for_rtt` living on the ABC so any custom matchmaker can opt into probing. |
| Waitroom timeout (client-enforced, completion code, redirect/scene options) | `wait: Duration` + `on_timeout: RELEASE`; ticket `released`/`expired` | **IMPROVE with GAPs**: server-side expiry fixes the client-only enforcement hole. GAPs: legacy release is terminal (completion code, permanent disable, optional `waitroom_timeout_redirect_url`/`timeout_scene_id` routing) — richer than "return the participant, mark ungrouped"; `hide_lobby_count`/timeout message/lobby-count display have no contract home; map `released` vs `expired` onto the three legacy exits. |
| `PlayerGroupManager` + `GroupReunionMatchmaker` | Shared authored `Group`; runtime Group with durable `group_id`; `OnMissing.WAIT/REGROUP` | **IMPROVE, with real semantic deltas** (below). |
| `MatchAssignmentLogger` JSONL | Runtime Group/ticket records | **PARITY-ish**; GAP: measured P2P RTT is persisted nowhere in either world unless added — attach probe outcomes to the ticket's `probing`→`matched` transition evidence. |
| Ping loop, `current_rtt`, pre-join `max_ping` exclusion | No construct in api-05/06 | **GAP to track elsewhere**: the *source* of `max_estimated_rtt` inputs (client-reported median socket RTT, 20-sample window, 1 s cadence) is contract-relevant to `MatchLatency` semantics. |
| `ContinuousMonitor` + `mid_game_exclusion` | `ConnectionLease` is the nearest construct | **GAP**: leases model liveness, not quality. Sustained-ping exclusion, tab-visibility policy, warning-before-exclusion, researcher callback, partner notification + completion code have no contract vocabulary in 0.2. Extend api-06/api-09 or defer explicitly. |

### Does the two-stage latency vocabulary capture `LatencyFIFOMatchmaker`?

Mostly yes at the strategy level, but four load-bearing behaviors are outside the schema: (1) estimate = *sum* of both parties' self-reported server RTTs; (2) missing measurements pass the pre-filter yet a failed *probe* rejects — opposite defaults at the two stages, both deliberate; (3) probing is pairwise and match-scoped, not ticket-scoped (state is per-*pair*: `_probing_subjects`, `_failed_probe_pairs`, `_pending_matches`); (4) exhaustion behavior (stay `waiting`, background rematch sweep) vs any notion of `released`.

### Does `GroupHistory` survive as the shared-Group-object model?

The contract model is **stronger and cleaner** and subsumes forward reunion. Deltas a parity plan must decide on:

- Legacy groups are implicitly (re)created on every game end (including exclusion/abort), and membership can *drift* (a FIFO-fallback rematch overwrites the original group). Contract groups are formed once and durable. `fallback_to_fifo=True` ≈ `OnMissing.REGROUP`; `False` ≈ `OnMissing.WAIT`. But legacy regrouping **mints a new group and destroys the old one**, whereas the contract's shared-`Group` identity persists — specify what `REGROUP` does to `group_id`.
- Legacy reunion is matchmaker-mediated and best-effort per arrival order; reverse reunion pairs-only — contract reunion is symmetric by construction. IMPROVE.
- Legacy `cleanup_subject` on any disconnect erases group membership — **a refresh between scenes forfeits reunion**; the contract's durable group changes participant-visible behavior. Deliberate improvement; note as behavior change, not parity.
- `source_scene_id` has no contract counterpart; runtime Group has `group_key`/`formed_at` — likely sufficient.

## 4. Intricacies register

1. **Locking discipline**: `find_match` runs under `waiting_games_lock`; probe callbacks re-acquire it before mutating state. Custom matchmakers are documented as thread-hostile.
2. **FIFO fairness shape**: matched set = first `group_size-1` waiters + arriving; arrival-order fairness applies to *waiters*, not to the closer.
3. **Missing-RTT leniency vs probe-failure strictness**: pre-filter passes unknown RTT; probe stage rejects unknown RTT. Both explicit design choices ("avoid penalizing participants for missing data").
4. **Median everywhere**: server RTT = median of last 20 socket pings (1 s cadence); probe RTT = median of ≤5 DataChannel pings (100 ms apart, 2 s each). Thresholds are tuned against medians.
5. **Re-probe cadence and exclusion interplay**: one probe at a time per subject; a probing subject defers new matches; failed pairs excluded from candidate filtering and the rematch sweep; `_failed_probe_pairs` is **never cleared** for the GameManager's lifetime — a once-failed pair can never match in that scene even if conditions improve. Rematch sweep stops after the first success.
6. **First-result-wins probe reporting**: both peers measure; the session is deleted on the first `probe_result` — the recorded RTT is whoever lands first.
7. **Deterministic WebRTC initiator** — lower subject id — shared between probe and game connections; probes deliberately do **not** force TURN relay while games may.
8. **Countdown UX contract**: `match_found_countdown` (3 s) must stop the waitroom timer client-side; single-player games skip the countdown.
9. **Waitroom timeout is per-client and restarts** on each `waiting_room` emission — a rejoin resets the participant's clock.
10. **Terminal timeout**: after timeout/partner-left/exclusion, the client permanently disables the start button and optionally shows a compensation completion code persisted server-side with `reason` variants.
11. **Group recording is unconditional on game end** — even for excluded/aborted games — and `create_group` *replaces* prior membership. History depth is exactly one group.
12. **Ping monitoring ignores hidden tabs** (stale-measurement guard); tab warnings take precedence; monitor pauses during episode transitions; ping-warning re-arm after 5 s.
13. **Client-authoritative exclusion**: the excluded client decides and reports; the server trusts it. Moving this server-side changes trust/abuse properties.
14. **Match log field semantics**: `participants[].rtt_ms` is the self-reported server RTT snapshot, not probe RTT; analysts depend on this file layout.
15. **Dead/vestigial state a rewrite should NOT copy**: unenforced `ProbeCoordinator.probe_timeout_s`, unenforced `scene.matchmaking_max_rtt`, unused `waitroom_timeouts` dict, superseded `_remove_from_waitroom`, and the `_probing_subjects`/`_pending_matches` leak on double-disconnect mid-probe — the contract's server-side ticket expiry is the fix.
