# Approved decisions ledger

Running record of decisions **approved** during the user-surface review, ready to
fold back into the real contracts under `docs/architecture/phase-0/`. One row per
approved decision. "Folded?" tracks whether it's been written into the contracts
yet (this review is design-time; folding happens deliberately, not automatically).

## Foundational decisions (cross-cutting)

| ID | Decision | Consequence | Folded? |
| --- | --- | --- | --- |
| F-1 | **Git-native versioning + stored compiled artifact.** Git is the source of truth for study source (branches, diff, PRs, collaboration). The platform does NOT implement drafts/branches/revisions. It compiles a **commit** into an immutable, resolved, access-partitioned `StudyVersion`, **stores that compiled artifact**, records the git commit as provenance, and binds every result to the resolved version digest. | **Major API-01 simplification.** Cuts `StudyDraft`, `DraftRevision` chains, optimistic head preconditions, `diff_revisions`, `allocate_definition_id`/`commit_revision` flow, and the mutable `DefinitionRegistry` aggregate. Keeps: compile→immutable version, content-digest identity, client/server/provenance split, secret-requirement/bind-at-deploy, availability (deprecate/withdraw ≠ delete). Chose **store compiled artifact** over rebuild-on-demand for defensible reproducibility. | ⬜ |
| F-2 | **MUG owns identity, not recruitment.** At the identity boundary MUG only: assigns pseudonymous study-scoped enrollments, keeps external refs (panel IDs) apart from research data, and lets a participant return via a stable link. Recruitment/reminders/panels/payment stay in the researcher's existing tools. | **API-03 scope reduction.** Collapses `ConsentRecord` (→ consent is an ordinary flow activity, recorded like any response) and `WaveSpec` (→ multi-part flow + stable return link). Cuts all invite/targeting/scheduling machinery. Keeps: `Enrollment` (pseudonymous), `LaunchTicket` (opaque), `ExternalIdentityLink` (blinded, stored apart). | ⬜ |
| F-3 | **No magic strings or numbers.** Every closed set of options MUG defines is exposed as a typed constant/enum, never a bare literal in user code; references point at typed handles, not dotted string paths. **Boundary:** author-defined identifiers (study keys, condition labels, definition keys, form-field names) stay plain strings — they're data, not MUG vocabulary. | Cross-cutting API-design rule (sibling of [[D01-8]] no-attribute-assignment). Retro-applies to already-approved illustrative code — `flow.terminal(outcome=Outcome.COMPLETE)`, secret `Resolution.CURRENT`/`PINNED`, `OfflineTolerance.BRIEF`/`ACTIVITY`, treatment `Assign.*`/`Order.*`. No behavior change; syntax/typing only. Folds into contracts at fold time. | ✅ (directive) |
| F-4 | **Governance is out of scope.** MUG does NOT implement authorization/roles/permissions, admin audit trails, retention schedules, deletion/data-rights workflows, or a governance layer. MUG is self-hosted; the researcher/institution owns the database + infrastructure and handles access control, IRB/compliance, retention, and deletion through their own means. | **Retracts API-20** as a user-facing family. Resolves deferred items: author/operator split (D03-2) is **not an enforced permission feature** (convention only, no grants); deprecate/withdraw (D02-5) is author-callable, no approval gating; export (surface 13) is ungated; delete-my-data / consent-withdrawal / re-identification (surface 04) are **not MUG features** — handled by the researcher against their own store. **Preserved (NOT governance):** immutable event capture for reproducibility (API-10, surfaces 5/8/13) stays; **secret storage** stays as a minimal security mechanism (by-reference, never in client/science) — only the governance/audit/rotation-authority *around* it is cut. | ✅ (directive) |

## Surface 01 — Researcher authoring a study (API-01)

| ID | Decision | Nuance / constraint | Folded? |
| --- | --- | --- | --- |
| D01-1 | Top-level noun is `Study` (not `Experiment`); `Scene`/`Stager`/`ExperimentConfig` are gone | — | ⬜ |
| D01-2 | Flow is an explicit closed algebra (`sequence`/`randomized_select`/`repeat`/`branch`/`terminal`), not imperative staging | **No** `flow.linear` sugar — keep the algebra as the only surface | ⬜ |
| D01-3 | Definitions carry permanent author-chosen keys; rename is explicit, deletes tombstone | — | ⬜ |
| D01-4 | Closed set of activity types (`Content`/`Form`/`Interaction`/`Preference`/`Terminal`); extend via plugins, not free-form scenes | — | ⬜ |
| D01-5 | `check()` is pure/local; `publish()` is the only committing call | `check()` **may require online package resolution** — it is not guaranteed fully offline | ⬜ |
| D01-6 | Authors declare secret *requirements*, never values; binding is an operator step at deploy | — | ⬜ |
| D01-7 | `publish()` returns an immutable, content-addressed `StudyVersion`; identical content re-published returns the same version | — | ⬜ |
| D01-8 | No public attribute assignment; every state change is a named method | **Idiom (a) mutable builder**; `set_*`/`add` **return `self`** for chaining. Immutability is reserved for the *published* artifact, not the in-progress builder | ⬜ |

### Surface 01 settled open questions
- **Authoring entry point:** plain Python modules for now; a `mug` CLI may come later.
- **`check()` output:** compiler-style diagnostic list (not a rendered flow preview).
- **Manifest split (client/server/provenance):** entirely the platform's concern; authors never see it.

## Surface 02 — Publishing, versioning, amendments (API-01, under F-1)

| ID | Decision | Nuance / constraint | Folded? |
| --- | --- | --- | --- |
| D02-1 | `publish()` auto-records the git commit; **dirty trees allowed** (HEAD + stored patch of uncommitted changes) | Platform stores the **patch bytes** so provenance stays whole; reproducible as *commit + patch* | ⬜ |
| D02-2 | Platform **stores the compiled artifact**, not just commit+lockfile-to-rebuild | Reproducibility survives toolchain rot; cost is artifact storage (the F-1 tradeoff) | ⬜ |
| D02-3 | Per version: hand-typed **version string** (unique, immutable, citable handle) + **resolved-content digest** (dedup identity) + **git SHA** (provenance) | Collision rules: same content+same string → idempotent; same content+new string → reject; new content+reused string → reject | ⬜ |
| D02-4 | Amendments are always new immutable versions; no in-place edit | Even a typo fix ships as a new version | ⬜ |
| D02-5 | Deprecate/withdraw is **availability only, never deletion**; deletion is governed (API-20) | Authority (author vs operator) revisited in surface 13 | ⬜ |
| D02-6 | `diff(a, b)` compares **resolved** versions (definitions/flow); source diff is git's job | Catches behavior changes with zero source diff (e.g. dependency bump) | ⬜ |
| D02-7 | Definition-key identity is **derived from published history**, not a mutable `DefinitionRegistry` aggregate | Keeps longitudinal guarantee (D01-3) while deleting a stateful subsystem | ⬜ |
| D02-8 | Fork = new `Study` bound to (forked) source + lineage; copies design, not data/secrets/enrollment | Mostly a git operation + thin platform record | ⬜ |

### Surface 02 settled open questions
- **Accepted source:** git only for v0 (HEAD + patch); an uploaded-artifact path for non-git authors is deferred, not in scope now.
- **Version-string format:** free-form, non-empty, unique & immutable within the study; no enforced semver.
- **Deprecate/withdraw authority:** provisionally author-callable (+ operator); final author/operator split settled in surface 13 (governance).

## Surface 03 — Deploying & secret binding (API-02, API-20)

Rewritten twice for friction: deployment is **one command**, guarantees are invisible.

| ID | Decision | Nuance / constraint | Folded? |
| --- | --- | --- | --- |
| D03-1 | Deploy is **one call** (`mug deploy study@version --at … --secret …`); revisions/satisfaction/promotion are hidden internals | Machinery still exists for history/rollback/teams; solo users never touch it | ⬜ |
| D03-2 | **One person, one role by default**; author/operator split is an opt-in team feature (API-20 grants) | Removes two-role friction for the common case | ⬜ |
| D03-3 | Secrets **passed at deploy time** (value/env); platform stores + references them | No pre-register step, no hand-managed `SecretRef`; value never enters science/artifact/record/client | ⬜ |
| D03-4 | Four guarantees **always on, invisible**: immutable deploy record, needs-met check, secret isolation, in-flight visit pinning | Surface only as a plain deploy error when something's wrong | ⬜ |
| D03-5 | **Two verbs total: `deploy` and `stop`** | No suspend/resume/retire vocabulary; "stopped" = not live, `deploy` brings it back; neither deletes data | ⬜ |

### Surface 03 still-open (deferred, not blocking)
- `mug run` (publish+deploy in one) for local dev? · external secret managers (Vault/AWS) by-reference vs. hand-`mug`-the-value · rotation default (follow-current vs pinned) · `deploy.toml` for repeatable deploys.

## Surface 04 — Identity, consent, returning participants (API-03, under F-2)

| ID | Decision | Nuance / constraint | Folded? |
| --- | --- | --- | --- |
| D04-1 | Pseudonymous study-scoped identity, **automatic**; external refs (panel IDs in URL) captured opaquely and stored **apart** from research data | The one guarantee MUG must own here | ⬜ |
| D04-2 | **MUG is not a recruiting tool**; the deploy URL is the whole surface | No invites/reminders/panel management; researcher uses existing tools | ⬜ |
| D04-3 | **Consent is a flow activity** (`Content`/`Form`), recorded like any response | No `ConsentRecord` subsystem; reproducible (in versioned study), conditional logic = flow branch | ⬜ |
| D04-4 | Longitudinal return is a **stable per-participant link**; MUG recognizes returners, doesn't do outreach | No wave windows/targeting/scheduler; re-contact logistics are the researcher's | ⬜ |

### Surface 04 still-open (deferred)
- Withdrawal/"delete my data" handled purely as governance (surface 13) via the enrollment handle? · anonymous vs external-id arrivals both zero-config? · is a completion redirect+code even needed for v0?

## Surface 05 — Participant launch & visit flow (API-04, API-09, API-03)

All are researcher-facing *guarantees*; none is a participant-visible step.

| ID | Decision | Nuance / constraint | Folded? |
| --- | --- | --- | --- |
| D05-1 | Visit plan + all randomization **fixed & committed up front**; recovery never re-rolls | Refresh/drop/return can't change condition or re-sample | ⬜ |
| D05-2 | **Assignment (intended)** vs **exposure (delivered)** recorded separately | Clean ITT vs per-protocol; a dropout isn't counted as exposed | ⬜ |
| D05-3 | Resume is **seamless & safe**: same plan, same pinned version, no double-exposure | Flaky connections/closed tabs don't corrupt data | ⬜ |
| D05-4 | Identity & condition **server-derived**; client never trusted for them | No URL/client spoofing of identity or condition | ⬜ |
| D05-5 | **No accounts**; the link is the entire entry | Returning depends on the stable return link (D04-4) | ⬜ |
| D05-6 | Offline tolerance is an **authoring knob**, default `"brief"` (opt into activity-length) | Needs a home in the study spec (fold into surface 06/08) | ⬜ |

### Surface 05 settled open questions
- **Offline tolerance:** configurable per study (→ D05-6), default brief.
- **Save-and-resume:** always automatic (re-open link); no explicit affordance.
- **Dead-link recovery:** dead end + contact researcher; no automated re-entry.

## Surface 06 — Treatment & randomization (API-04)

| ID | Decision | Nuance / constraint | Folded? |
| --- | --- | --- | --- |
| D06-1 | You **declare the design**; MUG samples/balances/records — no hand-coded `random.choice()` | The authoring side of D05-1's runtime honesty | ⬜ |
| D06-2 | Assignment policies are a **closed, typed set** (`Assign.random/balanced/blocked/stratified`) — no arbitrary code, no magic strings (F-3) | **No plugin escape hatch for v0** (adaptive/custom deferred) | ⬜ |
| D06-3 | Between- and within-subjects both first-class (`within=True`, `Order.*`) | Within-subject order recorded like any assignment | ⬜ |
| D06-4 | Conditions referenced via **typed handles** (`design.level(difficulty)`), so full design space is known at compile time | Typo'd condition = compile error; empty cells still enumerable | ⬜ |
| D06-5 | Assignment (intent) **and** exposure (delivery) both reach the author's data | ITT vs per-protocol; authoring view of D05-2 | ⬜ |
| D06-6 | Covariate-dependent (`Assign.stratified`) assigns at a defined flow point, recorded once | Reconciles D05-1: "recorded once" ≠ "all at t=0" | ⬜ |
| D06-7 | Assignment scope is typed: `Scope.PARTICIPANT` (default) or `Scope.GROUP` (whole session shares a condition) | Group condition assigned when the group forms (→ surface 07) | ⬜ |

### Surface 06 settled open questions
- **Custom/adaptive designs:** closed set only for v0; no plugin allocator yet.
- **Assignment scope:** per-participant *and* per-group (D06-7).
- **Balance window:** across the **study-version lifetime** (survives restarts) → requires durable per-cell allocation state; fixed behavior, not a knob.
- **Still open:** with `Scope.GROUP`, balance cells by *group count* or *participant count* when group sizes vary?

## Surface 07 — Seats, actors, human + LLM casting (API-05, API-13)

Model: **seat** (authored role) ⟵ **actor** (human XOR agent@version) ⟵ **controller** (how it acts per channel).

| ID | Decision | Nuance / constraint | Folded? |
| --- | --- | --- | --- |
| D07-1 | Roles (**seats**) separated from who fills them (**actors**); single-player declares neither | Game written against roles → human↔AI is a casting change, not a rewrite | ⬜ |
| D07-2 | An actor is human **XOR** software agent, never both | Clean recordable identity per seat per run | ⬜ |
| D07-3 | Casting is **swappable + treatment-driven** (human/AI partner via `Scope.GROUP`) | This swappability is the whole point of seat/actor split | ⬜ |
| D07-4 | Agents live **in the study repo**, versioned with the study (`agent@version`, rides F-1) | Standalone `mug publish-agent` reuse deferred | ⬜ |
| D07-5 | One actor can act through **different controllers per channel** (game via RL, chat via LLM); capability↔controller compatibility enforced | Mostly relevant when actor spans channels (surface 08) | ⬜ |
| D07-6 | LLM/agent casting declares provider needs + a **secret key**, never credentials | Consistent with F-2/D01-6; bound at deploy | ⬜ |
| D07-7 | Matchmaking is **author-declared `Pairing`** (size/wait/`on_timeout`), typed (F-3) | v0 `on_timeout=RELEASE`; agent-backfill deferred | ⬜ |
| D07-8 | **All-agent interactions allowed** (researcher/scheduler launch); **agent-backfill of a human seat is not** (v0) | All-agent needs a non-participant launch path (→ surface 05/10) | ⬜ |

### Surface 07 settled open questions
- Matchmaking → author-declared `Pairing` w/ defaults. · Agent authoring → in study repo. · Mid-interaction backfill → out of scope v0. · All-agent interactions → allowed (non-participant launch, detail → surface 11).

## Surface 08 — Interactions: game + chat in one activity (API-06/07/08)

Model: **one `Interaction`, multiple channels** (game + chat), causally linked but independently ordered.

| ID | Decision | Nuance / constraint | Folded? |
| --- | --- | --- | --- |
| D08-1 | A game-with-chat is **one interaction with multiple channels**, not two sessions | Replay can line up "what was on screen when this was said" | ⬜ |
| D08-2 | Channel kinds are **typed** (`Game`/`Chat`) and carry their ordering guarantee (chat total-order+idempotent, game per-producer) | Author picks the kind, not the ordering mechanics | ⬜ |
| D08-3 | Visibility/write is **per actor per channel**; no membership = everyone R/W (shorthand) | Explicit `Membership` only for asymmetry (observers/spectators/asymmetric-info) | ⬜ |
| D08-4 | Execution mode is a typed per-game-channel choice; **identical data shape across modes**; **all three (SERVER/BROWSER/P2P) in v0** | P2P flagged as the biggest/riskiest build — confirm v0 must-have vs fast-follow | ⬜ |
| D08-5 | `TurnPolicy` bounds LLM/model activations per turn (no loops); context snapshot per model request recorded | | ⬜ |
| D08-6 | Every action is a **normalized recorded event** (game transition+digest, chat ordered+snapshot) — invisible guarantee | Enables replay (surface 13)/export/audit, no author effort | ⬜ |
| D08-7 | Game env is a **Gym-style env class in the study repo**, versioned with the study | Exact `Env` protocol settled in surface 09 | ⬜ |

### Surface 08 settled open questions
- Env → Gym-style env in study repo. · Exec modes → all three in v0 (P2P risk flagged). · Rendering → **its own surface (new #09)**. · Chat default → all-seats shorthand.

## Surface 09 — Rendering & what participants see (API-07, API-09)

Rewritten after auditing current MUG (`mug/rendering/`, `phaser_gym_graphics.js`) to **not regress** existing capability.

| ID | Decision | Nuance / constraint | Folded? |
| --- | --- | --- | --- |
| D09-1 | Rendering stays **imperative per-frame Python** (`render(state, surface, seat)`), separate from a headless env | Renderer language: **Python-in-Pyodide default + optional JS/HTML** custom renderer | ⬜ |
| D09-2 | The full **`Surface` primitive set** + semantics preserved (delta compression, object identity/tween, depth, alpha, fills, coords, resolution independence) | F-3: typed known params + explicit **`extras=`** escape (no silent `**kwargs`) | ⬜ |
| D09-3 | **Client-side Pyodide execution is first-class**; server-auth + P2P are alternate transports of the same draw format | Worker ticks survive tab backgrounding | ⬜ |
| D09-4 | **Per-seat rendering is a v0 goal**: platform-enforced per-seat `RenderPacket` (partial observability) + preserved HTML overlay/DOM HUD | Hidden-info secrets never sent, not just client-hidden | ⬜ |
| D09-5 | Assets (image/atlas/spritesheet/multi-atlas) **bundled + versioned** with the study, content-addressed | Preserves existing preload workflows | ⬜ |
| D09-6 | Integrity is **mode-specific, stated honestly** (server-auth = thin client; Pyodide/P2P = client runs env, reconciled) | Corrects earlier blanket "client never trusted" | ⬜ |
| D09-7 | **Seat ↔ env agent-id binding is explicit** (untangles today's conflation) | Env keeps agent ids internally; role/actor/slot cleanly separated | ⬜ |
| D09-8 | Non-Surface render paths (**Unity/WebGL**) remain a supported alternate mode | Existing footsies-style capability kept | ⬜ |

### Surface 09 settled open questions
- Surface params → typed + `extras=`. · Renderer lang → Python default + optional JS/HTML. · Per-seat canvas → **v0 goal**. · Audio → **out of scope v0**. · Input handling → **surface 10**.

## Surface 10 — Participant playing / chatting (API-07/08/09)

| ID | Decision | Nuance / constraint | Folded? |
| --- | --- | --- | --- |
| D10-1 | Input bindings map keys to the **env's actual action space** (Gym/PettingZoo) — env `IntEnum` or raw `Discrete`/`Box` values | MUG never invents a parallel action vocabulary; F-3 via env's own enum | ⬜ |
| D10-2 | Both input modes preserved: `PRESSED_KEYS` (continuous) + `SINGLE_KEYSTROKE` (discrete); typed `on_no_input` fill | Real current MUG features kept | ⬜ |
| D10-3 | `input_delay` (human netcode) lives with `Input`; **`frame_skip` (agent decision rate) does NOT** — it's a policy/controller property (surface 11) | Separates two knobs current MUG conflated | ⬜ |
| D10-4 | Input routed **per-seat**; a participant controls only their bound seat/agent id | Runtime half of seat/actor model (D09-7) | ⬜ |
| D10-5 | Chat **totally ordered + idempotent**; AI replies **stream**, turn-bounded | No dupes/reorder on retry | ⬜ |
| D10-6 | Realtime honesty: local prediction for feel; **ack ≠ receipt**; canonical vs experienced capture | Snappy UX without dishonest data | ⬜ |
| D10-7 | MUG ships a **default chat widget**, customizable | Zero UI code for the common case | ⬜ |

### Surface 10 settled open questions
- Input devices → **keyboard only v0** (+ existing clickable HTML). · Mobile → **desktop-first**. · Chat UI → default widget + customizable. · Rebinding/a11y → **out of scope v0** (revisit).

## Surface 11 — Agent behavior: scheduling, providers, tools, memory (API-12–15)

Spine: **slow agent decisions never block a game frame/input/heartbeat** (async scheduler).

| ID | Decision | Nuance / constraint | Folded? |
| --- | --- | --- | --- |
| D11-1 | Three policy kinds in the study repo: **scripted** (`act(env, agent_id)`, full-state), **RL/ONNX** (obs), **LLM** | Preserves current heuristic full-env access + per-agent decision | ⬜ |
| D11-2 | Slow decisions **scheduled async**; game never blocks | Core enabler of real-time-humans + slow-LLMs | ⬜ |
| D11-3 | **Stale decisions discarded**; timeout/staleness → explicit `Fallback` | Correctness + liveness; no acting on stale state, no hangs | ⬜ |
| D11-4 | LLM agents are **immutable versions** (provider/model/prompt/tools/fallback pinned); secret by key; usage recorded | `frame_skip`→`decides_every` lives here (D10-3) | ⬜ |
| D11-5 | Tools **native + MCP**: immutable versions, egress allowlists, approval-for-mutations, replay substitution | Both mechanisms in v0 | ⬜ |
| D11-6 | Agent memory has a **treatment mode** (shared/isolated/ablated) | Memory as an isolated experimental variable | ⬜ |
| D11-7 | All-agent runs via **`mug simulate … --n`, headless by default** (settles D07-8) | `--render` to debug; scheduler drives | ⬜ |
| D11-8 | Agents implement the **MUG interface**; external frameworks wrapped, not run natively (v0) | Keeps scheduling/approval/replay guarantees | ⬜ |

### Surface 11 settled open questions
- Providers → OpenAI, Anthropic, local/OSS (Ollama/vLLM), generic HTTP. · Tools → native + MCP. · Framework interop → MUG interface only (wrap externals). · Simulate → `mug simulate` headless default.

## Surface 12 — Preference & annotation studies (API-17, API-18)

| ID | Decision | Nuance / constraint | Folded? |
| --- | --- | --- | --- |
| D12-1 | Forms are a **declarative typed activity** with default accessible widgets | Field types: core set + slider/rating (ranking/matrix/upload deferred) | ⬜ |
| D12-2 | Progression-gating responses require a **durable receipt before advancing** | "Submitted then connection blipped → lost" can't happen | ⬜ |
| D12-3 | Preference/annotation over **immutable candidate references** (not copies) | Task types: pairwise + rating (ranking/annotation deferred). Sources: outputs, chat, trajectory slices, media — all 4 in v0 | ⬜ |
| D12-4 | Candidates **blinded + order-randomized** without changing identity | Removes order/brand bias; choice maps to true candidate | ⬜ |
| D12-5 | A choice must be **one of the presented candidates** | No phantom/out-of-set choices | ⬜ |
| D12-6 | Content/forms have an **enforced WCAG floor** (keyboard+SR at AA) | Distinct from (not blocked by) surface-10 game-input a11y deferral | ⬜ |
| D12-7 | Multi-annotator **quality + adjudication** first-class | v0: multiple judgments + agreement metrics; full resolution workflow later | ⬜ |
| D12-8 | **Inline in-chat preference** (RLHF-in-the-loop): live A/B, pick continues the thread | Author-configurable, `n=2`; unchosen branch retained. **Built 2026-07-27 with one departure**: every turn by default rather than sampled, because writing `elicit_preference=` is already the opt-in and a silent halving is a surprise a reader of the data cannot see; `sample` remains, and which turns it elicits is derived rather than drawn | ✅ |
| D12-9 | **A comparison is answered on more than one axis** | Author-named axes on the protocol (`scope` pair/each, 1..10 points); a rating names the **candidate key** and never a screen position, and the zero value is the midpoint that favours neither. API-18 rev 0.3 | ✅ |
| D12-10 | **A tie is recordable, and it is still resolved** | `verdict` (`choice`/`tie`/`both-bad`) says what was meant and `choice` says which candidate the response resolved to, because a live thread must go on with one reply whatever the judgement was; `allow_tie` records whether a tie was offered at all. API-18 rev 0.3 | ✅ |

### Surface 12 settled open questions
- Field types → core + slider/rating. · Task types → pairwise + rating. · Candidate sources → all 4. · Inline pref → configurable, sampled default. · Adjudication → agreement metrics v0.

## Surface 13 — Export & replay (API-16, API-19)

| ID | Decision | Nuance / constraint | Folded? |
| --- | --- | --- | --- |
| D13-1 | Exports are schema-bound datasets in **ONE format: JSONL** | Familiar/greppable/appendable; LLM-ecosystem default; nested = nested JSON. Efficiency traded for ease | ⬜ |
| D13-2 | Every export carries a **complete lineage record** | Any row traces to its source evidence | ⬜ |
| D13-3 | Redacted/aggregated exports are **new lineage-bearing objects**, never silent edits | Share safe derivatives; source intact & derivation auditable | ⬜ |
| D13-4 | **Exact replay makes no provider/tool calls** — recorded outputs substituted from a decision tape | Free, safe, faithful | ⬜ |
| D13-5 | Replay declares a **capability level** (visual/deterministic/outcome); determinism verified or visual fallback declared | Honest about reproducibility; never fakes a match | ⬜ |
| D13-6 | Replay validation **detects tampered artifacts** | Archived `.mugrun` can be trusted or flagged | ⬜ |
| D13-7 | Replay supports **counterfactual branching** (recast/alter → new run w/ lineage) | Branched runs recompute (may call models) — distinct from exact replay; feeds D12-3 candidates | ⬜ |

### Surface 13 settled / deferred
- **Format → JSONL** (chosen over Parquet: familiarity/ease over columnar efficiency).
- **Deferred (not blocking):** replay levels in v0 (all 3 vs visual+deterministic) · branching v0 vs fast-follow · who-can-export (→ ungated per F-4) · live vs batch export.

## Surface 14 — Governance — CUT (see F-4)

Entire surface out of scope. No decisions. See foundational decision **F-4** and [14-governance.md](14-governance.md).

## Surface 15 — Extending MUG (largely cut)

| ID | Decision | Nuance / constraint | Folded? |
| --- | --- | --- | --- |
| D15-1 | **No formal extension-point/plugin system in v0**; closed sets stay closed | API-21 machinery + sharing/distribution all cut; generic HTTP provider absorbs most "new provider" needs | ⬜ |
| D15-2 | **Core authoring in Python is unaffected** (envs, policies, renderers, tools — surfaces 08/09/11) | The line: implement what closed sets allow; don't add new *kinds* in v0 | ⬜ |
| D15-3 | If extension points arrive post-v0, model is **plain Python against typed protocols** (F-1 pinned, no framework/sharing) | Recorded to avoid re-litigation | ⬜ |

### Surface 15 settled
- Extension points in v0 → **none** (deferred). Closed vocabularies stay closed for v0.

---

# REVIEW COMPLETE

All 15 user-facing surfaces reviewed: **01–13, 15 approved; 14 cut.** Four foundational
decisions (F-1…F-4) + the API-21 retraction shaped the whole. **Folded into
`docs/architecture/` on 2026-07-18** — see [FOLDING.md](FOLDING.md) (marked EXECUTED).

---

# Post-fold resolutions (2026-07-18)

The open questions carried out of the review, answered after folding and applied to
the contracts + [python-authoring-api.md](../../docs/architecture/phase-0/python-authoring-api.md):

| ID | Resolution | Applied to |
| --- | --- | --- |
| R-1 | **Git only** — no uploaded source bundle (settles D02-1's open half) | API-01 (A01-O16) |
| R-2 | **Version string is free-form unique** (non-empty, ≤128, unique per study) | API-01 (A01-O18; as encoded in `VersionString`) |
| R-3 | **A repo may hold several studies** via a repo-relative study root; `source_path` added to `GitProvenance` (schema restamped, suite green) | API-01 (A01-O17) |
| R-4 | **`mug run` ships, dev-only** — publish + local deploy in one; a real version is still created | API-02 (A02-O08), spec CLI |
| R-5 | **Pass-at-deploy is the only secret path in v0**; external managers post-v0 | API-02 (A02-O07) |
| R-6 | **Rotation default = follow-current** (`Resolution.CURRENT`); pinned is opt-in | API-02 (A02-O09) |
| R-7 | **Group balancing unit is an author knob**: `Assign.balanced(unit=Unit.GROUPS \| Unit.PARTICIPANTS)`, default `GROUPS` | API-04 (A04-O05) |
| R-8 | **Env protocol = pure Gym + optional declared hooks** (snapshot/restore, state_hash, per-seat observation) | API-07 |
| R-9 | **v0 replay = visual + deterministic**; outcome-level deferred | API-16 |
| R-10 | **Branching is a fast-follow**, not a v0 deliverable (API shape committed) | API-16 (A16-O02) |
| R-11 | **Export is batch, re-runnable snapshot**; no streaming mode in v0 | API-19 (A19-O04) |
| R-12 | **Content bodies** (2026-07-19): repo file or inline, Markdown or HTML — `Content.file/markdown/html` — compiled into the immutable version, never bound at deploy. Author HTML (custom CSS/JS) is explicit trusted study code; model/participant output never implicitly executable. Replaces the stale author-facing `slot=` sketch | API-17 (A17-O04), spec |
| R-13 | **In-page JS bridge** (2026-07-19): typed `window.mug` only — `mug.response.set/get` (+ auto-collection of named form controls → the activity response, receipt-gated per D12-2, downstream via `activity.field(...)`), `mug.state.get/set` (client-writable visit `StateDocument`), `mug.advance()`. `mugGlobals` retired; no shim | API-17 (A17-O05), API-09, spec |
| R-14 | ~~Effects live at the Treatment (`applies=[Cast/Param]`)~~ — **superseded same day by R-15** (user: the treatment/interaction separation was itself the problem) | — |
| R-15 | **Treatment inline at its point of effect** (2026-07-19): `cast={"seat": Treatment(key=..., levels={label: Actor...}, assign=...)}` and `Spec(field=Treatment(...))` — the treatment sits exactly where it takes effect. Multi-effect: reuse the same object, `t.map({...})` for per-site values. True factorial: optional `study.set_design(Design(cross=[...], assign=...))` for jointly balanced cells (independent assignment otherwise). Scope inferred where placement forces it (shared seat ⇒ GROUP; contradiction = compile error); `check()` prints the effect map; `Design` naming an unplaced treatment is a compile error. `Factor`/`Cast`/`Param`/`design.cast`/`design.level` all removed | API-04 (index + A04-O06), API-05, catalog, spec + example |
| R-16 | **Cast totality** (2026-07-19): omitting `cast` means every seat is human (common case stays one line); a present `cast` must name **every** seat — partial cast dicts are a compile error, so no seat's occupant is implicit alongside explicit ones | API-05, spec + example |
| R-17 | **Env creation is a factory, never an instance** (2026-07-19): `Game(env=make_env)` (module-level callable, or the class for no-arg construction), recorded by qualified name; every runtime — server worker, each Pyodide client, each P2P peer, each `mug simulate` worker — imports the study source (shipped via F-1 client manifest) and constructs its own env. Declared kwargs via `args={...}` (values may be inline `Treatment`s per R-15, resolved + recorded per occurrence); `requires=[...]` browser packages pinned at publish. Lambdas rejected; instances never pickled/shipped. Replaces `environment_initialization_code(_filepath)` + magic module-level `env` + `packages_to_install`. Mechanism proven 2026-07-19 in a real Pyodide runtime (zip → unpackArchive → import → make_env) | API-07 (index + A07-O04), catalog, spec + example |
| R-19 | ~~Deploy topology = platform + local auto-start (operator API, artifact push)~~ — **superseded same day by R-20** (user: too much machinery; take the Deliberate-Lab-style typical run path) | — |
| R-21 | **Deploy publishes** (2026-07-19): `mug deploy study@1.0` auto-publishes the current git state as "1.0" when the string is unused (safe via D02-3: byte-identical re-deploys idempotent; changed content under a used string is a plain error — bump the string). Bare `mug deploy study` = **localhost-only dev preview** of the working tree: no version minted, preview-marked/non-citable data, non-localhost `--at` refused. `mug run` retired (revises R-4/A02-O08); `mug simulate` auto-publishes identically; `mug export` never publishes; `study.publish()` remains the explicit/CI form | API-02 (verbs + §Process model + A02-O08/O11), API-01 §Publication note via spec, catalog, spec + example |
| R-20 | **Deploy topology = one typical run path** (2026-07-19, Deliberate-Lab-inspired): `mug deploy study@version --secret k=$V [--at URL]` runs **on the hosting machine** (laptop for dev, lab box/VM for collection — identical commands); it starts the local server process if needed (web + durable store + workers in one group), records the `DeploymentRevision` in the machine's local store, satisfaction-checks, serves. Study code reaches the host via git (`clone`/`pull`); publish idempotence (ADR-0013) means publishing the same commit + string on the host reproduces the identical version. `--at` = presented public URL for participant links (default localhost), never a remote target; no remote deployment protocol / operator API / artifact push; MUG provisions no machines/DNS/TLS | API-02 (§Process model + A02-O10), catalog, spec CLI |
| R-18 | **Grouping = shared `Group` object** (2026-07-19, generalizes `Pairing` to match current-MUG matchmaking): `Group(size=N, match=Match.FIFO \| Match.latency(max_estimated_rtt=, max_p2p_rtt=) \| custom mug.Matchmaker subclass, wait=, on_timeout=OnTimeout.RELEASE)`. `Match.latency` preserves the two-stage flow (server-RTT pre-filter → P2P probe of the proposal → reject/re-pool over `rank_candidates`); custom matchmakers are core authoring (today's ABC: `find_match(arriving, waiting, size)`), versioned with the study. **Persistence-by-shared-object**: the same `Group` on several interactions reunites the same participants (durable recorded group identity; `OnMissing.WAIT/REGROUP` = today's GroupReunionMatchmaker±fallback); `Scope.GROUP` treatments assign per `Group` and ride with it | API-05 (index + review), API-06, catalog, spec + example |

---

# Runtime-parity resolutions (RP-1..RP-10, 2026-07-20)

A separate decision family from the R-* authoring resolutions above. These
resolve the cross-cutting questions raised by the **runtime data-flow parity
audit** — a seven-dimension read-only audit of the current `mug/` runtime
(P2P transport, server-authoritative loop, Pyodide lifecycle, data capture,
matchmaking, scene flow, client policies) mapped onto the 0.2 contracts. The
audit reports and the full RP-1..RP-10 ledger with per-decision rationale live
at **[docs/architecture/runtime-parity/index.md](../../docs/architecture/runtime-parity/index.md)**;
this table is the pointer from the master ledger. Each RP decision is a contract
delta for the named family's next revision; the architecture family review
records track whether that fold has been executed.

| ID | Resolution (summary) | Folds into |
| --- | --- | --- |
| RP-1 | **P2P = N-peer mesh now** (not pairs-only); hidden-info incompatibility left per-study, not a blanket rule | API-07, API-06 |
| RP-2 | **Adopt the runtime's A07-O02 finality answers as-is**: RNG-inclusive logical snapshot coverage, confirmed→verified finality, min-frame episode barrier, lower-ID-defers live-resync direction, symmetric input delay. A07-O01's portable binary codec remains open. | API-07, API-16 |
| RP-3 | **Designated bot-decision authority in P2P** (one peer decides, streams like a remote human; decisions become recorded evidence) | API-12, API-07, API-16 |
| RP-4 | **Drop `on_game_step_code`** (env class + hooks + factory cover the uses) | API-07 |
| RP-5 | **Drop `custom_inference_fn`** (folds into the typed `OnnxPolicy` spec or a scripted `Policy`) | API-05, spec |
| RP-6 | **In-play quality monitoring = typed `MonitoringPolicy`** on the Interaction surface, server-authoritative enforcement | API-06, API-09 |
| RP-7 | **N>2 probe = pairwise mesh, all pairs pass** (consistent with RP-1) | API-05, API-06 |
| RP-8 | **Adopt readiness-gating `mug.gate` op**; state→env-args path and read-only participant handle **not** adopted (open sub-items) | API-09, API-17 |
| RP-9 | **Capture the full experienced stream** (canonical + experienced with `delivery_kind`) | API-10, API-16 |
| RP-10 | **Screening/eligibility callbacks = API-04 flow-level, fail-closed default** (opt-in fail-open); continuous exclusion rides RP-6 | API-04, API-06 |

**RP-3 revision-0.3 hardening choice (2026-07-20):** RP-3 selected a
designated deterministic authority but did not select its algorithm or failure
policy. Revision 0.3 uses the canonical highest eligible peer actor ID for each
bot seat and fixes that authority for the episode. A peer never elects itself
mid-episode; any later assignment requires a new fenced authority generation
with no overlap. This additional choice makes the API-07/API-12/API-16 fixture
contract executable and aligns the decision producer with RP-2's
lower-ID-defers live repair direction. It does not make that peer's state
scientifically authoritative when hashes disagree.

**Open sub-items** (from RP-8, still unresolved): the typed state→env-args
resolution path (replacement for the legacy `mugGlobals`→init-code env
parametrization channel), and whether page JS gets a read-only pseudonymous
participant handle. Both recorded in the parity audit index.
