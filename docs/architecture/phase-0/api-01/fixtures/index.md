# API-01 Golden Fixtures

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Last updated | 2026-07-20 |

The machine-readable [version-0 fixture manifest](v0/manifest.json) binds every
case to an exact schema fragment, validation layer, expected result, keyword,
and JSON Pointer. It contains 10 valid cases and 18 invalid cases; every invalid
case has one intended defect.

## Valid draft cases

- [Minimal normalized authoring document](v0/valid/authoring-document.minimal-static.json)
- [Participant-safe client manifest](v0/valid/client-manifest.minimal-static.json)
- [Private server-manifest template](v0/valid/server-manifest.minimal-static.json)
- [Protected provenance manifest with clean git provenance](v0/valid/provenance-manifest.minimal-static.json)
- [Scientific root manifest](v0/valid/scientific-manifest.minimal-static.json)
- [Closed compiled manifest set](v0/valid/manifest-set.minimal-static.json)
- [Successful empty validation report](v0/valid/validation-report.valid.json)
- [Git provenance for a clean commit](v0/valid/git-provenance.clean-commit.json)
- [Git provenance for a dirty tree with a stored patch](v0/valid/git-provenance.dirty-with-patch.json)
- [Published version envelope with version string and provenance](v0/valid/published-version.minimal-static.json)

These are structurally and semantically valid version-0 draft artifacts. They
are deliberately not valid publication inputs because their schema versions
are zero.

## Invalid cases

- [Secret requirement embeds a value](v0/invalid/secret-requirement.inline-value.json)
- [Optional observation omits disposition/completeness](v0/invalid/capability-requirement.optional-without-disposition.json)
- [Retired `plugin.*` capability namespace is rejected](v0/invalid/capability-requirement.plugin-namespace.json)
- [Retired server `plugin` binding kind is rejected](v0/invalid/server-runtime-binding.plugin-kind.json)
- [Error diagnostic is suppressible](v0/invalid/diagnostic.error-suppressible.json)
- [Authoring document duplicates a definition key](v0/invalid/authoring-document.duplicate-definition-key.json)
- [Flow references a missing node](v0/invalid/flow.undefined-child.json)
- [Randomized selection chooses too many children](v0/invalid/flow.randomized-choose-too-large.json)
- [Client component leaks an internal study ID](v0/invalid/client-manifest.internal-study-id.json)
- [Manifest content and artifact digests disagree](v0/invalid/manifest-artifact.digest-mismatch.json)
- [Publication closure contains version 0](v0/invalid/publication.version-zero-manifest.json)
- [Executable package uses a mutable URL as entry point](v0/invalid/code-package.mutable-entrypoint-url.json)
- [Dirty git provenance omits its patch](v0/invalid/git-provenance.dirty-without-patch.json)
- [Clean git provenance carries a patch](v0/invalid/git-provenance.clean-with-patch.json)
- [Commit SHA is not a full hex digest](v0/invalid/git-provenance.malformed-commit.json)
- [Patch artifact digest disagrees with the declared patch digest](v0/invalid/git-provenance.patch-digest-mismatch.json)
- [Published version omits git provenance](v0/invalid/published-version.missing-provenance.json)
- [Published version has a blank version string](v0/invalid/published-version.blank-version-string.json)

Version-string uniqueness and reuse rejection are transactional catalog rules;
they are exercised by the stateful cases in the
[conformance plan](../conformance.md), not by standalone JSON fixtures.

Fixture values are synthetic. They contain no usable credential, endpoint,
participant data, or production identifier.
