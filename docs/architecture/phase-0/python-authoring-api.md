# The Public Python Authoring API (`mug`)

| Field | Value |
| --- | --- |
| Status | Draft |
| Spec revision | `0.1` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-18 |
| Audience | Researchers writing studies in Python; secondarily the compiler (API-01) that consumes what they write |
| Depends on | ADR-0013 (git-native versioning), ADR-0014 (identity, not recruitment), ADR-0015 (governance out of scope), and the API-01…API-19/22 contracts |
| Decision sources | The approved 2026-07 user-surface review (F-1…F-4, D01-*…D15-*) plus the 2026-07-18 resolutions below |

## Purpose and position

This document specifies the **author-facing Python surface** of MUG — the layer a
researcher actually types. The Phase 0 API families define wire and persisted
contracts; this spec defines the public vocabulary that *produces* them. Where this
spec and a family contract disagree about a persisted shape, the family contract
controls; where they disagree about what an author writes, this spec controls.

The API is deliberately small at the surface and layered underneath: the common
case (one researcher, one study, one command) is short, and every guarantee —
immutability, provenance, capture, secret isolation — is invisible machinery, not
an author step.

## Design rules (normative)

1. **Methods, not attributes** (D01-8). The authoring surface never exposes
   settable attributes. Every mutation is a named method (`study.add(...)`,
   `study.set_flow(...)`); mutating methods return `self` for chaining. The
   in-progress `Study` is a mutable builder; immutability begins at `publish()`.
2. **No magic strings** (F-3). Every closed MUG vocabulary is a typed constant
   (`ExecutionMode.SERVER`, `Assign.balanced()`, `Dataset.TRAJECTORIES`).
   Author-defined identifiers — activity keys, condition labels, seat names,
   provider model ids — are the author's data and stay strings.
3. **Closed sets are closed** (D01-4, D15-1). Activity types, assignment
   policies, field types, providers, and channel kinds are fixed vocabularies in
   v0. There is no plugin system; extension is deferred post-v0 (ADR-0015).
   Writing your own envs, policies, renderers, and tools is core authoring, not
   extension, and is fully supported.
4. **Everything versions with the study** (F-1/ADR-0013, D07-4, D08-7). Envs,
   agents, renderers, tools, and assets live in the study's git repo and are
   pinned by `publish()`. One version string covers all of them.
5. **Secrets by name, never by value** (D01-6, D07-6). Authored code declares a
   secret *requirement* (a key like `"chat-provider-key"`); values are supplied
   at deploy (API-02) and never enter source, artifact, client, or export.
6. **`check()` is pure; `publish()` is the only committing call** (D01-5). Local
   validation/compilation has no side effects and can be run freely.

## Import surface

```python
from mug import (
    # study & flow
    Study, activities, flow,
    # treatment
    Treatment, Design, Assign, Scope, Order, Unit,
    # seats, casting & grouping
    Actor, Group, Match, Matchmaker, OnTimeout, OnMissing,
    # channels
    Game, Chat, ExecutionMode, Membership, TurnPolicy,
    # rendering
    Scene, Sprite,
    # input
    Input, InputMode, Key, NoInput,
    # agents
    Policy, OnnxPolicy, LLMAgent, Provider, Tool,
    Memory, MemoryScope, MemoryMode, Fallback,
    # forms, content & preference
    Field, Compare, Content,
    # data
    Dataset,
)
```

A study is one or more **plain Python modules in a git repository**. There is no
project scaffold requirement; the CLI (below) operates on the repo.

## The `Study` object

```python
study = Study(key="cooperative-foraging")      # stable program identity

study.add(welcome, game, survey)                # register definitions (explicit)
study.set_flow(flow.sequence(...))              # method call, returns self
study.set_design(Design(cross=[...]))           # optional: joint factorial balance (R-15)
study.set_metadata(title=..., contact=...)

report = study.check()                          # pure compile: diagnostics only
report.raise_if_errors()

version = study.publish(version="2.1", note="baseline")   # the only committing call
```

### Publication (F-1 / ADR-0013)

In the typical path publication is **implicit in deployment** (R-21):
`mug deploy study@1.0` compiles and publishes the current git state as `1.0`
when that string is unused, then deploys it. `study.publish()` remains the
explicit form (CI, publishing without serving). Either way the same rules
hold — `publish(version=..., note=...)`:

- **Git is the only accepted source** (settled 2026-07-18): every study is
  published from a git repository; there is no uploaded-bundle path.
- The author hand-types the **version string** — a free-form non-empty string
  (≤128 chars), unique within the study, immutable once used, the citable
  handle (`"2.1"`, `"pilot-3"`).
- Git provenance is captured **automatically**: current HEAD commit, plus a
  stored patch of any uncommitted changes. A dirty working tree is allowed; the
  exact source state is reproducible as *commit + patch*. The author never types
  a SHA.
- **One repository may hold several studies** (settled 2026-07-18): a study may
  declare a repo-relative root (`Study(key=..., root="studies/foraging")`,
  default the repo root), recorded in provenance as `source_path`. The commit
  and patch still cover the whole repository.
- The platform compiles to an immutable, resolved `StudyVersion` (API-01) and
  **stores the compiled artifact** — replay never depends on rebuilding.
- Identity rules: content digest is the dedup identity; same content + same
  string is idempotent; same content + new string is rejected; new content +
  reused string is rejected.

### Versions, diff, availability

```python
study = Study.load(key="cooperative-foraging")
print(study.diff("2.0", "2.1"))        # structural diff of RESOLVED versions; source diff is git's job
study.deprecate(version="1.0", reason="superseded")   # stop routing NEW visits; append-only
study.withdraw(version="1.0", reason="protocol defect")
```

Amendments are always new versions (D02-4). Deprecate/withdraw change routing for
new visits only; they never mutate bytes or delete data. Deletion of data is not a
MUG operation at all (ADR-0015) — the researcher owns the store.

## Flow algebra (API-01)

```python
study.set_flow(
    flow.sequence(
        consent,                                   # consent is just an activity (ADR-0014)
        welcome,
        flow.randomized_select(choose=1, among=[game_a, game_b]),
        flow.repeat(game, times=3),
        flow.branch(on=screening.field("age_band"), cases={...}, default=...),
        survey,
        flow.terminal(outcome=flow.Outcome.COMPLETE),
    )
)
```

The closed node set is `sequence / activity / randomized_select / repeat /
branch / terminal` (D01-2). The compiler validates references, reachability,
cycles, and terminal coverage; it records randomization *rules* and never
samples — sampling happens once per participant at visit time (API-04, D05-1).

## Activities (closed set, D01-4)

| Constructor | Purpose | Backing family |
| --- | --- | --- |
| `activities.Content(key=, body=, response_required=)` | Instructions, consent text, debrief | API-17 |
| `activities.Form(key=, fields=[...])` | Surveys; typed fields, default accessible widgets | API-17 |
| `activities.Interaction(key=, seats=, channels=[...] \| spec=, cast=, group=)` | Live game/chat session | API-05/06/07/08 |
| `activities.Preference(key=, candidates=, task=, blind=, randomize_order=)` | Judgments over recorded candidates | API-18 |
| `flow.terminal(outcome=...)` | Typed completion/ineligibility/withdrawal | API-01/04 |

Every definition carries a permanent author-chosen `key` (D01-3). Key identity is
derived from published versions at publish time (D02-7) — there is no server-side
registry; keys live in source.

### Content bodies (settled 2026-07-19)

The content of a `Content` activity is **authored in the study repo and compiled
into the immutable version** as a content-addressed presentation artifact — never
bound at deploy (that would let a redeploy silently change consent text,
violating D04-3 and API-02's scientific/deployment boundary). Authors supply it
as a repo file or inline, in Markdown or HTML:

```python
Content.file("content/consent.md")        # repo-relative file, versioned with the study
Content.file("content/instructions.html") # full HTML/CSS/JS page
Content.markdown("# Welcome!\n…")          # inline, safe rendered markdown
Content.html("<div id='demo'>…</div>")     # inline, explicit HTML
```

- **Markdown** is rendered safely by the default accessible components.
- **HTML is an explicit author choice** and may include custom CSS/JS for rich
  components — it is trusted study code, exactly like the env or renderer,
  versioned and content-addressed with everything else (preserving current
  MUG's arbitrary scene HTML/CSS/JS capability). What stays forbidden is
  *implicit* execution: model output, participant text, and any runtime string
  are always rendered as inert content (API-17), never interpreted as HTML.
- Delivery plumbing (API-01's neutral client-manifest slots and scoped handles)
  is invisible to authors; the author never names a slot.

### The in-page JS bridge (settled 2026-07-19; replaces `mugGlobals`)

Custom HTML pages interact with the platform through a **typed, page-scoped
`window.mug` bridge** — the mutable `mugGlobals` bag does not carry over (its
three jobs each get a first-class mechanism):

```html
<input type="radio" name="delivery_act_reward" value="0.5">   <!-- named inputs auto-collected -->
<script>
  mug.response.set("hidden_controls", generateRandomPair()); // stage computed values
  const draft = mug.response.get("delivery_act_reward");     // read staged/collected values
  mug.state.set("scroll_pos", window.scrollY);               // per-visit state (survives refresh)
  mug.advance();                                             // request advance (respects gating)
</script>
```

- **Responses**: named `<input>`/`<select>`/`<textarea>` elements are collected
  automatically on advance; `mug.response.set(...)` stages computed values. On
  advance they become the activity's response — schema-bound, idempotent, and
  recorded with a **durable receipt before the flow moves on** when
  `response_required=True` (D12-2). The submission travels the same API-09
  command path as a `Form` response.
- **Downstream use**: recorded response fields are addressable from the study
  definition as typed refs — `instructions.field("delivery_act_reward")` — in
  activity specs, `flow.branch(on=...)`, and `Assign.stratified(by=...)`. What
  was invisible global coupling becomes a declared, compiled dependency.
- **State**: `mug.state.get/set(...)` reads and writes the visit's namespaced,
  optimistically-versioned `StateDocument` (API-04) in a client-writable
  namespace — restored automatically on refresh/resume. Never research data;
  responses are.

## Treatment and randomization (API-04)

A `Treatment` is declared **inline, at its point of effect** (settled
2026-07-19, R-15): the treatment sits exactly where it takes effect, so the
manipulation and the thing manipulated are never separated.

**One factor, one effect — fully inline (the common case).** The treatment *is*
the casting choice; its levels map directly to what each condition gets:

```python
game = activities.Interaction(
    key="foraging",
    seats=["forager-1", "forager-2"],
    cast={"forager-2": Treatment(
        key="partner",
        levels={"human": Actor.human(),           # level labels = the dict keys
                "ai":    Actor.agent(ai_partner)},
        assign=Assign.balanced(unit=Unit.GROUPS),
    )},
    channels=[...],
)
```

The same works for an env argument (R-17 factories take declared kwargs):
`Game(env=make_env, args={"difficulty": Treatment(key="difficulty",
levels=["easy", "hard"], assign=Assign.balanced())})`.

**One factor, several effects — define once, place everywhere.** The same
`Treatment` object is placed at each effect point (Python identity ties them);
`t.map({...})` gives per-site values:

```python
difficulty = Treatment(key="difficulty", levels=["easy", "hard"],
                       assign=Assign.balanced())

game  = activities.Interaction(channels=[
    Game(env=make_env, args={"difficulty": difficulty}, ...)])  # level passed to the factory
intro = activities.Content(key="intro", body=difficulty.map({
    "easy": Content.file("intro_easy.md"),                  # per-site mapping
    "hard": Content.file("intro_hard.md"),
}))
```

**True factorial — declare only the crossing.** An optional study-level
`Design` expresses the *statistical* relationship (jointly balanced cells);
the effects themselves stay co-located:

```python
study.set_design(Design(cross=[difficulty, partner], assign=Assign.balanced()))
# without set_design, treatments assign independently (each balanced marginally)
```

- **Scope is inferred from placement** where it is forced: a treatment casting
  a shared seat, or parameterizing a shared interaction, must be `Scope.GROUP`
  (inferred; a contradictory explicit scope is a compile error). Elsewhere
  `Scope.PARTICIPANT` is the default and `scope=` may be set explicitly.
- **`check()` prints the effect map** (treatment → every activity/seat/field it
  touches), and the full design space is known at compile time (D06-4) — a
  typo'd level in any `map` is a compile error. A `Design(cross=...)` naming a
  treatment that is placed nowhere is a compile error.
- Fixed, unconditional casting (`cast={"forager-2": Actor.agent(...)}`) stays
  plain — an `Actor` where always-true structure goes, a `Treatment` where the
  condition varies.
- **Assignment policies** are a closed typed set (D06-2): `Assign.random()`,
  `Assign.balanced()`, `Assign.blocked()`, `Assign.stratified(by=form.field(...))`.
  Authors never hand-roll `random.choice()` (D06-1). Balance holds across the
  **study-version lifetime** (durable allocation state), not per process.
- **Scope** is typed (D06-7): `Scope.PARTICIPANT` (default) or `Scope.GROUP`
  (a matched group shares one assignment — assigned when the group forms).
  For `Scope.GROUP` with variable group sizes, the balancing unit is an author
  knob (settled 2026-07-18): `Assign.balanced(unit=Unit.GROUPS)` (default) or
  `Assign.balanced(unit=Unit.PARTICIPANTS)`.
- **Within-subjects** designs use `within=True` with `Order.COUNTERBALANCED`
  (or randomized) order, recorded like any assignment (D06-3).
- `Assign.stratified(by=...)` defers assignment to the flow point after its
  input, then records it once, immutably (D06-6).
- Assignment (intent) and exposure (delivery) both reach the data (D06-5).
- Treatment ≠ flow randomization: if you would `group_by` it in analysis, it is
  a `Treatment`; incidental structural variety is `flow.randomized_select`.

## Seats, actors, casting (API-05)

Single-participant studies declare nothing here. Multi-party interactions
declare **seats** (authored roles) and cast **actors** into them:

```python
game = activities.Interaction(
    key="foraging",
    seats=["forager-1", "forager-2"],                      # no cast at all → every seat human
    cast={"forager-1": Actor.human(),                      # a cast, once present, is TOTAL:
          "forager-2": Actor.agent("llm-partner@2")},      # every seat named (R-16)
    group=Group(size=2, wait=Duration(seconds=90), on_timeout=OnTimeout.RELEASE),
    channels=[...],
)

# CONDITION-DRIVEN casting: put a Treatment in the cast slot instead of an
# Actor (R-15) — the treatment sits exactly where it takes effect:
#   cast={"forager-2": Treatment(key="partner",
#                                levels={"human": Actor.human(),
#                                        "ai":    Actor.agent(ai_partner)},
#                                assign=Assign.balanced(unit=Unit.GROUPS))}
```

- **Casting is all-or-nothing** (R-16): omit `cast` entirely and every seat is
  a human participant (the common case is one line); once a `cast` dict is
  present it must name **every** seat — a partial cast is a compile error, so
  no seat's occupant is ever implicit alongside explicit ones.
- A seat is filled by a human XOR an agent version, never both (D07-2).
- A `Seat` is **explicitly bound to an environment agent id** at casting time
  (D09-7) — the authored role, the actor filling it, and the env's slot are
  three distinct recorded things.

### How a treatment reaches a seat (the propagation model)

The treatment sits in the seat's cast slot; group formation pulls the
assignment through it:

1. **Authoring**: the `Treatment` placed in `cast={"seat": Treatment(...)}` is
   itself the conditional rule (R-15) — its `levels` dict maps each condition
   to the actor that fills the seat. No assignment exists yet.
2. **Compile**: the rule is frozen into the version. Checks: every level is
   covered; level references in any `map` are real (typos are compile errors,
   D06-4); the treatment is `Scope.GROUP` (inferred from casting a shared
   seat — a contradictory explicit scope is a compile error, since two group
   members could otherwise get contradictory answers).
3. **Runtime**: matchmaking cannot know how many humans to wait for until the
   condition is drawn (human-human queues a second participant; human-AI starts
   at once) — so the group's assignment is drawn **once, at group formation**
   (API-04, durable balanced counters, seed commitment), and the recorded level
   resolves the rule into an `ActorInstance` + seat↔agent-id binding + controller
   (API-05/12). Exposure is recorded only when the interaction starts (D05-2);
   refresh never re-rolls (D05-1/3).
4. **The env never knows**: it just steps its agent ids — the game stays
   condition-blind (the point of D07-1/3).

The second propagation channel is env/spec arguments — the same inline idiom:
`Game(env=make_env, args={"difficulty": Treatment(...)})` (or a shared
treatment object / `t.map({...})`), resolved from the recorded assignment and
passed to the factory at occurrence start.
- All seats may be agents (simulations/baselines, D07-8) — launched by
  `mug simulate`, not a participant link. Agent backfill of a dropped human
  seat is deferred (not v0).

### Grouping and matchmaking (settled 2026-07-19, R-18)

A **`Group`** declares how human participants are brought together — N-size,
strategy, and timeout — and is author-declared and typed (D07-7):

```python
team = Group(
    size=4,                                  # N participants, not just pairs
    match=Match.latency(max_p2p_rtt=150),    # or Match.FIFO (default), or custom
    wait=Duration(seconds=90),
    on_timeout=OnTimeout.RELEASE,            # v0: release; agent-backfill deferred
)

game1 = activities.Interaction(key="round-1", group=team, ...)
game2 = activities.Interaction(key="round-2", group=team,   # SAME object ⇒ the
    on_missing_member=OnMissing.WAIT)        # group persists; members reunited
```

- **Persistence is the shared object** (the R-15 idiom): placing the same
  `Group` on several interactions means the *same participants* are reunited
  across them, and the group's identity is durable and recorded. A
  `Scope.GROUP` treatment is assigned per `Group` and **rides with it** across
  activities. `on_missing_member` declares what a later interaction does when
  a member is gone: `OnMissing.WAIT` or `OnMissing.REGROUP` (today's
  reunion-with-FIFO-fallback).
- **`Match` strategies are typed**: `Match.FIFO` (default, arrival order);
  `Match.latency(max_estimated_rtt=..., max_p2p_rtt=...)` — the current
  two-stage behavior preserved: cheap server-RTT pre-filter, then the proposed
  match is **P2P-probed** and rejected/re-pooled over ranked candidates when
  the measured RTT exceeds the bound.
- **Custom matchmaking is core authoring** (D15-2): subclass `mug.Matchmaker`
  in the study repo — `find_match(arriving, waiting, size)` and optionally
  `rank_candidates(...)` — exactly today's ABC, versioned with the study
  (ADR-0013), and pass the instance as `match=`.
- If an interaction has one human seat (or `size=1`), no `Group` is needed —
  grouping only exists where multiple humans must meet.

## Interaction channels (API-06/07/08)

A game-with-chat is **one interaction with multiple channels** (D08-1):

```python
def make_env():                                 # env FACTORY: module-level, in the repo
    return ForagingEnv(n_berries=20)

activities.Interaction(
    key="foraging",
    seats=["p1", "p2"],
    channels=[
        Game(key="board", env=make_env, render=render,
             input=controls, requires=["cogrid==0.3.2"],
             mode=ExecutionMode.SERVER),
        Chat(key="talk"),                       # no membership → every seat read/write
    ],
)

Chat(key="debrief", membership={
    "p1": Membership.READ_WRITE,
    "observer": Membership.READ_ONLY,           # asymmetric visibility, declared
})
```

- Channel kinds are typed and carry their ordering guarantee (D08-2): chat is
  totally ordered and idempotent; game channels are per-producer ordered.
- `ExecutionMode.SERVER / BROWSER / P2P` — all three ship in v0 (D08-4) and emit
  the identical normalized transition shape; where the game runs never changes
  the data. (P2P rollback is the flagged schedule risk.)
- `ExecutionMode.P2P` means a generation-fenced full mesh over the actual human
  replica actors, not a pair special case. One symmetric frame-denominated
  `input_delay` applies to every human seat. Confirmation requires the complete
  authoritative action set and every frozen peer; verification additionally
  requires unanimous peer state hashes. Episode content is
  `[0, end_frame_exclusive)`, where the boundary is the minimum complete peer
  end claim.
- Each P2P bot seat has one episode-fixed designated action publisher (the
  canonical highest eligible peer actor ID). Local scripted/ONNX policy work may
  run there; provider/tool-backed agents remain server-scheduled and the peer
  only injects the accepted recorded action. Rollback reuses that result and
  never re-decides.
- **`env=` is a factory, never an instance** (settled 2026-07-19, R-17): a
  module-level callable from the study repo — or the env class itself for
  no-arg construction (`env=SlimeVolleyballEnv`). It is recorded by qualified
  name in the compiled artifact, and **every runtime constructs its own
  instance** by importing the same module: the server worker, each Pyodide
  client (the study source ships in the client manifest — no separate
  "initialization code" file, no magic `env` variable), each P2P peer (which
  *must* build its own deterministic replica), and each `mug simulate` worker.
  Instances are never serialized (no pickle, per API-07). The browser-side
  mechanism is standard Pyodide (source bundle → virtual FS / wheel → `import`)
  and is already load-bearing in current MUG, which micropip-installs and
  imports the `mug` package itself in the browser. `check()` validates the
  factory is importable, and for `BROWSER`/`P2P` games **verifies the factory
  module's import graph is browser-loadable** (resolvable against the shipped
  source bundle + `requires` + Pyodide's package set) — a server-only import in
  an env module is a compile diagnostic, not a participant-facing crash.
  Lambdas are rejected (no stable qualified name).
  Condition- or study-dependent construction takes declared kwargs:
  `Game(env=make_env, args={"difficulty": Treatment(...)})` — resolved values
  are recorded per occurrence and passed to the factory.
- `requires=[...]` declares the game's browser/runtime packages; they are
  resolved and pinned at `publish()` into the client manifest (F-1) — the
  successor to today's `packages_to_install`.
- The env itself is **Gym/PettingZoo-style** (D08-7); MUG drives
  `reset()`/`step()` and normalizes transitions. The protocol is **pure Gym
  plus optional declared hooks** (settled 2026-07-18): an unmodified env runs
  as-is; optional capabilities — `snapshot()`/`restore()` (resume, P2P
  rollback), `state_hash()` (deterministic replay verification), per-seat
  observation — unlock those features when the env implements them.
- There is no `on_game_step_code` or equivalent source-injection hook. Per-step
  behavior belongs in the versioned environment's ordinary `step()` method;
  legacy occurrences are rejected without compatibility translation.
- LLM chat activations are bounded by `TurnPolicy` (D08-5); every action and
  message is a normalized recorded event (D08-6).

## Rendering (API-07/09)

The primary renderer is **imperative per-frame Python** — the current MUG
`Surface` model, preserved in full (D09-1/2):

```python
def render(state, surface, seat=None):          # per seat, per frame; Pyodide-capable
    surface.rect(id="bg", x=0, y=0, w=W, h=H, color="#111", persistent=True, depth=0)
    for berry in state.berries:                 # arbitrary Python per frame
        surface.circle(x=berry.x, y=berry.y, radius=6, color="crimson", depth=1)
    surface.image(id="p1", image_name="forager", x=state.p1.x, y=state.p1.y,
                  angle=state.p1.heading, depth=2, tween_duration=80)
```

- Primitives: `rect, circle, ellipse, line, polygon, arc, text, image` with
  `id, persistent, relative, depth, tween_duration`; delta compression;
  cross-frame identity and tweening (also used for P2P rollback smoothing);
  pixel or relative coordinates; resolution independence (D09-2).
- Known draw params are typed; a single explicit `extras={...}` dict carries
  renderer-specific keys — no silent `**kwargs` (F-3 reconciliation).
- Three transports, one draw format: Pyodide-local (env + renderer + bots in
  the browser, first-class), server-authoritative, P2P (D09-3, D09-6 states
  integrity per mode honestly).
- **Per-seat rendering is platform-enforced** (D09-4): `render` receives the
  seat and MUG builds one `RenderPacket` per seat — hidden information never
  reaches the other client. `seat_view=` (per-seat HTML overlay) and `hud=`
  (DOM HUD) are preserved.
- `Scene(grid_from=..., sprites={...})` is optional declarative sugar that
  lowers to the same draw commands; a custom JS/HTML renderer and the
  Unity/WebGL path remain supported alternates (D09-1, D09-8).
- Assets (image/atlas/spritesheet/multi-atlas) are bundled, content-addressed,
  and versioned with the study (D09-5).

## Input (API-09, D10-*)

```python
controls = Input(
    mode=InputMode.PRESSED_KEYS,                # or InputMode.SINGLE_KEYSTROKE
    bindings={
        Key.UP:    ForagingAction.MOVE_UP,      # the ENV's own action space
        Key.SPACE: ForagingAction.GRAB,
        (Key.SHIFT, Key.SPACE): ForagingAction.SPRINT_GRAB,   # composite
    },
    on_no_input=ForagingAction.NOOP,            # or NoInput.REPEAT_LAST
    input_delay=2,                              # human netcode feel (rollback/pacing)
)
```

**How a composite is spelled in the built runtime (2026-07-27).** The shipped
authoring surface takes key names rather than a `Key` enum, so a composite is one
binding whose name joins its keys with `+`:

```python
action_bindings = {
    "ArrowUp": UP,
    "ArrowLeft": LEFT,
    "ArrowUp+ArrowLeft": UPLEFT,   # composite: both keys held
}
```

A chord beats a single key, and a longer chord beats a shorter one, so the most
specific thing the participant is doing is what the seat does. The server
(`mug/game/runtime.py`) and both shipped clients resolve it identically, which
they must: a browser run is verified by re-execution, so a client that read a
different action would make an honest participant's run unverifiable.

This was **specified here from the start and not implemented** until a real study
was ported: `resolve_action` returned the first bound key, so Slime Volleyball's
diagonal jump could not be expressed. No record lacked a producer and no runtime
lacked a caller, so neither standing check would have found it. See
`examples/slime_volleyball/README.md`.

Bindings map to the **environment's actual action space** — an env-provided
`IntEnum` for readability or raw `Discrete`/`MultiDiscrete`/`Box` values. MUG
never invents a parallel action vocabulary (D10-1). Input routes only to the
participant's own bound seat (D10-4). `input_delay` (human timing) lives here;
an agent's decision cadence does not — it is `decides_every` on the policy
(D10-3). Keyboard-only in v0; desktop-first.

## Agents and policies (API-12/13/14/15)

```python
class GreedyBot(Policy):                        # scripted: full env access + agent id
    def act(self, env, agent_id):
        return ForagingAction.GRAB

rl = OnnxPolicy("greedy.onnx")                  # RL: consumes the agent's observation

partner = LLMAgent(
    provider=Provider.OPENAI,                   # typed; also ANTHROPIC, OSS, HTTP
    model="gpt-5",                              # the provider's own id (their vocabulary)
    prompt="You are a cooperative foraging partner…",
    tools=[Tool.mcp("search"), grab_tool],      # MCP + native Python tools
    memory=Memory(scope=MemoryScope.EPISODIC, mode=MemoryMode.ISOLATED),
    secret="chat-provider-key",                 # by key; value bound at deploy
    decides_every=4,                            # decision cadence (frame_skip)
    on_timeout=Fallback.REPEAT_LAST,            # mandatory explicit fallback
)
```

- Three policy kinds — scripted (`act(self, env, agent_id)`, privileged
  full-state access), ONNX RL, LLM — all versioned in the study repo (D11-1,
  D07-4) and referenced as `agent@version` when cast.
- Slow decisions are **scheduled asynchronously**; a game frame, human input,
  or heartbeat is never blocked by a thinking agent (D11-2). Stale decisions
  are discarded; the declared `Fallback` fills in (D11-3).
- LLM agents are immutable versions pinning provider/model/params/prompt/
  tools/fallback; usage, cost, and the resolved model are recorded as exposure
  (D11-4).
- Tools: immutable versions, egress allowlists, approval before a mutating
  call, recorded results substituted on replay (D11-5).
- Memory is an experimental variable: `MemoryScope.WORKING / EPISODIC /
  LONGITUDINAL` × `MemoryMode.SHARED / ISOLATED / ABLATED` (D11-6).
- External agent frameworks are wrapped behind `Policy`/`LLMAgent`; MUG owns
  the decision/scheduling/approval/replay loop in v0 (D11-8).

## Forms and preference (API-17/18)

```python
debrief = activities.Form(key="debrief", fields=[
    Field.likert("enjoyment", "How much did you enjoy this?", scale=7),
    Field.choice("strategy", "Which strategy did you use?", options=["hoard", "share"]),
    Field.text("comments", "Anything else?", required=False),
    Field.slider("confidence", "How confident are you?", low=0, high=100),
    Field.rating("partner", "Rate your partner", stars=5),
])

which_better = activities.Preference(
    key="cooperativeness",
    candidates=trajectory_slices,               # immutable refs: slices/outputs/chats/media
    task=Compare.pairwise(prompt="Which agent behaved more cooperatively?"),
    blind=True,
    randomize_order=True,
)

Chat(key="assistant", respond_with=partner,
     elicit_preference=Elicit.replies(n=2))     # inline RLHF: pick a reply, chat continues with it

Elicit.replies(n=2, ties=True, on=[             # judged on more than one axis
    Axis("helpful", "Which reply is more helpful?"),      # a slider between the two
    Axis("safe", "Which reply is safer?", pick=True),     # two buttons, no middle
    Axis("wordy", "How wordy is each reply?", each=True), # rate each, not compare
])
Elicit.between("partner", "rival")              # two model seats answer the same turn
```

- Field types: single/multi choice, Likert, short/long text, number, slider,
  rating (D12-1 + settled additions). Default widgets are accessible with an
  enforced WCAG AA floor (D12-6).
- A progression-gating response requires a **durable receipt before
  advancing** (D12-2).
- Candidates are immutable references, blinded and order-randomized without
  changing identity; a choice must be one of the presented candidates
  (D12-3/4/5). Tasks in v0: pairwise + rating.
- Inline in-chat elicitation (D12-8): n candidate replies (default 2, every turn
  by default -- `sample` elicits a fraction, and which turns is derived rather
  than drawn), the pick is recorded, the chosen reply continues the thread, and
  the unchosen branch is retained as data with its own provenance.
- A judgement is more than one bit (D12-9, D12-10): `ties=True` admits "about the
  same" and "both are bad" without inventing a choice, and `on=[Axis(...)]` adds
  author-named axes -- a slider between the two replies, a plain pick, or a rating
  of each. **An answer names a candidate, never a side of the screen**, so a
  shuffled presentation can not be read back wrong. `Comparison` takes both too.
- Preferences export as the flat rows the field trains on -- `prompt`, `chosen`,
  `rejected`, and a conversational `messages` list -- carrying what a published
  corpus can not: the verdict, each axis resolved to the reply it favoured, which
  reply was shown first, the response time, and the lineage back to the evidence.
- Multiple judgments + agreement metrics ship in v0; full adjudication
  workflow is deferred (D12-7).

## Export and replay (API-16/19)

```python
ds = study.export(Dataset.TRAJECTORIES)         # also EVENTS, PREFERENCES, CONVERSATIONS
print(ds.schema, ds.lineage, ds.path)           # exact row schema + full lineage
# pandas.read_json(ds.path, lines=True) / datasets.load_dataset("json", ...)

run = mug.replay("run_abc.mugrun")              # exact replay: NO provider/tool calls
run.watch()
report = run.verify()                           # deterministic state-hash check
what_if = run.branch(at_step=1200, recast={"forager-2": other_agent})
```

- **JSONL is the single export format** (D13-1); each dataset kind binds an
  exact row schema; nested data stays nested JSON. Export is a **batch,
  re-runnable snapshot** (settled 2026-07-18): running it mid-study exports
  everything recorded so far, consistent as of the snapshot; there is no
  streaming/follow mode in v0.
- Every export carries complete lineage back to the recorded evidence, the
  study version, and its git provenance (D13-2). Redaction/aggregation creates
  a *new* lineage-bearing object (D13-3).
- Exact replay substitutes recorded model/tool outputs from the decision tape
  (D13-4); replay capability levels are declared honestly (D13-5); tampered
  bundles are detected (D13-6); branching is a counterfactual fork with
  lineage — it may recompute and call models, and is clearly distinct from
  exact replay (D13-7).
- v0 scope (settled 2026-07-18): **visual + deterministic replay ship in v0**;
  outcome-level replay and counterfactual branching (`run.branch`) are
  fast-follows — the API above is the committed shape, not a v0 deliverable.

## The CLI

| Command | Meaning |
| --- | --- |
| `mug deploy study@version --secret key=$VAL [--at URL]` | Bring up, rewire, rotate a key, or bring back — one verb (D03-1/5), **run on the hosting machine** (R-20). **Publishes implicitly** (R-21): if `version` is unused, the current git state is compiled and published under it first; byte-identical re-deploys are idempotent; changed content under a used string is a plain error (bump the string). Then: start the local server if needed, record the revision, check satisfaction, serve. `--at` is the public URL the deployment presents (default localhost) — hosting/DNS/TLS are yours |
| `mug deploy study` (no `@version`) | **Dev preview** (R-21): serve the current working tree at localhost with no version minted; data marked preview/non-citable; refuses a non-localhost `--at`. The zero-bookkeeping iteration loop |
| `mug stop study` | Take down (on the same machine); no new participants; in-flight visits untouched |
| `mug export study@version --dataset trajectories` | JSONL export with lineage (D13-1/2) |
| `mug simulate study@version --n 100 [--render]` | Headless all-agent batch runs (D11-7) |
| ~~`mug run study`~~ | Retired by R-21: `mug deploy` now publishes implicitly and bare `mug deploy study` is the dev preview — `mug run` has nothing left to do |

Deployment is ungated (self-hosted; ADR-0015): whoever operates the install can
do everything; any author/operator split is social convention. Secrets are
passed at deploy (value or env var), stored, and referenced (D03-3) — this is
the only secret path in v0; external secret managers (Vault/AWS) are post-v0
(settled 2026-07-18). Rotation defaults to **follow-current**
(`Resolution.CURRENT`: the new value is used everywhere going forward,
including in-flight visits; `Resolution.PINNED` is the advanced opt-in —
settled 2026-07-18). The four deployment guarantees — immutable deployment
record, needs-met preflight, secret isolation, in-flight visit pinning —
always hold invisibly (D03-4).
Participant-facing: the deploy URL **is** the recruiting surface (D04-2);
consent is an activity in the flow (D04-3); returning participants use a stable
per-enrollment return link the researcher distributes themselves (D04-4).

## Typed vocabulary (F-3 appendix)

| Namespace | Members (v0) |
| --- | --- |
| `Assign` | `random()`, `balanced(unit=)`, `blocked()`, `stratified(by=)` |
| `Scope` | `PARTICIPANT`, `GROUP` |
| `Unit` | `GROUPS` (default), `PARTICIPANTS` — balancing unit for `Scope.GROUP` |
| `Order` | `RANDOMIZED`, `COUNTERBALANCED` |
| `ExecutionMode` | `SERVER`, `BROWSER`, `P2P` |
| `Membership` | `READ_WRITE`, `READ_ONLY`, `NONE` |
| `InputMode` | `PRESSED_KEYS`, `SINGLE_KEYSTROKE` |
| `NoInput` | `REPEAT_LAST` (or any env action value) |
| `Provider` | `OPENAI`, `ANTHROPIC`, `OSS`, `HTTP` |
| `MemoryScope` | `WORKING`, `EPISODIC`, `LONGITUDINAL` |
| `MemoryMode` | `SHARED`, `ISOLATED`, `ABLATED` |
| `Fallback` | `DEFAULT_ACTION`, `REPEAT_LAST` |
| `OnTimeout` | `RELEASE` |
| `Match` | `FIFO` (default), `latency(max_estimated_rtt=, max_p2p_rtt=)`, or a custom `Matchmaker` subclass |
| `OnMissing` | `WAIT`, `REGROUP` — later-activity behavior for a persistent `Group` |
| `Dataset` | `EVENTS`, `TRAJECTORIES`, `PREFERENCES`, `CONVERSATIONS` |
| `Compare` | `pairwise(...)`, `rating(...)` |
| `Field` | `likert`, `choice`, `multi_choice`, `text`, `number`, `slider`, `rating` |
| `flow` nodes | `sequence`, `activity`, `randomized_select`, `repeat`, `branch`, `terminal` |

Environment action vocabularies are the env's own (`ForagingAction.MOVE_UP`) —
MUG deliberately does not own them (D10-1).

## Contract mapping

| Authoring surface | Backing family |
| --- | --- |
| `Study`, `flow`, `publish`, `diff`, availability | API-01 |
| `study.deploy` / `mug deploy` / `mug stop`, secrets | API-02 |
| Enrollment, launch/return links | API-03 |
| `Treatment` (inline) / `Design` / `Assign` / `Scope`, visit plan | API-04 |
| seats, `Actor`, `Group`/`Match`/`Matchmaker`, casting | API-05/06 |
| `Interaction`, channels, `Membership` | API-06 |
| `Game`, env protocol, `render`/`Surface`, `ExecutionMode` | API-07 |
| `Chat`, streaming, `TurnPolicy` | API-08 |
| `Input`, per-seat routing, delivery | API-09 |
| capture guarantees (invisible) | API-10/11 |
| scheduler, `decides_every`, `Fallback` | API-12 |
| `Provider`, `LLMAgent` versions | API-13 |
| `Tool` (native + MCP), approval | API-14 |
| `Memory` treatment modes | API-15 |
| `mug.replay`, `verify`, `branch` | API-16 |
| `activities.Content`/`Form`, `Field` | API-17 |
| `activities.Preference`, `Compare`, inline elicitation | API-18 |
| `study.export`, `Dataset`, lineage | API-19 |
| compile jobs, `mug simulate` | API-22 |

## Resolutions (2026-07-18)

The open questions carried out of the surface review were all resolved on
2026-07-18 and are folded into the body above:

| Question | Resolution |
| --- | --- |
| Git-only or uploaded bundle (D02-1) | **Git only.** No uploaded-source path. |
| Version-string format (D02-3) | **Free-form unique** — any non-empty trimmed string ≤128 chars, unique per study. |
| Repo layout | **A repo may hold several studies** via a repo-relative study root (`source_path` in provenance); commit + patch cover the whole repo. |
| `mug run` | ~~Dev-only publish+deploy~~ — retired 2026-07-19 by R-21 (deploy publishes implicitly; bare `mug deploy` is the dev preview). |
| Publish/deploy bundling (2026-07-19) | **Deploy publishes** (R-21): `mug deploy study@1.0` auto-publishes the current git state when "1.0" is unused (D02-3 collision rules keep it safe — a used string never silently changes content); bare `mug deploy study` = localhost-only working-tree preview, no version minted, preview-marked data. `study.publish()` remains for explicit/CI use; `mug simulate` auto-publishes the same way; `mug export` never does. |
| External secret managers (D03-3) | **Pass-at-deploy only in v0**; Vault/AWS references post-v0. |
| Rotation default (D03-5) | **Follow-current** (`Resolution.CURRENT`); pinned is the advanced opt-in. |
| Group balancing unit (D06-7) | **Author knob**: `Assign.balanced(unit=Unit.GROUPS)` (default) or `Unit.PARTICIPANTS`. |
| Env protocol (D08-7) | **Pure Gym + optional declared hooks** (snapshot/restore, state_hash, per-seat observation). |
| Replay levels in v0 (D13-5) | **Visual + deterministic**; outcome-level deferred. |
| Branching (D13-7) | **Fast-follow** — committed API shape, not a v0 deliverable. |
| Live vs. batch export | **Batch, re-runnable snapshot**; no streaming mode in v0. |
| Content bodies (2026-07-19) | **Repo file or inline, Markdown or HTML** (`Content.file/markdown/html`) — compiled into the immutable version, never bound at deploy. Author HTML (with CSS/JS) is explicit trusted study code; model/participant output is never implicitly executable. |
| In-page JS bridge (2026-07-19) | **Typed `window.mug` only** (`mug.response`, `mug.state`, `mug.advance`) + auto-collection of named inputs; `mugGlobals` does not carry over. Responses get receipts and typed `activity.field(...)` refs downstream. |
| Treatment↔activity linkage (2026-07-19) | **Inline at the point of effect** (R-15, supersedes the earlier `applies=[Cast/Param]` shape): a `Treatment` object sits directly in the cast slot / spec field it manipulates, `levels={label: value}`; multi-effect reuses the same object (`t.map({...})` per site); joint factorial balance via optional `study.set_design(Design(cross=[...]))`; scope inferred from placement. |
| Cast totality (2026-07-19) | **All-or-nothing** (R-16): no `cast` → every seat human; a present `cast` must name every seat (partial cast = compile error). |
| Env creation (2026-07-19) | **`env=` is a factory, never an instance** (R-17): a module-level callable (or the class) from the study repo, recorded by qualified name; every runtime — server, each Pyodide client, each P2P peer, each simulate worker — imports the same module and constructs its own env. Declared kwargs via `args={...}` (may be `Treatment`s); `requires=[...]` pins browser packages at publish. Replaces `environment_initialization_code` + the magic `env` variable. |
| Grouping (2026-07-19) | **Shared `Group` object** (R-18, generalizes `Pairing`): N-size, typed `Match` strategies (FIFO default; `Match.latency` two-stage RTT pre-filter + P2P probe/re-pool; custom `mug.Matchmaker` subclasses = core authoring), `wait`/`on_timeout`. Same `Group` on several interactions ⇒ the group **persists** (reunion; `OnMissing.WAIT/REGROUP`), and `Scope.GROUP` treatments ride with it. |
| Deploy topology (2026-07-19) | **One typical run path** (R-20, supersedes the interim R-19 platform/operator-API model): `mug deploy` runs **on the hosting machine** (laptop dev, lab box collection — same commands), starts the local server process if needed, records the revision in the local durable store, serves. Code reaches the host via git; `--at` is the presented public URL, not a remote target; no deployment protocol/artifact push. MUG provisions no infrastructure. |

## A complete study, end to end

One worked example exercising the whole surface. The repo holds the study at
`studies/foraging/` (R-3); the env, agent, and renderer live beside the study
definition and version with it (design rule 4).

```text
lab-monorepo/
└── studies/foraging/
    ├── study.py          # everything below
    └── envs/
        └── foraging.py   # ForagingEnv (Gym-style) + ForagingAction (IntEnum)
```

### `studies/foraging/study.py`

```python
from mug import (
    Study, activities, flow,
    Treatment, Assign, Scope, Unit,
    Actor, Group, OnTimeout, Duration,
    Game, Chat, ExecutionMode,
    Input, InputMode, Key,
    LLMAgent, Provider, Fallback,
    Field, Content, Dataset,
)
from .envs.foraging import ForagingEnv, ForagingAction

W, H = 800, 600

def make_env():                                              # env factory (R-17): every
    return ForagingEnv(n_berries=20)                         # runtime builds its own instance

# --- The study: stable program identity + repo-relative root (R-3) -----------
study = Study(key="cooperative-foraging", root="studies/foraging")

# --- The AI partner (surface 11): immutable, versioned with the study --------
ai_partner = LLMAgent(
    provider=Provider.OPENAI,
    model="gpt-5",                                           # the provider's own id
    prompt="You are a cooperative foraging partner. Coordinate via chat; "
           "share berries fairly.",
    secret="chat-provider-key",                              # by name; value at deploy
    decides_every=4,                                         # decision cadence
    on_timeout=Fallback.REPEAT_LAST,                         # mandatory fallback
)

# --- Rendering (surface 09): imperative per-frame Surface --------------------
def render(state, surface, seat=None):
    surface.rect(id="bg", x=0, y=0, w=W, h=H, color="#123312",
                 persistent=True, depth=0)                   # static → sent once
    for i, berry in enumerate(state.berries):                # arbitrary Python
        surface.circle(id=f"berry-{i}", x=berry.x, y=berry.y,
                       radius=6, color="crimson", depth=1)
    for agent_id, forager in state.foragers.items():
        surface.image(id=f"forager-{agent_id}", image_name="forager",
                      x=forager.x, y=forager.y, angle=forager.heading,
                      depth=2, tween_duration=80)            # smooth motion

# --- Input (surface 10): keys → the env's OWN action space -------------------
controls = Input(
    mode=InputMode.PRESSED_KEYS,
    bindings={
        Key.UP:    ForagingAction.MOVE_UP,
        Key.DOWN:  ForagingAction.MOVE_DOWN,
        Key.LEFT:  ForagingAction.MOVE_LEFT,
        Key.RIGHT: ForagingAction.MOVE_RIGHT,
        Key.SPACE: ForagingAction.GRAB,
    },
    on_no_input=ForagingAction.NOOP,
    input_delay=2,
)

# --- Activities (surface 01): the closed set ---------------------------------
consent = activities.Content(key="consent",
                             body=Content.file("content/consent.md"),  # repo file, versioned with the study
                             response_required=True)          # just an activity (ADR-0014)
welcome = activities.Content(key="welcome",
                             body=Content.markdown("# Welcome!\nYou'll forage for berries "
                                                   "with a partner, then answer a few questions."))

game = activities.Interaction(
    key="foraging",
    seats=["forager-1", "forager-2"],                        # authored roles
    cast={                                                   # a cast names EVERY seat (R-16)
        "forager-1": Actor.human(),                          # always a participant
        # The experimental design, inline where it takes effect (R-15):
        # who is your partner? Group-scoped — the whole pairing is
        # human-human or human-AI (D06-7); assigned once when the group
        # forms; balanced across the version lifetime.
        "forager-2": Treatment(
            key="partner",
            levels={"human": Actor.human(),                  # wait & pair a second participant
                    "ai":    Actor.agent(ai_partner)},       # start at once with the LLM
            assign=Assign.balanced(unit=Unit.GROUPS),        # R-7 default, explicit here
        ),
    },
    group=Group(size=2, wait=Duration(seconds=90),         # Match.FIFO default; same
                on_timeout=OnTimeout.RELEASE),             # object on later activities
                                                           # would persist the pairing (R-18)
    channels=[
        Game(key="board", env=make_env,                      # factory by name, not an instance
             render=render, input=controls,
             requires=["cogrid==0.3.2"],                     # browser deps, pinned at publish
             hud=lambda state: f"Score: {state.score}",
             seat_view=lambda seat: f"<b>You are the {seat.key} forager.</b>",
             mode=ExecutionMode.SERVER),
        Chat(key="talk"),                                    # all seats read/write
    ],
)

debrief = activities.Form(key="debrief", fields=[
    Field.likert("enjoyment", "How much did you enjoy the task?", scale=7),
    Field.likert("partner_coop", "How cooperative was your partner?", scale=7),
    Field.choice("partner_guess", "Who do you think your partner was?",
                 options=["a person", "an AI", "not sure"]),
    Field.text("comments", "Anything else?", required=False),
])

study.add(consent, welcome, game, debrief)

# --- Flow (surface 01): explicit algebra -------------------------------------
study.set_flow(
    flow.sequence(
        consent,
        welcome,
        game,
        debrief,
        flow.terminal(outcome=flow.Outcome.COMPLETE),
    )
)

# --- Check locally (pure); publishing happens at deploy (R-21) ---------------
if __name__ == "__main__":
    study.check().raise_if_errors()             # compiler-style diagnostics, no side effects
```

### Running it

All commands run **on the machine that hosts the study** (R-20) — your laptop
while developing, the lab box for collection; the repo gets there via git:

```bash
# Dev loop (laptop): preview the working tree, zero version bookkeeping (R-21):
mug deploy cooperative-foraging          # localhost preview; no version minted

# Go live (lab box): ONE command — it publishes "1.0" from the current git
# state (commit + patch recorded), starts the server if needed, and serves.
# The URL is the whole recruiting surface (D04-2), wherever THIS machine is
# reachable:
git pull
mug deploy cooperative-foraging@1.0 \
    --at https://study.lab.edu \
    --secret chat-provider-key=$OPENAI_KEY
# → put https://study.lab.edu on Prolific / in an email; done.
# (Editing code and re-deploying @1.0 errors — publish it as @1.1.)

# Watch it fill; export any time (batch, re-runnable snapshot — R-11):
mug export cooperative-foraging@1.0 --dataset trajectories
mug export cooperative-foraging@1.0 --dataset conversations
mug export cooperative-foraging@1.0 --dataset preferences

# Take it down when collection ends (in-flight visits untouched):
mug stop cooperative-foraging
```

### Before launch: pilot with all-agent runs

```bash
mug simulate cooperative-foraging@1.0 --n 50        # headless: both seats agents
mug simulate cooperative-foraging@1.0 --n 1 --render  # watch one for debugging
# (simulate auto-publishes "1.0" the same way deploy does, R-21 — so piloting
#  before any deploy still works in one command)
```

### After: verify a session

```python
import mug

run = mug.replay("exports/run_0042.mugrun")   # no provider/tool calls
run.watch()                                    # visual playback
print(run.verify())                            # deterministic state-hash check
```

What the author never wrote: identity handling, randomization bookkeeping,
allocation counters, netcode, capture, receipts, provenance, or secret wiring —
each is an invisible guarantee of the families in the
[contract mapping](#contract-mapping) above.
