# Hooking an LLM into MUG -- platform internals

> **Defining a study? You are in the wrong file.** A study author writes about eight
> lines and sees none of this -- see `llm-agent-quickstart.md`. This file is the
> platform-builder view of what runs *under* that `LLMAgent(...)` facade: the
> provider adapter, the recorded model call, the scheduler, and the seat bridge. Read
> it only if you are building or debugging the machinery.

This note shows the machinery beneath the author-facing `LLMAgent`: how to write a
provider adapter, how the model call is recorded, how the scheduler turns a model
call into a seat action, and how that action reaches the game loop. Every symbol
below is real and built (P3b `mug.providers.runtime`, P3c `mug.scheduling.runtime`,
and `mug.game.controllers`).

The one rule to keep in mind: **the core imports no vendor SDK and never records a
secret.** A study injects the vendor call as an adapter, and the runtime resolves
the credential by name at call time and passes it to the adapter alone.

---

## The pieces

```
AgentVersion            a pinned build: provider + model + prompt + secret NAME
     │
ProviderAdapter         a study async fn: (payload, secret) -> completion   [vendor lives here]
     │
ModelProvider.invoke    records ProviderRequest -> calls adapter -> records ProviderResponse/Error
     │
AsyncController         a study async fn: observation -> action   (composes the provider)
     │
Scheduler.decide        awaits the controller under a deadline -> records DecisionResult -> fallback
     │
ScheduledSeat.apply     holds the decided action
     │
run_episode             samples the seat each frame through SeatActionSource.decide
```

The scheduler and the provider are **siblings** in the layer graph, so neither
imports the other. The glue that joins them (`llm_controller` below) lives in the
study, above both.

---

## 1. Write a provider adapter (the only vendor-facing code)

The adapter is any async callable of the shape
`ProviderAdapter = Callable[[ModelCall], Awaitable[ModelCompletion]]`. The runtime
hands it the rendered payload and the resolved secret; the adapter returns a
completion with the raw output and the usage.

```python
from anthropic import AsyncAnthropic  # a study dependency, NOT a core one

from mug.providers import ModelCall, ModelCompletion, Usage

async def anthropic_adapter(call: ModelCall) -> ModelCompletion:
    # `call.secret` is the credential the runtime resolved by name. Use it here
    # and nowhere else -- it must not enter a record, a log, or the return value.
    client = AsyncAnthropic(api_key=call.secret)
    reply = await client.messages.create(
        model=call.model_selector,
        max_tokens=256,
        messages=call.payload["messages"],
    )
    return ModelCompletion(
        outcome="completed",
        resolved_model=reply.model,
        usage=Usage(
            input_tokens=reply.usage.input_tokens,
            output_tokens=reply.usage.output_tokens,
            cost_micros=0,
        ),
        output={"text": reply.content[0].text},
    )
```

An adapter may also return `outcome="refused"` (no output) or `outcome="error"`
(with `error_class` and `retryable`); the runtime records each as its own terminal
state. For a timeout or a rate limit, catch the vendor error and return
`ModelCompletion(outcome="error", error_class="rate-limit", retryable=True, ...)`.

For tests and the `mug simulate` runner, use the built-in deterministic
`FakeProvider(respond)` instead of a vendor adapter -- it needs no network and no
key.

---

## 2. Declare the agent build and resolve the secret

The `AgentVersion` names the provider, the model, and the credential **by name**.
The value is bound at deploy time as a `SecretRef` (see `mug.platform`) and resolved
at call time through an injected `SecretResolver = Callable[[str], str]`.

```python
from mug.providers import AgentVersion

agent = AgentVersion(
    agent_version_id="agentver_...",
    agent_definition_id="agentdef_...",
    agent_key="foraging-partner",
    version_number=1,
    provider="anthropic",
    model_selector="claude-sonnet-4-5",
    prompt_version_id="promptver_...",
    parameters_digest=<digest of the sampling parameters>,
    tool_version_ids=[],
    fallback_policy_key="foraging-fallback",
    secret_name="chat-provider-key",   # a name, never the value
)

# The deployment supplies this; it reads the value from the bound SecretRef.
def resolve_secret(name: str) -> str:
    return deployment_secrets[name]
```

---

## 3. Run one model call

`ModelProvider.invoke` records the request, calls the adapter, and records the
outcome. It returns the raw output to the caller and persists only its digest. A
retry with the same `modelcall_id` replays the recorded outcome **without calling
the model again** (no double spend).

```python
from mug.providers import ModelProvider

provider = ModelProvider(
    store=store,
    adapter=anthropic_adapter,        # or FakeProvider(...) in a test
    now=clock,                        # () -> datetime
    new_generation_id=mint_generation_id,
)

result = await provider.invoke(
    modelcall_id="modelcall_...",     # content-addressed by the caller
    agent_version=agent,
    payload={"messages": [{"role": "user", "content": "..."}]},
    new_context=new_context,          # (aggregate_id) -> CommandContext, minted by the gateway
    resolve_secret=resolve_secret,
)
# result.output -> {"text": "..."}   (raw, transient)
# result.response.usage             (recorded)
```

`new_context` is the one entropy-and-clock boundary: a factory that mints a fresh
`CommandContext` on the call's stream, exactly as every family service takes one.

---

## 4. The prompting pipeline: game frame -> text -> prompt -> action

The `render` and `parse` in the controller below are not one function each -- they
are the two ends of a five-stage pipeline the API-12 catalog names. This is where
"the representation of the game in text" and "how that text becomes a prompt" live.

```
DecisionContextSnapshot        env state + agent id + memory_view + policy   (env-neutral container)
      │  ObservationEncoder.encode(env, agent_id)    ← reads the FULL env, not a flat obs array
      ▼
EncodedObservation             ← the game state, as text            (ENV-SPECIFIC serializer)
      │  assemble with PromptTemplateVersion  (system prompt + instructions + output contract)
      ▼
provider payload (messages)    ← the text, integrated into a prompt
      │  ModelProvider.invoke                                        [built -- §3]
      ▼
ProviderResponse (raw output)
      │  ActionDecoder.decode(response, allowed_intents)
      ▼
DecodeResult -> action         (constrained to the seat's legal actions; else a decode miss)
```

Your two questions map to two distinct stages: the **encoder** turns the frame into
text, and the **assembly** splices that text into a pinned **template**.

### The encoder reads the environment, not the observation array

A policy's observation is often a flat float array -- fine for a neural net, close to
useless for text. So the encoder does **not** take the observation vector. It takes
the **environment** (the object that holds the real, semantic state: the grid, the
piece positions, the inventories, the other agents, the tick) and the **agent id**
(which agent's perspective to render, e.g. `agent-0` from the seat's
`SeatAgentBinding.env_agent_id`). A multi-agent env is egocentric, so the same frame
encodes differently for each seat; the agent id selects the point of view.

```
encode(env, agent_id) -> str
```

The encoder reads the env **once, synchronously, at the decision frame** -- before the
model call awaits -- and does not retain the reference. In the server execution mode
the scheduler decides between frames, so the env is at a known, settled frame when the
encoder reads it. The observation array, if the encoder wants it at all, is just one
field it can pull from the env; it is no longer the interface.

### Who owns each stage, and what pins it

The stages are separate because each has a different owner and a different lifecycle.
This is the whole reason it is a pipeline and not one format string.

| Stage | Owner | Pinned by | Why it is separate |
|---|---|---|---|
| `ObservationEncoder` (env + agent id -> text) | **study code** | the env build | grid-to-text is environment-specific; the core cannot hold it |
| `PromptTemplateVersion` (system prompt, instructions, output format) | **authored content** | `prompt_version_id` (`promptver_`) | edited and versioned with no code change; reusable across studies |
| sampling parameters (temperature, max tokens) | authored | `parameters_digest` | pinned so a run reproduces |
| `ActionDecoder` (output -> discrete action) | **study code** | the env build | maps model output onto the env action space, with a legal-move guard |

The `AgentVersion` (§2) already references all of these -- `prompt_version_id`,
`parameters_digest`, `tool_version_ids`. It is the pinned bundle; the encoder and the
decoder are the study code that bookends it.

### The rule that shapes it: the encoder is deterministic

MUG replays and verifies a decision, so every input to the model call is
content-addressed:

- `DecisionRequest.source_observation_digest` pins the exact env state the encoder
  read -- the env's **canonical state** at the decision frame (the same
  `get_state()` MUG already hashes for its determinism check), not the flat obs array,
- `prompt_version_id` pins the exact template,
- `parameters_digest` pins the exact sampling parameters,
- `ProviderRequest.request_digest` pins the exact assembled payload,
- the API-16 decision tape records the whole call for replay.

So reading "the environment itself" does not weaken replay -- it strengthens what the
digest must cover: the digest is over the canonical env state the encoder consumes, so
`encode(env, agent_id)` **must be deterministic** -- the same env state and agent id
must produce byte-identical text, and thus the same `request_digest`. An encoder that
reaches for the wall clock, a set iteration order, or a hash seed breaks replay. This
is why the design promotes the encoder from "a lambda over an array" to "a pinned,
deterministic function of the settled env state".

### A worked example: a grid game

The encoder turns one frame into a stable block:

```
You are the chef at station ▲. Grid 5x3, tick 42:
  # # # # #
  # . P . #        P = you   o = onion   D = delivery
  # o . D #
Inventory: [onion]
Legal actions: UP, DOWN, LEFT, RIGHT, INTERACT, NOOP
```

The `PromptTemplateVersion` supplies the fixed frame around that block -- a system
message ("You play a cooperative cooking game. Reply with exactly one action token."),
the output contract, and the slot the encoded block fills. Assembly produces the
`messages` payload for §3. The decoder reads the reply, matches it against
`allowed_intents` (`UP` .. `NOOP`), and returns the discrete action -- or, on an
illegal or garbled reply, reports a **decode miss**, so the scheduler fallback fires
(the `repeat-last` / `default-action` path from §6).

```python
# Pseudocode for the two study-owned ends. Both are deterministic.

def encode(env, agent_id) -> str:                 # ObservationEncoder
    state = env.get_state()                        # the canonical, hashable env state
    grid = draw_grid(state, viewer=agent_id)       # egocentric; stable row/col order, no wall clock
    legal = ", ".join(env.legal_actions(agent_id)) # a fixed order
    return f"Grid {state.w}x{state.h}, tick {state.tick}:\n{grid}\nLegal actions: {legal}"

def assemble(encoded: str, template: PromptTemplateVersion) -> dict:
    return {"messages": [
        {"role": "system", "content": template.system},
        {"role": "user", "content": template.instructions + "\n\n" + encoded},
    ]}

def decode(output, allowed_intents) -> int | None:   # ActionDecoder
    token = str(output["text"]).strip().upper()
    return allowed_intents.index(token) if token in allowed_intents else None  # None -> fallback
```

### What is built here, and what is not

- **Built (§3, §6):** the model call, the timing, the recording, and the fallback --
  everything *around* the prompt.
- **Not built, not yet frozen:** `PromptTemplateVersion` has an id kind reserved
  (`promptver_`) but no frozen record schema; `ObservationEncoder`, `ActionDecoder`,
  and `DecisionContextAssembler` are catalog protocols, not code. The `render` and
  `parse` in §5 are the minimal stand-ins for the encoder + assembly + decoder. The
  built `DecisionContext` carries only `observation: Any`; the encoder seam refines it
  to carry the `env` handle and the `agent_id`. The next sub-phase freezes the template
  record, refines the context, and builds the encoder/decoder seam.

---

## 5. Compose the provider into a scheduler controller

The scheduler is controller-agnostic: it awaits an
`AsyncController = Callable[[DecisionContext], Awaitable[int]]`. The study writes the
`render` (the encoder + template assembly of §4) and the `parse` (the decoder of §4);
these are environment-specific, so they never live in the core.

`render` takes the **environment and the agent id**, not an observation array (§4).
Those reach the controller through the decision context: the encoder seam gives
`DecisionContext` an `env` handle and an `agent_id` (the seat's
`SeatAgentBinding.env_agent_id`, resolved from `request.actor_id`). The built
`DecisionContext` today carries only `observation: Any`; carrying `env` + `agent_id`
is the refinement the encoder seam adds.

```python
from mug.scheduling.runtime import AsyncController, DecisionContext

def llm_controller(*, provider, agent, template, resolve_secret, new_context) -> AsyncController:
    def render(env, agent_id) -> dict:
        encoded = encode(env, agent_id)             # §4: reads the full env, egocentric
        return assemble(encoded, template)          # §4: splice into the pinned template

    def parse(output, allowed_intents) -> int | None:
        return decode(output, allowed_intents)      # §4: constrained, or None -> fallback

    async def decide(ctx: DecisionContext) -> int:
        modelcall_id = "modelcall_" + ctx.request.decision_id.split("_", 1)[1]
        result = await provider.invoke(
            modelcall_id=modelcall_id,
            agent_version=agent,
            payload=render(ctx.env, ctx.agent_id),   # env + agent id, read at the decision frame
            new_context=new_context,
            resolve_secret=resolve_secret,
        )
        action = parse(result.output, ctx.env.legal_actions(ctx.agent_id))
        if action is None:
            raise ValueError("decode miss")          # the scheduler applies the seat fallback (§6)
        return action

    return decide
```

This factory is the entire "LLM hookup". The scheduler that awaits it never sees the
provider or the env; it just gets an action (or a decode miss, which it turns into the
seat fallback).

---

## 6. Decide under a deadline, with a fallback

`Scheduler.decide` awaits the controller against the request deadline. A result that
arrives in time is **produced**; one that arrives late is **timed out**; a controller
that raises is **failed**. A non-produced decision applies the seat fallback, so the
seat always has an action. Both the request and the result are recorded.

```python
from mug.scheduling import DecisionRequest, FallbackRule, Scheduler

scheduler = Scheduler(
    store=store,
    now=clock,
    fallback=FallbackRule(on_timeout="repeat-last", on_stale="repeat-last"),
    default_action=NOOP,
)

request = DecisionRequest(
    decision_id="decision_...",
    actor_id="actor_...",
    channel_key="game",
    execution_mode="server",
    episode_generation=1,
    source_observation_digest=digest_of(observation),
    deadline="2026-08-02T12:05:00.200000Z",
    validity_window=Duration(microseconds=200000),
    submitted_at="2026-08-02T12:05:00.000000Z",
)

outcome = await scheduler.decide(
    request=request,
    observation=observation,
    controller=llm_controller(provider=provider, agent=agent,
                              resolve_secret=resolve_secret, new_context=new_context),
    new_context=new_context,
    last_action=seat.current(),   # for a repeat-last fallback
)
# outcome.action        -> the action to apply (decided, or fallback)
# outcome.used_fallback -> True when the model missed the deadline or failed
```

---

## 7. Bridge to the game loop

`ScheduledSeat` is the held-action bridge. The scheduler decides off the frame clock
and calls `apply`; the loop samples the held action each frame through the same
`SeatActionSource` seam a person's input uses. A slow model never blocks a fast
frame.

```python
from mug.game.controllers import ScheduledSeat

seat = ScheduledSeat(default_action=NOOP)

# ... a decision loop, off the frame clock:
seat.apply(outcome.action)

# ... the game loop, on the frame clock (unchanged from a human seat):
summary = await run_episode(env, ..., seat_key="partner", input_state=seat, ...)
```

The decision loop and the frame loop run independently: the frame loop reads the
latest applied action; the decision loop refreshes it at the cadence a
`ControllerPolicy` declares (`decides_every`).

---

## What is proven, and what is deferred

Built and tested end to end (`tests/unit/providers/test_model_provider.py`,
`tests/unit/scheduling/test_scheduler.py`, `tests/unit/scheduling/test_llm_seat.py`):

- a model call records its request and outcome, with the output by digest;
- the resolved secret reaches the adapter and appears in no record;
- a retry replays the recorded outcome without a second call;
- a decision is produced / timed-out / failed and falls back correctly;
- an LLM decision drives a `ScheduledSeat`, which then steps the loop.

Deferred (the seams exist; the runtime does not yet):

- **peer-to-peer bot authority** -- a decision that runs on a peer, not the server
  (`P2PBotAuthority`, `execution_mode="p2p"`); it lands with the mesh phase.
- **the chat turn seam** -- an LLM as a `chat-message` controller (P3f); it reuses
  the same `ModelProvider`, without the frame-tick `SeatActionSource` bridge.
- **tools and memory** (P3d/P3e) -- an `AgentVersion` names `tool_version_ids`; the
  controller would call tools between the model call and the parse.
- **the decision tape** (API-16) -- the durable, replayable record of the applied
  action; the scheduler records the decision, and the tape records what the episode
  did with it.
- **autoregressive thoughts** -- the author-facing `thoughts` (the model's own
  reasoning carried across steps, written via `reflect`; see
  `llm-agent-quickstart.md`). Determinism constraint: a carried thought is model output
  that becomes an *input* to the next call, so it changes that call's `request_digest`.
  The thought text must therefore be recorded verbatim (the API-16 model-output tape)
  and replayed -- on replay the model is not re-called, so the recorded thought is what
  feeds the next prompt. `history`, `chat`, and `thoughts` are all read-only projections
  the controller assembles into the payload; none adds a new capture path, only a read.
  (The `chat` view exposes the interaction's chat channel, so a human partner can
  instruct an agent seat.)

## Layer note

`mug.scheduling` and `mug.providers` are siblings, so the `llm_controller`
composition lives in the study (or an app-layer module above both), never in either
family. The core stays vendor-free and environment-agnostic; the study injects the
adapter, the render, and the parse.
