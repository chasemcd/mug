# Phase 0 Acceptance Scenarios

| Field | Value |
| --- | --- |
| Status | Proposed |
| Last updated | 2026-07-18 |
| Purpose | Validate that independently designed APIs compose into the required platform |

These are architecture acceptance scenarios, not yet implementation tests.
During Phase 0, each scenario must be walked through using concrete API calls,
state transitions, wire messages, events, artifacts, retries, and failures.
Golden fixtures created from these scenarios become implementation contract
tests in later phases.

## Common assertions

Every scenario must identify:

- Study version and deployment
- Enrollment, visit, visit plan, and activity occurrence
- Seats, actor instances, controller bindings, and channel memberships
- Authority and ordered stream for every accepted intent
- Assignment and actual exposure
- Events, artifacts, capture policy, and privacy classifications
- The durable boundary before each participant-visible acknowledgment
- Restart, reconnect, duplicate, timeout, and cancellation behavior
- Replay capability and completeness claims
- Export lineage

The [shared-kernel conformance plan](shared-kernel/conformance.md) assigns
`SK-01` through `SK-32` to the common wire, retry, transaction, ordering,
fencing, artifact, and privacy paths. `SK-01` through `SK-10` begin with concrete
version-0 schemas/fixtures; the stateful cases become executable as their owning
domain APIs are specified. This trace does not imply those domain contracts are
already accepted.

## NS-01 — Preference over trajectories

One participant completes two game episodes under different blinded partner
conditions. Each episode produces canonical trajectory and visual replay
artifacts. A preference activity materializes two opaque candidates, randomizes
their display order, records playback exposure, and collects pairwise choice,
tie/abstain, ratings, confidence, and optional rationale.

**Pass conditions**

- Candidate identity is independent of A/B position.
- Private partner/model metadata is absent from the client manifest.
- The response cannot advance the visit before durable acknowledgment.
- Refresh resumes the same assignment and presentation order.
- Export rows link to protocol version, assignment, candidate, episode, bundle
  digest, and transformation version.

## NS-02 — Preference over LLM outputs

A candidate-generation job records two model generations for the same versioned
input. An independent annotator compares the published outputs without running
the original chat interaction or contacting either provider.

**Pass conditions**

- Generic artifact candidate references do not depend on a trajectory type.
- Raw provider response, normalized generation, and participant-visible output
  are distinct references.
- Provider and model identity can be blinded while remaining available in
  private provenance.
- Preference collection succeeds when the provider is offline.

## NS-03 — One human chats with one LLM

One human and one LLM actor share a chat channel. The LLM responds on each
accepted human turn, streams presentation deltas, uses a persisted context
snapshot, and publishes one committed participant-visible message.

**Pass conditions**

- Provider work does not run on a realtime socket or environment lock.
- Message start, deltas, commit, delivery, and acknowledgment are distinguishable.
- Refresh restores committed history and the current pending/failed turn.
- A late provider result from an obsolete interaction generation is recorded as
  discarded and cannot publish or write memory.

## NS-04 — Multiple humans chat with one LLM

Two humans and one LLM share a group channel. Humans submit messages
concurrently; the channel establishes canonical order and the activation policy
creates an explicit LLM response plan from a defined context boundary.

**Pass conditions**

- Actor identity and authorization are derived from connection leases.
- Canonical order does not depend on client clocks.
- Each participant's delivery timing may differ without changing canonical
  message identity.
- The context snapshot records exactly which ordered messages the LLM saw.

## NS-05 — Multiple humans chat with multiple LLMs

Two humans share a public channel with a partner LLM and a coach LLM. Only one
human can see a private coaching channel. The partner responds when mentioned;
the coach responds after a configured event. Both LLMs have independent model,
prompt, memory, and tool policies.

**Pass conditions**

- Membership and effective capability checks prevent private-channel leakage.
- Activation rules prevent accidental response storms.
- Concurrent agent completions receive deterministic publication order.
- Model, memory, and tool evidence remains isolated by actor and treatment.

## NS-06 — Humans play while chatting

Two humans play a multiplayer game while using public and team chat. Game and
chat channels share one interaction but have independent latency and ordering
requirements.

**Pass conditions**

- Chat I/O cannot stall environment stepping.
- Evidence relates independently ordered game and chat streams through
  causation, environment step, render frame, channel sequence, and server
  monotonic anchors without pretending one global order describes what every
  participant experienced. An optional coordinator acceptance sequence is
  labeled only as server acceptance order.
- Chat remains usable during configured pause/intermission states.
- Replay can show messages synchronized with game progress.

## NS-07 — An LLM plays and chats

An LLM partner observes structured game state and public chat. On an
event-triggered cadence it returns a short validated action plan and a chat
message. A deterministic local controller executes the plan between LLM
decisions.

**Pass conditions**

- The LLM is not called once per render frame.
- Game actions and chat messages have independent validity and publication
  rules.
- Invalid actions, deadline expiry, and provider outage invoke the declared
  fallback without silently changing treatment.
- Exact replay injects recorded executed actions and messages and makes zero
  provider calls.

## NS-08 — Durable longitudinal recovery

A participant enters the first part of a multi-part flow through an external
panel launch link. Their treatment and randomized visit plan are committed, the
server is terminated at each activity boundary in separate test runs, and the
participant later returns via their stable return link for the second part
under an intentionally updated study version.

**Pass conditions**

- Restart never rebuilds or reshuffles the committed plan.
- Duplicate launch and completion requests return stable receipts.
- Assignment and exposure histories remain distinct across parts.
- Only state namespaces declared for the second part are carried forward.
- Direct external identity never appears in research object keys or ordinary
  exports; the external reference lives only in the blinded
  `ExternalIdentityLink` stored apart from research data.

## NS-09 — P2P rollback, evidence, and replay

Three humans run a browser/P2P game as a generation-fenced full mesh under
injected latency, packet loss, rollback, and focus loss. Each peer uploads
canonical claims and its experienced stream.

**Pass conditions**

- Every required action reaches every peer; confirmation and state-hash
  verification include the complete frozen three-peer membership.
- `confirmedFrame` and `verifiedFrame` advance as distinct contiguous
  high-water marks; a predicted action cannot confirm a frame.
- The episode's `end_frame_exclusive` is the minimum complete end claim over
  all three peers, and actions beyond it are not canonical episode content.
- Matching final peer digests produce `peer_reconciled` evidence.
- Missing peer evidence is explicitly partial/unverified.
- Conflicting peer evidence is quarantined, not silently selected.
- Lower-ID-defers may choose a live state-repair direction but cannot convert a
  disagreement into verified evidence.
- Speculative and rollback events remain outside the finalized canonical
  trajectory but are available in experienced/diagnostic streams.

## NS-10 — Preference submission failure and recovery

The connection drops after the server commits a response but before the browser
receives its receipt. The client retries with the same idempotency key, then
tries a conflicting payload under that key.

**Pass conditions**

- The identical retry returns the original receipt.
- The conflicting retry returns an idempotency conflict.
- Exactly one response is canonical.
- Visit progression occurs at most once.

## NS-11 — Tool side effect, timeout, and replay

An LLM requests a read-only retrieval tool and a reversible environment command.
The first completes; the second times out after being accepted by its execution
authority.

**Pass conditions**

- Tool authority, schema, scopes, and approval are checked before execution.
- The environment command is applied only by the owning environment runtime.
  Mutating external tools are unavailable in replicated P2P until a later
  authority contract explicitly supports them.
- Retry cannot duplicate an accepted side effect.
- Replay substitutes the recorded result/status and executes neither tool.
- A stale agent completion cannot commit a memory write based on the timed-out
  turn.

## NS-12 — Privacy, export, and the researcher-owned store

A chat contains participant text classified as sensitive; an external identity
mapping is PII; provider credentials are secrets. The researcher exports the
dataset (export is ungated; MUG is self-hosted), and later honors a
participant's withdrawal by acting directly on the researcher-owned store —
deleting the `ExternalIdentityLink` and any restricted artifacts themselves.
Withdrawal and deletion workflows are not MUG features (F-4, ADR-0015).

**Pass conditions**

- Secrets appear only through server-side references and never enter events,
  bundles, logs, or client manifests.
- Every export carries source and transformation lineage for MUG-managed
  records and artifacts. Copies or derivatives created after export remain the
  institution's responsibility.
- The external identity mapping lives only in the blinded link stored apart
  from research data; deleting it severs re-identification without touching
  research evidence.
- The classification lattice (`research+sensitive`, `research+pii`, `secret`)
  keeps sensitive text outside its declared channel/presentation audience and
  out of ordinary logs.
- MUG's data lives in a store the researcher controls and can query, export,
  or delete directly; MUG imposes no retention or deletion layer of its own.

## Integrated Phase 0 walkthrough

The final walkthrough combines NS-01, NS-05, NS-06, NS-07, NS-08, NS-09, and
NS-12 into the north-star story. Reviewers must trace:

1. Study compilation and publication
2. Signed launch, enrollment, assignment, and visit-plan materialization
3. Matchmaking and interaction creation
4. Human, game-controller, and LLM-controller bindings
5. Public, private, and game channel membership/write validity
6. Concurrent game, chat, provider, tool, and storage behavior
7. Crash/reconnect and stale-completion paths
8. Canonical and experienced capture
9. Replay-bundle construction and offline validation
10. Trajectory and model-output preference assignments
11. Longitudinal return under an intentional version transition
12. Ungated export with lineage; researcher-owned withdrawal/deletion against
    their own store

Phase 0 fails if any step requires an unversioned dictionary, ambiguous actor or
participant identity, client-trusted ownership, implicit randomization,
unrecorded provider/tool behavior, or an unspecified acknowledgment boundary.

## Shared-kernel trace summary

| Scenario | Primary shared-kernel cases |
| --- | --- |
| NS-01/NS-02 | SK-04, SK-06 through SK-10, SK-22, SK-23 |
| NS-03 | SK-01 through SK-05, SK-17, SK-24, SK-30 |
| NS-04/NS-05 | SK-02, SK-17, SK-20, SK-28, SK-30 |
| NS-06/NS-07 | SK-17, SK-20, SK-21, SK-24, SK-25 |
| NS-08 | SK-08, SK-12, SK-15, SK-17, SK-29 |
| NS-09 | SK-17 through SK-21 |
| NS-10 | SK-04, SK-05, SK-11 through SK-16, SK-27, SK-29 |
| NS-11 | SK-17, SK-24, SK-26 |
| NS-12 | SK-02, SK-06 through SK-08, SK-23, SK-28, SK-30 |

## API-01 trace summary

Every scenario first passes through the same immutable API-01 publication
boundary; this table identifies its additional authoring and manifest
obligations.

| Scenario | API-01 compile/publication obligation |
| --- | --- |
| NS-01 | Game/replay candidates, blinding rules, presentation requirements, capture/replay schemas, and client-safe slots compile without candidate/model leakage |
| NS-02 | Provider-independent generation artifacts and preference protocol compile with private provider/model provenance and offline presentation capability |
| NS-03 | Human/LLM seats, channel, activation, model/prompt policy, context/capture requirements, and logical provider secret slot are pinned |
| NS-04/NS-05 | Multiple seats/channels/agents, independent visibility, activation budgets, and per-agent model/prompt/tool packages are cross-validated |
| NS-06 | One interaction composes independent game/chat channels and presentation components without coupling their runtime ordering |
| NS-07 | Game observation/action/chat schemas, slow decision cadence, deterministic controller package, fallback, and zero-provider replay requirement are pinned |
| NS-08 | Stable definition-key lineage (derived from published history), multi-part flow/version transition, flow/randomization rules, and a second intentional publication compile; no restart reconstructs source |
| NS-09 | P2P execution/capture/reconciliation capabilities and deterministic package requirements fail closed when unsupported |
| NS-10 | Preference/form response schema and durable-progression requirement are part of the published protocol |
| NS-11 | Tool definition/policy/authority requirements and replay substitution capability are pinned; credentials remain deployment bindings |
| NS-12 | Data flows, privacy classifications, client disclosure rules, and logical secret requirements pass privacy compilation; retention/withdrawal are the researcher's own store, not compiled policy |
