# Dimension 4 — Data Capture & Persistence

| Field | Value |
| --- | --- |
| Audit date | 2026-07-19 |
| Sources | `mug/server/app.py` data handlers, `mug/server/match_logger.py`, `mug/server/admin/aggregator.py`, `mug/server/participant_state.py`, client buffering in `pyodide_multiplayer_game.js` / `pyodide_remote_game.js` / `phaser_gym_graphics.js` / `index.js` |
| Contracts mapped | API-02 (NS-08), API-10, API-11, API-19, shared-kernel privacy labels (rev 0.2) |

Everything durable lands under a flat file tree rooted at `data/{experiment_id}/...` relative to the server CWD. There is no database, no fsync, no write-ahead anything. The only global gate is `CONFIG.save_experiment_data`, checked per-handler.

## 1. Mechanism map

### 1.1 Episode/trajectory data (Pyodide games — the primary scientific record)

| Aspect | Single-player | Multiplayer (P2P lockstep/rollback) |
|---|---|---|
| Producer | Client: `RemoteGameDataLogger` (`phaser_gym_graphics.js:117-204`), fed per-step at `:527` and per-reset at `:481` | Client: `storeFrameData()` into `speculativeFrameData` (`pyodide_multiplayer_game.js:3498-3508`), promoted to canonical `frameDataBuffer` when inputs confirm (`:2791-2808`), force-promoted at episode boundary (`:2877-2907`) |
| Buffer | Single in-page JS object, grows for whole episode | Two Maps (speculative + canonical); rollback clears `>= targetFrame` (`:3515-3529`) |
| Flush trigger | Episode end detected in `step()` → `emitEpisodeData()` | `signalEpisodeComplete()` → `_emitEpisodeDataFromBuffer()` (`:3696-3769`) |
| Event | `emit_episode_data` — **no ack callback, no retry** | `emit_episode_data` **with ack + up to 5 retries at 2 s intervals** (`:3726-3764`); buffers cleared immediately after first emit attempt (`:3767-3768`) |
| Encoding | msgpack binary of column-oriented dict (`t`, `episode_num`, `timestamp`, per-agent `actions/rewards/terminateds/truncateds/infos/isFocused`) | Same, plus per-agent `wasSpeculative` and `rollbackEvents` metadata (`:3626-3630`) |
| Server handler | `receive_episode_data` (`app.py:1148-1210`) — msgpack-decode, flatten/pad (`_game_data_to_dataframe`, `app.py:1085-1106`), write CSV, then ack `{"status":"ok","saved":true}` (write-before-ack) | Same handler |
| Disk | `data/{experiment_id}/{scene_id}/{subject_id}_ep{episode_num}.csv` + `{subject_id}_globals.json` overwritten each episode | Same |
| Dedup | Filename determinism only — a retried episode overwrites the same file (idempotent last-write-wins). No content digest, no server-side dedup record | Same |
| Authority | Client is sole authority; server trusts payload wholesale | **Each of the two clients independently emits its own copy of the shared episode**, keyed by its own `subject_id`; the server never reconciles them into one canonical trajectory. Cross-checking is deferred to the metrics aggregation file (1.4) |

Scene-end residue path: `terminateGymScene` (`index.js:1625-1663`) always emits `emit_remote_game_data`; handler (`app.py:1109-1145`) writes `data/{experiment_id}/{scene_id}/{subject_id}.csv` or logs "data was sent per-episode" if empty. For multiplayer, step data never enters `remoteGameLogger` but **reset rows do**, so multiplayer scenes produce a `{subject_id}.csv` containing only per-episode reset rows.

Note: observations are structurally **never persisted** — `logDataForField` creates the `observations` key but skips the push (`phaser_gym_graphics.js:144-146`).

### 1.2 Static scene data (surveys/forms)

- Producer: DOM scrape `getData()` on `terminate_scene` (`index.js:1359-1413`), emitted as `static_scene_data_emission` with full `window.mugGlobals`.
- Server: `data_emission` (`app.py:1036-1082`) → one-row CSV `data/{experiment_id}/{scene_id}/{subject_id}.csv` + `{subject_id}_globals.json`, plain JSON, `"w"` overwrite. Server stamps `timestamp`. No ack, no retry.
- Also syncs `mugGlobals` into the in-memory `ParticipantSession`.

### 1.3 Multiplayer validation metrics

- Producer: `exportMultiplayerMetrics()` (`pyodide_multiplayer_game.js:7820-7916`) — connection health, input delivery counts, cumulative `allHashes`/`allActions`/`allDesyncEvents`/`allRollbacks`, per-episode summaries, `sessionStatus` partial-session marking, latency and focus-loss telemetry.
- Emission `emit_multiplayer_metrics` fires from **four+** places: normal scene termination, partner disconnect, own mid-game exclusion, focus-loss timeout, partner-exclusion `trigger_data_export`. Fire-and-forget, no ack.
- Server: `receive_multiplayer_metrics` (`app.py:1213-1272`) writes `{subject_id}_multiplayer_metrics.json` (`"w"`, last write wins). Both-player aggregation: in-memory `PENDING_MULTIPLAYER_METRICS` keyed `(scene_id, game_id)`; when 2 player_ids present, `_create_aggregated_metrics` (`app.py:1302-1440`) writes `{game_id}_aggregated_metrics.json` with frame-by-frame hash/action comparison and deletes the pending entry.
- Authority: purely client-reported from both peers; the server-side comparison file is the only cross-client reconciliation artifact in the system.

### 1.4 Match assignments

- Producer: server (`MatchAssignmentLogger.log_match`, called from both game-creation paths).
- Disk: **append-only JSONL** `data/{experiment_id}/match_logs/{scene_id}_matches.jsonl` (`match_logger.py:63-71, 129-142`) — record: timestamp, scene_id, game_id, `[{subject_id, rtt_ms}]`, matchmaker class. The only genuinely append-only research file in the system. Write failures swallowed with a log line.

### 1.5 Participant state / terminal status

- `ParticipantStateTracker`, `ParticipantSession` (`PARTICIPANT_SESSIONS`), `PROCESSED_SUBJECT_NAMES`: all in-memory only, never persisted.
- `participant_terminal_state` handler (`app.py:2023-2071`): updates tracker/aggregator, closes console log file. **Writes nothing durable itself.**
- Durable adjacent artifacts: completion codes `data/{experiment_id}/completion_codes/{subject_id}.json` (via `waitroom_timeout_completion`, also reused for partner-disconnect codes); scene metadata `{subject_id}_metadata.json` via `export_metadata` — which **ignores `save_experiment_data`**.

### 1.6 Diagnostics & admin telemetry

- Server `_log_game_diagnostics` (`pyodide_game_coordinator.py:455-497`): inter-action delay stats → Python logger only; the coordinator's module logger has no configured handler, so these are effectively ephemeral.
- `AdminEventAggregator`: capped in-memory deques (activity 500, console tail 1000, completed games 100, wait/latency samples, problems 200); broadcast to `/admin` at 1 s. None persisted. Sole durable output: console logs.

### 1.7 Client console logs

- Producer: console monkey-patch (`index.js:124-194`), rate-limited to 10 logs/s, 500-char truncation, emitted only while the socket is connected.
- Server: append + flush to `data/{experiment_id}/console_logs/{subject_id}_console.jsonl`; handle held open until terminal state closes it. Errors/warns also become admin "problems".

### 1.8 `client_callback`

- Dispatches to `Scene.on_client_callback`, whose base implementation is `pass`. No built-in persistence. Crashes with AttributeError if `current_scene` is None (no guard).

## 2. Loss windows (ordered by severity)

1. **In-progress episode on any abnormal end (multiplayer).** Trajectory buffers are emitted only from `signalEpisodeComplete()`. Partner disconnect, own exclusion, focus-loss timeout, and partner-exclusion export all emit **metrics only** — the partial episode's frames are silently discarded. `sessionStatus.terminationFrame` in metrics is the only trace they existed.
2. **Tab close / browser crash mid-episode.** No `beforeunload`/`pagehide` flush anywhere (verified by grep). Everything since the last episode boundary vanishes. For static scenes, all form data vanishes (scraped only at terminate).
3. **Single-player episode emission has no ack/retry.** If the socket is down at episode end, the episode is unrecoverable — the logger was already `reset()` before emission.
4. **Multiplayer retry ceiling.** After 5 unacked attempts over ~10 s the client gives up; buffers were cleared at first attempt, so a socket outage >10 s at an episode boundary loses the episode even though the client remains open.
5. **Server restart loses all coordination state**: sessions, stagers, processed-subject blocking (restart re-admits completed subjects — double-participation risk), tracker, pending metrics pairs (never aggregated), group manager, admin aggregates. Files on disk survive.
6. **Metrics from one side only.** If the disconnecting player's browser dies, their metrics JSON is never written and the pending entry sits forever — no aggregated comparison file, no cleanup.
7. **Console logs after terminal state** are dropped; rate limiting silently drops bursts — precisely the error storms most worth capturing.
8. **Ack-vs-durability gap.** Episode ack fires after `df.to_csv` returns — OS page cache, no fsync; `"w"`-mode writers can leave truncated files on crash mid-write.
9. **Session-mapping race under load**: episode data with no session mapping falls back to the *client-provided* `subject_id` (`app.py:1166-1171`) — a trust escalation and spoofable identity path; if also absent, the file is written as `None_ep{n}.csv`.
10. **Coordinator diagnostics**: dropped entirely under default logging config.
11. **Exclusion of the remaining player**: partner's `trigger_data_export` covers metrics only — same trajectory hole as (1).

## 3. Identity & joinability

- **Primary key everywhere is `subject_id`** (URL path segment, participant-supplied), joined with `scene_id` via directory layout. Filenames are the schema.
- **`game_id` appears only** in the match JSONL, the aggregated-metrics filename, and inside per-player metrics JSON. **Episode CSVs do not carry `game_id`** — joining a trajectory to its match requires the embedded `player_subjects` columns → match JSONL by subject pair + scene + rough timestamp. Lossy if a subject plays multiple games in one scene (re-pooling after failed P2P validation makes this real).
- **No visit/session entity exists in the data.** Reconnects and re-runs **overwrite** prior CSVs (same filename); episode numbering resets per game instance, so a re-pooled subject's `_ep0.csv` from game 2 clobbers game 1's.
- Timestamps heterogeneous: client `Date.now()` in trajectories, server `pd.to_datetime("now")` for static scenes, server `time.time()` in match logs.

## 4. Contract mapping (0.2)

### API-10 — EventEnvelope, CapturePolicy, canonical/experienced

| Legacy mechanism | Verdict | Notes |
|---|---|---|
| Episode CSV batches | **GAP** | Nothing envelope-shaped: no event_id, stream/producer position, payload digest, recorded_at, data_handling. Mutable last-write-wins files violate append-only immutability. The append-only model **inverts authority**: today the client's buffered batch *is* the record; under API-10 the server's accepted stream is authoritative — the single largest behavioral change for the rewrite. |
| Canonical vs experienced streams | **IMPROVE** (concept latent) | Legacy speculative→confirmed promotion + `wasSpeculative` + `rollbackEvents` is a hand-rolled `ExperiencedFrame.delivery_kind`. Mapping: promoted-confirmed → `delivered`, boundary-promoted → `speculative`, rollback-replaced → `corrected`, post-boundary-skipped → `skipped`. Today the *experienced* stream (as rendered pre-rollback) is discarded on rollback — the record the contract requires does not exist today. |
| CapturePolicy | **GAP** | Completeness implicit and inconsistent: multiplayer ≈ best-effort with bounded retry, single-player fire-and-forget, static fire-and-forget. No accounting of failed captures. §2 losses 1-4 are exactly what `completeness: "complete"` must eliminate. |
| Multiplayer metrics / desync evidence | **IMPROVE** | Real provenance evidence in mutable JSON; becomes canonical events + a projection. |

### API-11 — ArtifactStaging, UnitOfWork, outbox

- **GAP (total)**: no staging/finalization, no digest closure, no transaction combining state + idempotency + event + outbox, no ReceiptDurability — the ad-hoc `{"status":"ok","saved":true}` ack is the only receipt in the system and its durability is unstated. Deterministic filenames are the only idempotency mechanism (blind to divergent-content duplicates — a retried payload with different bytes silently replaces the original with no evidence).
- The match JSONL append is the closest legacy analog to an outbox-backed append — the parity baseline.

### API-19 — export lineage/completeness

- **GAP**: today "export" is the `data/` directory itself: mixed CSV/JSON/JSONL vs the single-NDJSON rule; no LineageRecord, no DatasetSchemaBinding, no row→evidence trace. The flatten-and-pad CSV transform is a **lossy, schema-erasing derivation applied at capture time** — under 0.2 it must move to export-time over intact evidence. Column sets differ per scene/env, so no exact row schema exists to bind.
- Partial-session marking (`sessionStatus.isPartial`) is the legacy completeness signal → maps to export completeness metadata. Preserve the `terminationReason`/`terminationFrame`/`disconnectedPlayerId` vocabulary — analysts depend on it.

### API-02 — NS-08 visit pinning

- **GAP**: the legacy "visit" (`ParticipantSession` + stager index) is memory-only; restart destroys it, and there is no version/deployment pinning at all — a mid-experiment redeploy changes semantics for in-flight participants silently. Completion blocking is memory-only, so restart re-admits finished subjects.

### Shared-kernel privacy labels

- **GAP**: no privacy labels on any file. Concrete conflicts: console-log capture forwards arbitrary browser console content (including any PII a page logs) into research-grade storage and the admin UI; `mugGlobals` dumped wholesale into `_globals.json` (broad serialization explicitly forbidden); completion codes double as payment identifiers stored beside trajectories; admin auth defaults to `admin123` (`mug/server/admin/routes.py:20`).

## 5. Intricacies register

1. **Episode-boundary frame windowing**: export filters `frame < syncedTerminationFrame` so both clients emit *identical* frame counts; boundary promotion skips frames beyond it. Bilateral equality is what makes hash/action comparison meaningful.
2. **Input-confirmation wait before export**: bounded busy-wait then proceed-with-warning — capture proceeds under packet loss rather than blocking the participant. Deliberate best-effort semantics.
3. **`wasSpeculative` is per-agent, per-frame, and true for any frame that ever transited the speculative buffer** — not just mispredicted frames. Keep (or refine), never drop.
4. **Ack/retry envelope**: 5 × 2 s chained `setTimeout` (deliberately not `setInterval`); payload object reused so retries are byte-identical; server ack only after CSV write; connected-check skip consumes a retry slot without emitting (arguably a bug, but current behavior).
5. **Per-episode chunking exists to avoid giant scene-end payload failures**; scene-end residue channel tolerates empty.
6. **Padding semantics**: all columns padded to max list length with `None`; scalars become `[v, None, ...]` — downstream analysis depends on this exact shape.
7. **Globals overwrite cadence**: `_globals.json` rewritten on every episode emission, latest-wins; `mugGlobals` piggyback on every data event.
8. **Metrics multi-emission**: up to 4 trigger sites; cumulative content makes last-write-wins correct today. Aggregation exactly-once per game — but only if both sides ever report.
9. **Console log micro-protocol**: 10/s rate limit, 500-char truncation both sides, JSON-stringify of object args, per-subject persistent handle with flush-per-line, closed at terminal state (lazily reopened).
10. **Write-gating asymmetry**: `save_experiment_data` gates trajectories/metrics/codes/console logs, but scene metadata and match logs write regardless — unify deliberately.
11. **Client-provided subject fallback** on `emit_episode_data` only — an availability-over-integrity choice the 0.2 producer identity should replace, not replicate.
12. **Terminal states suppress scene advance but not capture**: terminal flags make `isDone()` false so `terminateGymScene` never runs; metrics emitted directly in the terminal handlers are the *only* record. Ordering (export → overlay → notify server) is load-bearing.
13. **Ping tuning trade-off**: socketio 8/30 delays server disconnect detection to ~38 s in favor of Pyodide-load survival, relying on 500 ms P2P detection — affects when partner-disconnect data paths fire.
14. **`data_emission` list-wrapping**: static values wrapped `{k: [v]}` before DataFrame construction; radio/checkbox/select extraction rules live client-side.

**Bottom line**: the legacy scientific record is a client-buffered, filename-keyed, last-write-wins CSV/JSON tree whose only delivery guarantees are one ack'd retry loop (multiplayer episodes) and one append-only JSONL (matches). The 0.2 contracts flip authority to a server-side append-only accepted stream with digests and receipts. Carry over: the canonical/speculative frame discipline, bilateral frame-window equality, partial-session vocabulary, per-episode chunked flush. Close: the loss windows in §2 — partial-episode discard on abnormal end being the most scientifically damaging.
