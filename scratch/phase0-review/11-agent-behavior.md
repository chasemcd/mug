# 11 — Agent behavior: scheduling, providers, tools, memory

| Field | Value |
| --- | --- |
| User | Researcher defining AI agents (scripted, RL, or LLM) that act in interactions |
| Goal | Define how a bot/LLM decides, calls tools, and remembers — with slow decisions never freezing the game and everything reproducible |
| Backing contract | [API-12](../../docs/architecture/phase-0/api-12/index.md) (scheduler) · [API-13](../../docs/architecture/phase-0/api-13/index.md) (providers) · [API-14](../../docs/architecture/phase-0/api-14/index.md) (tools) · [API-15](../../docs/architecture/phase-0/api-15/index.md) (memory) |
| Status | ✅ all 8 decisions approved (see [DECISIONS.md](DECISIONS.md)) |

## What the user is trying to do

"My AI partner should be an LLM with a system prompt, able to call a search tool, that
remembers what happened earlier in the session — and it must not freeze the game while
it's 'thinking.' For a baseline I also want a fast scripted bot and an RL policy from
an ONNX file."

### Today (what we're replacing)

Current MUG has scripted `HeuristicPolicy` classes, ONNX RL policies (`ModelConfig`),
and human/random, all keyed by `policy_mapping`; bots run client-side in Pyodide (ONNX
via `onnx_inference.js`, heuristics in-browser). What's missing is a first-class,
non-blocking path for *slow* agents (LLMs, tools) and structured memory. We keep the
fast-policy capability and add the async LLM/tool/memory model.

## The model: agents decide asynchronously; the game never waits

```text
GAME LOOP (synchronous, never blocks)
   │  needs an action for an agent seat
   ▼
SCHEDULER (API-12)  ── submits an immutable DecisionRequest ──▶  slow work off the hot path
   │                                                              (LLM call · tool call · memory read)
   │  a result is accepted ONLY if its episode/observation/deadline/validity still match
   ▼                                                              stale/late decision → discarded
apply action  ──or, on timeout/staleness──▶  explicit FallbackPolicy (default / repeat-last)
```

The north-star guarantee: **a slow or failed LLM/tool decision never freezes a game
frame, human input, or heartbeat.**

## What the user writes

### Fast policies (preserved from today)

```python
class GreedyBot(mug.Policy):                        # scripted/heuristic, Python
    def act(self, env, agent_id):                   # full ENV (not just obs) + which agent it decides for
        return ForagingAction.GRAB                  # can inspect complete env state, like today's HeuristicPolicy

rl = mug.OnnxPolicy("greedy.onnx")                  # RL policy: consumes that agent's observation vector
```

Scripted policies decide from the **environment and the `agent_id`** (privileged full-state
access, matching current MUG heuristics) — not limited to the observation. RL/ONNX
policies consume the agent's observation; LLM agents are prompt/context-driven.

### An LLM agent (immutable, versioned with the study)

```python
from mug import LLMAgent, Provider, Tool, Memory, MemoryScope, MemoryMode, Fallback

partner = LLMAgent(
    provider=Provider.OPENAI,                      # typed provider (F-3)
    model="gpt-5",                                 # the provider's own model id (their vocabulary, a string)
    prompt="You are a cooperative foraging partner…",
    tools=[Tool.mcp("search"), grab_tool],         # native + MCP tools
    memory=Memory(scope=MemoryScope.EPISODIC, mode=MemoryMode.ISOLATED),
    secret="chat-provider-key",                    # by key, never a credential (D07-6)
    decides_every=4,                               # frame_skip: act every 4 frames (was in surface 10)
    on_timeout=Fallback.REPEAT_LAST,               # explicit fallback if it's slow/stale
)
# cast into a seat (surface 07): cast={"forager-2": Actor.agent(partner)}
```

## What happens behind the scenes

| Author action | Contract behavior (API-12–15) |
| --- | --- |
| any agent decision | The **scheduler** submits an immutable `DecisionRequest`; slow provider/tool work runs off the game's hot path (API-12). |
| a decision returns | Accepted only if episode generation, observation, deadline, and validity window still match; a **stale decision is discarded, never applied** across an episode boundary. |
| `on_timeout=…` | Timeout/staleness resolves via an explicit **`FallbackPolicy`** — the game always gets *an* action, never hangs. |
| `decides_every=4` | The policy's **decision cadence** (frame_skip) — how often this agent selects an action; a property of the agent, not human input (D10-3). |
| `LLMAgent(...)` | Pins provider/model/params/prompt/tools/fallback as an **immutable agent version** (D07-4); references the secret **by key**; usage/cost/errors and the resolved model are recorded as exposure (API-13). |
| `tools=[…]` | Tool versions are **immutable with egress allowlists**; a **mutating tool call requires approval**; results are recorded and **substitute during replay** (API-14). |
| `memory=Memory(...)` | Working/episodic/longitudinal memory with a **treatment mode** (shared/isolated/ablated); immutable reads, compare-and-swap writes with provenance; a stale decision can't commit memory (API-15). |

## Decisions to review

Mark each `Status:` line.

### D11-1 — Three policy kinds, all versioned in the study repo; scripted policies get env + agent_id
Scripted/heuristic Python policies (`act(env, agent_id)` — **full environment access**
plus the agent id, matching current MUG heuristics), ONNX RL policies (consume the
agent's observation), and LLM agents — all defined in the study repo and versioned with
it (D07-4). All client-side capable where applicable.
- **Why it matters:** keeps the fast-bot and RL workflows MUG already has — including scripted bots' privileged full-state access and per-agent decisions — and adds LLM agents in the same casting model (surface 07). Reproducible because they're part of the study version.
- **Status:** ✅ approved

### D11-2 — Slow agent decisions are scheduled asynchronously; the game never blocks
An async scheduler runs LLM/tool/memory work off the hot path; a game frame, human
input, and heartbeat are never blocked by a thinking agent.
- **Why it matters:** the core reason MUG can mix real-time humans with slow LLMs — without it, one slow model call freezes everyone. Invisible to the author beyond declaring the agent.
- **Status:** ✅ approved

### D11-3 — Stale decisions are discarded; timeout/staleness resolves via an explicit fallback
A decision is applied only if it still matches its episode/observation/deadline/validity
window; otherwise it's dropped and a declared `Fallback` (default action / repeat-last)
fills in.
- **Why it matters:** a late LLM reply can't act on a stale game state or cross an episode boundary, and the game never hangs waiting — correctness *and* liveness.
- **Status:** ✅ approved

### D11-4 — LLM agents are immutable versions: provider/model/prompt/tools/fallback pinned; secret by key; usage recorded
An LLM agent pins everything that determines its behavior and references credentials by
key only; token usage, cost, errors, and the resolved model are recorded as exposure.
- **Why it matters:** reproducibility ("the AI partner in wave 1"), cost visibility, and the secret boundary (F-2/D07-6) all hold. Trade-off: changing a prompt/model is a new agent version.
- **Status:** ✅ approved

### D11-5 — Tools (native + MCP): immutable versions, egress allowlists, approval for mutations, replay substitution
Agents can call tools; each tool version is immutable with an egress allowlist, a
mutating call needs approval before it runs, and recorded results substitute during replay.
- **Why it matters:** agent tool use is safe (no ungoverned network egress, no un-approved side effects) and reproducible (replays don't re-fire real side effects). MCP support opens the tool ecosystem.
- **Settled:** **both native Python tools and MCP** ship in v0 — simple in-repo tools *and* the MCP ecosystem.
- **Status:** ✅ approved

### D11-6 — Agent memory has a treatment mode (shared / isolated / ablated)
Working/episodic/longitudinal memory is configurable, and its **treatment mode** makes
memory an experimental variable isolated across actors and conditions.
- **Why it matters:** memory is often the thing being studied (does the agent remembering help/hurt?); treatment isolation means one condition's memory can't leak into another. Trade-off: a real concept for authors to learn, but only when they use memory.
- **Status:** ✅ approved

### D11-7 — All-agent runs launch via `mug simulate`, headless by default (settles D07-8)
An interaction with no human seats (D07-8) is run by `mug simulate study@version --n 100`
— N all-agent runs, headless (no renderer), data captured like any run; `--render` to
watch one for debugging. The scheduler drives all decisions.
- **Why it matters:** unlocks agent-only simulations, baselines, and pilot data as a first-class, scriptable batch operation — the non-participant launch path D07-8 required.
- **Status:** ✅ approved

### D11-8 — Agents implement the MUG interface; external frameworks are wrapped, not native (v0)
Agents must implement MUG's `Policy`/`LLMAgent` interface. External frameworks
(LangChain/LangGraph/AutoGen/…) can be *wrapped* to fit, but MUG owns the
decision/scheduling/tool-approval/memory/replay contracts — v0 does not run a foreign
framework's own agent loop directly.
- **Why it matters:** keeps the reproducibility, scheduling, and replay guarantees intact (a foreign loop's internal LLM/tool calls would bypass the scheduler and approval/replay boundaries). Trade-off: existing framework agents need a thin wrapper.
- **Status:** ✅ approved

## Settled (your calls)

- **Providers (D11-4) → OpenAI, Anthropic, local/OSS (Ollama, vLLM), and a generic HTTP provider** all ship typed in v0.
- **Tools (D11-5) → native Python + MCP both.**
- **Framework interop (D11-8) → MUG interface only for v0** (external frameworks wrapped).
- **Simulation (D11-7) → `mug simulate`, headless by default**, `--render` to debug.
