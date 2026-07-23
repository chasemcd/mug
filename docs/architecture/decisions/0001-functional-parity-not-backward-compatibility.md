# ADR 0001: Functional Parity Without Backward Compatibility

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-07-16 |
| Owners | MUG maintainers |
| Supersedes | Any implicit compatibility assumption in the initial roadmap |
| Affects | All APIs, phases, examples, and release gates |

## Context

The current MUG architecture couples authoring objects, process-global runtime
state, browser payloads, socket events, and filesystem exports. Preserving those
interfaces would constrain the new study, interaction, evidence, agent, replay,
and preference architecture and would preserve known correctness and security
problems.

The useful platform capabilities must remain, but existing experiment code does
not need to run on the replacement.

## Decision

The next major MUG architecture targets functional capability parity and has no
backward-compatibility obligation.

The replacement may change or remove old:

- Python APIs and import paths
- Configuration classes, builder methods, defaults, and inference behavior
- Experiment scripts and callbacks
- Browser and WebSocket protocols
- Internal component boundaries
- Storage schemas, directories, filenames, and data formats
- Deployment procedures

The platform must preserve the capabilities subsequently accepted through the
[functional-parity contract](../functional-parity.md). That inventory remains
Proposed until its Phase 0 review. Representative examples will be rewritten
against the new APIs and used as outcome-based fixtures.

No legacy adapter, dual-write path, or old-data importer is required unless a
separate ADR justifies that specific work.

## Scope and non-goals

This decision governs the transition from the current platform to vNext. It
does not allow silent breaking changes after vNext contracts are published.
Published study versions, manifests, client protocols, events, artifacts, and
replay bundles require explicit schema/version policies and supported readers.

## Invariants

- Every retained current capability maps to a target API and acceptance test.
- Known bugs and unsafe incidental behavior are not parity requirements.
- Old scripts are not used as the release gate; ported scenarios are.
- A capability can be removed only by an explicit product decision updating
  the parity contract.
- Published vNext scientific and evidence versions remain immutable/readable
  according to their accepted retention and schema policy.

## Consequences

### Positive

- Domain, security, and storage boundaries can be designed coherently.
- The implementation need not accumulate compatibility layers before the new
  contracts are understood.
- Current accidental semantics do not become permanent platform commitments.

### Costs and constraints

- Existing studies must remain on the current major version or be rewritten.
- Documentation and examples must be replaced alongside the new APIs.
- Capability parity needs an explicit inventory and a larger acceptance suite.
- Cutover is a major-version product event rather than a transparent upgrade.

### Failure consequences

Without the parity matrix, teams could interpret this decision as permission to
drop difficult multiplayer, rendering, recovery, Unity/external-client, or
administrative capabilities. The functional-parity gate is therefore mandatory.

## Security and privacy

The redesign may replace unsafe client-trusted state, raw external IDs,
implicit public metadata, and unversioned callbacks instead of preserving them.
No compatibility argument may override the target threat model.

## API and schema impact

All target APIs start from the [API design standard](../phase-0/api-design-standard.md).
Old wire/data schemas do not require readers. New schemas still require explicit
versions and published-study stability.

## Alternatives considered

### Preserve the existing authoring API

Rejected because existing objects mix authored configuration, live state,
serialization, and transport behavior. An adapter would constrain the target
model before it is understood.

### Preserve the existing data layout while changing APIs

Rejected because current filenames and rows cannot represent durable visits,
repeated occurrences, immutable artifacts, multi-wave treatment, chat, model
traces, or replay completeness safely.

## Validation

- Every row in the functional-parity contract has a target owner and scenario.
- Ported browser, P2P, server-authoritative, rendering, policy, form, Unity, and
  administration fixtures pass before vNext cutover.
- No release gate requires importing or executing an old experiment script.
