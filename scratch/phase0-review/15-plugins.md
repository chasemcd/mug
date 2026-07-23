# 15 — Extending MUG — no extension system in v0

| Field | Value |
| --- | --- |
| Status | ✅ approved (largely cut — no formal extension points in v0; closed sets stay closed) |
| Backing contract | ~~API-21~~ retracted for v0 |

## Decision

**There is no formal extension-point / plugin mechanism in v0.** MUG's type
vocabularies are **closed** for v0 — you cannot add a new *kind* of activity, form
field, assignment policy, or model provider beyond what ships. No plugin framework, no
manifest/negotiation/trust classes, and (per your call) no sharing/distribution either.

## The critical distinction: this does NOT remove writing your own code

"No extension points" is about **adding new kinds to MUG's closed vocabularies** — not
about writing custom logic. Everything you already author in Python stays fully in v0:

| You can still (core authoring, in v0) | Where it lives |
| --- | --- |
| Write your own **environment** (Gym-style) | surface 08 (D08-7) |
| Write **scripted / RL / LLM policies** | surface 11 (D11-1) |
| Write a **render function** (or custom JS/HTML renderer) | surface 09 (D09-1) |
| Write **native Python tools** (+ MCP) | surface 11 (D11-5) |

These are core surfaces, not plugins. The line: **implement what the closed sets already
allow; you just can't add new *types* to those sets in v0.**

## What this closes for v0 (deferred, not permanent)

- Custom **activity types** beyond Content/Form/Interaction/Preference/Terminal (D01-4).
- Custom **assignment policies** beyond the built-in set (D06-2 — already deferred).
- Custom **form field types** beyond core + slider/rating (D12-1).
- Custom **model providers** beyond OpenAI/Anthropic/OSS — though the **generic HTTP
  provider** (D11-4) already covers most "new provider" needs without an extension point.

## Decisions to review

Mark each `Status:` line.

### D15-1 — No formal extension-point / plugin system in v0; closed sets stay closed
MUG's type vocabularies are closed for v0. Adding new *kinds* (activity types, field
types, assignment policies, providers) is deferred; the drafted API-21 plugin machinery
(`PluginManifest`, `CapabilityNegotiation`, trust/sandbox) is cut, and so is any
sharing/distribution.
- **Why it matters:** removes a whole subsystem with little v0 demand; the built-in sets plus core authoring (below) cover the real cases, and the generic HTTP provider already absorbs most "new provider" needs.
- **Status:** ✅ approved

### D15-2 — Core authoring in Python is unaffected (envs, policies, renderers, tools)
Writing your own env, scripted/RL/LLM policies, render function, and native tools are
core capabilities (surfaces 08/09/11), fully in v0 — they are not "extension points."
- **Why it matters:** the important flexibility (custom games, agents, visuals, tools) is retained; only *adding new kinds to closed vocabularies* is deferred.
- **Status:** ✅ approved

### D15-3 — When extension points do arrive (post-v0), the model is plain Python against typed protocols
Recorded so it isn't re-litigated later: any future extensibility is a class in the repo
implementing a typed `ExtensionPoint` protocol, pinned via F-1 — never a plugin
framework or sharing system.
- **Why it matters:** sets the eventual direction cheaply now, consistent with F-1/F-4 and "extensions are just Python," without building anything in v0.
- **Status:** ✅ approved

## Open questions for you

- None outstanding — extension points are deferred for v0.
