# ADR 0016: The external-client activity (Unity/WebGL)

| Field | Value |
| --- | --- |
| Status | **Accepted (2026-07-29)** — option A: withdrawn from v0, successor kept specified |
| Date | Proposed 2026-07-27; accepted 2026-07-29 |
| Owners | Chase M. (product owner) |
| Supersedes | None |
| Superseded by | None |
| Affects | API-07 (interaction runtime), API-09 (client wire), API-17 (content), functional-parity fixture 9, plan item W17 |

This document uses ASD-STE100 Simplified Technical English.

## Context

`docs/architecture/functional-parity.md` requires ten reference fixtures before
the legacy runtime may be removed. Nine of them are built and run in
`tests/parity`. The tenth, fixture 9, reads:

> A Unity/external-client activity or an explicitly accepted successor
> capability.

**The legacy runtime has the capability. The rewrite does not.** This is a
statement of fact, not an estimate:

| | Legacy | Rewrite |
| --- | --- | --- |
| Activity kind | `mug/scenes/unity_scene.py` (210 lines) | none |
| Author surface | `UnityScene().webgl(build_name=..., width=..., height=..., allow_continue_on=..., preload_game=...)` and `.game(num_episodes=..., score_fn=...)` | none |
| Wire | the `unityEpisodeStart` and `unityEpisodeEnd` socket events in `mug/server/app.py` | none |
| Shipped evidence | `examples/footsies/`, with two WebGL builds under `assets/web_gl/` and a 673-line study over seven training conditions | the study composition is portable; the activity is not |

So the parity gate can not pass on evidence. It passes only on a decision, which
is what the gate itself says: every capability must be *accepted, deliberately
replaced, or explicitly removed by an ADR approved by the product owner*.

Two further facts bear on the decision:

- **Nothing else waits on it.** The other nine fixtures are proven, so the
  legacy runtime is otherwise free to go. Fixture 9 alone holds the gate shut,
  and with it the 12,780 legacy lines, the four test modules the gate ignores,
  and the ~285 standing type errors that come from five legacy modules.
- **The rewrite's own shape makes this cheaper than it was.** An external client
  is a game channel whose authority is neither the server nor the browser
  runtime the platform ships. The frozen API-07 contract already carries a
  `browser` authority for a run the platform did not step, and the API-09 edge
  already validates a client-reported episode against a re-execution. An external
  client is the same shape with one difference that matters: **the platform can
  not re-execute a Unity build**, so a reported run can not be verified.

## Decision

**Option A is accepted (2026-07-29).** The product owner deferred the
capability: v0 does not include Unity/WebGL, a later version may, and this
document is kept as the specification of what that version must build. The
alternatives below stay recorded, because the decision was made on the evidence
and a later version may revisit it.

**Option A (accepted): withdraw the Unity/WebGL activity from v0, and replace it
with a declared *external-client activity* in a later version.**

Concretely, for v0:

1. Fixture 9 is recorded as **withdrawn**, not built and not deferred silently.
   `tests/parity/_parity_manifest.py` names this ADR, and
   `test_the_parity_gate_is_not_claimed_while_a_capability_is_undecided` fails if
   the set of undecided fixtures changes without this document changing with it.
2. A study that needs Unity keeps running on the legacy runtime until the
   successor lands. That is the honest position: the capability exists today, and
   removing the legacy runtime removes it.
3. The successor is specified before it is built, because the hard part is not
   the embedding. It is the trust boundary (see **Invariants**).

## Scope and non-goals

This decides whether the **v0 rewrite** ships a Unity/WebGL activity.

It does not decide:

- whether the legacy runtime is removed. That is §10 of the implementation plan
  and it needs this decision, but it is a separate one;
- the design of the successor capability beyond the invariants below;
- anything about WebGL as a rendering target. The platform's own canvas renderer
  is unaffected, and fixture 8 covers it.

## Invariants

Any successor capability must preserve these. They are what makes the external
client hard, and they are the reason it is worth specifying before building.

1. **An unverifiable run is recorded as unverifiable.** The platform re-executes
   a browser (Pyodide) run and refuses one whose state hashes do not match. It
   can not re-execute a Unity build. A run an external client reports must
   therefore be recorded with an authority that says so, and never under an
   authority that implies the platform stood behind it. A dataset must be able to
   separate the two without reading the study's code.
2. **The external client is untrusted, exactly like a browser.** It reports; it
   never asserts identity. The episode id, the interaction id, and the seat are
   minted server-side and shipped to it, as API-07 already requires.
3. **No secret reaches the build.** A WebGL build is a static asset a participant
   downloads. It carries no provider key, no signing key, and no private manifest
   field, and the public projection that reaches it is a whitelist.
4. **The activity declares the accessibility it delivers.** `wcag-a` at best, on
   the same rule as the game canvas: an external client is pixels. A study whose
   participants need a text view must supply one, and the manifest reports the
   floor (see `mug/content/components.py`).
5. **The build is content-addressed.** A study version names the build by digest,
   so a published study says which build it ran, and a replay says the same.

## Consequences

### Positive

- The parity gate can be settled on the evidence rather than left open, which
  unblocks the decision on legacy removal.
- The invariants above are written down while the capability is still cheap to
  shape. The legacy implementation has none of them: `unityEpisodeEnd` accepts
  whatever the client sends and stores it under a scene id.
- v0 ships with no capability that the platform can not verify.

### Costs and constraints

- **A real capability is lost on the day the legacy runtime is removed.** The
  Footsies study is a real study, and it can not be run on the rewrite.
- A researcher with a Unity environment has no path on v0.
- The successor has to be built later, against a frozen contract, which is more
  work than building it now would be.

### Failure consequences

- If the decision is taken and the successor is never built, the platform has
  quietly narrowed what it is for. The mitigation is that this document says so
  in the open, and the parity manifest test refuses to let the record drift.
- If the legacy runtime is removed **before** this decision is recorded as
  accepted, the capability is lost with no record of the choice. The manifest
  test exists to make that failure loud.

## Security and privacy

An external client widens the trust boundary, which is the substance of
invariants 1 to 3. The legacy implementation does not honour them: it takes an
episode payload from the socket and stores it, so a participant's browser decides
what the record says. Any successor closes that, or it should not be built.

No participant data leaves the deployment either way. A WebGL build is served as
a static asset and reports back to the same origin.

## API and schema impact

**None for v0**, which is one reason to take the decision now rather than later:
nothing is frozen against a capability that does not exist.

A successor would need, at least:

- an authority value in API-07 for a run the platform can not re-execute;
- an activity kind in API-17, with its accessibility profile;
- a delivery and a report frame in API-09;
- an asset kind for the build, addressed by digest.

Each is an additive change to a frozen bundle, and each goes through the
contract-freeze gate (`docs/architecture/phase-0/contract-freeze.md`).

## Alternatives considered

### Build the Unity/WebGL activity for v0

This is the alternative that keeps the capability, and it is credible: the
Footsies study proves there is demand, and the study composition around it
(seven training conditions, randomized between subjects) already ports to the
rewrite's `Treatment` and `Order`.

It is not proposed because of invariant 1. Every other execution mode in the
rewrite is verifiable -- the server steps it, or the platform re-executes it, or
the peers agree on it. An external client is the first mode where the platform
records what it is told. That deserves its own design pass rather than a port of
`unityEpisodeEnd`, and doing it properly is not v0-sized.

### Keep the legacy Unity path beside the rewrite

Rejected. It is the status quo, and its cost is the whole point of §10: two
runtimes, two data paths, four test modules the gate can not run, and ~285 type
errors that never go down.

### Declare the browser (Pyodide) mode the successor

Rejected as dishonest. Pyodide runs Python; it does not run a Unity build. A
researcher with a Unity environment is not served by being told to rewrite it.

## Validation

- `tests/parity/test_parity_manifest.py::test_every_withdrawn_fixture_names_a_decision_record`
  requires this document to exist.
- `tests/parity/test_parity_manifest.py::test_a_capability_is_withdrawn_only_by_an_accepted_decision`
  **reads the status field of this document**. The parity gate opens because this
  ADR says `Accepted`, and it shuts again the moment the word changes. So the
  gate can not be claimed by editing a test.
- `tests/parity/test_parity_manifest.py::test_the_parity_gate_is_settled`
  records that fixture 9 is the only withdrawn capability, and fails if that set
  changes without the parity document changing.
- `docs/architecture/functional-parity.md` records the outcome under its parity
  gate.

## Follow-up decisions

| Decision | Owner | Needed by |
| --- | --- | --- |
| ~~Accept, reject, or amend this ADR~~ | product owner | **done: accepted 2026-07-29** |
| Which version the successor capability is built for, if any | product owner | open; the capability is deferred, not cancelled |
| If the successor is wanted: the authority value and the verification story for a run the platform can not re-execute | architecture | before any schema change |
