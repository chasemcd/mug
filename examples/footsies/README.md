# Footsies — waiting on a decision

This example has **no updated version**, and that is a decision rather than an
omission.

These documents use ASD-STE100 Simplified Technical English.

## What it was

Footsies is a fighting game that runs as a **Unity WebGL build**, not as a Python
environment. The legacy study around it was a real one: a survey, a tutorial, an
opening challenge, one of seven training conditions drawn between subjects
(fixed high skill, fixed low skill, random difficulty, dynamic difficulty,
controllable difficulty, and two empowerment conditions), a training survey, a
final challenge, and an exit survey.

Everything in that list **except the game itself** ports to the new stack today:

| What it needed | On the new stack |
| --- | --- |
| Surveys and static pages | `Form`, `Page` |
| One of seven conditions, drawn between subjects | `Treatment(..., assign=Assign.balanced())` |
| Repeated rounds with an interval | `Game(..., episodes=n, between=...)` |
| A completion code and a return link | `return_url=` and the completion delivery |
| The Unity WebGL activity | **nothing** |

## Why there is nothing

The rewrite has no external-client activity. The legacy runtime has one
(`mug/scenes/unity_scene.py`, and the `unityEpisodeStart` / `unityEpisodeEnd`
socket events), and it is the only capability of the ten required parity fixtures
that the rewrite does not have.

It is not a small gap to close honestly. Every other execution mode the platform
offers is **verifiable**: the server steps it, or the platform re-executes the
shipped bundle and refuses a run whose hashes do not match, or the peers agree
with each other. An external client is the first mode where the platform would
record what it is told. The legacy implementation takes an episode payload from
the socket and stores it, which is exactly what should not be built again.

## What happens next

`docs/architecture/decisions/0016-external-client-activity.md` sets the
decision out for the product owner: withdraw the capability from v0 and specify a
successor, or build it now, or keep the legacy runtime for it. **The ADR is
proposed and not accepted**, so nothing here has been settled.

Until it is, a study that needs Unity runs on the legacy runtime. The WebGL builds
and the static pages this example shipped are still here, under `assets/` and
`static/`, so nothing has to be rebuilt when the decision is made.

The original study code is in git history, at commit `7d92d9e`.
