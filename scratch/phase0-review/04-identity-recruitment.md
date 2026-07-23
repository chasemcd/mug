# 04 — Identity, consent, returning participants

| Field | Value |
| --- | --- |
| Users | Participant (arrives at a link); researcher (points their own recruiting at it) |
| Goal | Give people a pseudonymous identity, let consent be part of the study, and let the same person come back — without MUG becoming a recruiting tool |
| Backing contract | [API-03](../../docs/architecture/phase-0/api-03/index.md) (scope reduced — recorded as F-2 on approval) |
| Status | ✅ all 4 decisions approved (see [DECISIONS.md](DECISIONS.md), F-2) |

## What MUG does — and deliberately does not — do here

MUG's job at this boundary is small:

- ✅ Give each arriving participant a **pseudonymous, study-scoped identity**.
- ✅ Keep any external reference (a Prolific ID in the URL, say) **apart** from research data.
- ✅ Let the **same person return** for a later part via a stable link.

MUG does **not**:

- ❌ Send emails or reminders.
- ❌ Manage a participant panel or recruit anyone.
- ❌ Integrate with Prolific/MTurk beyond capturing an opaque ID and offering a completion redirect.
- ❌ Target or schedule "invitations."

Recruitment, follow-up outreach, and payment are done with the tools researchers
already use (Prolific, email, an LMS). MUG hands you a URL; you distribute it.

## What the users actually see

**Participant:** clicks a link → gets a pseudonymous enrollment → does the study
(including any consent step, which is just part of the study) → at the end, an
optional completion code / redirect back to wherever they came from.

**Researcher:**

```bash
mug deploy cooperative-foraging@2.1 --at https://study.lab.edu    # (surface 03) — this IS your recruiting URL
```

Put `https://study.lab.edu` on Prolific, in an email, on a flyer — MUG doesn't care.
Each visitor gets a fresh pseudonymous enrollment automatically.

### Consent is just an activity

No separate consent system. Consent is a `Content`/`Form` step in the flow
(surface 01's closed activity set), and its response is recorded like any other. It
lives in the versioned study, so you always know exactly which consent text a
participant saw.

```python
consent = activities.Content(key="consent", slot="consent-v1", response_required=True)
# ...then it's just the first node in the flow, and you can branch on the response if you want.
```

### Returning for a later part

For longitudinal studies, MUG gives each enrollment a **stable return link**. You
capture it (it's in the completion redirect / available via export) and send it
however you like — MUG doesn't do the sending. When the participant follows it, MUG
recognizes them as the same enrollment and routes them to the right part.

## What happens behind the scenes

| Situation | Contract behavior (API-03, reduced) |
| --- | --- |
| participant arrives | Opaque, expiring **`LaunchTicket`** → a pseudonymous **`Enrollment`** (`enroll_…`), study-scoped, structurally unable to hold account/panel/PII. |
| URL carries an external id (e.g. `?PROLIFIC_PID=…`) | Captured once as a blinded reference stored **apart** from research data, classified PII. Used only for a completion redirect; never joined into your dataset by default. |
| consent | A recorded **activity response** in the visit — not a separate `ConsentRecord` subsystem. Reproducible because the consent activity is in the immutable study version. |
| returning participant | The stable return link resolves to the existing enrollment; MUG routes to the next part. No invitation/targeting machinery. |

## Decisions to review

Mark each `Status:` line.

### D04-1 — Pseudonymous study-scoped identity, automatic; external refs kept apart
Every visitor gets an `enroll_…` with no real identity attached. An external id in
the URL is captured opaquely and stored apart from research data.
- **Why it matters:** identity leakage into datasets is structurally prevented, at zero effort — and it's the one guarantee MUG *must* own here.
- **Status:** ✅ approved

### D04-2 — MUG is not a recruiting tool; the deploy URL is the whole surface
Recruitment, reminders, invitations, and payment are the researcher's existing
tools. MUG provides the study URL (surface 03) and an optional completion redirect —
nothing more.
- **Why it matters:** MUG doesn't reinvent Prolific/email; far less to build and maintain, and researchers keep the recruiting workflow they already have.
- **Status:** ✅ approved

### D04-3 — Consent is an activity in the flow, not a dedicated subsystem
Consent is a `Content`/`Form` step whose response is recorded like any other, living
in the versioned study. No `ConsentRecord` API, no scope-gating engine.
- **Why it matters:** big simplification, and consent is still reproducible (it's in the immutable version) and branchable (flow algebra). Trade-off: no built-in "consent scope" concept — if a study needs conditional logic, it's an ordinary flow branch on the response.
- **Status:** ✅ approved

### D04-4 — Longitudinal return is a stable per-participant link; MUG doesn't do outreach
Each enrollment gets a durable return link. The researcher captures and sends it
through their own channel; MUG recognizes the returning person and routes them.
- **Why it matters:** supports multi-part/longitudinal studies with almost no MUG machinery — no wave windows, no targeting, no scheduler. Trade-off: re-contact logistics (who to email, when) are entirely on the researcher.
- **Open question:** does "route them to the right part" need anything explicit in the study (named parts/checkpoints), or does the flow's own position-tracking cover it?
- **Status:** ✅ approved

## Open questions for you

- **Withdrawal / "please delete my data":** handled purely as governance (surface 13)
  via the stable enrollment handle, or is any runtime concept needed here at all?
- **Anonymous vs external-id arrivals:** both fully supported with no config (a bare
  link works; a link with `?PROLIFIC_PID=…` just also captures the blinded ref)?
- **Completion redirect:** is a return URL + completion code enough of a "panel
  integration," or do we not even need that for v0?
