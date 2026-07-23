# Phase 0 User-Surface Review (scratch)

This is a working review of the Phase 0 architecture from the **user's point of
view**. For each surface a user touches, we describe:

1. **Who** the user is and **what they're trying to do**.
2. **What they see / write / click** — the concrete API or UX surface.
3. **What happens behind the scenes** — the contracts (API-01…22) that back it.
4. **Decisions** — discrete, numbered, individually approve/reject-able.

We iterate: I draft a surface, you mark each decision, I revise. Nothing here is
binding on the contracts until we agree and I fold it back into the real docs
under `docs/architecture/phase-0/`.

## Status legend

Mark any decision by editing its status line:

- `⬜ pending` — not yet reviewed
- `✅ approved` — locked in; I fold it into the contracts
- `❌ rejected` — drop it; note why and I redesign
- `🔄 revise` — right idea, wrong details; note what to change

## The users

| User | Cares about | Primary surfaces |
| --- | --- | --- |
| **Researcher / author** | Designing and publishing a study in code | Authoring, versioning, agents, preferences |
| **Operator** | Deploying and running it safely | Deployment, secrets, governance |
| **Participant** | Doing the study in a browser | Launch, game/chat, forms |
| **Analyst** | Getting trustworthy data out | Export, replay, lineage |
| **Extension author** | Adding a component or integration | Plugins |

## Surface index (review order)

| # | Surface | User | Backing families | Status |
| ---: | --- | --- | --- | --- |
| 01 | [Researcher authoring a study](01-researcher-authoring.md) | Author | API-01 | ✅ approved |
| 02 | [Publishing, versioning, amendments](02-publishing-versioning.md) | Author | API-01 | ✅ approved |
| 03 | [Deploying & secret binding](03-deploying-secrets.md) | Operator | API-02, API-20 | ✅ approved |
| 04 | [Identity, consent, returning participants](04-identity-recruitment.md) | Author/Operator | API-03 | ✅ approved |
| 05 | [Participant launch & visit flow](05-participant-launch.md) | Participant | API-03, API-04, API-09 | ✅ approved |
| 06 | [Treatment & randomization](06-treatment-randomization.md) | Author | API-04 | ✅ approved |
| 07 | [Seats, actors, human+LLM casting](07-seats-actors-casting.md) | Author | API-05, API-13 | ✅ approved |
| 08 | [Interactions: game + chat in one activity](08-interactions-game-chat.md) | Author | API-06, API-07, API-08 | ✅ approved |
| 09 | [Rendering & what participants see](09-rendering.md) | Author/Participant | API-07, API-09 | ✅ approved |
| 10 | [Participant playing / chatting](10-participant-playing.md) | Participant | API-07, API-08, API-09 | ✅ approved |
| 11 | [Agent behavior: scheduling, providers, tools, memory](11-agent-behavior.md) | Author | API-12–15 | ✅ approved |
| 12 | [Preference & annotation studies](12-preference-annotation.md) | Author | API-17, API-18 | ✅ approved |
| 13 | [Export & replay](13-export-replay.md) | Analyst | API-16, API-19 | ✅ approved |
| 14 | [~~Governance: consent, deletion, audit~~](14-governance.md) | — | ~~API-20~~ | ❌ cut (F-4, out of scope) |
| 15 | [Extending MUG (no plugin system)](15-plugins.md) | Extension author | ~~API-21~~ | ✅ approved (largely cut) |

Infra families (API-10 events, API-11 storage, API-22 jobs) are mostly invisible
to users; they surface only as guarantees ("your response was saved") and appear
inside the relevant surfaces above rather than as their own review unit.
