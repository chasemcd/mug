# ADR 0002: Principal, Actor, Seat, Controller, and Channel Model

| Field | Value |
| --- | --- |
| Status | Accepted |
| Accepted | 2026-07-20 (accountable-owner ratification; principal/actor/seat/controller/channel model folded + test-covered in API-05; family schema v1 freeze is a separate per-family gate) |
| Date | 2026-07-16 |
| Owners | Unassigned |
| Affects | API-03 through API-09, API-12, API-15, API-18 |

## Context

Participant identity, environment agent ID, experimental role, and policy type
are distinct concepts. Combining them prevents reliable multi-human/multi-LLM
interaction, controller replacement, team/private channels, and longitudinal
identity.

## Decision

The target model separates:

- Principal: durable authentication/linkage identity
- Enrollment: study-scoped research identity
- Seat: authored role or slot
- Actor instance: concrete human or software participant in one interaction
- Controller binding: producer of one actor capability in one modality
- Channel: typed communication medium with membership and grants
- Interaction: shared coordination and evidence boundary

Controller technical capability, channel/seat authorization, context visibility,
and effect-time validation are separate. Effective authority is their
intersection.

Game, chat, and annotation protocols remain typed even when they share common
channel membership concepts. Preference workflow is not required to masquerade
as a live channel.

## Invariants

- Environment agent IDs are not participant or actor IDs.
- Changing a controller version does not implicitly change actor identity.
- A human or software actor may use different controller bindings for game and
  chat.
- An actor sees and emits only data granted for that channel and context.
- Authorization is rechecked when an effect is applied or published.

## Consequences

The model is more explicit than a policy mapping, but it supports every target
human/LLM topology without experiment-specific routing code.

## Alternatives considered

### Treat each policy/environment agent as the actor

Rejected because it conflates control with experimental identity and cannot
represent one person controlling multiple agents or separate game/chat control.

### Use one generic untyped event bus as all channels

Rejected because game, chat, and preference interactions have different
authority, ordering, validation, and durability semantics.

## Validation

Walk NS-03 through NS-07 with role replacement, private channels, one actor
controlling multiple capabilities, and independent controller versions.

