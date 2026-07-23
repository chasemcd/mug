# Dimension 7 — Client-Side Automated Policies & Determinism Infrastructure

| Field | Value |
| --- | --- |
| Audit date | 2026-07-19 |
| Sources | `mug/server/static/js/{onnx_inference,heuristic_policies,seeded_random,phaser_gym_graphics}.js`, `mug/scenes/gym_scene.py`, `mug/configurations/configuration_constants.py`, `mug/server/remote_game.py`, examples (slime_volleyball, cogrid) |
| Contracts mapped | API-05, API-12, API-13, API-16 (rev 0.2) |

## 1. Mechanism map

### 1.1 Declaring a policy seat (config surface)

- Seats declared via `GymScene.policies(policy_mapping=..., load_policy_fn=..., policy_inference_fn=..., frame_skip=...)` (`gym_scene.py:393-440`). Defaults: `policy_mapping={}`, `frame_skip=4`.
- `policy_mapping` values may be: `PolicyTypes.Human` (`"human"`) or `PolicyTypes.Random` (`"random"`); a `ModelConfig` dataclass with `onnx_path` (ONNX seat); a `HeuristicPolicy` **subclass** (the class itself — instances rejected, `gym_scene.py:462-467`).
- `_decompose_model_configs()` (`gym_scene.py:442-467`) rewrites the mapping: a `ModelConfig` becomes its bare `onnx_path` string plus its `to_dict()` in `policy_configs[agent_id]`; a `HeuristicPolicy` subclass becomes `"heuristic:<ClassName>"` plus `{"type": "heuristic", "name", "code": <full module source text>}` from `to_config()` (`configuration_constants.py:226-254`) — which refuses classes defined in `__main__` or without a locatable source file.
- The whole scene (policy mapping, configs, `frame_skip`, `default_action`, `action_population_method`) ships to the browser via `scene_metadata`. **Policy detection client-side is purely string-shaped**: `.onnx` suffix ⇒ ONNX, `heuristic:` prefix ⇒ heuristic, `"random"` ⇒ random (`phaser_gym_graphics.js:606-621`).
- `_auto_infer_multiplayer()` sets `pyodide_multiplayer=True` only when there are ≥2 `"human"` seats.
- `ModelConfig` fields (`configuration_constants.py:107-114`): required `obs_input`, `logit_output`; optional `onnx_path`, recurrent triple `state_inputs`/`state_outputs`/`state_shape`, `fixed_inputs` (constant scalar feeds), `custom_inference_fn` (inline **JavaScript source string** — an escape hatch).

### 1.2 ONNX path (browser)

- **Runtime**: onnxruntime-web **1.10.0 loaded from cdnjs CDN** as global `window.ort` (`index.html:335`), WASM execution provider only.
- **Model loading**: lazy, on first inference — `InferenceSession.create(policyID, ...)` where the `onnx_path` string **is a URL** resolved against the Flask server (researchers expose model dirs via `ExperimentConfig.static_files()`). Sessions cached in module-level `loadedModels` keyed by path.
- **Observation preprocessing** (`onnx_inference.js:84-139`): flatten nested arrays; coerce to `Float32Array`; dict observations flattened by **sorted key order** and concatenated; batch dim of 1; single input tensor `[1, len]`. Observations come from `currentObservations` — the env's post-step obs of the previous frame.
- **Feeds**: declarative path uses `obs_input`, per-agent hidden-state tensors (zero-init from `state_shape`), and `fixed_inputs`; a legacy fallback hardcodes `obs`, RLlib `state_in_*` autodetection with `[1, 256]`, and `seq_lens`.
- **Postprocessing**: logits from `logit_output` → numerically-stabilized softmax → **stochastic categorical sampling** using `seeded_random.getRandom()`.
- **Recurrent state**: per-agent `hiddenStates` updated from `state_outputs` each call. **Never reset on episode boundaries, scene re-entry, or rollback** — module-level and untouched by `initModelConfigs`. LSTM state leaks across episodes.
- **`custom_inference_fn`**: compiled once per agent via `AsyncFunction(session, observation, modelConfig)` and given full control — bypasses softmax, sampling, and the seeded RNG entirely.
- **Cadence & buffering** (`phaser_gym_graphics.js:599-653`): for bot seats, when `step_num % frame_skip == 0`, `queryBotPolicy` fires **fire-and-forget async**; the result is pushed to `botActionBuffers[agentID]` and consumed by `shift()` on a *later* frame — an ONNX action executes ≥1 frame after the observation it was computed from. Empty buffer → fallback `previous_submitted_action` (repeat-last) or `default_action` per `action_population_method`.

### 1.3 Heuristic path (browser)

- Author interface: subclass `HeuristicPolicy`, implement `compute_action(self, env, agent_id)` receiving the **live env instance** (privileged full state). One instance per agent (instance attributes hold per-agent state).
- Execution: the shipped module source is `exec`'d inside the same Pyodide interpreter that hosts the env (`heuristic_policies.js:47-78`), including a shim injecting `HeuristicPolicy` into the in-Pyodide mug package if it predates the class. Called **synchronously** per decision frame, with the same numeric-string agent-id coercion and `.item()` unwrapping of numpy scalars.
- Cadence: same `frame_skip` gate; returns immediately (no buffer); on non-decision frames it falls to repeat-last/default (heuristics never populate `botActionBuffers`).

### 1.4 Where policies run; double execution

- **Single-player Pyodide**: browser only; bot actions merge into the same action dict as the human's.
- **Multiplayer P2P (GGPO)**: **both peers execute every bot policy locally, every frame — no designated authority, bot actions never exchanged.** Human seats take GGPO delayed/predicted inputs; bot seats take the locally computed value directly, with no `INPUT_DELAY` (`pyodide_multiplayer_game.js:2109-2122`). Consistency relies entirely on determinism: shared `game_seed` seeding both the JS Mulberry32 RNG and Python RNGs. Divergence is *detected* (per-frame state-hash exchange) and repaired by resync — not prevented.
- **Rollback interaction**: replay after a late input reuses **recorded** bot actions from the original execution rather than re-running policies — explicit `TODO: Ideally re-compute with correct RNG state for full determinism` (`pyodide_multiplayer_game.js:4645-4659`).
- **Server-authoritative mode**: a parallel CPython implementation in `RemoteGame`: `_load_policies()` exec's heuristic source; other policies defer to researcher-supplied `load_policy_fn`; `_get_bot_action()` calls heuristics with the live env, samples the action space for Random, or calls `policy_inference_fn(agent_id, policy, observation)`. **There is no server-side ONNX runtime** — an `.onnx` mapping value only works server-side if the researcher supplies both functions themselves.

### 1.5 Seeding / determinism inventory

- `seeded_random.js`: Mulberry32 PRNG + module singleton. `getRandom()` returns the seeded stream **only when multiplayer mode is active; otherwise plain `Math.random()`**. Reset to the original seed at every episode boundary alongside re-seeding Python RNGs and `env.reset(seed=gameSeed)`.
- Consumers of the seeded stream: **only ONNX `sampleAction`**. The `"random"` policy uses raw `Math.random()` even in multiplayer — a real divergence hole. `custom_inference_fn` gets no seeded RNG handle.
- `GymScene.env_seed` (default 42) is **dead config — no consumer anywhere** (verified by repo-wide grep). Single-player runs are entirely unseeded.
- Decision gate uses `step_num` (reset per episode), distinct from GGPO `frameNumber`.

## 2. Failure semantics

- **ONNX model load failure** (404, CORS, CDN down): rejects inside fire-and-forget `queryBotPolicy` **with no `.catch`** → unhandled promise rejection per decision frame; the buffer stays empty so the bot silently emits `default_action` (or repeats last) forever. No UI surfacing, no retry, no abort. If the CDN `ort.min.js` script fails, every query throws with the same silent-default outcome.
- **ONNX inference error mid-episode**: identical — silent fallback; episode continues.
- **Heuristic error (browser)**: try/catch at the call site — `console.error` then fall to buffer/repeat-last/default. Failed registration is retried (and re-fails) every decision frame.
- **Heuristic error (server-authoritative)**: **uncaught** — propagates out of `RemoteGame.step()` into the game loop tick (crash-the-game semantics, unlike the browser's degrade-to-default).
- **Missing policy config**: browser throws (caught); server logs a warning and stores `None` → permanent `default_action`.
- **Multiplayer divergence from policy nondeterminism**: not prevented, only detected/repaired; rollback replays recorded bot actions.

## 3. Contract mapping (0.2)

| Legacy mechanism | Contract | Verdict | Notes |
|---|---|---|---|
| `policy_mapping` values (string/path/class) | api-05 `ActorSpec`/`AgentActorSpec` with `agent_ref` name@version; `CastDeclaration` | **GAP** | No versioning, no identity: an ONNX seat is a mutable file path, a heuristic is a class name + whatever source is on disk at launch. The 3-kind split (scripted/ONNX/LLM) in the authoring spec maps cleanly; LLM is net-new. |
| String-shape dispatch (`.onnx` suffix, `heuristic:` prefix) | api-05 `ControllerBinding.controller_kind` closed enum + `controller_ref` | **GAP/IMPROVE** | Typed binding replaces stringly-typed detection. `SeatAgentBinding.env_agent_id` matches legacy's numeric-string coercion pain point. |
| `frame_skip` scene-global, all bot seats, also consumed by rendering | api-12 `ControllerPolicy.decides_every` — per-policy | **GAP** | Legacy is scene-global, not per-agent; and server-auth mode **ignores frame_skip entirely** (bots decide every tick) — a client/server parity break the rewrite must not reproduce. |
| Empty-buffer fallback: `action_population_method` | api-12 `Fallback` enum `repeat-last`/`default-action`; mandatory for realtime seats | **PARITY (semantics) / GAP (declaration)** | The two behaviors match one-to-one. But legacy fallback is scene-wide and shared with *human* input population; contract requires explicit per-policy declaration and separates human `on_no_input` (api-09) from policy fallback. |
| Async ONNX query + `botActionBuffers` | api-12 `DecisionRequest`/`DecisionResult`/`SchedulerState` | **GAP** | Legacy has the germ of the scheduler (non-blocking async decision — D11-2 already true for ONNX) but: no decision identity, no `episode_generation` guard (**a stale in-flight ONNX result from just before `env.reset()` can be consumed after the reset** — single-player buffers are not cleared on episode transition; multiplayer clears queues at reset), no deadline, no validity window, no staleness classification, no source-observation digest. Heuristics are synchronous in-frame — fine only because they're fast. |
| Decision evidence | api-12 `DecisionResult.action_digest`; api-16 `DecisionTape`; api-10 evidence | **GAP (the big one)** | In-browser policies record **no decision-level evidence**: no record of which observation a decision consumed, model identity/digest, logits, RNG state at sampling, or fresh-vs-fallback status. Deterministic replay of legacy bot behavior is action-replay only. The rewrite's DecisionTape can be fed from the action log for repeat-value fidelity, but tape entries reference `modelcall_id`s legacy cannot supply. |
| Seeded Mulberry32 + shared game_seed + episode reset-to-seed | api-16 determinism declaration + `StateHashCheck` | **PARITY (foundations) / IMPROVE** | Legacy already has the env-hook triple in P2P. Contract makes determinism a *declared capability*; legacy silently degrades. Keep the reset-to-original-seed-per-episode semantics or hash-chain continuity across episodes breaks. |
| `custom_inference_fn` (inline JS, full session control) | no contract counterpart | **GAP (decide)** | Arbitrary code injected from Python config into the client. Unversioned, undigested, bypasses seeded sampling. Either becomes a versioned artifact of the OnnxPolicy spec or is dropped. |
| ONNX seat authoring | authoring spec `OnnxPolicy(...)` | — | **What OnnxPolicy must carry** (from legacy `ModelConfig`): model artifact ref **with digest/version** (not a mutable URL); tensor binding (`obs_input`, `logit_output`); recurrent triple **plus explicit hidden-state lifecycle (reset on episode start; snapshot/restore for rollback — both missing today)**; `fixed_inputs`; observation canonicalization rule (flatten + **sorted-key dict concat** + float32 — must be pinned/digested, since it silently defines the model's input contract); action-selection mode (categorical-sample vs argmax) + RNG stream binding; `decides_every`; `fallback`; execution provider/runtime version pin (today an unpinned CDN global). |
| LLM seats | api-13 `AgentVersion`/`Provider` | **GAP (net-new)** | No legacy counterpart. `load_policy_fn`/`policy_inference_fn` are the legacy "bring your own provider" escape hatch api-13 replaces. |
| P2P double-execution of policies | api-12 scheduler model (one logical decision per request) | **GAP (architectural)** | Legacy P2P has two independent executions reconciled only by hash-detect-and-resync; rollback substitutes recorded actions (a de-facto decision tape). A rewrite keeping browser-local execution needs either a designated decision authority per bot seat (record on one peer, stream to the other) or a proof obligation that the decision function is a pure function of (seeded RNG state, obs) — which the async buffer timing breaks today. |

## 4. Intricacies register

1. **One-frame (minimum) decision-to-action lag for ONNX** — buffered FIFO consumption. Heuristics have zero lag. Making ONNX synchronous changes bot timing observed by participants.
2. **Observation snapshot semantics**: ONNX consumes the previous frame's post-step obs captured at query time; heuristics/scripted read the **live env at execution time**. Different information sets per policy kind.
3. **Dict-observation flattening is sorted-by-key** — models are trained against this implicit ordering; changing it silently breaks every existing model.
4. **Numeric-string agent-id coercion** in three places must stay consistent: obs lookup, heuristic call, env step.
5. **Seeded RNG is consumed only by ONNX categorical sampling** — RNG-stream alignment across peers depends on both peers making the *same number* of `getRandom()` calls in the same order; any per-peer difference in inference count desynchronizes all subsequent sampling. `"random"` policies and `custom_inference_fn` are outside the seeded stream.
6. **Episode-boundary RNG reset**: JS RNG resets to the original seed and Python RNGs re-seed with the *same* seed each episode — episodes are RNG-identical, not a continuing stream. Env also resets with `seed=gameSeed` every episode.
7. **Recurrent hidden state never resets** across episodes/scenes and is invisible to snapshots/rollback — a determinism hole to fix; note some deployed studies' bot behavior implicitly includes it.
8. **Module-level caches keyed by path/agent** (`loadedModels`, `compiledCustomFns`): two agents sharing one `.onnx` path share one session (fine); a changed `custom_inference_fn` for the same agent id in a later scene is masked by the cache.
9. **Fallback duality**: `previous_submitted_action` repeats the *entire previous action* (including a prior fallback), and the same `action_population_method` governs both human and bot gap-filling, browser and server.
10. **frame_skip client/server asymmetry**: honored only in the browser; gates on `step_num`, which resets per episode.
11. **Bot actions bypass GGPO input delay** — humans act through the delayed buffer, bots act same-frame; relative human/bot reaction timing depends on `input_delay`.
12. **Rollback replay does not re-run policies** — it substitutes recorded bot actions; the only place legacy behaves like the api-16 tape model, and it's labeled a TODO.
13. **Heuristic code shipping = whole module source exec'd** in Pyodide and in CPython — arbitrary code execution by design; classes must be arg-less-constructible, self-contained modules; a `HeuristicPolicy` shim is injected for older in-Pyodide packages.
14. **Silent-degradation failure posture in the browser** (bot freezes to default with console noise only) vs crash posture on the server — the typed `DecisionResult.outcome=failed` + fallback should replace both; note participants today can complete episodes against a dead model with nothing recorded.
15. **`env_seed` is dead config** — single-player runs, including bot studies, are entirely unseeded and unreproducible today; only P2P multiplayer gets seeds.
16. **onnxruntime-web pinned at 1.10.0 via CDN global** — not self-hosted, not integrity-pinned; model opset compatibility implicitly frozen to that runtime.
