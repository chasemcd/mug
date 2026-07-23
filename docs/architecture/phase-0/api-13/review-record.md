# API-13 Review Record

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Review opened | 2026-07-17 |
| Accountable owner | Unassigned |
| Target accepted version | `1` |

## Deliverable status

| Deliverable | Status | Evidence |
| --- | --- | --- |
| Ownership, lifecycles, and boundary | Drafted | [Index](index.md) |
| Version-0 schemas | Drafted | `provider.schema.json` |
| Golden fixtures and harness | Drafted | 13 fixtures, 16 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Agent versions are immutable and pin the full provider configuration
- [x] Provider requests reference a secret by key, never material
- [x] Completed responses name output; usage/resolved model recorded as exposure
- [x] Hidden vendor backend is exposure evidence, not content-addressed
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [x] `0.2` schema/fixture re-draft encoding the folded decisions: typed closed
      `Provider` vocabulary (`openai` / `anthropic` / `oss` / `http`; free-form
      platform strings rejected), immutable agent versions citable as
      `agent_key@version_number` (`llm-partner@2`), and secrets referenced by
      name only (`secret_name`; secret material structurally rejected on agent
      versions and provider requests)
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [ ] Fake/compatible/direct provider adapters defined
- [ ] Per-study/interaction budgets and emergency cancellation defined
- [ ] Safe output handling and content-filter provenance defined with API-08
- [ ] NS-02 through NS-07 walkthroughs pass
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A13-O01 | Provider secret isolation | Requests carry only a secret name resolved server-side via API-02 deploy-time binding | ['API-02'] |
| A13-O02 | Budget and cost enforcement | Per-study and per-interaction token/cost budgets enforced before dispatch; operator-configured, ungated (self-hosted; ADR-0015) | ['Version 1'] |
| A13-O03 | Adapter normalization scope | Normalize request/response/usage/error; provider extensions are explicit | ['Version 1'] |

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Provider normalization and provenance |
| Runtime/distributed systems | Unassigned | Pending | — | Latency, cancellation, budget, failure handling |
| Data/replay | Unassigned | Pending | — | Usage/cost/response evidence and replay |
| Security/privacy | Unassigned | Pending | — | Secret isolation, safe output, residency |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-13: agent-version, provider request/response/error, usage schemas, secret-by-key, completed-response evidence, exposure vs content-addressing, 9 fixtures, 13 tests |
| 2026-07-18 | `0.2 (docs)` | Folded user-surface-review decisions (docs only; schema bundle stays `0.1`): typed closed provider vocabulary, immutable agent versions named `agent@version`, secrets by name bound at deploy, API-20 references removed (ADR-0015) |
| 2026-07-19 | `0.2` | Re-drafted the schema bundle to the `0.2` docs: `AgentVersion.provider` is the typed closed `Provider` vocabulary (`openai`, `anthropic`, `oss`, `http`) replacing free-form `provider_class` (D11-1, boundary #5); `AgentVersion` gains `agent_key` + `version_number >= 1` so every version is citable as `agent@version` (D11-4), plus an optional pinned `secret_name`; `ProviderRequest.secret_requirement_key` renamed `secret_name` (secrets by name, bound at deploy via API-02; material structurally rejected); `ProviderResponse` / `Usage` / `ProviderError` unchanged; 13 fixtures (5 valid, 8 invalid), 16 tests; bundle digests restamped |

## Folded decisions (2026-07-18)

Approved user-surface-review decisions applied to this family's docs
(schema/fixture re-draft landed at `0.2` on 2026-07-19):

| ID | Applied as |
| --- | --- |
| D11-1 | Provider set is a typed closed vocabulary: `Provider.OPENAI`, `Provider.ANTHROPIC`, OSS/self-hosted serving (Ollama, vLLM), and a generic HTTP provider that absorbs most "new provider" needs; model ids stay the provider's own strings |
| D11-4 | Agent versions are immutable (`llm-partner@2`): provider/model/params/prompt/tools/fallback pinned, any change is a new version; secrets referenced by name and bound at deploy (API-02); usage/cost/errors and the resolved model recorded as exposure |
| F-3 | Illustrative Python uses typed constants (`Provider.*`, `Fallback.*`), never magic strings; author-chosen names (agent keys, secret names, provider model ids) remain plain strings by rule |
| F-4 / ADR-0015 | API-20 stripped from Consumers, ownership boundary, and open decisions; secret handling is API-02 by-reference only; budgets are operator-configured and ungated (self-hosted) |
