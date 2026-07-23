# API-07: Environment, Game, Input, Rendering, and Execution Modes

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.3` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-20 |
| Consumers | API-06 (game channel), API-09 (input/render delivery), API-10/16 (evidence/replay), API-12 (agent actions) |
| Depends on | [Shared kernel 0.2](../shared-kernel/index.md), [API-06 0.3](../api-06/index.md), proposed ADRs 0005, 0006, 0013 |
| Implementation phase | Phase 1 |
| Stability tiers | Wire, archival |

## Outcome

API-07 defines the game runtime contract across all three execution modes.
Every runtime emits the same normalized transition (action + resulting state
digest), one writer owns each environment instance (or replica), and exact
mid-episode resume is offered only when the environment and controllers provide
compatible snapshot contracts. Rollback P2P is an N-peer full mesh with a frozen
membership generation, explicit speculative/confirmed/verified/disputed frame
status, an exclusive minimum-frame episode barrier, and one fenced publisher for
each recorded bot decision.

## Execution modes

Execution mode is a typed per-game-channel choice (D08-4, F-3). **All three
ship in v0**, and all emit the identical data shape — moving a study between
modes never changes its recorded results:

| Mode | Where the env runs | Integrity model (D09-6) |
| --- | --- | --- |
| `ExecutionMode.BROWSER` | Pyodide in the participant's browser (env + renderer + bots); Worker ticks survive tab backgrounding | Client runs the env by design; correctness from determinism + canonical/experienced reconciliation |
| `ExecutionMode.SERVER` | Server-authoritative; thin client renders a streamed packet | Client cannot fabricate canonical state |
| `ExecutionMode.P2P` | Rollback netcode across an N-peer full mesh of deterministic replicas | Complete peer-action sets, unanimous hash verification, explicit disputes, and fenced decision publication |

**Recorded schedule-risk flag (D08-4):** rollback-P2P is by far the largest,
riskiest build (deterministic replicas, input delay, finality barrier,
reconciliation authority). It is committed to v0, with the risk noted here so
Phase-1 scoping inherits it explicitly.

## Rollback-P2P protocol

`ExecutionMode.P2P` means one exact protocol, not a menu of loosely compatible
implementations (RP-1/RP-2). API-06 freezes the human replica actors for an
interaction/game channel in a `P2PMeshMembership`; API-07 records that object's
canonical digest and positive membership generation on peer transitions,
finality records, and terminal barriers. The frozen peer actor IDs are sorted
canonically, contain every group participant's human actor exactly once, and
form a **full mesh**: every replica exchanges input with every other replica.
Pairs are merely the N=2 case.

`P2PFrameFinality` is self-contained for one zero-based transition frame:

| Status | Exact meaning |
| --- | --- |
| `speculative` | The action set may be incomplete; predicted actions may have been experienced. |
| `confirmed` | Exactly one recorded action from every frozen peer is present. Hash collection may still be incomplete. |
| `verified` | The complete peer-action set is confirmed, every frozen peer supplied a full state hash, every hash is equal, and `agreed_state_hash` records that value. |
| `disputed` | The complete peer-action and peer-hash sets are present, but at least two full peer hashes differ. There is no agreed state hash and the frame is never represented as verified. |

Action and hash arrays are in canonical peer-ID order, contain no duplicate or
non-member reporter, and remain bound to one mesh digest/generation. A hash
mismatch is preserved as disputed evidence. The deterministic
`lower-peer-actor-id-defers` rule is only the live state-repair direction; it
does not erase disagreement, select scientific truth, or manufacture verified
finality. Repair must be followed by a new complete confirmation and unanimous
verification.

Frame coordinates and episode ends are unambiguous: transition frames are
zero-based and an `EpisodeBoundary.end_frame_exclusive = N` covers transitions
`[0, N)`. A P2P terminal boundary freezes one proposed exclusive end from every
mesh peer and chooses their minimum. Missing-peer or non-minimum barriers are
invalid. Human `input_delay` is applied symmetrically across all human seats;
API-09 owns the numeric input declaration, while this protocol owns the
cross-seat symmetry rule.

Rollback snapshots cover all state that can change replayed execution:
environment state, platform bookkeeping state, Python RNG state, numpy RNG
state, and MUG's JavaScript RNG state. These are coverage obligations, not a
serialization decision: the portable snapshot/trajectory codec remains
A07-O01.

### P2P bot decision publication

RP-3 assigns one exclusive publisher to each bot action entering the P2P input
stream. At episode start, the publisher is the canonically highest eligible
peer actor ID (an actor in the frozen mesh with a current fenced connection
lease). That selection is fixed for the episode. A peer may neither self-elect
nor switch authority unilaterally; any future authority change starts a new,
non-overlapping fenced publisher generation.

The publisher may compute a local scripted/ONNX decision, or receive an already
accepted server `DecisionResult` and inject its recorded action. ADR-0005 remains
unchanged: provider-, LLM-, and tool-backed work stays asynchronous and
server-authoritative; it never moves onto a peer merely because that peer owns
publication. `GameTransition.applied_decisions` links the actor, decision ID,
exact `DecisionResult` digest, action digest, decision authority, publisher
actor, and publisher generation. Rollback reuses those exact decision
IDs/actions and never calls or re-runs the controller.

## Environment contract

The game environment is a **Gym/PettingZoo-style env class in the study repo**
(D08-7): `reset`/`step`/state, versioned with the study (git-native,
ADR-0013), so one commit covers study + env + agents. MUG drives the env and
normalizes each step into the transition contract; the env is headless and
separate from rendering, so all-agent `mug simulate` runs need no renderer.

**Env creation is a factory, never an instance** (settled 2026-07-19, R-17):
`env=` names a module-level callable (or the env class) from the study repo,
recorded by **qualified name** in the compiled artifact. Every runtime imports
the same module and constructs its own instance — the server worker, each
Pyodide client (the study source ships in the client manifest), each P2P peer
(each replica is locally constructed by definition), and each `mug simulate`
worker. Env instances never cross a process/network boundary (no pickle).
Declared factory kwargs arrive via recorded per-occurrence `args` (values may
be treatments, R-15); `requires=[...]` browser packages are resolved and pinned
at publish into the client manifest. This replaces current MUG's
`environment_initialization_code`(`_filepath`) exec-string and its implicit
module-level `env` variable, and `packages_to_install` — same capability, now
compile-checked (importability; lambdas rejected). The browser mechanism is
standard Pyodide (client-manifest source bundle → `unpackArchive`/wheel →
`sys.path` → import) and module import in Pyodide is already load-bearing in
current MUG (micropip installs and imports the `mug` package itself, plus
study deps such as `slimevb`). For `BROWSER`/`P2P` games, compile verifies the
factory's **import graph is browser-loadable** against the shipped bundle +
`requires` + Pyodide's package set; a server-only import fails at compile,
never in a participant's browser. C-extension deps remain limited to Pyodide's
package distribution (unchanged from today).

There is deliberately no `on_game_step_code` or other per-step source-injection
field (RP-4). Per-step behavior belongs in the ordinary, versioned environment
class's `step` implementation and declared hooks. Unknown legacy injection
fields fail closed; there is no compatibility shim.

**Protocol shape (settled 2026-07-18): pure Gym plus optional declared hooks.**
An unmodified Gymnasium/PettingZoo env runs as-is. Optional capabilities —
`snapshot()`/`restore()` (mid-episode resume, P2P rollback), `state_hash()`
(deterministic replay verification), and per-seat observation (platform-enforced
partial observability) — are declared, not assumed, and unlock those features
only when the env implements them.

**Actions are the env's own action space.** Input bindings and agent decisions
map to the environment's native actions — an env-provided `IntEnum` or raw
`Discrete`/`Box` values (D10-1). MUG never invents a parallel action
vocabulary; F-3 is satisfied through the env's own enum.

The env keeps its internal agent ids; each seat is explicitly bound to one env
agent id at casting time (API-05, D09-7), and per-seat input routing and render
packets key off that recorded binding.

## Rendering: the imperative `Surface` API (primary)

Rendering is **imperative per-frame Python**, preserved as the primary API
(D09-1, D09-2) — not replaced by a declarative subset:

```python
def render(state, surface, seat=None):     # per seat, every frame; Pyodide by default
    surface.rect(id="bg", x=0, y=0, w=W, h=H, color="#111", persistent=True, depth=0)
    for berry in state.berries:            # arbitrary Python per frame
        surface.circle(x=berry.x, y=berry.y, radius=6, color="crimson", depth=1)
    surface.image(id="p1", image_name="forager", x=state.p1.x, y=state.p1.y,
                  angle=state.p1.heading, depth=2, tween_duration=80)

Game(key="board", env=make_env, render=render, mode=ExecutionMode.SERVER)
```

| Preserved capability | Contract behavior |
| --- | --- |
| Primitive set | `rect/circle/ellipse/line/polygon/arc/text/image`, each with `id, persistent, relative, depth, tween_duration`; alpha, area fills, sprite frame/rotation; pixel or 0–1 relative coords; resolution independence (D09-2) |
| Typed params | Every known draw param is typed; a single explicit `extras={...}` dict carries renderer-specific keys — no silent `**kwargs` (F-3) |
| Delta compression | `persistent` objects retransmit only on change; a `commit()` produces a delta-compressed `RenderPacket` |
| Object identity + tweening | Matching `id` across frames + `tween_duration` gives smooth motion and rollback smoothing after P2P corrections |
| Per-seat rendering | `render(state, surface, seat)` runs per seat; the platform derives **one `RenderPacket` per seat** so hidden-information state is never sent to the wrong client, not merely hidden (D09-4) |
| HTML overlay + DOM HUD | Per-seat HTML overlay and DOM HUD preserved alongside the canvas (role banners, scores, legends) |
| Three transports, one draw format | The same `Surface` format flows through browser-local, server-authoritative, and P2P delivery (D09-3) |
| Assets | Image/atlas/spritesheet/multi-atlas bundled and versioned with the study, content-addressed (D09-5) |
| Alternate paths | Optional JS/HTML custom renderer; Unity/WebGL embed remains a supported non-Surface mode (D09-1, D09-8) |

A declarative `Scene` helper may lower to the same draw commands as optional
sugar; it never replaces the imperative API.

## Ownership boundary

API-07 owns `GameTransition`, `P2PFrameFinality`, `RenderPacket`,
`EpisodeBoundary`, `ExecutionMode`, and the `EnvFactory` record (the game
channel's compiled env contract). Mesh membership is API-06; controller
decision acceptance is API-12; channel/interaction ownership is API-06;
delivery is API-09; canonical evidence is API-10; replay assembly is API-16.

## Non-negotiable game boundary

1. Every runtime produces the same normalized transition contract, in all three
   execution modes (D08-4).
2. Server/browser environments have one writer per instance; P2P has one writer
   per deterministic replica plus explicit input/finality/reconciliation
   authority. Integrity claims are mode-specific and stated honestly (D09-6).
3. Provider/tool/storage latency never blocks a real-time environment lock.
4. Actions are values of the env's own action space; no invented action names
   (D10-1).
5. Each seat's `RenderPacket` is derived only from that seat's view; hidden
   state is never delivered to another seat's client (D09-4).
6. Exact mid-episode resume requires compatible snapshot contracts; otherwise a
   weaker recovery is declared.
7. P2P confirmation requires the complete frozen peer-action set; verification
   additionally requires equal full hashes from the same peer set. Disagreement
   remains disputed, never verified by tie-break.
8. Episode end is exclusive and a P2P terminal barrier is the minimum proposed
   end over every frozen peer.
9. A designated peer publishes bot actions under one episode-fixed fenced
   generation; rollback replays recorded decisions, and external-agent work
   remains server-authoritative.

## Current executable evidence

- 15 valid and 23 one-defect invalid examples; 50 API-07 tests including the
  N-peer mesh protocol, four-state finality, exclusive minimum-frame barrier,
  designated decision publisher, recorded rollback links, deterministic
  snapshot coverage, writer/mode rules, factory-never-instance rule, pinned
  browser dependencies, and rejection of per-step code injection.

The 0.3 schema bundle encodes the complete RP-1..RP-4 fold: the closed
`P2PExecutionContract`, RNG-inclusive snapshot coverage, `P2PFrameFinality`,
peer-bound transitions with applied-decision links, exclusive episode ends and
minimum barriers, P2P factory hook requirements, and explicit rejection of
`on_game_step_code`. It retains the R-17 `EnvFactory`, per-seat `RenderPacket`,
and typed `Surface` vocabulary from 0.2. Per-op required-parameter matrices and
the trajectory/snapshot binary codecs remain Phase-1 work (A07-O01).

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md).
