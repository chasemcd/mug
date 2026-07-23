# API-21 Review Record

| Field | Value |
| --- | --- |
| Status | Retracted for v0 |
| Review opened | 2026-07-17 |
| Review closed | 2026-07-18 |
| Outcome | Family retracted under decisions D15-1..3 (ADR-0015) |

## Decision

The phase-0 user-surface review (surface 15) concluded that **v0 ships no formal
extension-point / plugin system** (D15-1): closed vocabularies stay closed, and the
drafted API-21 machinery — `PluginManifest`, `CapabilityNegotiation`,
`IntegrationBinding`, trust classes, sandboxing, sharing/distribution — is cut, along
with its v0 schemas, fixtures, and contract-fixture tests.

Core authoring in Python (own envs, policies, renderers, native tools + MCP) is
unaffected (D15-2) and lives in API-07/12/14/17. The recorded post-v0 direction
(D15-3) is typed `ExtensionPoint` protocols implemented as plain Python classes pinned
via git-native versioning (ADR-0013) — never a plugin framework. See the
[tombstone index](index.md).

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-21: plugin-manifest, capability-negotiation, integration-binding, extension-point schemas, subset-grant and fail-closed rules, trust classes, 9 fixtures, 12 tests |
| 2026-07-18 | — | **Retracted** for v0 under D15-1..3 (ADR-0015): schemas, fixtures, and tests deleted; index rewritten as a tombstone recording the plain-Python post-v0 direction |
