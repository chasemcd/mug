# Contract freeze tracker

| Field | Value |
| --- | --- |
| Status | Bytes pinned for all 22 bundles; owner sign-off recorded for 0 |
| Source of truth | `contract-freeze.json` |
| Purpose | Record what each contract bundle pins, and what it still needs |

> **This file is generated.** Rebuild it with
> `uv run python tests/architecture/_freeze.py`. Do not edit it by hand:
> `tests/architecture/test_contract_freeze.py` compares it to the ledger,
> and the ledger to the bytes on disk and the running code.

## What a freeze means here

Phase 0 closed with each family's byte-freeze deferred to the
implementation phase, to be run against code rather than against a
design. The mechanical half of that gate is now enforced:

1. **The bytes are pinned.** The digest below is the digest the running
   loader computes for the bundle. A schema edit that is not recorded
   here fails the gate.
2. **The fixtures are pinned.** The manifest carries its own digest, and
   so do the fixture bytes it indexes, so the evidence cannot move under
   the schema either.
3. **The surface is pinned.** The records column is every `$defs` name
   the fixtures exercise. A new record in the contract fails the gate
   until the freeze is amended.
4. **The running code holds the same bytes.** The digest is read through
   the runtime package's own accessor, not recomputed beside it.
5. **Every record has a model.** The conformance suite binds each record
   name to a model that accepts what the schema accepts and refuses what
   it refuses.

The remaining half needs a person. The Phase-0 ladder ends with an
adversarial review panel and the accountable owner's sign-off, and no
tool can write those. `owner_sign_off` stays empty until a human records
it, and this table shows it empty rather than assuming it.

## What is still open

**Every declared record has a fixture behind it.** A walk of every
`$ref` in the corpus, from every definition a fixture case names,
reaches every record every bundle declares, so no record is held by the
contract and the code alone. The count is pinned per bundle below, so a
new record that nothing exercises fails the gate. Definitions named
`Fixture...` are left out: through the corpus that prefix types the
evidence rather than the contract.

**No bundle carries an owner sign-off.** The mechanical gates say the
bytes and the code match. They say nothing about whether the contract is
the right contract, which is what the review panel was for.

## Bundles

| Bundle | Rev | Bundle digest | Records | No fixture | Runtime | Pinned | Owner sign-off |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `shared-kernel` Shared kernel | 0.2 | `f675d9ec…` | 14 | — | `mug.kernel` | 2026-07-25 | — |
| `api-01` Study authoring, compilation, and publication | 0.2 | `96958cdf…` | 18 | — | `mug.authoring` | 2026-07-25 | — |
| `api-02` Platform composition and deployment | 0.2 | `4fe71236…` | 5 | — | `mug.platform` | 2026-07-25 | — |
| `api-03` Identity, launch, and enrollment | 0.2 | `9e1a5bbf…` | 3 | — | `mug.identity` | 2026-07-25 | — |
| `api-04` Visit plans, flow, treatment, exposure, and state | 0.3 | `5985bd0d…` | 8 | — | `mug.visits` | 2026-07-25 | — |
| `api-05` Seats, actor instances, capabilities, and controller bindings | 0.3 | `df3da1e1…` | 7 | — | `mug.casting` | 2026-07-25 | — |
| `api-06` Interactions, channels, membership, matchmaking, and leases | 0.3 | `538a17e3…` | 9 | — | `mug.interactions` | 2026-07-25 | — |
| `api-07` Environment, game, input, rendering, and execution modes | 0.3 | `2c41f0fe…` | 6 | — | `mug.game` | 2026-07-25 | — |
| `api-08` Conversation, routing, history, streaming, and delivery | 0.2 | `0e305fb3…` | 6 | — | `mug.conversation` | 2026-07-25 | — |
| `api-09` Participant client, realtime, browser P2P, HTTP, and uploads | 0.4 | `ec6d3f00…` | 20 | — | `mug.client` | 2026-07-25 | — |
| `api-10` Events, capture, provenance, and projections | 0.3 | `f8d8da4c…` | 3 | — | `mug.events` | 2026-07-25 | — |
| `api-11` Storage, artifacts, repositories, transactions, and outbox | 0.2 | `007023d2…` | 4 | — | `mug.storage` | 2026-07-25 | — |
| `api-12` Automated controllers, scheduling, and execution | 0.3 | `b7ac5272…` | 6 | — | `mug.scheduling` | 2026-07-25 | — |
| `api-13` Model providers, content, usage, and errors | 0.2 | `4d5daed9…` | 4 | — | `mug.providers` | 2026-07-25 | — |
| `api-14` Tools, approval, and environment commands | 0.2 | `0dc762fe…` | 5 | — | `mug.tools` | 2026-07-25 | — |
| `api-15` Experimental agent memory | 0.2 | `a04cf73e…` | 4 | — | `mug.memory` | 2026-07-25 | — |
| `api-16` Replay capture, bundles, validation, reading, and branching | 0.3 | `73201d6c…` | 7 | — | `mug.replay` | 2026-07-25 | — |
| `api-17` Content, forms, presentation, and accessible UI components | 0.3 | `63d88932…` | 7 | — | `mug.content` | 2026-07-25 | — |
| `api-18` Preferences, annotation, quality, and adjudication | 0.3 | `717b95bd…` | 5 | — | `mug.preferences` | 2026-07-27 | — |
| `api-19` Dataset query, export, lineage, and external annotation | 0.2 | `97155dd5…` | 4 | — | `mug.export` | 2026-07-25 | — |
| `api-22` Durable background jobs and workers | 0.2 | `df34b114…` | 4 | — | `mug.jobs` | 2026-07-25 | — |
| `command-results` Command-result payloads (runtime layer) | — | `973f571c…` | 3 | — | `mug.runtime` | 2026-07-25 | — |

Tombstones carry no bytes and can hold no freeze record: `api-20`, `api-21`.

## What each bundle pins

### `shared-kernel` — Shared kernel

- Schema: `docs/architecture/phase-0/shared-kernel/schemas/v0/shared-kernel.schema.json`
- Bundle digest: `f675d9ec1f6258719da93a507421689b26babf69d36503c7df90b5039e238d6d`
- Fixtures: `docs/architecture/phase-0/shared-kernel/fixtures/v0/manifest.json`
- Fixture digest: `ae15e77fbc625c8f6d1af8a2c4110b589d7d6d1ab65438128f2170fe29e1bd90`
- Fixture bytes: `02473ad2c6a788a21e9dd33dc47c13e742c80f4e445d9074b6f0ee2c906b4b67`
- Runtime: `mug.kernel.load_shared_kernel_schema()`
- Conformance: `tests/unit/kernel/test_kernel_conformance.py`
- Records (14): `ArtifactRef`, `CanonicalizationVectorSet`, `CapabilitySet`, `CommandReceipt`, `DomainError`, `EventCursor`, `InlineBytes`, `PublicHandle`, `ResourceRef`, `SchemaRef`, `SecretRef`, `SemVer`, `TraceContext`, `WireCommandEnvelope`

### `api-01` — Study authoring, compilation, and publication

- Schema: `docs/architecture/phase-0/api-01/schemas/v0/study-authoring.schema.json`
- Bundle digest: `96958cdf2ab34fd541208d2adcd17f0d2c7d43ee2c1f5e433d2c87e323e2d58f`
- Fixtures: `docs/architecture/phase-0/api-01/fixtures/v0/manifest.json`
- Fixture digest: `ade79e8bb9535a64a6acdbf2a10725d00156b422412d21ad7ca265368f26a758`
- Fixture bytes: `280fa0abe949bde9880284f2bc47ee8e268747906e24a6b29bc49f78a78b173c`
- Runtime: `mug.authoring.authoring_schema()`
- Conformance: `tests/unit/authoring/test_authoring_conformance.py`
- Records (18): `AuthoringDocument`, `CapabilityRequirement`, `ClientManifest`, `CodePackageRef`, `CompiledStudyCandidate`, `Diagnostic`, `FlowSpec`, `GitProvenance`, `ManifestArtifact`, `ManifestSet`, `ProvenanceManifest`, `PublishedStudyVersion`, `ScientificManifest`, `SecretRequirement`, `ServerRuntimeBindingBase`, `StudyPublicationResult`, `StudyServerManifest`, `ValidationReport`

### `api-02` — Platform composition and deployment

- Schema: `docs/architecture/phase-0/api-02/schemas/v0/platform-deployment.schema.json`
- Bundle digest: `4fe71236a986f298966abe5ed4a6e9d1b53121a6b22de829eeb9a52826e09825`
- Fixtures: `docs/architecture/phase-0/api-02/fixtures/v0/manifest.json`
- Fixture digest: `fa570f026661759e02a0e9c62a4f9630fdc99cfbe9ed9678e9d9e53e155b22c2`
- Fixture bytes: `3210d1954055fdf640ba74fd022c146f55ba289a45b27070d6aa05500ec75d2b`
- Runtime: `mug.platform.platform_schema()`
- Conformance: `tests/unit/platform/test_platform_conformance.py`
- Records (5): `ClientDeploymentProjection`, `Deployment`, `DeploymentRequirement`, `DeploymentRevision`, `SatisfactionReport`

### `api-03` — Identity, launch, and enrollment

- Schema: `docs/architecture/phase-0/api-03/schemas/v0/identity-enrollment.schema.json`
- Bundle digest: `9e1a5bbf831cf1e93b854ffce55b56cdd67ce6499f1e7f5b266665d4a2894caf`
- Fixtures: `docs/architecture/phase-0/api-03/fixtures/v0/manifest.json`
- Fixture digest: `ca481359186f6a7060aa771060a05103de4b70b18db7983b98e1badd18a0781d`
- Fixture bytes: `541e6ba7a8142a8859ba1eff1dde32cbdd071e6580b1a590ea3a07a3806b625d`
- Runtime: `mug.identity.identity_schema()`
- Conformance: `tests/unit/identity/test_identity_conformance.py`
- Records (3): `Enrollment`, `ExternalIdentityLink`, `LaunchTicket`

### `api-04` — Visit plans, flow, treatment, exposure, and state

- Schema: `docs/architecture/phase-0/api-04/schemas/v0/visit-plan.schema.json`
- Bundle digest: `5985bd0df049a1a3fa2fc730e66fe0fe89c7a49038e40d1ce07a46f6a0fea161`
- Fixtures: `docs/architecture/phase-0/api-04/fixtures/v0/manifest.json`
- Fixture digest: `2c5a3505f8988366577e5d51d8255dbf7bd1f5889cf31f7adc9aa6d9212f0f38`
- Fixture bytes: `2c8d0a7fd329180f812e10c82c27384617a19e0663ed7e799ef4b85a3e62464d`
- Runtime: `mug.visits.visits_schema()`
- Conformance: `tests/unit/visits/test_visits_conformance.py`
- Records (8): `AllocationState`, `EligibilityCallback`, `StateDocument`, `TreatmentAssignment`, `TreatmentExposure`, `TreatmentPlan`, `Visit`, `VisitPlan`

### `api-05` — Seats, actor instances, capabilities, and controller bindings

- Schema: `docs/architecture/phase-0/api-05/schemas/v0/actor.schema.json`
- Bundle digest: `df3da1e10ffec853c052c7188e617cd2f2f529876c19b86d852164ba97552c1f`
- Fixtures: `docs/architecture/phase-0/api-05/fixtures/v0/manifest.json`
- Fixture digest: `3a746a5a13efd44a446645978c7fd02d460b9f4ea363ed55d2a6f0f265292f8e`
- Fixture bytes: `0c472248d405aa963491c23ac157486ee323be745c95b69776d82aeb89248336`
- Runtime: `mug.casting.casting_schema()`
- Conformance: `tests/unit/casting/test_casting_conformance.py`
- Records (7): `ActorInstance`, `CastDeclaration`, `ControllerBinding`, `Group`, `OnnxPolicy`, `SeatAgentBinding`, `SeatDefinition`

### `api-06` — Interactions, channels, membership, matchmaking, and leases

- Schema: `docs/architecture/phase-0/api-06/schemas/v0/interaction.schema.json`
- Bundle digest: `538a17e390be96543227d1cdef37274dbf0e59d1c10c457f3c3f428be182dc02`
- Fixtures: `docs/architecture/phase-0/api-06/fixtures/v0/manifest.json`
- Fixture digest: `4a60975b6cf6378f48a89d818e879817fbd03644e22b1bd937f93cefcc72798d`
- Fixture bytes: `f34b5a214e965a006527d154a33bc837be2a2865f31cc599bc522ab794b05515`
- Runtime: `mug.interactions.interactions_schema()`
- Conformance: `tests/unit/interactions/test_interactions_conformance.py`
- Records (9): `ChannelInstance`, `ConnectionLease`, `Group`, `Interaction`, `MatchmakingTicket`, `Membership`, `MeshLatencyProbe`, `MonitoringPolicy`, `P2PMeshMembership`

### `api-07` — Environment, game, input, rendering, and execution modes

- Schema: `docs/architecture/phase-0/api-07/schemas/v0/game.schema.json`
- Bundle digest: `2c41f0fe7bacf95174dc6c1cc1e57a4ce478d1deca1aeadd9d857f91d7d2caaa`
- Fixtures: `docs/architecture/phase-0/api-07/fixtures/v0/manifest.json`
- Fixture digest: `d5b0c18c033f4c6b826c92be122c83c461bb0911a99607a1b4ac683983a0162c`
- Fixture bytes: `2b8aa37bf73833eab0be35c0b2b9804d005e29407cf68427508d4dcf30055142`
- Runtime: `mug.game.game_schema()`
- Conformance: `tests/unit/game/test_game_conformance.py`
- Records (6): `EnvFactory`, `EpisodeBoundary`, `ExecutionMode`, `GameTransition`, `P2PFrameFinality`, `RenderPacket`

### `api-08` — Conversation, routing, history, streaming, and delivery

- Schema: `docs/architecture/phase-0/api-08/schemas/v0/conversation.schema.json`
- Bundle digest: `0e305fb358b6d53126d9081ae36f078f18a683684f2bfe799a97197c3d549d4a`
- Fixtures: `docs/architecture/phase-0/api-08/fixtures/v0/manifest.json`
- Fixture digest: `2037b93e86cae9659d08ae1c8987fe553dc450bc4628216ef49233b3ee219382`
- Fixture bytes: `e3a8ca6ac572c666fcb791417e06fdc377b806677c7ee0ba58b96330963b8eac`
- Runtime: `mug.conversation.conversation_schema()`
- Conformance: `tests/unit/conversation/test_conversation_conformance.py`
- Records (6): `CandidateReplySet`, `ChatMessage`, `ContextSnapshot`, `ConversationSegment`, `DeliveryReceipt`, `TurnPolicy`

### `api-09` — Participant client, realtime, browser P2P, HTTP, and uploads

- Schema: `docs/architecture/phase-0/api-09/schemas/v0/client.schema.json`
- Bundle digest: `ec6d3f0019480421a8cdc9ce8db2f2e88f2398e0daf0c7773ced3841ba435029`
- Fixtures: `docs/architecture/phase-0/api-09/fixtures/v0/manifest.json`
- Fixture digest: `7736d2d39e5044caca0626248ff7b38b1a830af9bef3fb0165cd80f39f34bba6`
- Fixture bytes: `3585dfc813bb2d566ff577683782f33a0a901ec53f08e8b33fc973c6f43ad542`
- Runtime: `mug.client.client_schema()`
- Conformance: `tests/unit/client/test_client_conformance.py`
- Records (20): `BridgeMessage`, `ClientHandshake`, `GateOp`, `InputScheme`, `MonitoringMeasurement`, `P2PCaptureSubmission`, `P2PIceGrantRequest`, `P2PMeshAbort`, `P2PMeshBootstrap`, `P2PMeshFinish`, `P2PMeshStart`, `P2PPeerComplete`, `P2PPeerReady`, `P2PSignal`, `P2PSignalAck`, `P2PSignalDelivery`, `RealtimeCommand`, `SeatDelivery`, `TransportAck`, `UploadTicket`

### `api-10` — Events, capture, provenance, and projections

- Schema: `docs/architecture/phase-0/api-10/schemas/v0/evidence.schema.json`
- Bundle digest: `f8d8da4c9fc94a6ce9234132cf0f22f166d3a3f8668a1e8113d2cebf9c7c4d6b`
- Fixtures: `docs/architecture/phase-0/api-10/fixtures/v0/manifest.json`
- Fixture digest: `5a59d1daf840c9b05fc49ca62b454218e37f16ff027176ea8f560fcaeb40cd58`
- Fixture bytes: `f399e3ba00eb1e2660689f958b34f5f2445d7a052f922a0efff23a5f937e7e64`
- Runtime: `mug.events.events_schema()`
- Conformance: `tests/unit/events/test_events_conformance.py`
- Records (3): `CapturePolicy`, `EventEnvelope`, `ExperiencedFrame`

### `api-11` — Storage, artifacts, repositories, transactions, and outbox

- Schema: `docs/architecture/phase-0/api-11/schemas/v0/storage.schema.json`
- Bundle digest: `007023d2d389fee6f93450c95aac747b412f4ecdfe033820df73c484b75b247e`
- Fixtures: `docs/architecture/phase-0/api-11/fixtures/v0/manifest.json`
- Fixture digest: `49a2ef690a0920c3881bc49c9e548ebbb0940c4b41fdb18428e9d1fb439e9e02`
- Fixture bytes: `76ac295539ba1f38f1a00cce583d61d2ffb4ea1afe87a169ab7e4e687f1b2c16`
- Runtime: `mug.storage.storage_schema()`
- Conformance: `tests/unit/storage/test_storage_conformance.py`
- Records (4): `ArtifactStaging`, `FinalizedArtifact`, `OutboxRecord`, `UnitOfWorkReceipt`

### `api-12` — Automated controllers, scheduling, and execution

- Schema: `docs/architecture/phase-0/api-12/schemas/v0/scheduler.schema.json`
- Bundle digest: `b7ac5272d5f4ddbbbb1779afb7f6045a51382067e3318b0c5b800a7658d13a76`
- Fixtures: `docs/architecture/phase-0/api-12/fixtures/v0/manifest.json`
- Fixture digest: `fa40c33a55a05aee659d85d3b24a9b13caa0d0ac593bb67351ec6fe3594eb712`
- Fixture bytes: `953006a8c81e6cecdf08bf75d3c763d6006829b589e89a6044ac91d6d3045384`
- Runtime: `mug.scheduling.scheduling_schema()`
- Conformance: `tests/unit/scheduling/test_scheduling_conformance.py`
- Records (6): `ControllerPolicy`, `DecisionRequest`, `DecisionResult`, `FallbackPolicy`, `P2PBotAuthority`, `SchedulerState`

### `api-13` — Model providers, content, usage, and errors

- Schema: `docs/architecture/phase-0/api-13/schemas/v0/provider.schema.json`
- Bundle digest: `4d5daed964741e873a261d06732f45e8d4342562325528d4824d7d1ab9915cdc`
- Fixtures: `docs/architecture/phase-0/api-13/fixtures/v0/manifest.json`
- Fixture digest: `53a7c9392b9862e969ada9bec699311cbc2117a0264564d88c6715c10a465410`
- Fixture bytes: `74264ec1ff84cf10593c89ad7a65391632352a26678b0cddd8d414747bb29b46`
- Runtime: `mug.providers.providers_schema()`
- Conformance: `tests/unit/providers/test_providers_conformance.py`
- Records (4): `AgentVersion`, `ProviderError`, `ProviderRequest`, `ProviderResponse`

### `api-14` — Tools, approval, and environment commands

- Schema: `docs/architecture/phase-0/api-14/schemas/v0/tools.schema.json`
- Bundle digest: `0dc762fe68b24cf27065b570c468a76323514d650016cd5b4d87150732766941`
- Fixtures: `docs/architecture/phase-0/api-14/fixtures/v0/manifest.json`
- Fixture digest: `0b66dd1bda3ffe3a80c151c116e9eacf00fe95870a6724e3f17caabb0c092bb3`
- Fixture bytes: `750f119830ced843345e7e2a4c9a27cc086a6af54cf03e884fd4a4cbf20defa6`
- Runtime: `mug.tools.tools_schema()`
- Conformance: `tests/unit/tools/test_tools_conformance.py`
- Records (5): `EnvironmentCommandMailbox`, `ToolApproval`, `ToolCall`, `ToolResult`, `ToolVersion`

### `api-15` — Experimental agent memory

- Schema: `docs/architecture/phase-0/api-15/schemas/v0/memory.schema.json`
- Bundle digest: `a04cf73e88cd0e0b15725930fb0206cde24296e6b93159ed969a54cb8d49ac4e`
- Fixtures: `docs/architecture/phase-0/api-15/fixtures/v0/manifest.json`
- Fixture digest: `242e2375cab3363ceb6e9265d3a431ec6613a01f3bf0a1803ce0dace83a142b0`
- Fixture bytes: `86a0985322aeb2e305c8722e22bfb8c02538b0721d4f5ea1171bd329a6c0bd51`
- Runtime: `mug.memory.memory_schema()`
- Conformance: `tests/unit/memory/test_memory_conformance.py`
- Records (4): `MemoryCommit`, `MemoryProposal`, `MemoryRead`, `MemoryScope`

### `api-16` — Replay capture, bundles, validation, reading, and branching

- Schema: `docs/architecture/phase-0/api-16/schemas/v0/replay.schema.json`
- Bundle digest: `73201d6c79a1df974207da0d252faa122f5231b10ce2211a03f0acf6e32e7c79`
- Fixtures: `docs/architecture/phase-0/api-16/fixtures/v0/manifest.json`
- Fixture digest: `2af70cf68e7d410e615786bb1fd88a522a3eab80ea9c66a71f885a429e423ef0`
- Fixture bytes: `ea97fbaa0e592846f78fcf807ac98c40fbee8806c966376c9cfdc907fd5f7051`
- Runtime: `mug.replay.replay_schema()`
- Conformance: `tests/unit/replay/test_replay_conformance.py`
- Records (7): `DecisionTape`, `DeterminismDeclaration`, `ExperiencedFrameLineageEntry`, `P2PFinalityOutcome`, `ReplayBundleValidation`, `ReplayManifest`, `StateHashCheck`

### `api-17` — Content, forms, presentation, and accessible UI components

- Schema: `docs/architecture/phase-0/api-17/schemas/v0/content.schema.json`
- Bundle digest: `63d889325b5004a974527cd9401c5819a22dbcf385c573d7cfad70595313c86f`
- Fixtures: `docs/architecture/phase-0/api-17/fixtures/v0/manifest.json`
- Fixture digest: `926dd7876c11e3e3ad1221a097b800a028ba3e77cb017bd1649858df615f583b`
- Fixture bytes: `c64fa0667c12e5d7cb87dc95bbed0efb6f0244b78ba9ca2e075309700b46684b`
- Runtime: `mug.content.content_schema()`
- Conformance: `tests/unit/content/test_content_conformance.py`
- Records (7): `AccessibilityProfile`, `ContentBody`, `ContentSpec`, `FormResponse`, `FormSpec`, `GateControl`, `PresentationComponent`

### `api-18` — Preferences, annotation, quality, and adjudication

- Schema: `docs/architecture/phase-0/api-18/schemas/v0/preference.schema.json`
- Bundle digest: `717b95bd477ea2e7f21fc8f77309896fdb7ad5e2b06b64a6de5b9289564d4db3`
- Fixtures: `docs/architecture/phase-0/api-18/fixtures/v0/manifest.json`
- Fixture digest: `7a6dc1cc0f34e56541d5776b299f40b4b06566a4a7e16f785c2de1865828048b`
- Fixture bytes: `c9c1aa50dd8e12adab6bff18565f0cede9b86bc7c9d9ddd535b1d3c0bc8a6014`
- Runtime: `mug.preferences.preferences_schema()`
- Conformance: `tests/unit/preferences/test_preferences_conformance.py`
- Records (5): `CandidateRef`, `PreferenceAssignment`, `PreferenceProtocol`, `PreferenceResponse`, `QualityEvidence`

### `api-19` — Dataset query, export, lineage, and external annotation

- Schema: `docs/architecture/phase-0/api-19/schemas/v0/export.schema.json`
- Bundle digest: `97155dd5f5f7945722339f859b002c11e7fdade91f224cb23a9bee28b7b21343`
- Fixtures: `docs/architecture/phase-0/api-19/fixtures/v0/manifest.json`
- Fixture digest: `9a05c36b4393e7cd56af9c12dbb3d0923fa26b42e77b54d4b1e4bf6441fec289`
- Fixture bytes: `7072b7ba0b0446f7017c46362633518abb5c01c6dd12e74d8634f8e2f35b3151`
- Runtime: `mug.export.export_schema()`
- Conformance: `tests/unit/export/test_export_conformance.py`
- Records (4): `DatasetSchemaBinding`, `ExportBundle`, `ExportRequest`, `LineageRecord`

### `api-22` — Durable background jobs and workers

- Schema: `docs/architecture/phase-0/api-22/schemas/v0/jobs.schema.json`
- Bundle digest: `df34b114612fea375a7a9e76da5b94bddf2bd5809da6a6277fe51b203e567c33`
- Fixtures: `docs/architecture/phase-0/api-22/fixtures/v0/manifest.json`
- Fixture digest: `fd6fa5c07be02b98543bf72cbf6eaceed5008dbc6ff0eecb32adb640eaeb4fae`
- Fixture bytes: `48889bf8dfdb04adf840e3fb7ceca34b4947cc2959fd5727a9da11e7678d0b37`
- Runtime: `mug.jobs.jobs_schema()`
- Conformance: `tests/unit/jobs/test_jobs_conformance.py`
- Records (4): `FirstClassJobKind`, `JobRequest`, `JobResult`, `JobRun`

### `command-results` — Command-result payloads (runtime layer)

- Schema: `docs/architecture/phase-0/command-results/schemas/v0/command-results.schema.json`
- Bundle digest: `973f571c3b28d6944f773126f0fd51fb69e640a89bb10ff8fd928cd23b1c84e8`
- Fixtures: none; the bundle is exercised through its users
- Runtime: `mug.runtime.command_results_schema()`
- Conformance: `tests/unit/runtime/test_command_results.py`
- Records (3): `EnrollmentResult`, `LaunchResult`, `VisitTransitionResult`

