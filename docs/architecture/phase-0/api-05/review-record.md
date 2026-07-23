# API-05 Review Record

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.3` |
| Review opened | 2026-07-17 |
| Accountable owner | Unassigned |
| Target accepted version | `1` |

## Deliverable status

| Deliverable | Status | Evidence |
| --- | --- | --- |
| Ownership, lifecycles, and boundary | Drafted | [Index](index.md) |
| Version-0 schemas | Drafted | `actor.schema.json` |
| Golden fixtures and harness | Drafted | 25 fixtures, 31 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Seat is an authored role distinct from the actor that fills it
- [x] Actor is human (enrollment) xor software (agent version)
- [x] Controller binding maps one capability in one channel to one controller kind
- [x] Human input carries no controller reference; software controllers must
- [x] Capability and controller kind compatibility is enforced
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [x] Explicit seat↔env-agent-id binding, casting model, `Group` (né `Pairing`, R-18), and all-agent allowance documented (docs and schema)
- [x] Seat↔env-agent-id binding record, `Group`/`Match`, and all-agent castings in the schema bundle
- [x] RP-5/RP-7 decisions recorded: no `custom_inference_fn` escape hatch;
      latency-bounded N-person groups require every pair in the P2P mesh to pass
- [x] Fold RP-5/RP-7 into the 0.3 contract, exact policy/group schemas,
      semantic rules, and fixtures; the current 0.2 bundle does not encode them
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [ ] Human-takeover and mid-interaction rebinding semantics defined (agent-backfill of a human seat is out of scope for v0, D07-8)
- [ ] Per-modality effect-time capability checks defined with API-06 (interaction membership; ungated, self-hosted — ADR-0015)
- [ ] API-12 scheduler and API-07/08 channel-execution compatibility reviewed
- [ ] NS-03 through NS-07 walkthroughs pass
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A05-O01 | Human takeover of a software seat | Rebind the actor's controller under a new fenced binding; prior evidence immutable. (Reverse direction — agent-backfill of a human seat — is decided out of scope for v0, D07-8) | ['API-06 review'] |
| A05-O02 | Controller reference to policy vs agent version | Software controllers reference an immutable agent/policy version; no live client | ['API-12/API-13'] |
| A05-O03 | Per-channel capability checks | Effect-time capability checks against interaction membership; ungated (self-hosted; ADR-0015) — no grant system | ['API-06 review'] |
| A05-O04 | All-agent launch path detail | `mug simulate … --n`, headless by default, scheduler-driven (D07-8/D11-7); exact command contract with API-22 | ['API-12/API-22'] |

## Settled runtime-parity input (folded in revision 0.3)

- **RP-5:** `custom_inference_fn` is dropped. Typed `OnnxPolicy`
  preprocessing/selection or a versioned scripted `Policy` covers custom
  behavior; there is no inline-JavaScript inference escape hatch. **Folded 0.3:**
  the `OnnxPolicy` bundle (`mug.api-05.onnx-policy`) declares a typed
  `preprocessing` rule (closed vocabulary `identity`/`normalize`/`standardize`/
  `clip`/`flatten`/`one-hot`) and a closed-enum `selection_mode`
  (`argmax`/`sample`, with an optional `temperature` only under `sample`);
  `ControllerBinding` and `OnnxPolicy` use `additionalProperties: false`, so an
  inline-code field such as `custom_inference_fn` is structurally rejected.
- **RP-7:** N>2 latency matching probes every pair and forms the group only when
  all pairwise RTTs satisfy `max_p2p_rtt`. **Folded 0.3:** the two-stage
  `MatchLatency` strategy declares `max_p2p_rtt`; its description states that the
  group forms only when every pairwise RTT is within the bound. This is the
  author-facing declaration; the runtime all-pairs probe-evidence record is owned
  by API-06 (referenced by name, not pinned by digest), so no author-time
  semantic rule applies.

## Folded runtime-parity decisions in revision 0.3

| Decision | Settled input |
| --- | --- |
| RP-5 | `custom_inference_fn` inline-JavaScript inference is dropped. Custom pre/post-processing lives in a typed, digested `OnnxPolicy` (`mug.api-05.onnx-policy`) — declared `preprocessing` rule from a closed vocabulary plus a closed-enum `selection_mode` (`argmax`/`sample`, optional `temperature` under `sample`) — or a versioned scripted `Policy` in study code. Controller-reference objects are closed (`additionalProperties: false`); an inline-code field is structurally rejected. |
| RP-7 | The two-stage latency `MatchStrategy` declares `max_p2p_rtt`; the group forms only when ALL pairwise peer-to-peer RTTs among candidate members satisfy the bound (a single failing pair blocks formation). API-06 owns the runtime probe-evidence record; API-05 owns this author-facing declaration and references API-06 by name only. |

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Seat/actor/controller semantics and takeover |
| Runtime/distributed systems | Unassigned | Pending | — | Rebinding, fencing, membership validity |
| Data/replay | Unassigned | Pending | — | Schemas and archival readability |
| Security/privacy | Unassigned | Pending | — | Capability isolation and impersonation defense |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-05: seat/actor/controller-binding schemas, subject exclusivity, controller-reference and capability compatibility rules, 10 fixtures, 15 tests |
| 2026-07-18 | `0.2 (docs)` | Folded approved user-surface-review decisions (docs only; schema bundle stays 0.1): explicit seat↔env-agent-id binding, casting model, `Pairing`, all-agent allowance |
| 2026-07-19 | `0.2 (docs)` | R-15/R-16/R-18: treatments inline in the cast slot; cast totality (all-or-nothing); `Pairing` generalized to the shared `Group` object (N-size, typed `Match` strategies incl. two-stage RTT and custom `Matchmaker` subclasses, persistence-by-shared-object, `OnMissing.WAIT/REGROUP`) |
| 2026-07-19 | `0.2` | Schema bundle re-drafted to the 0.2 docs: `CastDeclaration` with total casts (R-16) and inline-treatment cast slots (`ActorSpec`/`CastTreatment`, R-15); `SeatAgentBinding` record (D09-7); shared `Group` with typed `Match` strategies (FIFO / two-stage latency / custom `Matchmaker` ref), `wait`/`on_timeout`, and per-later-activity `OnMissing` (R-18); all-agent cast fixture (D07-8); 21 fixtures, 26 tests; digests restamped |
| 2026-07-20 | `0.3 input (docs)` | Recorded settled RP-5 custom-inference removal and RP-7 all-pairs probe rule; exact contract/schema/fixture fold remains pending |
| 2026-07-20 | `0.3` | Folded RP-5/RP-7 into exact bytes: typed `OnnxPolicy` bundle (`mug.api-05.onnx-policy`) with closed-vocabulary `preprocessing` and closed-enum `selection_mode` (+ conditional `temperature`) replacing the dropped inline `custom_inference_fn` (structurally rejected by `additionalProperties: false`); two-stage `MatchLatency` `max_p2p_rtt` bound with all-pairs formation description (API-06 owns runtime evidence, referenced by name). Bundle digest `df3da1e1…`; 25 fixtures, 31 tests; digests restamped |

## Folded decisions (2026-07-18)

Approved user-surface-review decisions applied to the API-05 docs (schema
bundle re-drafted to match at `0.2`, 2026-07-19):

- **D07-1** — seats (authored roles) separated from actors (who fills them); single-player studies declare neither.
- **D07-2** — an actor is a human XOR an agent@version, never both.
- **D07-3** — casting is swappable and treatment-driven (`Scope.GROUP` decides human/AI partner per group).
- **D07-4** — agents live in the study repo, versioned with the study (`agent@version`; ADR-0013).
- **D07-5** — one actor can act through different controllers per channel; capability↔controller compatibility enforced.
- **D07-6** — LLM/agent casting declares provider needs plus a secret key, never credentials (bound at deploy).
- **D07-7** — matchmaking is author-declared and typed (F-3); v0 timeout policy is `RELEASE` only. Generalized 2026-07-19 (R-18) to the shared `Group` object: N-size, typed `Match` strategies (FIFO / latency two-stage RTT / custom `mug.Matchmaker` subclass), and persistence-by-shared-object across interactions (`OnMissing.WAIT/REGROUP`), matching current MUG's Matchmaker ABC, LatencyFIFOMatchmaker, and GroupReunionMatchmaker capabilities.
- **D07-8** — every seat may be an agent (all-agent interactions via headless `mug simulate`); agent-backfill of a human seat is out of scope for v0.
- **D09-7** — seat ↔ env agent id binding is explicit and recorded, never conflated; the env keeps agent ids internally.
