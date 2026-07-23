# 08 — Interactions: game + chat in one activity

| Field | Value |
| --- | --- |
| User | Researcher authoring a live multi-party activity |
| Goal | Build "a two-player game where players can also chat" as *one* coherent activity, with the right ordering, visibility, and where-it-runs choices |
| Backing contract | [API-06](../../docs/architecture/phase-0/api-06/index.md) (interaction/channels) · [API-07](../../docs/architecture/phase-0/api-07/index.md) (game runtime) · [API-08](../../docs/architecture/phase-0/api-08/index.md) (conversation) |
| Status | ✅ all 7 decisions approved (see [DECISIONS.md](DECISIONS.md)) |

## What the user is trying to do

"My foraging game has two players who can talk to each other while they play. That's
one activity — a game surface and a chat, side by side, causally connected — not two
separate things. I want to say who can see and send in each, and choose whether the
game runs on the server or in the browser."

### Today (what we're replacing)

Today a game and a chat are wired separately, with ad-hoc coupling, inconsistent
ordering, and no shared evidence boundary — so a replay can't reconstruct "what was
on screen when this message was sent." We keep the outcome (game + chat together) and
make the interaction one coherent, recorded boundary.

## The model: one interaction, multiple channels

```text
INTERACTION  (one coordination + evidence boundary — seats, actors, membership)
  ├── CHANNEL "board"  (Game)  — per-producer ordering, one writer per instance
  └── CHANNEL "talk"   (Chat)  — total ordering, idempotent, turn-bounded
        the two streams are causally linked but independently ordered
```

A game-with-chat is **one `Interaction` with two channels**, not two sessions. That's
what lets a replay line up "this message was sent at this game state."

## What the user writes

```python
from mug import Game, Chat, ExecutionMode, Membership
from .envs.foraging import ForagingEnv     # a Gym-style env class in the study repo (D08-7)

game = activities.Interaction(
    key="foraging",
    seats=["p1", "p2"],
    channels=[
        Game(key="board", env=ForagingEnv(...), mode=ExecutionMode.SERVER),
        Chat(key="talk"),                    # no membership given → every seat read/write
    ],
)
```

Asymmetric visibility (e.g. a silent observer seat, or one-way announcements) is
declared per channel, not hacked into the game:

```python
Chat(key="debrief", membership={
    "p1": Membership.READ_WRITE,
    "p2": Membership.READ_WRITE,
    "observer": Membership.READ_ONLY,     # sees the chat, cannot post
})
```

## What happens behind the scenes

| Author action | Contract behavior (API-06/07/08) |
| --- | --- |
| `Interaction(channels=[…])` | One **`Interaction`** owns seats, actors, channels, membership, and leases — the single coordination + evidence boundary (API-06). |
| `env=ForagingEnv(...)` | A **Gym-style env class in the study repo** (versioned with the study, like agents in D07-4). MUG drives its `step()` and normalizes each result into the transition contract (D08-7). |
| `Game(...)` vs `Chat(...)` | Typed channel kinds carry their **ordering guarantee**: chat is **totally ordered** and idempotent; a game channel uses **per-producer** ordering. The author doesn't hand-manage ordering. |
| `mode=ExecutionMode.SERVER` | Server-authoritative, browser-local, or rollback-P2P — all emit the **same normalized transition** (action + resulting state digest), so the *data shape is identical* regardless of where it runs (API-07). All three ship in v0 (D08-4). |
| `Chat(key="talk")` / `membership=…` | With no membership, **every seat is read/write** (the common case, one line). **`Membership`** declares visibility + write capability per actor per channel (typed, F-3) only when you need asymmetry — observers, spectators, one-way channels. |
| chat with an LLM actor | A **`TurnPolicy`** bounds model activations per turn so agents can't loop; the **exact context snapshot** for each model request is persisted for replay/audit (API-08). |
| every action | Game transitions (action + state digest) and chat messages (totally ordered + context snapshots) are **normalized recorded events** — the interaction is replayable and auditable (surface 12). |

## Decisions to review

Mark each `Status:` line.

### D08-1 — A game-with-chat is one interaction with multiple channels
Game and chat that belong together are channels of **one `Interaction`** (shared
seats/actors/evidence), causally linked but independently ordered — not two sessions.
- **Why it matters:** replay and analysis can line up "what was on screen when this was said"; the coupling is real and recorded, not incidental.
- **Status:** ✅ approved

### D08-2 — Channel kinds are typed and carry their own ordering guarantee
`Game` and `Chat` are distinct typed channels; chat is totally ordered + idempotent,
game is per-producer ordered. The author picks the kind, not the ordering mechanics.
- **Why it matters:** deterministic chat replay and correct game concurrency come for free; the author can't accidentally pick an unsafe ordering.
- **Status:** ✅ approved

### D08-3 — Visibility/write is per actor per channel; "everyone" is the default shorthand
A `Chat`/channel with no membership means **every seat read/write** (one line). Explicit
`Membership` (read/write, read-only, none) is only needed for asymmetry — observers,
spectators, one-way announcements, asymmetric-information designs.
- **Why it matters:** the common case is a one-liner, while information structure (who sees/says what) — a core experimental variable — is declared explicitly when it matters, rather than hacked into game logic.
- **Status:** ✅ approved

### D08-4 — Execution mode is a typed per-game-channel choice; identical data shape; all three in v0
`ExecutionMode.SERVER` / `BROWSER` / `P2P` is chosen per game channel; all modes emit
the same normalized transition contract, and **all three ship in v0**.
- **Why it matters:** where the game runs is an operational/latency/trust decision, **not** a change to the science or the recorded data — you can move a study server↔browser↔P2P without altering its results shape.
- **Caveat (flagged, not blocking):** rollback-P2P is by far the largest, riskiest build (deterministic replicas, input delay, finality + reconciliation authority per API-07). Committing it to v0 is ambitious; worth confirming it's a v0 *must-have* vs. a fast-follow, since it materially affects Phase-1 scope.
- **Status:** ✅ approved *(your call: all three in v0)*

### D08-5 — LLM/chat turn policy bounds model activations to prevent loops
A `TurnPolicy` caps how many times a model can be activated per turn, and the exact
context snapshot per model request is recorded.
- **Why it matters:** multi-agent or human+LLM chat can't spin into an activation loop (a real cost/runaway risk), and every model call is auditable/replayable.
- **Status:** ✅ approved

### D08-6 — Every action is a normalized, recorded event (invisible guarantee)
Game transitions (action + state digest) and chat messages (ordered + context
snapshots) are recorded uniformly — the author does nothing; the interaction is
replayable and auditable.
- **Why it matters:** replay (surface 13), export, and audit all work because capture is built in, not bolted on. No author effort.
- **Status:** ✅ approved

### D08-7 — The game environment is a Gym-style env class in the study repo
Authors write a Gymnasium-style env (`reset`/`step`/state) in the study repo,
versioned with the study (like agents, D07-4); MUG drives it and normalizes each
result into the transition contract.
- **Why it matters:** reuses the RL ecosystem and mental model researchers already have; one repo, one version stamp covers study + agents + env. Trade-off: MUG commits to a specific env interface (exact `Env` protocol is the open item below).
- **Open question:** the exact `Env` protocol MUG commits to — pure Gym shape, or Gym + MUG hooks (snapshot-for-resume, per-seat multi-agent, render)?
- **Status:** ✅ approved

## Settled (your calls)

- **Env interface → Gym-style env in the study repo** (D08-7), versioned with the study.
- **Execution modes → all three (server + browser + P2P) in v0** (D08-4) — flagged the P2P scope risk.
- **Rendering → its own review surface.** Big enough (render packets, per-seat views,
  delivery, assets) that it becomes **new surface 09**; the rest of the index shifts down.
- **Default chat scope → all-seats shorthand** (D08-3): `Chat(key=…)` with no membership = everyone read/write.

## Open questions for you

- **Exact `Env` protocol** (D08-7): pure Gym, or Gym + MUG hooks (snapshot/resume,
  per-seat views, multi-agent step)? (may be settled within the new rendering/runtime surface)
