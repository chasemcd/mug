# 10 — Participant playing / chatting

| Field | Value |
| --- | --- |
| User | Participant (playing/chatting live); the input scheme is authored |
| Goal | Controls feel responsive, chat is coherent, and everything the participant does is captured faithfully — across server, browser, and P2P modes |
| Backing contract | [API-07](../../docs/architecture/phase-0/api-07/index.md) (input/step) · [API-08](../../docs/architecture/phase-0/api-08/index.md) (chat) · [API-09](../../docs/architecture/phase-0/api-09/index.md) (realtime wire) |
| Status | ✅ all 7 decisions approved (see [DECISIONS.md](DECISIONS.md)) |

## What the user is trying to do

**Participant:** "I press arrow keys and my forager moves *now*, not half a second later.
I type a message and it appears in order for everyone. If my partner is an AI, it
replies quickly and its message streams in."

**Author:** "I want to say 'arrow keys drive movement, space grabs a berry' — continuous
hold vs. discrete press — and get responsive, correctly-routed, fully-recorded input
without wiring key handlers or netcode."

### Today (what we're replacing)

Current MUG already has a real input model (`InputModes.PressedKeys` /
`SingleKeystroke`, composite key combos, `frame_skip`, `input_delay`, per-seat action
routing) and streaming chat. We keep those capabilities and give them a typed,
declarative surface instead of scattered config.

## What the participant experiences

- Presses keys → their seat responds immediately (local prediction in browser/P2P;
  input-delay-smoothed in server mode). Only *their* seat responds to their keys.
- Types chat → message appears in a single, consistent order for everyone; an AI
  partner's reply **streams in** token by token.
- Refresh/drop mid-game → resumes exactly (surface 05); no double-moves, no lost messages.

## What the author writes (the input scheme, typed)

```python
from mug import Input, InputMode, Key, NoInput
from .envs.foraging import ForagingEnv, ForagingAction   # ForagingAction is the env's own IntEnum

controls = Input(
    mode=InputMode.PRESSED_KEYS,                 # continuous: held keys drive every frame
    bindings={                                   # keys → ACTUAL env action-space values
        Key.UP:    ForagingAction.MOVE_UP,       # env-defined action (a Discrete value)
        Key.DOWN:  ForagingAction.MOVE_DOWN,
        Key.SPACE: ForagingAction.GRAB,
        (Key.SHIFT, Key.SPACE): ForagingAction.SPRINT_GRAB,   # composite → an env action that exists
    },
    on_no_input=ForagingAction.NOOP,             # the env's no-op action (or NoInput.REPEAT_LAST)
    input_delay=2,                               # human-input netcode feel (P2P/rollback)
)
# Note: an AI agent's decision frequency (frame_skip) is NOT here — it's a property of
# the policy/controller (surface 11), since it governs how often that agent acts.

Game(key="board", env=ForagingEnv(...), render=render, input=controls, mode=ExecutionMode.SERVER)
```

Bindings map to the **environment's own action space** — an env-provided `IntEnum`
(`ForagingAction`) for readability, or raw `Discrete`/`MultiDiscrete`/`Box` values
(`Key.UP: 2`) when the env doesn't define one. MUG never invents a parallel action
vocabulary. `InputMode.SINGLE_KEYSTROKE` (one action per press) is the alternative to
`PRESSED_KEYS` (continuous hold).

## What happens behind the scenes

| Moment | Contract behavior (API-07/08/09) |
| --- | --- |
| key press | Mapped to an **actual env action-space value** via the typed scheme; only the participant's **own seat** (bound env agent id, D09-7) receives it, and the env's `step()` gets exactly that action. |
| responsiveness | Browser/P2P: **local prediction** runs the env immediately (zero-latency feel). Server-authoritative: input is queued with **`input_delay`** draining for smoothness. |
| no input this frame | Filled per `on_no_input` (`DEFAULT_ACTION` or `REPEAT_LAST`) — deterministic, not undefined. |
| realtime commands | Carry an **idempotency key** for safe retry; a **transport ack ("received") is not a durable receipt ("recorded")** (API-09) — the client never mistakes one for the other. |
| chat | Messages are **totally ordered + idempotent on submission**; an AI partner's response **streams** and is bounded by `TurnPolicy` (D08-5); the exact model context is snapshotted (API-08). |
| capture | Every action/message is recorded to the canonical stream, with what the participant actually experienced kept distinct (canonical vs. experienced) — invisible to the participant, exact for the researcher. |

## Decisions to review

Mark each `Status:` line.

### D10-1 — Input bindings map keys to the environment's actual action space (not invented names)
Authors declare a typed `Input` (mode, bindings, composites, no-input fill), and each
binding's value is a **real Gym/PettingZoo action** — an env-provided `IntEnum` for
readability, or raw `Discrete`/`MultiDiscrete`/`Box` values. MUG never introduces a
parallel action vocabulary; `on_no_input` is likewise an actual env action (or repeat-last).
- **Why it matters:** the action a key produces is exactly what the env `step()` receives and what analysis sees — no lossy translation layer, and it stays honest to the underlying Gym/PettingZoo env (D08-7). Typed via the env's own enum satisfies F-3 without MUG owning the names.
- **Status:** ✅ approved

### D10-2 — Both input modes preserved: continuous hold and discrete keystroke
`InputMode.PRESSED_KEYS` (held keys drive every frame) and `InputMode.SINGLE_KEYSTROKE`
(one action per press) both first-class, with typed `on_no_input` fill (`DEFAULT_ACTION`
/ `REPEAT_LAST`).
- **Why it matters:** real-time control games and discrete/turn-based games have opposite needs; current MUG supports both and we keep them.
- **Status:** ✅ approved

### D10-3 — `input_delay` (human netcode feel) lives here; `frame_skip` (agent decision rate) does not
`input_delay` — the rollback/pacing knob for human input in real-time multiplayer —
is a typed `Input` setting. **`frame_skip`** — how often an AI controller selects an
action — is deliberately **not** here; it's a property of the policy/controller
definition (surface 11), because it governs agent behavior, not human input.
- **Why it matters:** the two knobs were conflated in current MUG; separating them puts each where it conceptually belongs — human-input timing with input, agent decision rate with the agent. Real-time multiplayer feel is preserved either way.
- **Status:** ✅ approved

### D10-4 — Input is routed per-seat; a participant controls only their seat
A participant's keys drive only their bound seat/agent id (D09-7); other seats are
filled by their own actors (humans/bots/LLMs).
- **Why it matters:** correctness in multiplayer — no cross-control, clean per-seat action records — and it's the runtime half of the seat/actor model.
- **Status:** ✅ approved

### D10-5 — Chat is totally ordered, idempotent, and streams model responses
Every participant sees the same message order; submission is idempotent (no dupes on
retry); AI replies stream token-by-token and are turn-bounded.
- **Why it matters:** coherent multi-party conversation and replayable AI turns; retries/drops never duplicate or reorder messages.
- **Status:** ✅ approved

### D10-6 — Realtime honesty: local prediction for feel; ack ≠ receipt; faithful capture
Browser/P2P predict locally for responsiveness; the client distinguishes "received"
(transport ack) from "recorded" (durable receipt); everything is captured to canonical
vs. experienced streams.
- **Why it matters:** participants get a snappy experience while the data stays honest — what was predicted vs. authoritative, received vs. durably saved, is never conflated.
- **Status:** ✅ approved

### D10-7 — MUG ships a default chat widget, customizable
`Chat(key=…)` renders a ready-to-use chat UI (input box + scrolling transcript +
streaming) out of the box, with styling/slots to customize.
- **Why it matters:** the common case (a working chat) needs zero UI code, while studies that want a bespoke look can override — no study has to build chat from scratch.
- **Status:** ✅ approved

## Settled (your calls)

- **Input devices → keyboard only for v0** (plus existing clickable HTML). Formal mouse/touch/gamepad deferred.
- **Mobile → desktop-first**; responsive/touch mobile support deferred to a later version.
- **Chat UI → default widget + customizable** (new D10-7).
- **Rebinding & accessibility → out of scope for v0** (fixed author-defined bindings; sensible defaults only). Flagged to revisit — inclusion matters, just not a v0 commitment.
