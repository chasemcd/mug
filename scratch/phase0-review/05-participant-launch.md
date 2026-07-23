# 05 — Participant launch & visit flow

| Field | Value |
| --- | --- |
| User | Participant (doing the study); the guarantees matter to the researcher |
| Goal | Someone clicks a link and completes the study — with progress, randomization, and identity handled so the data stays trustworthy even across refreshes and drops |
| Backing contract | [API-04](../../docs/architecture/phase-0/api-04/index.md) (visit plan/flow) · [API-09](../../docs/architecture/phase-0/api-09/index.md) (client wire) · [API-03](../../docs/architecture/phase-0/api-03/index.md) (launch) |
| Status | ✅ all 6 decisions approved (see [DECISIONS.md](DECISIONS.md)) |

## What's happening

The participant's side is deliberately dull: click a link, do the study, finish.
Everything interesting here is **invisible runtime machinery that protects the
data** — and that's what the decisions are about. Participants should never think
about any of it; researchers should be able to trust all of it.

### Today (what we're replacing)

Today a refresh can re-run randomization, a dropped connection can lose progress or
double-record, and the client is partly trusted for identity/condition. There's no
crisp separation between "what condition we meant to give" and "what they actually
saw." We keep the outcome (a completed session) and make the runtime honest.

## What the participant experiences

1. Clicks the link → the study loads. **No account, no login** — the link is the entry.
2. Does the activities in order (a game, a survey, whatever the flow says).
3. Refreshes the tab / loses wifi / closes and reopens the link → **lands exactly
   where they left off**, in the same condition. Nothing re-rolls, nothing repeats.
4. Finishes → a completion screen (and optional redirect back to where they came from).
5. On a dead/expired link → a plain, friendly "this link is no longer active" — not a crash.

## What happens behind the scenes

| Moment | Contract behavior |
| --- | --- |
| link click | Server derives identity from the **opaque launch ticket** — never from anything the client sends (API-09). A participant can't edit a URL to change who they are or what condition they're in. |
| study starts | The **`VisitPlan` is materialized and committed *before* participation** — the whole sequence and all randomization outcomes are decided and recorded once, up front (API-04), pinned to one study version + deployment (NS-08). |
| randomization | **Recorded once, immutably, with a seed commitment.** Recovery reloads the plan and **never re-samples** — a refresh cannot reshuffle a condition. |
| each step | Runs as an `ActivityOccurrence`; the participant's progress/state is saved as a **namespaced, per-visit, optimistically-versioned `StateDocument`**. |
| what they saw | **Assignment (intended treatment)** and **exposure (delivered treatment)** are separate records — assignment is set up front, exposure is written only when they actually reach it. |
| refresh / drop / return | Reloads the committed plan at the pinned version+wiring; realtime commands are **idempotent** (safe retry), and a transport ack is not a durable receipt (API-09). No lost progress, no double-exposure. |
| finish / dead link | Completion is recorded once; an expired/invalid ticket yields a **bounded, friendly error**, never a stack trace or a silent broken state. |

## Decisions to review

Mark each `Status:` line. (All are researcher-facing *guarantees*; none is a
participant-visible step.)

### D05-1 — The visit plan is fixed up front; randomization happens once
The full sequence and every randomization outcome are decided and committed before
the participant starts, and recovery never re-rolls them.
- **Why it matters:** a participant refreshing, dropping, or returning can't change their condition or re-run a random draw — the single most common way ad-hoc studies corrupt their own randomization.
- **Status:** ✅ approved

### D05-2 — Intended vs. delivered treatment are recorded separately
"What condition we assigned" (up front) and "what they actually saw" (when reached)
are distinct records; exposure is only written when the participant truly gets there.
- **Why it matters:** analysis can tell intent from delivery — e.g. someone assigned to condition B who dropped out before seeing it is *not* silently counted as exposed. Clean intent-to-treat vs. per-protocol analysis.
- **Status:** ✅ approved

### D05-3 — Resume is seamless and safe: same plan, same version, no double-exposure
A participant who refreshes, disconnects, or follows their return link lands exactly
where they were, on the same pinned version+wiring, with no repeated or skipped steps.
- **Why it matters:** real participants have flaky connections and close tabs; the data stays intact without the participant (or researcher) doing anything.
- **Status:** ✅ approved

### D05-4 — Identity and condition are server-derived; the client is never trusted for them
The server determines who the participant is and what they get from authenticated
launch state, not from client-supplied fields.
- **Why it matters:** a participant can't spoof identity or self-select a condition by editing the URL or client state — integrity against both accidents and tampering.
- **Status:** ✅ approved

### D05-5 — No accounts; the link is the entire entry
Participants never register or log in. The launch link is the whole authentication
surface.
- **Why it matters:** lowest-friction possible for participants (matches surface 04), and nothing for them to forget or leak. Trade-off: "returning" depends entirely on the stable return link (D04-4), since there's no account to log back into.
- **Status:** ✅ approved

## Settled (your calls)

- **Offline tolerance → configurable per study.** The author picks it (a realtime
  multiplayer game and a self-paced survey have different needs). Adds one authoring
  knob with a sensible default (lean `"brief"`); needs a place in the study spec —
  fold into surface 06/08 authoring. *(new decision D05-6 below)*
- **Save-and-resume → always automatic.** Re-opening the link always lands the
  participant where they left off; no explicit save button, no "resume later" UI.
  Reinforces D05-3 and D05-5 — resume is simply a property of the link.
- **Dead-link recovery → dead end + contact researcher.** An expired/invalid ticket
  shows a plain "this link is no longer active" plus a way to reach the researcher.
  No automated re-entry (which would lean on the panel integration we minimized in
  surface 04, F-2).

### D05-6 — Offline tolerance is an authoring knob, default "brief"
Studies declare how long the client rides through a bad connection before showing a
"reconnecting…" state; default is a short (~seconds) window, with an "activity-length"
option for studies that need it.
- **Why it matters:** realtime and self-paced studies have genuinely different needs; a single global choice would be wrong for one of them.
- **Status:** ✅ approved
