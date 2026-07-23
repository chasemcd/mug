# API-21: Plugins — RETRACTED for v0 (extensions are plain Python)

| Field | Value |
| --- | --- |
| Status | Retracted for v0 (decisions D15-1..3, recorded in ADR-0015) |
| Contract revision | — (retired; no schemas or fixtures) |
| Last updated | 2026-07-18 |

## Decision

**There is no formal extension-point / plugin mechanism in v0.** MUG's type
vocabularies are **closed** for v0 — you cannot add a new *kind* of activity, form
field, assignment policy, or model provider beyond what ships. The drafted API-21
machinery — `PluginManifest`, `CapabilityNegotiation`, `IntegrationBinding`, trust
classes, sandboxing, and all sharing/distribution — is cut. This page is a tombstone
kept so the decision stays visible.

## The critical distinction: this does NOT remove writing your own code

"No extension points" is about **adding new kinds to MUG's closed vocabularies** — not
about writing custom logic. Everything you author in Python is core capability and
stays fully in v0:

| You can still (core authoring, in v0) | Where it lives |
| --- | --- |
| Write your own **environment** (Gym-style, in the study repo) | [API-07](../api-07/index.md) |
| Write **scripted / RL / LLM policies** | [API-12](../api-12/index.md) |
| Write a **render function** (or custom JS/HTML renderer) | [API-07](../api-07/index.md) |
| Write **native Python tools** (+ MCP) | [API-14](../api-14/index.md) |
| Author **content and forms** within the shipped field types | [API-17](../api-17/index.md) |

These are core surfaces, not plugins. The line: **implement what the closed sets
already allow; you just can't add new *types* to those sets in v0.** The generic HTTP
provider already absorbs most "new provider" needs without an extension point.

## What this closes for v0 (deferred, not permanent)

- Custom **activity types** beyond Content/Form/Interaction/Preference/Terminal.
- Custom **assignment policies** beyond the built-in typed set.
- Custom **form field types** beyond core + slider/rating.
- Custom **model providers** beyond the shipped set + generic HTTP.
- Any plugin **sharing/distribution** mechanism.

## Recorded post-v0 direction (so it isn't re-litigated)

If extension points arrive after v0, the model is **typed `ExtensionPoint` protocols
implemented as plain Python classes in the study repo**, pinned via git-native
versioning ([ADR-0013](../../decisions/0013-git-native-study-versioning.md)) — never a
plugin framework, manifest/negotiation system, trust-class hierarchy, or sharing
mechanism.

## References

- Decisions **D15-1** (no formal extension points in v0; closed sets stay closed),
  **D15-2** (core authoring in Python unaffected), and **D15-3** (post-v0 model is
  plain Python against typed protocols), approved in the phase-0 user-surface review.
- **ADR-0015**, which records the retraction.
- [Review record](review-record.md) for the retraction decision.
