# 07 — Seats, actors, human + LLM casting

| Field | Value |
| --- | --- |
| User | Researcher authoring a multi-party interaction |
| Goal | Say "this game has two roles; role 1 is a participant, role 2 is another human *or* an AI partner" — and swap humans/agents without rewiring the study |
| Backing contract | [API-05](../../docs/architecture/phase-0/api-05/index.md) (seats/actors/controllers) · [API-13](../../docs/architecture/phase-0/api-13/index.md) (agent versions) |
| Status | ✅ all 8 decisions approved (see [DECISIONS.md](DECISIONS.md)) |

## What the user is trying to do

"My foraging game has two players. Sometimes I want two humans paired together;
sometimes I want one human and one AI partner (as a between-groups condition). I
want to declare the *roles* once and cast humans or agents into them — without the
game code caring which is which."

### Today (what we're replacing)

Today "who plays which role" is tangled into the environment: a human is a socket, an
AI is an env agent ID, and swapping one for the other means rewriting the interaction.
There's no clean separation between the role, who fills it, and how they act. We keep
the outcome (human/human, human/AI, etc.) and separate the three cleanly.

## The model: seat → actor → controller

MUG's differentiator lives here — the same interaction can be driven by humans,
scripted policies, or LLMs, interchangeably — because three things are kept apart:

```text
SEAT            an authored role in the interaction        ("forager-1", "forager-2")
  ⟵ filled by
ACTOR           who/what fills it for one run              a human (enrollment)  XOR  a software agent (agent@version)
  ⟵ acts through
CONTROLLER      how that actor acts in a given channel     human input · scripted · RL policy · LLM
```

The payoff: role 2 can be a human today and an LLM tomorrow with **no change to the
game** — only the casting changes.

## What the user writes

### Single-player (the common case): nothing extra

Most studies have one participant. No seats, no casting — the participant is the
implicit actor. You only reach for this surface when there's more than one role.

### Two humans

```python
game = activities.Interaction(
    key="foraging",
    seats=["forager-1", "forager-2"],     # authored roles; both human by default → pair two participants
    spec=ForagingSpec(...),
)
```

### One human, one AI partner

```python
from mug import Actor

game = activities.Interaction(
    key="foraging",
    seats=["forager-1", "forager-2"],
    cast={"forager-2": Actor.agent("llm-partner@2")},   # role 1 human (default), role 2 an agent version
    spec=ForagingSpec(...),
)
```

### Human vs. AI partner as a condition (from surface 06)

```python
# `partner` is a Scope.GROUP treatment (D06-7): the whole pairing is human-human or human-AI
game = activities.Interaction(
    key="foraging",
    seats=["forager-1", "forager-2"],
    cast={"forager-2": partner.cast({"human": Actor.human(), "ai": Actor.agent("llm-partner@2")})},
    spec=ForagingSpec(...),
)
```

## What happens behind the scenes

| Author action | Contract behavior (API-05 / API-13) |
| --- | --- |
| `seats=[…]` | Each is an authored **`SeatDefinition`** — a role that exists before any actor fills it. |
| default (no cast) | The seat is filled by a **human `ActorInstance`** referencing an enrollment. |
| `Actor.agent("llm-partner@2")` | Fills the seat with a **software `ActorInstance`** referencing an **immutable agent version**. An actor is human **XOR** software — never both. |
| `partner.cast({...})` | Casting is resolved from the group's treatment assignment (D06-7) when the group forms, and recorded — so "this pair was human-AI" is in the data. |
| how an actor acts | A **`ControllerBinding`** maps one capability in one channel to one controller. Human input carries no controller; scripted/RL/LLM controllers reference one, and capability↔controller compatibility is enforced (a scripted policy can't drive a chat message). |
| LLM agent | The agent version pins provider/model/params/prompt/tools/fallback and references a secret **by key**; no credential appears (bound at deploy, surface 03). |

## Decisions to review

Mark each `Status:` line.

### D07-1 — Roles are separated from who fills them: seat vs actor
An interaction declares **seats** (authored roles); **actors** (humans or agents)
are cast into them per run. Single-player studies declare neither (implicit).
- **Why it matters:** the game is written against roles, so swapping a human for an AI (or vice versa) is a casting change, not a rewrite. Cost: a new concept for anyone doing multi-party studies (but zero cost for single-player).
- **Status:** ✅ approved

### D07-2 — An actor is a human XOR a software agent, never both
A human actor references an enrollment; a software actor references an immutable
agent version. Never a blend.
- **Why it matters:** clean, recordable identity — every seat in every run is unambiguously human or software, which the data and analysis depend on.
- **Status:** ✅ approved

### D07-3 — Casting is swappable and can be driven by a treatment
The same seat can be human or agent depending on a condition (human/AI partner
studies), assigned via a `Scope.GROUP` treatment (D06-7); human-takeover of an agent
seat is the same mechanism.
- **Why it matters:** this swappability *is* the point of separating seat from actor — it's what makes human/AI comparison and takeover studies first-class instead of custom code.
- **Status:** ✅ approved

### D07-4 — Agents live in the study repo, versioned with the study (`agent@version`)
An agent (scripted, RL, or LLM) is a Python class/config **in the study's git repo**,
compiled and versioned as part of the study — it rides on F-1, so one commit/version
stamp covers study + agents. Its behavior (code, or provider/model/params/prompt/
tools/fallback) is fixed and reproducible.
- **Why it matters:** one repo, one version — "the AI partner in wave 1" means the same thing in wave 3 because it's part of the same immutable study version. Trade-off: agents aren't reusable across studies without copying (a standalone `mug publish-agent` flow is deferred, not in v0).
- **Status:** ✅ approved

### D07-5 — One actor can act through different controllers per channel
An actor can drive the game with one controller (scripted/RL) and chat with another
(LLM); capability↔controller compatibility is enforced.
- **Why it matters:** supports rich agents that both act and talk, without conflating the two. Mostly relevant when an actor spans channels (developed in surface 08). Enforcement stops nonsensical bindings (a scripted policy "sending chat").
- **Status:** ✅ approved

### D07-6 — LLM/agent casting declares provider requirements + a secret key, never credentials
An LLM agent version names the provider/model it needs and references a secret by
key; the actual credential is bound at deploy (surface 03), never in the study.
- **Why it matters:** consistent with the secret boundary (F-2/D01-6) — authors cast an LLM partner without ever holding a key.
- **Status:** ✅ approved

### D07-7 — Matchmaking is author-declared pairing config
When human seats must be filled, the author declares a typed `Pairing` (F-3): group
size, how long to wait, and what to do on timeout. No hidden magic queue behavior.
```python
Interaction(
    seats=["p1", "p2"],
    pairing=Pairing(size=2, wait=Duration(seconds=90), on_timeout=OnTimeout.RELEASE),
    spec=ForagingSpec(...),
)
```
- **Why it matters:** pairing behavior is explicit and reproducible, not opaque platform luck. Sensible defaults keep the simple case light (size = number of human seats, a standard wait).
- **Note:** `on_timeout` in v0 is `RELEASE` (return the waiting participant / mark unpaired) — **agent-backfill on timeout is deferred** (see D07-8), keeping it consistent with "no agent takeover of a human seat in v0."
- **Status:** ✅ approved

### D07-8 — All-agent interactions are allowed; agent-backfill of a human seat is not (v0)
An interaction may cast **every** seat to an agent (multi-LLM/scripted simulations,
baselines, pilot data) — these launch via a **researcher/scheduler**, not a
participant link. But a seat that *was* human is **not** taken over by an agent if the
human drops or never arrives (deferred).
- **Why it matters:** unlocks agent-only simulations and baselines now, while avoiding the messy partial-session semantics of a mid-run human→agent swap. Trade-off: all-agent runs need a non-participant launch path (touches surface 05's launch model).
- **Open question:** what launches an all-agent interaction — a `mug run-interaction`-style command, or a scheduler surface? (defer detail to the agent-scheduler surface 11)
- **Status:** ✅ approved

## Settled (your calls)

- **Matchmaking → author-declared `Pairing` config** (D07-7), with defaults for the simple case.
- **Agent authoring → in the study repo, versioned with the study** (D07-4); standalone publishable agents deferred.
- **Mid-interaction backfill → out of scope for v0** (D07-8); a dropped human follows normal recovery (surface 05).
- **All-agent interactions → allowed** (D07-8), launched by a researcher/scheduler rather than a participant.
