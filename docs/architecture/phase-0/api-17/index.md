# API-17: Content, Forms, Presentation, and Accessible UI Components

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.3` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-20 |
| Consumers | API-01 (authoring), API-04 (occurrences), API-09 (delivery), API-18 (elicitation), API-10/11 (evidence) |
| Depends on | [Shared kernel 0.1](../shared-kernel/index.md), [API-04 0.1](../api-04/index.md), proposed ADRs 0007, 0014 |
| Implementation phase | Phase 1 onward |
| Stability tiers | Wire, application command/query, archival |

## Outcome

API-17 defines forms, content, presentation components, and accessibility
profiles. Field types are a **typed closed set** (F-3): core — likert, choice,
text, number — plus slider and rating. A form response that gates flow
advancement requires a **durable receipt** before advancing, and every shipped
component declares an accessibility profile with an enforced **WCAG floor**.
Consent is an ordinary content+form flow activity recorded like any response
(ADR-0014) — there is no special consent record.

```python
debrief = activities.Form(key="debrief", fields=[
    Field.likert("enjoyment", "How much did you enjoy this?", scale=7),
    Field.choice("strategy", "Which strategy did you use?", options=["hoard", "share"]),
    Field.text("comments", "Anything else?", required=False),
])
```

Field constructors are the typed vocabulary; field keys, labels, and options are
author-defined data and stay plain strings (the F-3 boundary).

**Content bodies (settled 2026-07-19):** the body of a content activity is
authored **in the study repo** — a repo-relative file or an inline string, as
Markdown or HTML (`Content.file(...)`, `Content.markdown(...)`,
`Content.html(...)`) — and compiled into the immutable study version as a
content-addressed `PresentationArtifact`. Content is never bound at deploy: a
redeploy cannot change what a participant reads or consents to (D04-3; the
API-02 scientific/deployment boundary). **Author-supplied HTML is an explicit
choice and trusted study code** — it may carry custom CSS/JS for rich
components, exactly like the env or renderer, versioned with the study. Model
output, participant text, and any runtime string remain safely rendered and are
never interpreted as HTML.

## Ownership boundary

API-17 owns `FormSpec`, `FormResponse`, `PresentationComponent`,
`AccessibilityProfile`, and `GateControl`. Preference elicitation is API-18;
delivery is API-09; occurrence lifecycle is API-04. Consent activities are
composed from ordinary content+form pieces here (ADR-0014); no consent-specific
record type exists.

**Readiness gating (RP-8, folded 0.3):** the start/advance control is a
first-class `GateControl` content component — it declares its gate target
(`advance` vs `join`), its gate action (`block`/`unblock`), and the
interaction/flow `anchor` it gates, carries an accessibility profile like any
shipped component, and pins the inert API-09 `mug.api-09.gate-op` bundle it
emits. API-09 owns the `GateOp` itself; API-17 owns only the content/UI control
that surfaces the gate, formalizing the legacy startButton/advanceButton
interval hacks. RP-8's state→env-args resolution path and read-only participant
handle were not adopted and remain open.

## Non-negotiable content boundary

1. Field types are a closed, typed set — likert, choice, text, number, slider,
   rating; field keys are unique within a form.
2. A response that gates flow advancement requires a durable receipt before
   advancing — a submitted-then-dropped-connection response cannot be lost.
3. Every shipped component declares an accessibility profile; the WCAG floor is
   enforced (AA requires keyboard navigation and screen-reader support).
4. Accessibility and technical-problem paths are first-class, not afterthoughts.
5. Consent is a content+form flow activity (ADR-0014), recorded like any other
   response — never a special-cased record or wave mechanism.
6. Content bodies are repo-authored and compiled into the immutable version,
   never bound at deploy. Author HTML is explicit and trusted; model/participant
   content is never implicitly executable.
7. Custom-page responses use the typed `window.mug` bridge (settled 2026-07-19):
   named form controls are auto-collected on advance and `mug.response.set(...)`
   stages computed values; together they form the activity's response, subject to
   the same durable-receipt gating as a `Form` response. There is no shared
   mutable global (`mugGlobals` retired). Recorded fields are addressable
   downstream as typed `activity.field(...)` references.

## Current executable evidence

- 10 valid and 13 one-defect invalid examples; 26 API-17 tests including
  duplicate field detection, the accessibility floor, the author/participant
  executable-content trust boundary, and the `GateControl` readiness control
  (gate target/action enums, required API-09 gate-op binding, and
  anchor/target-coherence).

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md).
