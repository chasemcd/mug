# Promotion plan: Draft → Accepted (working document)

**Status:** v0.3, 2026-07-20. PG-1..PG-8 settled; G7 decisions D1/D2/D3 settled.
**Shared-kernel CORE layer FROZEN** (ADR-0008 + ADR-0011 Accepted; digest
checkpoint `f675d9ec`; 638 tests). Runtime layer + Wave-2 families next.
**How we work this doc:** same as the surface reviews. I propose the gate
framework, order, and concrete artifacts (with examples) below; you review,
strike/rewrite/approve, and report back. Settled items get folded into the real
tracker (`docs/architecture/phase-0/api-review-tracker.md`) and each family's
`review-record.md`. Open questions are the **PG-\*** rows — those are the ones I
need you to weigh in on.

---

## 1. Where we actually are

The RP-1..RP-10 folds are done; **breadth is no longer the problem.** Every one
of the 21 active families + the shared kernel has drafted schemas, fixtures, and
a passing semantic harness (553 tests). What's missing is the *acceptance
evidence* that turns a Draft into a frozen v1.

Concretely, nothing is Accepted yet:

- **ADRs:** only **0001** is Accepted. **0002–0015 are all Proposed** — and every
  family's acceptance checklist has an "ADR dependencies accepted" gate, so no
  family can freeze until its ADRs are Accepted.
- **Sign-off:** every family (and the kernel) shows **Unassigned** owner and
  **4 Pending** reviewer roles (domain/scientific, runtime/distributed,
  data/replay, security/privacy).
- **Open per-family checklist items:** ~7–9 each, concentrated in three classes
  that don't exist yet — **NS scenario golden traces**, **fault-injection
  fixtures**, and **cross-language conformance** (RFC 8785 + browser/Pyodide).
- **Revisions:** 9 families at 0.3 (04/05/06/07/09/10/12/16/17), 11 at 0.2
  (01/02/03/08/11/13/14/15/18/19/22), kernel at 0.2. Revision ≠ acceptance;
  it just tracks the last fold.

So promotion is mostly about **manufacturing the missing evidence classes once**
(they're reusable across families) and then **walking each family through a
fixed gate**, in dependency order, clearing a short list of cross-cutting
blockers first.

---

## 2. Proposed definition of "Accepted" (the gate)

I propose consolidating the tracker's 18-item checklist into **9 gates**, each
with a named evidence artifact so "done" is verifiable, not a vibe. A family is
**Accepted** only when G0–G8 all hold.

| Gate | Name | Evidence artifact | Status across corpus today |
| --- | --- | --- | --- |
| **G0** | Drift & decision closure | No stale prose vs. current decisions; every open decision that *blocks this family* is resolved or explicitly deferred with a reason | **Blocked** — see §3 |
| **G1** | Spec completeness | Index doc covers goals/non-goals, vocabulary, state machine, authority, ordering, idempotency, errors, privacy | Mostly met; audit per family |
| **G2** | Schema & fixtures | Persisted+wire schemas; golden valid/duplicate/stale/conflicting/invalid fixtures; digests pinned | **Met** for all families (this is our strength) |
| **G3** | Scenario traces | The family's NS-\* walkthroughs pass as **golden fixtures**, not prose | **Missing** — new artifact class (§4a) |
| **G4** | Fault injection | Each `failure-matrix` row that touches the family has a fixture/test | **Missing** — new artifact class (§4b) |
| **G5** | Cross-language conformance | RFC 8785 canonicalization vectors pass in Python **and** browser; Pyodide import/⁠make_env where applicable | **Missing** — kernel-level (§4c) |
| **G6** | ADR acceptance | Every ADR the family depends on is **Accepted** | **Blocked** — 0002–0015 Proposed |
| **G7** | Sign-off | Accountable owner + 4 reviewer-role sign-offs recorded in `review-record.md` | **Missing** — needs a model (PG-1) |
| **G8** | Freeze | v1 bytes frozen; publication compiler **rejects v0**; digest recorded | Not started (terminal gate) |

**G2 is essentially bought.** The work is G3/G4/G5 (build once, apply widely),
G6 (a focused ADR-acceptance pass), and G7 (a sign-off model we agree on).

---

## 3. Cross-cutting blockers (clear these before any freeze) — **G0**

These gate *multiple* families, so they go first as a "wave 0". Each is a small,
self-contained fold/decision.

| ID | Blocker | Affected | Proposed disposition |
| --- | --- | --- | --- |
| B-1 | **API-01 still carries plugin-era schema** (`PluginRequirement` $def) after ADR-0015 retracted plugins | API-01 (+ digest cascade) | Remove the $def + prose; restamp api-01 digests; add a rejection fixture. Mirrors the shared-kernel `plugin.*` removal already done. |
| B-2 | **north-star.md prose drift** — still references accounts / waves / invitations retired by F-2/ADR-0014 | north-star (corpus-wide narrative) | Reconcile prose to identity-not-recruitment; no schema impact. |
| B-3 | **quality-attributes.md drift** — governance/plugin language retired by F-4/ADR-0015 | quality-attributes | Reconcile prose; no schema impact. |
| B-4 | **A07-O01** portable binary snapshot codec still open | API-07, API-16 freeze | Either accept a codec ADR now, or **freeze v1 with the codec explicitly deferred to a v1.1 addendum** (my lean — it doesn't block the JSON contract). Needs your call → **PG-3**. |
| B-5 | **RP-8 sub-items** open (state→env-args path; read-only participant handle) | API-09 freeze | Same choice as B-4: resolve now or freeze-with-explicit-deferral. → **PG-3** |
| B-6 | **RFC 8785 cross-language vectors** absent (shared-kernel SK-O04) | kernel + everything | This is G5; build the vector set (§4c). Blocks kernel freeze specifically. |
| B-7 | **The test harness canonicalizer is knowingly non-conforming** (MEASURED — see §11). `_contract_harness.canonical_bytes` uses `json.dumps(sort_keys=True, separators, ensure_ascii=False)`; the kernel spec (serialization doc, l.119) states outright this "is not a conforming substitute for RFC 8785." Every digest across the 553-test corpus was computed with it. | kernel + pinned digests | Corpus scan: **0 non-ASCII keys**, **16 raw floats** (7 fixtures), **1 control-char string**. Schemas + all cross-family chain fixtures are float-free ⇒ a swap to conforming JCS leaves the 553 tests and the whole digest web **unchanged**. Only the float/control fixtures need attention — but several look like **numeric-profile violations** (raw floats in digestable content the profile wants as safe-int/string-decimal). See §11 + **PG-8**. |

---

## 4. New evidence classes (build once, reuse) — with examples

### 4a. NS golden scenario traces (G3)

Today NS-01..NS-12 are prose walkthroughs in `acceptance-scenarios.md`. Proposal:
each becomes a **golden fixture directory** — an ordered, cross-family sequence
of already-valid contract objects that together enact the scenario, checked by a
harness that (i) validates each object against its owning family's schema and
(ii) asserts the cross-family digest links resolve. This reuses the existing
harness machinery; it just spans families.

Proposed layout:

```
tests/architecture/scenarios/ns-09-p2p-rollback/
  00-interaction.json            → mug.api-06.interaction / Interaction
  01-mesh-membership.json        → mug.api-06 / P2PMeshMembership
  02-frame-finality.confirmed.json → mug.api-07 / P2PFrameFinality
  03-episode-boundary.json       → mug.api-07 / EpisodeBoundary
  04-decision-tape.json          → mug.api-16 / DecisionTape
  05-replay-manifest.json        → mug.api-16 / ReplayManifest (closes over 01–04 digests)
  trace.json                     → the ordered step list + expected digest links
```

The win: NS-09 stops being a paragraph and becomes a **runnable proof** that
api-06/07/12/16 actually compose. Several of these can reuse the p2p fixtures we
just built. → sequencing question in **PG-4**.

### 4b. Fault-injection fixtures (G4)

`failure-matrix.md` and `threat-model.md` enumerate failure/abuse cases. Proposal:
each row that asserts a contract-level outcome gets an **invalid/adversarial
fixture** proving the contract rejects or safely degrades it. Many already exist
as our `invalid/` fixtures — this gate is largely **mapping existing invalid
fixtures to failure-matrix rows** and filling the gaps (e.g. the loss-window
cases from the parity audit's finding F: partial-episode discard, missing
`beforeunload` flush, retry-ceiling).

Example gap → fixture: "partial episode on abnormal end must still be captured"
→ an `ExperiencedFrame`/`CapturePolicy` fixture asserting `completeness` cannot
silently drop frames. (RP-9 gave us the shape for this.)

### 4c. Cross-language conformance vectors (G5)

A single shared fixture set of canonicalization vectors: `{value, canonical_bytes,
sha256}` triples covering the tricky RFC 8785 cases (unicode normalization, number
formatting, key ordering, lone surrogates — the harness already rejects these in
Python). Run the **same vectors** through a browser/JS canonicalizer to prove
Python≡browser. Plus the Pyodide import/`make_env()` fixture that API-07's record
already validated the *mechanism* for (2026-07-19). → **PG-5** on how we execute
the browser side (headless node vs. real browser shell).

---

## 5. Proposed freeze order (waves)

Dependency-first, so a family never freezes before what it references. Kernel is
absolute-first (everything pins it); replay/export are last (they close over
everyone).

| Wave | Families | Rationale |
| --- | --- | --- |
| **0** | Clear §3 blockers B-1..B-6 | Unblocks G0/G5/G6 corpus-wide |
| **1** | **shared-kernel** | Every family pins it; freeze the vocabulary first |
| **2** | API-01, API-03, API-04 | Authoring / identity / flow foundations |
| **3** | API-05, API-06, API-07 | Casting / interaction / game core |
| **4** | API-10, API-11, API-22 | Evidence / storage / jobs (capture backbone) |
| **5** | API-09, API-12, API-13, API-08 | Client / scheduler / providers / conversation |
| **6** | API-14, API-15, API-16, API-17, API-18, API-19 | Tools / memory / replay / content / QC / export |

I recommend we **prove the whole gate on one family end-to-end first** (a
"vertical slice") before scaling — the shared kernel in Wave 1 — so we discover
gate friction on the family that matters most. → **PG-2** confirms order + slice.

---

## 6. Sign-off model — the open question I most need you on

Every family needs an accountable owner + 4 reviewer-role sign-offs. Options:

- **(a) You are all roles.** Simplest; you record sign-off per family. Honest for
  a solo project but no independent adversarial pressure.
- **(b) Agent review panels (my lean).** For each family, one adversarial agent
  per reviewer role (domain / runtime / data-replay / security) produces a
  written sign-off record with findings it *tried and failed* to break; you are
  accountable owner and give final acceptance. Reuses the workflow pattern that
  found real issues during the folds. Independent-ish, cheap, auditable.
- **(c) Real external reviewers.** Highest assurance, slowest; probably reserve
  for the kernel + the science-critical families (API-07/10/16).

→ **PG-1.** My proposal: **(b) as default, (c) for the kernel and API-07/10/16.**

---

## 7. Proposed first deliverable (the vertical slice)

If you approve the framework, I'd start with **shared-kernel freeze** and produce,
in this order:

1. **Wave-0 blockers that touch the kernel** — none of B-1..B-3 do; B-6 (RFC 8785
   vectors) does. Build the G5 vector set (§4c).
2. **G3 for the kernel** — the kernel has no NS scenario of its own; instead prove
   it via the label-lattice + identifier + canonical-JSON vectors it already owns.
3. **G6** — accept **ADR-0008** (identifiers/serialization/evolution),
   **0009** (command/receipt/idempotency), **0010** (clocks/ordering/fencing),
   **0011** (classification/retention/secrets): the four the kernel depends on.
   Each ADR moves Proposed→Accepted with a short acceptance note.
4. **G7** — run the sign-off model we pick in PG-1 against the kernel.
5. **G8** — freeze kernel v1 bytes; record the frozen digest; state the
   "publication compiler rejects v0" rule.

That produces a **worked example of every gate** on the highest-leverage family,
which we then template across the waves.

---

## 8. Decisions I need from you (PG-\*)

| ID | Question | **Settled answer (2026-07-20)** |
| --- | --- | --- |
| **PG-1** | Sign-off model? | **Agent review panels per role (default); real human review for the kernel + API-07/10/16.** |
| **PG-2** | Freeze order + kernel vertical slice first? | **Yes — §5 waves, shared kernel first as the end-to-end slice.** |
| **PG-3** | A07-O01 codec & RP-8 sub-items before freeze? | **Freeze now, defer both** to a v1.1 addendum (JSON contract doesn't depend on them). |
| **PG-4** | NS golden traces up front or per-wave? | **Per-wave** — build each NS trace when its last spanning family reaches G3. |
| **PG-5** | Browser conformance execution? | **Real browser shell in CI** (not headless node). ⇒ new infra; see §9. |
| **PG-6** | Git commit policy? | **Stay working-tree-only** — no commits until further notice. |

### Implications of the two non-default answers

- **PG-5 (real browser CI).** G5 for the kernel now requires an actual
  browser-shell harness, so that harness becomes a **kernel-freeze prerequisite**,
  not a Phase-1 deferral. It needs its own small approach decision → **§9 / PG-7**.
  The RFC 8785 vector **data** is harness-agnostic and can be built first; only
  the browser *executor* waits on PG-7.
- **PG-6 (working-tree-only).** No freeze commit at G8; a "frozen" contract is
  recorded by its pinned v1 digest in the review-record, not by a git tag. Fine —
  the digest is the real freeze artifact.

---

## 9. PG-5 follow-on: how we stand up the real browser shell (PG-7)

Standing up a browser shell in CI touches tooling/config, so before I build it I
want your approach call. Options I'll detail on request:

- **(a) Playwright + Chromium**, a tiny JS canonicalizer module loaded into a
  blank page, vectors fed in and `{canonical_bytes, sha256}` compared to the
  Python-authored golden. Most representative of the real client.
- **(b) Reuse the existing MUG client JS** (`mug/server/static/js/…`) if it
  already contains a canonicalizer, wrapped in a browser test — proves the *real*
  shipping code, not a test stand-in.
- **(c) Web-platform runtime via Pyodide-in-browser**, extending the 2026-07-19
  Pyodide precedent to a real browser rather than node.

**PG-7 (settled 2026-07-20): (a) Playwright + Chromium** with a small JS
canonicalizer module loaded into a blank page; vectors fed in and
`{canonical_bytes, sha256}` compared to the Python-authored golden. I'll scope
the harness before adding any tooling/config (respecting PG-6 — working-tree
only, no commits).

### PG-7 raises the real substance of G5 (see B-7)

Because the browser side must run **conforming JCS**, so must the Python side —
which means G5 is not "author vectors against `json.dumps`", it is "stand up a
**real RFC 8785 implementation** (Python + JS), prove they agree, and prove the
existing corpus digests are unaffected." The vector set must therefore include
the divergence-prone cases on purpose:

- integers at the safe boundary (`±9007199254740991`) — expect agreement
- **non-integer numbers** (`1.0`, `0.5`, `100.0`) — the case where `json.dumps`
  (`1.0`) and JCS (`1`) **disagree**; this is the one that could invalidate a
  pinned digest
- ASCII-key ordering (agrees by construction) and a deliberately-rejected
  astral/lone-surrogate key (proves the ASCII constraint is enforced, not relied
  on by luck)
- control-character string escaping (`\b`, `\t`, ` `) — check JCS vs
  `json.dumps` escape choices

The deliverable includes a **corpus digest-diff report**: every digested value
run through both canonicalizers, listing any deltas. My expectation is **zero
deltas** (the profile forbids the divergent cases in identity-bearing fields),
which would confirm the 553-test digest web is JCS-valid and no re-stamp is
needed — but we verify rather than assume.

---

## 11. B-7 measured: corpus canonicalization scan (2026-07-20)

Scanned all 471 corpus JSON files (schemas + fixtures + manifests) with the
strict parser the digests use. Result:

- **Object keys: 0 non-ASCII.** Key-sort ordering is safe corpus-wide — JCS's
  UTF-16 sort ≡ code-point sort ≡ the current sort for every key. No risk.
- **Control-char strings: 1**, an `\n` in `api-17 content-spec.inline-markdown`.
  **Not a divergence** — both `json.dumps` and JCS emit the short escape `\n`.
  (Only the no-short-escape control chars U+0000–U+001F would differ, and none
  appear.) No risk.
- **Raw floats: 16**, in 7 fixtures. All are **non-integral** (`0.8`, `1.2`,
  `0.25`, `0.75`, `0.5`, `-0.25`, `120.5`, `96.25`) — none is an integral float
  (`1.0`) and none needs exponent notation, which are the cases where `json.dumps`
  and JCS/ES6 actually diverge. So `json.dumps` very likely already equals JCS
  byte-for-byte on all 16 (to be **confirmed** when the real JCS impl lands, not
  assumed). Schemas and every cross-family chain fixture (mesh / authority /
  decision-result / decision-tape) are float-free, and the 16 float fixtures are
  digest **leaves** (their own canonical digest isn't pinned elsewhere).

**Prong 1 (canonicalization).** Swapping the harness to a conforming JCS
implementation is required by the spec and is the core of G5 — but the scan says
it should need **zero digest re-stamps**: identical bytes for all float-free/ASCII
content (schemas + chain), and near-certainly identical for the 16 non-integral
floats too. We prove this with the JCS diff rather than trusting it.

**Prong 2 (numeric-profile compliance) — the real decision.** The kernel numeric
profile says digest-bearing JSON numbers should be **safe integers**, with exact
/fractional values carried in string form (`{"kind":"decimal","decimal":"…"}`).
Some of the 16 raw floats sit in clearly digestable content and look like
profile violations; others are plausibly legitimate non-identity display/config:

| Float | Location | Read |
| --- | --- | --- |
| `confidence: 0.8` | shared-kernel `wire-command` payload (a digested `TypedObject`) | **Candidate violation** — identity-bearing model confidence should be string-decimal or scaled int |
| `temperature: 1.2` | api-05 `onnx-policy` (a versioned/digested policy spec) | **Candidate violation** — spec-bearing; I introduced `0 < t ≤ 100` as a raw float in the RP-5 fold |
| `x/y: 120.5 / 96.25` | api-07 `render-packet` Surface draw coords | Likely **legitimate** — resolution-independent sub-pixel coords (D09-2); confirm render packets aren't identity-digested |
| `0.25 / 0.75` | api-09 `bridge-message` response-set | Judgment — participant response values; violation iff captured as digested evidence |
| `0.5 / -0.25` | api-09 `input-scheme` analog axis bindings | Likely **legitimate** — analog axis config |

**PG-8 (open):** how do we treat raw floats in digestable content?

- **(a) Targeted (my lean).** Convert the identity/spec-bearing ones
  (`confidence`, `temperature`) to the profile's string-decimal form; keep raw
  floats where they are non-identity display/config (render coords, analog axes),
  and add a schema note that those fields are non-digested display data.
- **(b) Strict.** Forbid raw floats in all digested content; convert all 16 to
  string-decimal / scaled-int. Maximum profile purity; touches 5 families.
- **(c) Relax.** Amend the numeric profile to permit finite non-integral floats
  in digested content (since JCS makes them deterministic). Least work; weakens
  the "no float identity" guarantee the profile was written to give.

---

## 12. PG-8 settled: relax the numeric profile — implications + drafts

**PG-8 (settled 2026-07-20): Relax.** Finite non-integral binary64 floats are
permitted in digested content; the 16 floats stay. **Consequence:** float
formatting is now identity-bearing, so (i) the harness MUST move off
`json.dumps` to a **conforming JCS canonicalizer**, and (ii) G5 must *prove*
Python-JCS ≡ browser-JCS on the hard number cases, because real v1 digests will
depend on it.

### 12a. Proposed numeric-profile amendment (kernel serialization doc) — for your review

Draft addition to `shared-kernel/serialization-and-schema-evolution.md`
§"Numeric profile" (I have NOT edited the real doc yet — approve first):

> Digested content MAY carry finite non-integral IEEE-754 binary64 numbers.
> Their canonical form is the RFC 8785 / ECMAScript `Number`-to-`String`
> serialization (shortest round-tripping decimal), which is identical across
> conforming Python and browser implementations, so a float value has one
> canonical digest. Integral-valued numbers have a single canonical form
> regardless of source spelling (`1`, `1.0`, and `1e0` all canonicalize to `1`);
> schemas therefore still declare `integer` where integer semantics are intended.
> Negative zero is forbidden where its sign is meaningful; non-finite values
> remain rejected at parse. Values needing precision beyond binary64 (exact
> decimals, uint64, bit patterns) still use the typed string form and never a
> raw JSON number.

This *narrows* the old "steer identity values to integers/strings" guidance to
"integers/strings are required only when binary64 can't represent the value
exactly," and leans on JCS determinism for everything else — which is precisely
the bet PG-8 makes.

### 12b. JCS implementation approach (my recommendation, not a blocking question)

Hand-rolling conforming ES6 number formatting is the intricate part and easy to
get subtly wrong. I recommend the **Python side uses a vetted RFC 8785 library**
(e.g. the `rfc8785` package) as the canonical implementation, wired into
`_contract_harness.canonical_bytes`, rather than a bespoke formatter — with our
vector set as the cross-check. The **browser side** (PG-7 Playwright) uses a
matching vetted JS JCS module. Adding the dep is a tooling change only (uv /
node), consistent with PG-6 (working-tree-only, no commits). Say the word if
you'd rather I hand-roll it to avoid the dependency.

---

## 13. G7 kernel review results + triage (2026-07-20)

Four adversarial agent panels ran. **Verdicts: 2 SIGN-OFF (domain, security), 2
BLOCK (data/replay, runtime).** The review did its job — it found a real gap I
introduced and a set of genuine pre-freeze items. Per PG-1 the kernel also still
needs a **real human review** (you) on top of these agent panels.

### Triage

| # | Panel | Sev | Finding | Disposition |
| --- | --- | --- | --- | --- |
| 1 | data/replay | **BLOCK** | `test_contract_fixtures.py` + `test_api01` kept **local `json.dumps` canonicalizers**; only `_contract_harness` was swapped. A future integral-float in a schema would freeze a non-conforming digest. | **FIXED this turn** — both migrated to `rfc8785`; added `test_frozen_bundle_digest_is_jcs_conforming` guard; suite **630** green. |
| 2 | runtime | **BLOCK** | `LeaseRef`, `EventCursor`, `StreamPosition`, `Duration` are frozen value shapes with **no golden fixture**; NS-10/12 walkthroughs unbuilt. | **DECISION D3** — build shape fixtures now + scope the NS obligation. |
| 3 | domain | MAJOR | Receipt embeds no pinned `study_version_id`/`deployment_revision_id`/`semantic_fingerprint` → not a self-contained reproducibility anchor. | **DECISION D1** |
| 4 | domain+security | MAJOR | `ArtifactRef` mandates a digest; a full ref reaching a client unblinds treatment by digest/size equality. | **DECISION D2** (gate SK-O08) |
| 5 | data/replay+domain | MAJOR | Embedded `canonicalization-vectors.json` has 2 int/ASCII vectors, no floats — the amendment isn't exercised in the shipped corpus. | **WILL-FIX** — add float/`-0`/collapse/exponent vectors to the embedded fixture, validated via `rfc8785`. |
| 6 | data/replay | MINOR | Conformance set lacks an astral-**key** vector + `1e20`/17-digit. | **WILL-FIX** — add to the 37-vector set. |
| 7 | security | MINOR | Unreferenced `PrivacyLabel` enum = latent lattice-bypass footgun. | **WILL-FIX** — remove the `$def` (kernel-digest change; batch with other schema edits). |
| 8 | security | MINOR | No **Receipt row** in privacy destination matrix; commit receipts leak stream cardinality if they reach a participant. | **WILL-FIX** — prose. |
| 9 | runtime | MINOR | Indeterminate receipt not required to carry `stream_positions`. | **WILL-FIX** — schema `minProperties:1` on the indeterminate `then` (batch). |
| 10 | domain | MINOR | Indeterminate receipt doesn't constrain `error.code`. | **WILL-FIX** — schema `const external.unknown_outcome` (batch). |
| 11 | runtime | MINOR | Fencing rule 4 reads generation-only; rule 7 epoch-collision can defeat it. | **WILL-FIX** — prose: require epoch+generation atomic condition. |
| 12 | runtime | MINOR | Idempotency-scope discriminator inconsistent between two doc sections. | **WILL-FIX** — prose reconciliation. |
| 13 | runtime | NOTE | Review-record cites stale "50 tests"; actual 630. | **WILL-FIX** — prose. |
| 14 | domain | NOTE | `etag` `sha256:` vs `Digest.algorithm` `sha-256` spelling split. | **WILL-FIX** — prose note. |
| 15 | data/replay+domain | NOTE | `ArtifactRef.content_schema` optional → not self-describing for opaque media types. | **DEFER** — gate SK-O06 (binary codec ADR). |

**Common thread:** every panel's sign-off is contingent on the same open gates —
**SK-O04** (now largely met: rfc8785 + browser vectors landed), **SK-O08**
(artifact redaction), **SK-O15** (handle policy), and **ADR-0008..0011 accepted**.
Nothing overturned the kernel's core soundness — the "tried-and-failed-to-break"
lists are extensive (no wire-injectable trusted context, no fingerprint
collision, no lattice downgrade, no handle correlation, no stale-lease effect).

### The schema-changing WILL-FIX items (7, 9, 10) + whatever D1/D2 imply all touch
the kernel bundle, so I'll **batch every kernel schema edit, restamp the kernel
digest cascade once**, then re-verify — rather than restamping repeatedly.

### Decisions I need before executing the batch → §14.

## 14. G7 decisions settled + narrow-freeze scope (2026-07-20)

- **D1 = Self-contained receipt.** Embed `study_version_id` + `deployment_revision_id`
  + the `semantic_fingerprint` digest in `commit`/`artifact_commit` receipts.
  **Applies at the runtime-layer freeze** (per D3), not the core freeze.
- **D2 = Guardrail now, client ref in API-11.** Mark `ArtifactRef`
  trusted/archival-only (prose + a destination-matrix rule that condition-linked
  content must not expose digest/size to clients); the concrete blinding-safe
  client delivery reference is deferred to API-11 under SK-O08. No kernel schema
  growth.
- **D3 = Narrow the freeze — the kernel freezes in TWO events:**
  - **Core layer (freeze NOW):** identifiers/resource hierarchy; canonical
    JSON/serialization/numeric/evolution; `TypedObject`, `SchemaRef`,
    `ArtifactRef`, `SecretRef`, `PublicHandle`, `VersionStamp`; privacy
    classification lattice + `DataHandlingRef`; wire-command envelope + the
    `DomainError` taxonomy. **Accept ADR-0008 + ADR-0011.**
  - **Runtime layer (freeze WITH API-06/12):** command/receipt/idempotency
    (**ADR-0009**), clocks/ordering/fencing — `LeaseRef`, `EventCursor`,
    `StreamPosition`, `Duration` (**ADR-0010**). D1 and WILL-FIX #9/#10/#11/#12
    land here, with the runtime panel's shape+state-machine fixtures.

**Realization (my default, override if you want a hard split):** keep the single
`shared-kernel.schema.json` bundle. The core freeze = **change-control on the
core `$defs` + accepted ADR-0008/0011**, with the current bundle digest recorded
as a checkpoint; the whole-bundle immutable digest is re-recorded when the
runtime layer freezes. A physical core/runtime bundle split (clean hard core
digest now, at the cost of a corpus-wide `$ref` cascade) is the alternative,
deferred unless you ask for it.

**Core batch to execute now:** #5 (float vectors), #6 (astral-key/`1e20` vectors),
#7 (remove `PrivacyLabel`), #8 (destination-matrix Receipt row), #13 (test
count), #14 (etag note), **D2** (ArtifactRef archival-only guardrail).
**Deferred to runtime-layer freeze:** #9, #10, #11, #12, **D1**.

---

## 16. ADR ledger fully accepted (2026-07-20)

All 15 ADRs are now **Accepted** (0001 was already). Ratification decisions:

- **Batch formalities (accept as-is; substance folded + test-covered):** 0002
  (actor/channel model), 0003 (immutable versions + materialized plans), 0004
  (storage tiers), 0005 (server-authoritative external agents), 0006
  (canonical + experienced streams), 0007 (provenance manifests), 0014
  (identity-not-recruitment), 0015 (governance out of scope).
- **0009 / 0010 (runtime layer):** *decisions* accepted; the schema **byte-freeze**
  + the runtime review-panel findings (#9–#12) + D1 self-contained receipt land
  with the **API-06/12 runtime-layer freeze** (D3). Accepting the decision ≠
  freezing the bytes.
- **0012:** accepted **as amended by 0013 + 0015** (draft/registry machinery in
  the body is not part of the accepted decision).
- **0013:** accepted; non-git-author path is an explicit v0 limitation, retention
  defers to API-11.

**Framing:** accepting an ADR ratifies the architectural *decision* (all folded +
covered by the 638-test suite). Each **family** still runs its own G0–G8
(adversarial panel + freeze) before its v1 bytes lock — the kernel showed that
review finds real defects, so ADR acceptance deliberately does not skip it.

### Round-2 ADR follow-up resolutions (2026-07-20)

- **0013 repo layout:** both one-repo-per-study and monorepo-subdir allowed
  (version pins commit + subpath).
- **0015 operational logging:** v0 ships minimal ops logging (health/errors/traces),
  distinct from audit; owned by API-22.
- **0014 routing:** flow position in the materialized plan suffices; no named
  checkpoints.
- **All other ADR follow-ups (~15, ADR-0009 ×4 / 0010 ×5 / 0012–0014 residual):**
  routed to their owning family gates (they are exact-schema design, not
  standalone approvals).

**ADR ledger: 0001–0015 all Accepted.** Remaining Phase-0 gate work is now purely
per-family (G0–G8) + the two deferred kernel/family byte-freezes.

---

## 10. Kernel vertical-slice execution checklist (Wave 1)

Concrete, ordered, respecting the settled answers. Items marked **[infra-free]**
I can start immediately; **[needs PG-7]** waits on the browser-shell approach.

0. **[DONE] B-7 resolved.** `_contract_harness.canonical_bytes` now calls the
   vetted `rfc8785` library (added to the `test` extra). Full-corpus diff showed
   **0 byte deltas** vs the prior `json.dumps` form, so no pinned digest moved and
   the suite stays **553 green**. Numeric-profile amendment landed in the kernel
   serialization doc (finite non-integral floats permitted; integral-float
   collapse `1.0`→`1`). Chromium verified launchable (`String(1.0)`→`"1"`).
1. **[DONE] G5 vector data + Python test** — `tests/architecture/conformance/rfc8785-vectors.json`
   (37 vectors) + `test_rfc8785_python_conformance.py`; includes the official RFC
   8785 §3.2.3 appendix example (hand-verified).
2. **[DONE] G5 browser executor (PG-7 Playwright)** — vendored MIT `canonicalize.js`
   + `test_rfc8785_browser_conformance.py` drives Chromium and asserts every vector
   byte-identical to the Python golden. **0 Python≡browser divergences** across all
   37 (incl. `-0.0`→`0`, `1e21`→`1e+21`, integral-float collapse). Suite now **629**.
3. **[infra-free] G6 ADR acceptance** — move **ADR-0008/0009/0010/0011**
   Proposed→Accepted, each with a short acceptance note citing the kernel
   review-record evidence. (These four are the kernel's ADR dependencies.)
4. **[infra-free] G1/G3 kernel evidence audit** — confirm the kernel's own
   vector suites (label lattice, identifiers, canonical JSON, typed-object
   second-stage validation) stand in for its scenario traces; record the mapping.
5. **[panel] G7 sign-off** — run the 4 agent review panels + flag the kernel for
   real human review (PG-1); record sign-off rows in the kernel review-record.
6. **[freeze] G8** — freeze kernel v1 bytes; record the frozen bundle digest and
   the "publication compiler rejects v0" rule in the review-record.

---

*Next action: on your nod I start items 1 and 3 (both infra-free) and bring back
the RFC 8785 vector set + the four ADR acceptance notes for review; item 2 waits
on PG-7 (browser-shell approach).*

---

## 17. Phase 0 closed as-is (2026-07-20) — owner decision

**Decision (accountable owner):** Phase 0 is **closed as-is**. It is declared
complete on the strength of the accepted decision ledger + the frozen shared-
kernel core, without carrying the remaining families through per-family G0–G8.
Rationale: the abstract contract phase has served its purpose (a consistent,
test-covered vocabulary and 15 ratified decisions); further per-family freezing
is better done against real implementation, when the bytes can be validated by
running code rather than fixtures alone.

### What "closed as-is" locks vs. defers

| Item | State at close |
| --- | --- |
| **15 ADRs (0001–0015)** | **Accepted** — the decision ledger is final. |
| **Shared-kernel CORE layer** | **Frozen** (ADR-0008/0011; digest `f675d9ec`). The one frozen v1 contract. |
| **638-test corpus** | Green; canonicalizer is conforming RFC 8785; G5 Python≡browser proven. |
| **Prose drift (B-2 north-star, B-3 quality-attributes)** | **Already clean** — verified 2026-07-20: every governance/plugin/recruitment reference is correct negative framing aligned to ADR-0014/0015. No edit needed; the B-2/B-3 blocker rows were stale (reconciliation landed with the ADR folds). |
| **B-1 (API-01 plugin residue)** | **Already clean** — the only `plugin.*` references in API-01 are rejection fixtures asserting the retired namespace is refused; no live `PluginRequirement` $def. |
| **Kernel RUNTIME layer** (ADR-0009/0010 byte-freeze; LeaseRef/EventCursor/StreamPosition/Duration fixtures; D1 self-contained receipt; WILL-FIX #9–12; NS-10/12 traces) | **Deferred to implementation** (freezes with API-06/12). |
| **Per-family byte-freeze (G8) for all ~20 families, waves 2–6** | **Deferred to implementation** — each family runs its own G0–G8 (agent panel + freeze) when its code is built. |
| **New evidence classes** — G3 NS golden traces, G4 fault-injection fixtures | **Deferred** — build alongside the implementation they validate. |
| **Still-open sub-items** — A07-O01 binary snapshot codec; the two RP-8 sub-items (state→env-args; read-only participant handle); completion-redirect shape; ~15 routed ADR family follow-ups | **Carried forward to the owning family gate at implementation time.** |

### Why this is a safe close, not a shortcut

- **Nothing is silently frozen.** Only the kernel core has locked v1 bytes; every
  other family is explicitly "Drafted (design-accepted)", not "Accepted". A family
  freeze is a deliberate future act, gated by its own adversarial panel — the
  kernel proved that panel finds real defects, so we did not skip it, we scheduled
  it against real code.
- **The decisions are final and covered.** All 15 ADRs are Accepted and folded;
  the 638-test suite exercises every family's schemas + the cross-family digest DAG.
- **No stale prose ships.** B-1/B-2/B-3 verified clean at close.

**Phase 0 status: CLOSED (as-is), 2026-07-20.** Remaining contract work is now
owned by the implementation phase, per family, against running code.
