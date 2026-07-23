# API-13: Model Providers, Content, Usage, and Errors

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-19 |
| Consumers | API-12 (scheduler), API-14 (tools), API-08 (chat), API-10 (evidence), API-02 (secrets) |
| Depends on | [Shared kernel 0.1](../shared-kernel/index.md), [API-12 0.1](../api-12/index.md), proposed ADRs 0005, 0011 |
| Implementation phase | Phase 3B |
| Stability tiers | Application command/query, archival |

## Outcome

API-13 normalizes model providers behind immutable agent versions and records
provenance, usage, cost, and failures. It pins the requested provider, model
selector, parameters, prompt, tools, and fallback, while recording the
provider-resolved model as runtime exposure rather than a content-addressing
claim. Provider credentials never appear here; requests reference a secret by
name, bound at deploy (API-02).

The provider set is a **typed closed vocabulary** (D11-1, F-3):
`Provider.OPENAI`, `Provider.ANTHROPIC`, OSS/self-hosted serving (e.g. Ollama,
vLLM), and a **generic HTTP provider** that absorbs most "new provider" needs
without opening the vocabulary. Model ids within a provider remain the
provider's own strings (their vocabulary, not the platform's).

Agent versions are **immutable** (D11-4): `llm-partner@2` names a pinned
provider/model/params/prompt/tools/fallback bundle; any change — even a prompt
tweak — is a new version, so "the AI partner participants interacted with in a
given study version's flow" is always an exact, citable configuration
(versioning per ADR-0013).

```python
from mug import LLMAgent, Provider, Fallback

partner = LLMAgent(                    # published as llm-partner@2 — immutable
    provider=Provider.ANTHROPIC,       # typed closed provider vocabulary
    model="claude-sonnet-4-5",         # the provider's own model id (a string, their vocabulary)
    prompt="You are a cooperative foraging partner…",
    secret="chat-provider-key",        # secret referenced by name; value bound at deploy (API-02)
    on_timeout=Fallback.REPEAT_LAST,
)
```

## Ownership boundary

API-13 owns `AgentVersion`, `ProviderRequest`, `ProviderResponse`, `Usage`,
`ProviderError`, and the typed provider vocabulary. Scheduling/admission is
API-12; tools are API-14; secret storage and deploy-time binding are API-02
(by-reference only; ungated, self-hosted; ADR-0015).

## Non-negotiable provider boundary

1. Agent versions are immutable and pin provider/model/params/prompt/tools/fallback;
   any change is a new version (`llm-partner@2`).
2. Provider requests reference a secret by name (bound at deploy via API-02);
   no credential or token appears.
3. A completed response names its output digest; usage and resolved model are
   recorded as exposure evidence.
4. The hidden vendor serving backend is recorded as actual exposure, not
   content-addressed.
5. The provider identifier is a value of the typed closed vocabulary
   (`Provider.OPENAI`, `Provider.ANTHROPIC`, OSS/self-hosted, generic HTTP);
   never a free-form platform string.

## Current executable evidence

- 5 valid and 8 one-defect invalid examples; 16 API-13 tests including
  completed-response evidence, closed-vocabulary rejection of free-form
  provider strings, `agent@version` citability (`agent_key` +
  `version_number >= 1`), and no-secret-material on both agent versions
  and provider requests.

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md).
