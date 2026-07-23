# Folding plan — scratch review → real contracts

> **STATUS: EXECUTED 2026-07-18.** All sections below were folded into
> `docs/architecture/` on 2026-07-18: ADRs 0013–0015 landed; API-01 rewritten
> (git-native, rev 0.2, schema+fixtures+tests regenerated); API-03 reduced;
> API-20 removed / API-21 retracted (tombstones, corpus tests updated); per-family
> doc deltas applied to API-02, 04–19, 22 as `0.2 (docs)` (schema bundles remain
> 0.1 pending re-draft); cross-cutting docs updated; and the net-new public
> Python authoring API spec written at
> `docs/architecture/phase-0/python-authoring-api.md`. Full
> `tests/architecture` suite: 332 passed. This file is retained as the plan of
> record.

This is the map of what folding the approved decisions in actually means. Ordered
biggest-structural-change first.

## A. Foundational changes (do these first — they reshape families)

| # | Change | Contract impact |
| --- | --- | --- |
| **F-1** | Git-native versioning + stored compiled artifact | **Major API-01 rewrite.** Remove `StudyDraft`, `DraftRevision` chains, head/registry optimistic preconditions, `diff_revisions`, `allocate_definition_id`/`commit_revision`, the mutable `DefinitionRegistry` aggregate. Add: git commit **+ patch** provenance, hand-typed **version string** (unique/immutable handle) alongside content digest, "store the compiled artifact." Keep: compile→immutable `StudyVersion`, content-digest identity, client/server/provenance manifests, secret-requirement slots, availability (deprecate/withdraw). |
| **F-2** | MUG owns identity, not recruitment | **API-03 scope reduction.** Collapse `ConsentRecord` → consent is an ordinary flow activity (recorded response). Collapse `WaveSpec` → multi-part flow + stable return link. Remove invite/targeting/scheduling. Keep `Enrollment`, `LaunchTicket`, `ExternalIdentityLink`. |
| **F-3** | No magic strings | **Cross-cutting.** Every closed vocabulary in every family schema/doc becomes a typed constant/enum; references become typed handles. Author-defined identifiers stay strings. No behavior change; typing/shape only. |
| **F-4** | Governance out of scope | **Remove API-20 entirely** (authorization/roles/audit/retention/deletion/data-rights). Re-home the two things that weren't governance: immutable event capture stays in **API-10**; minimal secret *storage* (by-reference, never in client/science) stays in **API-02**. Update every "authorized by an API-20 grant" reference across families to "ungated / self-hosted." |
| **API-21 retraction** | Extensions = plain Python; no framework | Remove `PluginManifest`, `CapabilityNegotiation`, trust classes/sandboxing, and all sharing/distribution. No extension points in v0 (closed sets closed). Keep only the recorded post-v0 direction (typed `ExtensionPoint` protocol). |

## B. Per-family impact

| Family | Change | Driving decisions |
| --- | --- | --- |
| API-01 Authoring | **Major rewrite** (F-1) | F-1, D01-*, D02-* |
| API-02 Deployment | Simplify: one-call deploy, `deploy`/`stop` only, secret pass-at-deploy, in-flight pin; drop API-20 authority coupling | D03-1…5, F-4 |
| API-03 Identity | **Scope reduction** (F-2) | F-2, D04-* |
| API-04 Visit/Treatment | Add `Scope.GROUP` treatment, balance-across-version-lifetime (durable allocation), declarative treatment surface; keep assignment/exposure split | D06-*, D05-1/2 |
| API-05 Actors | Add explicit **seat↔env-agent-id binding**, casting model, `Pairing` config, all-agent allowance | D07-*, D09-7 |
| API-06 Interactions | Typed channel kinds, `Membership` (all-seats default) | D08-1/2/3 |
| API-07 Game runtime | **All 3 exec modes v0** (P2P risk), Gym-style env, **preserve full `Surface`**, per-seat render packets | D08-4/7, D09-* |
| API-08 Conversation | Default chat widget, streaming, inline preference hook | D10-5/7, D12-8 |
| API-09 Client | Typed input scheme (env action space), per-seat routing/delivery | D10-* |
| API-10 Evidence | **Preserved** (now the home of immutable capture, not governance) | F-4, D05-6/D08-6 |
| API-11 Storage | Preserved | — |
| API-12 Scheduler | `decides_every`/frame_skip, explicit fallback | D11-2/3/4 |
| API-13 Providers | Provider set (OpenAI/Anthropic/OSS/HTTP), immutable agent version | D11-1/4 |
| API-14 Tools | Native + MCP, approval, replay substitution | D11-5 |
| API-15 Memory | Treatment modes | D11-6 |
| API-16 Replay | Levels, no-external-call, branching, trajectory-slice candidates | D13-4/5/6/7 |
| API-17 Content/Forms | Field types (core+slider/rating), gating receipt, WCAG floor | D12-1/2/6 |
| API-18 Preferences | Pairwise+rating, blinding/order, inline in-chat | D12-3/4/5/8 |
| API-19 Export | **JSONL single format**, lineage, redaction-as-new-object | D13-1/2/3 |
| API-20 Governance | **REMOVE** | F-4 |
| API-21 Plugins | **Retract machinery**; defer | D15-* |
| API-22 Jobs | Preserved (compile jobs, `mug simulate` batch) | D11-7 |

## C. Net-new work (not just edits to existing families)

1. **The public Python authoring API layer.** Phase-0 contracts are wire/persisted;
   this review defined a whole author-facing Python surface (`Study`, `activities`,
   `flow`, `Treatment`/`Factor`, `Seat`/`Actor`, `Game`/`Chat`, `Input`, `LLMAgent`,
   `Scene`/`Surface`, `Form`/`Preference`, `Dataset`, …) that needs its own contract/spec.
   Biggest new artifact. Must obey D01-8 (methods not attributes) and F-3 (typed vocab).
2. **Git provenance type** (commit + patch bytes) in the shared kernel / API-01.
3. **CLI surface** (`mug deploy`/`stop`/`export`/`simulate`) — a new operator/analyst
   interface not previously specified.
4. **`mug simulate`** headless batch runner (API-22 + API-05 all-agent).

## D. ADR implications

- New/updated ADR for **git-native versioning** (supersedes parts of ADR-0012 deterministic
  compilation/atomic publication).
- New ADR: **governance out of scope** (removes the governance half of ADR-0011; keeps
  data-classification/secret-reference parts as security).
- New ADR: **MUG scope boundary** (not recruitment/panels/governance) — records F-2/F-4.
- ADRs 0002–0012 are still *Proposed*; reconcile each against F-1…F-4 before Acceptance.

## E. Suggested order

1. Land the ADRs for F-1/F-2/F-4 (they gate the rewrites).
2. Rewrite API-01 (F-1) and reduce API-03 (F-2); remove API-20 (F-4); retract API-21.
3. Apply F-3 typing sweep across all remaining families.
4. Fold the per-family deltas (table B).
5. Author the net-new public Python API spec (C-1) — largest single new piece.
6. Regenerate schemas/fixtures/digests and re-run `uv run pytest` (see the digest-regen memory).
