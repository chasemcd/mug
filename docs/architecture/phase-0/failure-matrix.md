# Phase 0 Failure and Recovery Matrix

| Field | Value |
| --- | --- |
| Status | Proposed |
| Note | Defaults require confirmation by the owning ADR and API specification |
| Last updated | 2026-07-20 |

Every API specification must either adopt these defaults or link an accepted
decision that replaces them. "Retry" is not a complete failure policy.

| Failure | Proposed semantic default | Owning API families |
| --- | --- | --- |
| Transport parses/queues a command but domain work is not terminal | Return only `TransportAck` or mutable `CommandStatus`; never claim a `CommandReceipt` or advance participant workflow. | API-09, API-22, all command APIs |
| Same idempotent command is already running | Return/poll the existing status; do not start another execution. | All command APIs, API-22 |
| Server commits a mutation, then crashes before replying | Retry with the same idempotency key returns the original `CommitReceipt`. | API-04, 06, 08, 09, 18 |
| Same key is retried with different content | Reject with an idempotency conflict; do not create a second effect. | All command APIs |
| A version string is reused for different content, or identical content is republished under a new string | Reject both (F-1 collision rules); identical content under the same string is idempotent and returns the existing version. | API-01 |
| Identical compilation inputs produce different canonical bytes | Quarantine the compiler build and make neither candidate publishable. | API-01, API-22 |
| Candidate artifact disappears or changes before publication | Reject before the catalog transaction; expose no partial version or accepted receipt. | API-01, API-11 |
| Two publishers submit identical scientific content | Create one immutable version and `published` event; the other valid command gets its own durable `publication_resolved_existing` fact/receipt pointing to that version. | API-01 |
| Publication commits, then the service crashes before replying | Same command returns the original publication receipt and version; no ordinal/event is duplicated. | API-01, API-11 |
| Two browser tabs claim one participant/actor | A durable lease generation fences the loser; stale commands cannot mutate state. | API-03, 06, 09 |
| A stale game/interaction worker continues after reassignment | Effect application checks the fencing generation and rejects the stale owner. | API-06, 07, 12 |
| Ephemeral lease state is lost | Authority changes its lease namespace epoch before accepting effects; every prior token is fenced even if a generation collides. | API-06, 07, 09, 12, 22 |
| Game worker dies mid-episode | Resume only with a verified complete snapshot contract; otherwise close a partial attempt and start a new occurrence/attempt. | API-07, 10, 16 |
| Browser closes before a capture chunk is durable | Declare IndexedDB/bounded buffering and completeness policy; accepted server chunks remain readable as a partial artifact. | API-09 through 11 |
| Artifact bytes upload but metadata transaction fails | Bytes remain unreferenced staging/orphan data and are garbage-collected safely. | API-11 |
| Metadata exists but final object cannot be read | Keep the artifact in non-final/read-error state; never expose it as a committed readable reference. | API-11 |
| A previously committed object later becomes unavailable or fails integrity | Mark availability/integrity failure, withdraw dependent replay/presentation capabilities, alert operators, and restore or quarantine; do not deny the historical commit. | API-11, 16, 18 |
| Database is unavailable during research-significant command | Do not acknowledge acceptance; apply the activity's declared pause, bounded-buffer, or fail-closed policy. | API-04, 06, 08, 09, 18 |
| Capture store is unavailable mid-interaction | Capture profile declares pause, bounded local buffer, degraded continuation, or fail closed; resulting completeness is explicit. | API-07, 09 through 11 |
| Event batch arrives twice or out of order | Duplicate batch returns the prior receipt; a sequence gap/conflict is rejected or quarantined according to producer policy. | API-10 |
| Provider times out and later succeeds after reset | Record provider outcome, but mark the decision stale/discarded; apply no action, message, tool effect, or memory write. | API-12, 13, 15 |
| A non-designated or old-fence peer publishes a P2P bot action | Reject it before environment application; retain the attempt as evidence. The episode-fixed authority does not change by self-election, and the declared realtime fallback/pause/abort policy applies. | API-07, 10, 12 |
| Provider fails after streaming partial text | Deltas remain provisional experienced-delivery evidence; no final canonical message exists unless commit policy succeeds. | API-08, 12, 13 |
| Channel membership changes while an LLM is running | Revalidate membership and effect validity at publication time; discard or quarantine output that is no longer valid. | API-06, 08, 12 |
| LLM emits chat and game action together but action is stale | Validate effects independently by default under one decision ID; optional all-or-none policy must be explicit before request. | API-05, 07, 08, 12 |
| Provider fallback is invoked | Fallback must be predeclared, budgeted, and recorded as actual exposure; otherwise fail using the declared non-fallback policy. | API-04, 12, 13 |
| Tool times out before known side effect | Apply the tool's retry/idempotency policy. | API-14 |
| External tool times out after a possible side effect | Mark `unknown_outcome`; never retry automatically; require reconciliation or compensation. | API-14 |
| Environment-mutating tool completes in worker | Worker result is only a proposal; the authoritative environment mailbox validates and applies it once. | API-07, 14 |
| LLMs recursively activate one another | Enforce activation depth, turn, concurrency, time, token, and cost budgets plus loop detection. | API-08, 12, 13 |
| P2P peers disagree at finalization | Preserve claims and diagnostics; mark disputed/quarantined and do not advance `verifiedFrame`. Lower-ID-defers may choose live repair direction but does not invent scientific agreement. | API-07, 10, 16 |
| Only one P2P peer uploads evidence | Mark partial/unverified according to the capture policy. | API-07, 10, 16 |
| One P2P peer is absent from the episode-end claims | Do not silently shrink the frozen mesh. The minimum `end_frame_exclusive` barrier is incomplete, so finalization follows the declared partial/abort policy. | API-06, 07, 10, 16 |
| Participant disconnects from a group interaction | Apply the versioned policy: grace/pause, substitute, continue partial, abort, or compensate; record all effects. | API-06 through 09 |
| Participant reconnects after interaction generation changed | Provide current snapshot or terminal outcome; reject commands from the obsolete generation. | API-06, 09 |
| Study changes between longitudinal visits | Follow an explicit part/version transition rule in the multi-part flow; never move an active or returning enrollment automatically to latest. | API-01 through 04 |
| Preference connection drops after response commit | Retry returns the same receipt and progression occurs at most once. | API-04, 09, 18 |
| Candidate/presentation artifact is unavailable | Do not substitute a different candidate silently; pause, reassign under policy, or invalidate with evidence. | API-11, 16, 18 |
| Memory revision changes while a decision is running | Reject or explicitly rebase the proposed write; never overwrite silently. | API-12, 15 |
| Decision becomes stale after reading memory | Discard its write proposal even if provider work succeeded. | API-12, 15 |
| Unknown critical event/schema version is read | Preserve bytes, stop the affected projection/replay, and report unsupported schema; never skip critical scientific state silently. | API-10, 16, 19 |
| Version-0 proposal schema appears in publication/deployment/evidence | Reject publication/deployment/ingest. Version 0 is mutable review material, never retained scientific data. | API-01, 02, 09 through 11, 16, 19 |
| Unknown noncritical observational event is read | Preserve and surface an unsupported-event diagnostic; a versioned projection may skip only if its contract allows it. | API-10, 19 |
| Replay artifact is modified or missing | Integrity validation fails and affected capabilities are withdrawn; never perform best-effort exact replay. | API-11, 16 |
| Replay encounters a state-hash mismatch | Stop deterministic verification at first divergence and offer visual fallback only if independently available. | API-07, 16 |
| Researcher deletes source data from their own store after export/bundle creation | Lineage identifies every dependent derivative so the researcher can act on them; MUG defines lineage, not deletion workflows — the researcher-owned store is authoritative (F-4). | API-11, 16, 19 |
| Provider lacks a published required capability | Compilation/deployment fails closed; do not silently degrade scientific semantics. | API-01, 02, 13 |
| Operator terminates or quarantines an interaction | Append immutable termination/quarantine event facts and finalize evidence according to policy; do not rewrite prior canonical events. The action is ungated (self-hosted). | API-06, 10 |

## Required sequence diagrams

Phase 0 produces normal and failure sequence diagrams for at least:

1. Publish: git-state capture (commit + patch), compilation job, manifest
   finalization, and atomic publication
2. Visit start with assignment and plan materialization
3. Activity advance with response/evidence transaction
4. Browser artifact upload and finalization
5. Interaction join, lease fencing, disconnect, and resume
6. Server-authoritative game action and committed transition
7. P2P speculative action, rollback, finalization, and disagreement
8. Human chat submission and durable publication
9. Streaming LLM response followed by success, cancellation, and late result
10. Tool call with read-only success, idempotent mutation, and unknown outcome
11. Preference presentation, response, lost receipt, and duplicate retry
12. Replay bundle build, validation, deterministic divergence, and visual fallback
13. Return-link re-entry across a multi-part flow and an intentional version
    transition; compile job and headless `mug simulate` batch run

## Failure-matrix gate

Phase 0 fails if any mutable API lacks:

- A durable acknowledgment boundary
- Idempotency and conflict behavior
- Authority/fencing semantics
- Timeout and cancellation behavior
- Partial/degraded state representation
- Privacy-safe error behavior
- Evidence emitted for both success and failure
