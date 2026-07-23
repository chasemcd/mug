# API-01 Current-MUG Parity Map

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Last updated | 2026-07-20 |
| Accountable owner | Unassigned |
| Consumers | API-01 designers, domain-API owners, parity reviewers, implementers |
| Purpose | Ground API-01 in the author-facing capabilities and failure modes of the current repository |

This document is repository evidence, not an accepted target contract. It maps
what researchers can author today to the API family that must own the equivalent
vNext capability, and turns current implicit behavior into compiler
requirements.

The normative draft contracts that consume this evidence are
[Study Authoring and Publication](authoring-and-publication.md) and
[Manifest and Packaging Boundaries](manifests-and-packaging.md).

## Compatibility boundary

MUG vNext owes **functional parity, not source or behavioral compatibility**.
Existing experiment scripts, fluent builders, callbacks, import paths, socket
events, defaults, inference rules, filesystem layouts, and browser payloads do
not have to keep working. Equivalent studies must remain possible through the
new contracts. Unsafe or accidental behavior is not a parity obligation.

This is the boundary accepted by
[ADR 0001](../../decisions/0001-functional-parity-not-backward-compatibility.md)
and elaborated by the [functional-parity contract](../../functional-parity.md).
The API-01 compiler is therefore free to reject configurations that the current
runtime silently drops, mutates, exposes, or interprets by convention.

This map is a parity floor, not the complete north-star authoring surface.
Conversation, hosted-model, tool, memory, replay, and first-class preference
protocols have no adequate current-MUG equivalent. API-01 must also compose
those new domain specifications as they are defined; their absence from the
legacy capability tables does not remove them from scope. This document does
not choose the final public Python syntax or require a generic arbitrary-code
escape hatch.

## Ownership rule

API-01 owns study composition, flow definitions, compilation, the complete
scientific manifest and its participant-safe client, private-server, and
provenance projections, immutable scientific versions, and publication. It
composes typed objects owned by other API families; it does not redefine their
semantics. Its study-code package, capability, and deployment-requirement types
are composition and pinning wrappers. Executable customization is ordinary,
content-bound study code implementing closed, MUG-owned typed domain protocols;
API-02 separately owns deployment satisfaction. The accepted API-01 root must
reference those owners' exact schemas.

| Concern composed by a study | Target owner |
| --- | --- |
| Study, flow, compiler, manifests, study version, publication | API-01 |
| Deployment requirements and immutable deployment revisions | API-02 |
| Launch/return links, enrollment, and eligibility | API-03 |
| Treatment, assignment, exposure, visit plan, activity occurrence, participant state | API-04 |
| Seats, actors, controllers, and controller bindings | API-05 |
| Interactions, memberships, matchmaking, and connection leases | API-06 |
| Environments, game channels, input, rendering, and execution modes | API-07 |
| Conversation content, routing, history, streaming, and delivery | API-08 |
| Participant transport and realtime protocol | API-09 |
| Capture policy, events, metrics, and provenance | API-10 |
| Artifacts, repositories, transactions, and outbox | API-11 |
| Automated-controller scheduling and execution | API-12 |
| Hosted model-provider invocation and normalized output | API-13 |
| Tool definitions, approval, and execution | API-14 |
| Experimental agent memory | API-15 |
| Replay bundles, readers, validation, and branching | API-16 |
| Content, forms, presentation, and accessible UI | API-17 |
| Preference protocols, assignments, responses, quality, and adjudication | API-18 |
| Dataset query, export, and lineage | API-19 |
| Privacy classification and secret-reference primitives | Shared kernel; API-02 binds secrets at deployment |
| Durable compilation or generation jobs, when required | API-22 |

The complete ownership assignments are in the
[API catalog](../api-catalog.md#contract-ownership-rule).

## Current capability map

### Study configuration and launch

| Current author capability | Repository evidence | Required target expression | Owner or referenced contract |
| --- | --- | --- | --- |
| Name an experiment, attach its participant flow, and enable or disable data saving | [`ExperimentConfig` fields and `experiment()`](../../../../mug/configurations/experiment_config.py#L13-L69) | `StudySpec` with a `FlowSpec`; a separately owned capture policy. The study key is not a runtime occurrence ID or a content digest. | API-01, API-10, shared kernel |
| Select host, port, and broad latency settings | [`hosting()`](../../../../mug/configurations/experiment_config.py#L71-L86) | Deployment requirements in the study and concrete settings in an immutable deployment revision. Eligibility thresholds are versioned eligibility rules, not hosting fields. | API-02, API-03 |
| Serve researcher-provided asset directories | [`static_files()`](../../../../mug/configurations/experiment_config.py#L88-L103), [route registration](../../../../mug/server/app.py#L2929-L2937) | Declared, content-addressed asset collections with media type, integrity, privacy classification, and client-manifest placement. Physical serving is deployment-owned. | API-11, API-17, API-02 |
| Configure TURN credentials and force relay | [`webrtc()`](../../../../mug/configurations/experiment_config.py#L105-L126) | A logical transport and secret requirement in the study; API-02 later binds it to a deployment-owned `SecretRef`. Never place secret bytes or the deployment binding in scientific manifests. | API-02, API-06, shared kernel |
| Exclude by device, browser, latency, or a custom callback and customize messages | [`entry_screening()`](../../../../mug/configurations/experiment_config.py#L128-L203), [`get_entry_screening_config()`](../../../../mug/configurations/experiment_config.py#L205-L219) | Versioned eligibility rules over declared client-capability evidence, with durably recorded server decisions and safe presentation content. | API-03, API-09, API-10, API-17 |
| Aggregate browser-Python requirements across scenes | [`get_pyodide_config()`](../../../../mug/configurations/experiment_config.py#L221-L249) | Pure compilation of explicit backend and dependency requirements, followed by validation against the closed supported-capability set and deployment target. | API-01, API-02, API-07, API-11 |
| Start a study from a Python object graph | [representative configuration and `app.run()`](../../../../examples/slime_volleyball/slimevb_human_heuristic.py#L122-L141), [runtime entry point](../../../../mug/server/app.py#L2882-L2973) | Validate, compile, publish, then deploy an immutable study version. A mutable in-process object is not a published protocol. | API-01, API-02 |

### Flow and participant progression

| Current author capability | Repository evidence | Required target expression | Owner or referenced contract |
| --- | --- | --- | --- |
| Define an ordered flow with required start and terminal scenes | [`Stager.__init__`](../../../../mug/scenes/stager.py#L20-L41) | A typed `FlowSpec` whose root is an ordered composition and whose reachable terminal behavior is compiler-validated. Dedicated legacy `StartScene`/`EndScene` classes are not required. | API-01 |
| Create a participant-local copy of a study flow | [`Stager.build_instance()`](../../../../mug/scenes/stager.py#L43-L57), [`Scene.build()` and `copy()`](../../../../mug/scenes/scene.py#L53-L69) | A durable `VisitPlan` materialized from an immutable study version before exposure. Runtime objects are created from plan occurrences, not by deep-copying author objects. | API-04 |
| Advance sequentially and resume at the current activity | [`start()` and `advance()`](../../../../mug/scenes/stager.py#L75-L97), [`get_state()`, `set_state()`, and `resume()`](../../../../mug/scenes/stager.py#L99-L131) | Durable, idempotent activity progression over stable occurrence IDs, with a commit receipt and explicit recovery state. | API-04, API-10, API-11 |
| Nest flow wrappers | [`SceneWrapper`](../../../../mug/scenes/scene.py#L184-L215) | A closed, recursively composable flow algebra with strict schemas and exhaustive compiler traversal. | API-01 |
| Randomize order, select `keep_n`, and repeat activities per participant | [`RandomizeOrder`](../../../../mug/scenes/scene.py#L218-L247), [`RepeatScene`](../../../../mug/scenes/scene.py#L250-L265), [representative randomized study](../../../../examples/footsies/footsies_experiment.py#L14-L40) | Versioned random-selection/order and repetition nodes. API-04 persists assignment inputs, selected definitions, order, parameters, and distinct activity occurrence IDs before exposure. | API-01, API-04 |
| Redirect or issue a completion code at the end | [`EndScene.redirect()`](../../../../mug/scenes/static_scene.py#L152-L184), [`CompletionCodeScene`](../../../../mug/scenes/static_scene.py#L187-L231) | Typed terminal actions and an idempotent durable completion claim. Redirect parameters and external handoff behavior are explicit and privacy-reviewed. | API-03, API-04, API-17 |
| Carry participant-defined state between activities through browser globals | [client state submission](../../../../mug/server/static/js/index.js#L1645-L1654), [server synchronization](../../../../mug/server/app.py#L453-L474) | Namespaced, schema-versioned participant state documents with explicit readers, writers, privacy labels, persistence placement, and conflict rules. | API-04, API-10, API-11, shared kernel |

### Content, forms, and responses

| Current author capability | Repository evidence | Required target expression | Owner or referenced contract |
| --- | --- | --- | --- |
| Present headings and arbitrary inline or file-backed HTML/JavaScript | [`StaticScene.display()`](../../../../mug/scenes/static_scene.py#L74-L139), [body-file resolution](../../../../mug/scenes/scene.py#L128-L142) | Versioned content and presentation artifacts. Raw active content is an explicit trusted-study-code artifact with declared origin and execution semantics rather than an incidental string field. | API-17, API-11 |
| Collect required or optional free text | [`TextBox`](../../../../mug/scenes/static_scene.py#L234-L303) | A typed form protocol with a stable field key, validation schema, accessibility contract, privacy label, and durable response receipt. | API-17, API-10, shared kernel |
| Collect option selection, Likert scales, and rationale together | [`OptionBoxesWithScalesAndTextBox`](../../../../mug/scenes/static_scene.py#L306-L468), [`ScalesAndTextBox`](../../../../mug/scenes/static_scene.py#L471-L592) | Typed, composable form components. Preference-specific candidates, assignment, exposure, and responses are references to API-18 contracts rather than DOM positions. | API-17, API-18 |
| Collect single- and multi-select questions with optional images | [`MultipleChoice`](../../../../mug/scenes/static_scene.py#L595-L755) | Stable question and option IDs, typed answer cardinality, versioned assets, and server-side validation. | API-17, API-11 |
| Automatically retrieve declared browser elements and save a response | [DOM retrieval](../../../../mug/server/static/js/index.js#L1359-L1412), [CSV write](../../../../mug/server/app.py#L1036-L1082) | Submit a schema-bound response command with caller idempotency, a transactional commit receipt, lineage to the activity occurrence and form version, and progression only after durable acceptance. | API-09, API-10, API-11, API-17 |

### Environment, game, controller, and multiplayer authoring

| Current author capability | Repository evidence | Required target expression | Owner or referenced contract |
| --- | --- | --- | --- |
| Select an environment factory, configuration, and seed | [`GymScene.environment()`](../../../../mug/scenes/gym_scene.py#L253-L279) | A pinned ordinary study-code package implementing API-07's typed environment protocol, with typed configuration, seed policy, state/action/observation schemas, and exact artifact/dependency requirements. | API-01, API-07, API-11 |
| Map environment agents to humans, random policies, ONNX models, heuristic code, or custom loaders/inference | [`PolicyTypes` and `ModelConfig`](../../../../mug/configurations/configuration_constants.py#L7-L168), [`GymScene.policies()`](../../../../mug/scenes/gym_scene.py#L393-L506) | Explicit seats and controller bindings. Human, seeded-random, ONNX, packaged Python, and server-controller implementations conform to the closed typed capability and lifecycle protocols owned by API-05/API-07/API-12. | API-01, API-05, API-07, API-11, API-12 |
| Define keyboard mappings, composite keys, default/held actions, frame skip, episodes, and step limits | [`GymScene.gameplay()`](../../../../mug/scenes/gym_scene.py#L524-L598) | Typed input maps, action-population and cadence policies, and episode lifecycle/limit specs validated against the environment adapter. | API-07 |
| Define render cadence, viewport, coordinate representation, HUD, background, and rollback smoothing | [`GymScene.rendering()`](../../../../mug/scenes/gym_scene.py#L281-L357) | A versioned logical rendering/presentation spec with explicit experienced-stream capture requirements. | API-07, API-10 |
| Register preload assets, animation configuration, and initial render state | [`GymScene.assets()`](../../../../mug/scenes/gym_scene.py#L359-L391) | Content-addressed assets and typed renderer initialization. | API-07, API-11, API-17 |
| Draw rectangles, circles, lines, polygons, text, images, arcs, and ellipses in pixel or relative coordinates | [`Surface` asset and wire model](../../../../mug/rendering/surface.py#L21-L178), [`Surface` primitives](../../../../mug/rendering/surface.py#L184-L353) | API-07 owns a versioned typed renderer protocol and primitive semantics; API-01 pins any ordinary study-code implementation and API-11 artifact. | API-01, API-07, API-11 |
| Preserve render-object identity, delta updates, removal, depth, persistence, and tweening | [`Surface.commit()`, `remove()`, and `reset()`](../../../../mug/rendering/surface.py#L359-L412) | Typed object identity and delta/finality semantics, plus capture policy for canonical versus experienced presentation. | API-07, API-10 |
| Supply lobby/in-game content and participant-specific game-page HTML | [`GymScene.content()` and `waitroom()`](../../../../mug/scenes/gym_scene.py#L600-L676) | Content/presentation refs associated with typed interaction lifecycle states. Participant-specific views are manifest-partitioned client projections, not arbitrary HTML callbacks. | API-06, API-17, shared kernel |
| Run Python in the browser and declare packages, initialization source, and per-step source | [`GymScene.runtime()`](../../../../mug/scenes/gym_scene.py#L739-L814) | A pinned ordinary study-code package executed by API-07's typed browser backend, with exact source/dependency artifacts, deterministic-state claims, closed capability requirements, and deployment constraints. The environment factory replaces initialization-source injection; per-step behavior belongs in the versioned environment's ordinary `step()`/declared hooks. `on_game_step_code` is deliberately removed, rejected as an unknown field, and receives no compatibility translation. | API-01, API-02, API-07, API-11 |
| Choose P2P rollback or server-authoritative execution | [`GymScene.multiplayer()` mode](../../../../mug/scenes/gym_scene.py#L816-L866), [mode application](../../../../mug/scenes/gym_scene.py#L951-L989) | A typed game execution mode with mode-specific authority, determinism, reconciliation, capture, and recovery requirements. | API-07, API-10, API-16 |
| Configure matchmaking, known groups, wait time, RTT limits, continuous eligibility, reconnect, partner loss, and focus behavior | [`GymScene.multiplayer()` configuration and validation](../../../../mug/scenes/gym_scene.py#L816-L1132) | Versioned matchmaking and interaction-recovery rules over durable membership plus ephemeral queues/leases; client evidence and exclusion outcomes are durably captured. | API-03, API-06, API-09, API-10 |
| Run multiple independent game instances concurrently and let a participant progress to a later game activity | [`GameManager` tracks games and subject membership independently](../../../../mug/server/game_manager.py#L78-L110), [a new game is created for each match](../../../../mug/server/game_manager.py#L961-L1065), [scene advance clears game participation before the next scene](../../../../mug/server/app.py#L517-L558) | Each matched group receives a distinct durable `Interaction`/environment-session identity bound to one activity occurrence, membership set, controller set, and execution state. Concurrent games and sequential game activities share no mutable per-scene singleton; lifecycle, capture, and recovery remain independently addressable. | API-04, API-06, API-07, API-10, API-11 |
| Probe actual peer-to-peer RTT before creating a game, reject a failed pair, try another candidate, and re-pool unmatched participants | [probe/re-pooling contract in `Matchmaker`](../../../../mug/server/matchmaker.py#L64-L120), [probe iteration and waitroom re-matching](../../../../mug/server/game_manager.py#L536-L835) | A versioned connection-probe protocol with scoped candidate handles, deadlines, peer evidence, explicit accept/reject reasons, fenced matchmaking ownership, and durable assignment/exposure facts. Failure returns eligible participants to a queue without duplicating membership or repeatedly probing a rejected pair. | API-06, API-09, API-10 |

### External clients and authored study code

| Current author capability | Repository evidence | Required target expression | Owner or referenced contract |
| --- | --- | --- | --- |
| Embed a Unity/WebGL build, set dimensions/preloading/continue conditions, and run multiple scored episodes | [`UnityScene` configuration](../../../../mug/scenes/unity_scene.py#L14-L158) | A pinned ordinary study-code package implements API-07's typed external-client activity protocol and references exact build artifacts; API-17 owns its presentation content. | API-01, API-07, API-11, API-17 |
| React to Unity episode events and emit game-specific configuration | [`UnityScene` lifecycle hooks](../../../../mug/scenes/unity_scene.py#L160-L210), [custom Footsies hooks](../../../../examples/footsies/footsies_scene.py#L33-L114) | Pinned ordinary study code implements an API-07-owned event-handler protocol with declared event/configuration schemas, capabilities, deterministic/recovery claims, and API-10 evidence requirements. | API-01, API-07, API-10, API-11 |
| Subclass scenes and execute connect/client callbacks | [`Scene` lifecycle hooks](../../../../mug/scenes/scene.py#L53-L69), [`on_connect()` and `on_client_callback()`](../../../../mug/scenes/scene.py#L89-L125) | Pinned ordinary study code implements MUG-owned typed lifecycle callback protocols. Callbacks submit typed domain commands and cannot bypass runtime invariants, durable progression, or capture boundaries. | API-01, API-04, API-06, API-07, API-10, API-11 |
| Provide environment, rendering, HUD, policy loading/inference, page HTML, scoring, eligibility, and exclusion callables | [`GymScene` callable fields](../../../../mug/scenes/gym_scene.py#L69-L128), [`ExperimentConfig` eligibility callback](../../../../mug/configurations/experiment_config.py#L37-L52) | Pinned ordinary study-code packages implement each owning domain's closed typed protocol and configuration schema. Live Python callable identity is not a publishable protocol. | API-01, API-11, owning domain API |

### Data, evidence, diagnostics, and administration

These are current platform outcomes, even where they are not direct authoring
methods. Functional parity requires an explicit vNext owner; it does not require
retaining the current CSV/JSON filenames, in-memory projections, or admin wire
events.

| Current platform capability | Repository evidence | Required target expression | Owner or referenced contract |
| --- | --- | --- | --- |
| Save static/form responses, final game data, and per-episode game data | [static response CSV emission](../../../../mug/server/app.py#L1036-L1082), [final game-data emission](../../../../mug/server/app.py#L1109-L1145), [incremental episode emission and acknowledgement](../../../../mug/server/app.py#L1148-L1210) | Schema-bound append commands and immutable response/step/episode artifacts with activity-occurrence, interaction, actor/controller, study/deployment, and capture-rule lineage. Durable receipts distinguish accepted bytes from client attempts; exports are derived views rather than canonical storage filenames. | API-09, API-10, API-11, API-19 |
| Capture and compare peer-reported multiplayer hashes, actions, delivery, rollback, and desynchronization metrics | [per-player metrics and pending aggregation](../../../../mug/server/app.py#L1213-L1272), [frame/action/desync/rollback comparison output](../../../../mug/server/app.py#L1391-L1440) | Versioned peer-evidence records bind reporter, interaction, episode/frame domain, algorithm, coverage, and finality. Reconciliation classifies complete, partial, disputed, or quarantined evidence; it never treats a two-file comparison as authoritative merely because both arrived. | API-10, API-16 |
| Record match assignments, participant RTTs, and matchmaker identity for analysis and the live timeline | [`MatchAssignmentLogger` JSONL/admin outputs](../../../../mug/server/match_logger.py#L44-L140) | One durable assignment decision and exposure trail with candidate-set/rule version, accepted membership/order, relevant network evidence, and idempotent receipt. Scientific evidence is separate from the operational dashboard projection. | API-04, API-06, API-10, API-11 |
| Observe participant progress, waitrooms, active/completed games, connection health, terminations, aggregates, and problems in an authenticated admin dashboard | [admin aggregation state](../../../../mug/server/admin/aggregator.py#L110-L167), [session termination/history projection](../../../../mug/server/admin/aggregator.py#L207-L303), [authenticated state namespace](../../../../mug/server/admin/namespace.py#L39-L100) | Privacy-filtered operator read models derive from durable lifecycle/evidence facts and declare freshness/completeness. Operator mutations use ordinary idempotent domain commands; process-local caches, console logs, and dashboard projection state are never canonical scientific truth. | API-10, API-11, API-19 |
| Stream participant browser console diagnostics into the admin view and optionally persist them | [client console-log ingress](../../../../mug/server/app.py#L1275-L1299), [bounded diagnostic aggregation and persistence setup](../../../../mug/server/admin/aggregator.py#L86-L109) | A separately classified operational diagnostic stream has size/rate limits and redaction. Deployment-perimeter controls determine access, and the researcher-owned store determines storage lifecycle; diagnostics are not silently promoted to research evidence. | API-10, API-11 |

## Representative parity evidence

These studies demonstrate combinations the target authoring and compiler API
must eventually be able to express. They are repository evidence for future
acceptance outcomes, not legacy fixtures to execute in vNext and not features
demonstrated by the current minimal version-0 contract fixture.

| Scenario | Current example |
| --- | --- |
| One human and browser ONNX controller | [`slimevb_human_ai.py`](../../../../examples/slime_volleyball/slimevb_human_ai.py#L16-L25), [scene configuration](../../../../examples/slime_volleyball/slimevb_human_ai.py#L45-L89) |
| One human and deterministic Python heuristic | [`slimevb_human_heuristic.py`](../../../../examples/slime_volleyball/slimevb_human_heuristic.py#L25-L28), [scene configuration](../../../../examples/slime_volleyball/slimevb_human_heuristic.py#L49-L93) |
| Two humans in browser/P2P execution with matchmaking and rollback settings | [`slimevb_human_human.py`](../../../../examples/slime_volleyball/slimevb_human_human.py#L100-L156) |
| Two humans in a server-authoritative environment | [`overcooked_server_auth.py`](../../../../examples/cogrid/overcooked_server_auth.py#L65-L109) |
| Randomized condition selection inside a longer content/game/form flow | [`footsies_experiment.py`](../../../../examples/footsies/footsies_experiment.py#L14-L40) |
| External Unity client with adaptive researcher-defined behavior | [`footsies_scene.py`](../../../../examples/footsies/footsies_scene.py#L33-L114) |

The normative outcome inventory and ported-fixture requirement remain in
[Functional Parity](../../functional-parity.md#required-reference-fixtures).

## Compiler hazards exposed by the current implementation

The following behaviors must become validation errors, explicit versioned
semantics, or deliberately owned runtime policies. They must not survive as
hidden compiler behavior.

| Hazard | Exact current evidence | Compiler or publication requirement |
| --- | --- | --- |
| Browser metadata is derived from a broad object-attribute projection | Base scenes serialize `vars(self)` in [`Scene.scene_metadata`](../../../../mug/scenes/scene.py#L95-L107); Gym scenes include every non-underscore attribute in [`GymScene.scene_metadata`](../../../../mug/scenes/gym_scene.py#L238-L251). Both add a local timestamp. | Every field has one typed destination: client, private server, provenance, or non-manifest runtime state. Time-dependent runtime fields cannot affect a scientific digest. Apply allowlists, not deny-list filtering. |
| Unserializable values silently disappear | [`serialize_dict()`](../../../../mug/scenes/scene.py#L145-L181) filters values using `json.dumps`; a nested container containing one unsupported value can be dropped before recursion. | Unknown or unserializable scientific input is fatal and reported with a stable diagnostic code and source path. No meaningful field is silently omitted. |
| Validation depends on removable `assert` statements | Endpoint checks use assertions in [`Stager`](../../../../mug/scenes/stager.py#L28-L34); author settings do so throughout [`GymScene`](../../../../mug/scenes/gym_scene.py#L328-L333) and [`ExperimentConfig`](../../../../mug/configurations/experiment_config.py#L168-L200). | Validation is deterministic, structured, environment-independent, and identical under optimized Python. `validate()` returns all safe diagnostics; `compile()` fails on errors. |
| Unknown authoring input can be ignored | [`Scene.scene(..., **kwargs)`](../../../../mug/scenes/scene.py#L37-L51) accepts but does not process extra keywords. | Schemas and MUG-owned domain protocols are closed; every unknown field fails. |
| Mutable fluent objects and automatic inference make meaning depend on call order | Policy configuration mutates/decomposes mappings in [`GymScene.policies()`](../../../../mug/scenes/gym_scene.py#L421-L461); multiplayer is inferred in [`_auto_infer_multiplayer()`](../../../../mug/scenes/gym_scene.py#L508-L522) and again from runtime settings in [`runtime()`](../../../../mug/scenes/gym_scene.py#L800-L813). | Authoring definitions are immutable values. Compilation resolves defaults and derived values once, records them, and produces the same bytes regardless of harmless construction order. |
| Validation or requirement discovery can mutate randomization | [`get_pyodide_config()`](../../../../mug/configurations/experiment_config.py#L237-L243) calls `unpack()`; [`RandomizeOrder.unpack()`](../../../../mug/scenes/scene.py#L241-L247) shuffles the authored list. `build()` shuffles and truncates it again. | `validate()`, `compile()`, `diff()`, and requirement discovery are pure. Author-time flow traversal never samples participant randomization. |
| Recovery identifies progress only by a list index | [`Stager.get_state()` and `set_state()`](../../../../mug/scenes/stager.py#L99-L118) persist only `current_scene_index`, while randomization can rerun. | Materialize and commit the exact visit plan, assignment, order, repetitions, branches, parameters, study version, and occurrence IDs before exposure. Recovery loads that plan. See [ADR 0003](../../decisions/0003-immutable-study-versions-and-materialized-plans.md). |
| Repetition lacks occurrence identity and storage can overwrite | [`RepeatScene.build()`](../../../../mug/scenes/scene.py#L250-L265) multiplies the same definitions; form output is keyed only by experiment, scene, and participant in [`data_emission()`](../../../../mug/server/app.py#L1053-L1079). | Definition identity and runtime occurrence identity are distinct mandatory types. Each repetition receives a stable occurrence ID and each response has its own append/receipt identity. |
| Source and content files depend on the launch working directory and are not pinned | [`resolve_scene_body()`](../../../../mug/scenes/scene.py#L128-L142) and [`GymScene.runtime()`](../../../../mug/scenes/gym_scene.py#L773-L792) read paths directly; [`static_files()`](../../../../mug/configurations/experiment_config.py#L88-L103) resolves from the current process directory. | Build context resolves declared sources inside its captured roots, records bytes, media type, dependency metadata, and digest, then emits immutable artifact references. Publication cannot depend on later filesystem contents. |
| Dependency output is nondeterministic and weakly specified | [`get_pyodide_config()`](../../../../mug/configurations/experiment_config.py#L234-L248) converts an unordered set to a list; package strings are otherwise passed through. | Dependencies use a canonical sorted lock with exact artifact/version integrity and backend compatibility checks. Equivalent inputs compile to byte-identical manifests. |
| Browser models and arbitrary JavaScript are weakly packaged | [`ModelConfig`](../../../../mug/configurations/configuration_constants.py#L30-L168) uses plain `asdict()` and permits an inline custom JavaScript body; policy decomposition infers ONNX from a filename suffix in [`_validate_policy_configs()`](../../../../mug/scenes/gym_scene.py#L469-L506). | Models and custom controller implementations are typed, content-bound artifacts with declared schemas, runtime capabilities, dependency locks, and execution policy. File extensions are not type evidence. |
| Heuristic code is introspected and executed without an artifact contract | [`HeuristicPolicy.to_config()`](../../../../mug/configurations/configuration_constants.py#L220-L254) reads an entire module and identifies it by class name; [`load_from_config()`](../../../../mug/configurations/configuration_constants.py#L256-L276) calls `exec`. | Package a versioned ordinary study-code controller artifact with a collision-proof reference, digest, entry point, dependency lock, closed API-05/API-07/API-12 protocol declaration, and supported execution backends. |
| Forms encode semantics in DOM IDs and presentation indexes | Form fields generate IDs such as `scale-0` and `mc-0` in [`static_scene.py`](../../../../mug/scenes/static_scene.py#L449-L468) and [`MultipleChoice`](../../../../mug/scenes/static_scene.py#L679-L718); the browser scrapes those IDs in [`getData()`](../../../../mug/server/static/js/index.js#L1373-L1412). | Stable form, field, option, candidate, and presentation-assignment identities are schema fields independent of DOM structure and A/B position. Server validation uses the pinned form/protocol version. |
| Response acceptance has no idempotent durable receipt | The browser emits data while terminating a scene in [`index.js`](../../../../mug/server/static/js/index.js#L1359-L1368); the server overwrites a CSV in [`data_emission()`](../../../../mug/server/app.py#L1036-L1082). | A response command is schema-bound and idempotent. Response, canonical domain event, receipt, and at-most-once progression commit atomically; refresh/retry returns the original receipt. |
| Arbitrary client-authored global state is trusted without a declared schema | The browser submits `window.mugGlobals` in [`index.js`](../../../../mug/server/static/js/index.js#L1645-L1654), and [`sync_globals()`](../../../../mug/server/app.py#L453-L474) merges every supplied key into session state. | Study compilation resolves every participant-state namespace, schema, reader/writer capability, merge rule, privacy labels, persistence placement, and client-visible projection. Runtime commands validate the writer and schema. |
| Completion is generated during scene rebuilding | [`CompletionCodeScene.build()`](../../../../mug/scenes/static_scene.py#L194-L222) creates a new UUID as the scene is built. | Completion is a durable idempotent domain transition, not build-time randomness. Its claim, terminal action, and external handoff have stable receipts and scientific-event lineage. |
| Secret values can enter mutable configuration directly | TURN username and credential are ordinary fields in [`ExperimentConfig`](../../../../mug/configurations/experiment_config.py#L32-L35) and direct arguments to [`webrtc()`](../../../../mug/configurations/experiment_config.py#L105-L126). | Authoring and scientific manifests contain only typed logical `SecretRequirement`s. API-02 owns the deployment overlay containing `SecretRef` bindings. Compilation rejects secret bytes and deployment bindings in every scientific projection and never resolves a secret value. |
| There is no immutable compile or publication boundary | [`app.run()`](../../../../mug/server/app.py#L2882-L2886) assigns the mutable config and stager directly to module globals; participant/session/game state is process-global in [`app.py`](../../../../mug/server/app.py#L78-L125). | Runtime deployment accepts only a published `StudyVersionRef` plus an immutable `DeploymentRevisionRef`. Source edits in git cannot alter active visits or deployed manifest bytes; only publishing a new version changes what future visits run. |

These requirements implement the explicit manifest split in
[ADR 0007](../../decisions/0007-explicit-client-server-provenance-manifests.md):
unknown or unserializable scientific configuration fails compilation, secrets
remain references, and browser payloads contain only participant-safe data.

## API-01 requirements derived from the map

The detailed API-01 specification may choose different type names, but it must
cover these concepts without taking ownership from another domain:

1. **Typed study root.** `StudySpec` composes a stable study key, `FlowSpec`,
   domain-owned activity specifications or references, treatments, data
   policy, and an exact API-02-owned deployment-requirement object. API-01 owns
   the composition wrapper and cross-reference validation, not those objects'
   domain semantics.
2. **Closed flow algebra.** At minimum, the author can express sequence,
   activity reference, randomized selection/order, repetition, versioned
   conditional branch, and terminal behavior. Every node has a stable author
   key; author keys, definition IDs, and runtime occurrence IDs are distinct.
3. **Explicit build context.** Compilation receives declared source roots, an
   offline schema/artifact registry, compiler/build identity, and the closed
   supported-core-capability set. It does not receive or resolve secret bytes.
4. **Explicit compilation policy.** The policy controls warnings-as-errors,
   pinning requirements, executable-content policy, reproducibility checks,
   client-exposure scanning, and unsupported-capability handling. It cannot
   weaken shared-kernel security or archival invariants.
5. **Pure validation and compilation.** `validate`, `compile`, requirement
   discovery, and `diff` do not mutate input, sample randomization, contact live
   providers, or depend on runtime clocks. Defaults are resolved before
   canonicalization.
6. **Cross-domain validation.** The compiler checks reference existence,
   uniqueness, reachability, role/controller/environment compatibility,
   execution-mode capabilities, asset/dependency integrity, schema bindings,
   privacy placement, terminal paths, and recovery claims.
7. **Explicit scientific manifest and projections.** The scientific manifest
   binds the complete protocol and projection digests. The client manifest
   contains only participant-safe browser configuration; the private
   server-manifest template contains private runtime, treatment, provider,
   prompt, tool, ordinary study-code package, and logical secret-requirement
   configuration; the provenance manifest contains versions, digests, and only
   content permitted by capture rules and privacy classification.
8. **Immutable compiled candidate.** `CompiledStudyCandidate` binds the
   normalized resolved specification, exact schema references, scientific
   manifest and projections, artifact/dependency lock, compiler identity,
   capability requirements, and validation evidence. Publication binds that
   candidate to an immutable `StudyVersion`; a compilation result is not itself
   a publication occurrence.
9. **Scientific/deployment separation.** A study version pins scientific
   semantics and participant experience. A deployment revision pins builds,
   adapters, endpoints, region, and secret bindings. A visit pins both; neither
   may change silently.
10. **Safe publication.** Publication is an ungated operation inside the
    trusted self-hosted deployment and is idempotent for identical canonical
    content. It rejects identifier/digest conflicts, forbids proposal-only
    schema versions, and never mutates an existing version.
11. **Meaningful diff.** Study-version diff identifies changed normalized
    fields, artifacts, schemas, manifests, and capability requirements and
    distinguishes scientific changes from eligible deployment-only changes.
12. **Portable failure evidence.** Validation diagnostics have stable codes,
    paths, severity, safe details, and source provenance. Compilation never
    turns an unsupported feature into a silent default.

The initial catalog surface is recorded in
[API-01](../api-catalog.md#api-01-study-authoring-compiler-manifests-and-publication).
The north-star architectural boundary is described in
[Authoring and publication](../../north-star.md#authoring-and-publication).

## Parity gate for API-01

API-01 is not ready for acceptance until:

- every current capability in this map is linked to a target owner and an
  acceptance scenario, or explicitly removed by a product decision updating
  the functional-parity contract;
- ported studies express browser-local Gymnasium, mixed human/controller,
  rollback P2P, server-authoritative multiplayer, content/form/randomized flow,
  independent concurrent and sequential game instances, connection
  probe/re-pooling, Surface rendering, and external-client scenarios without
  legacy adapters;
- ported evidence/admin cases express response and episode capture, peer
  reconciliation, match-assignment lineage, lifecycle/history projections,
  operational diagnostics, and operator administration without treating
  process-local state or filenames as canonical truth;
- compile-twice fixtures produce byte-identical canonical manifests and digests;
- validation and requirement discovery leave authored values byte-for-byte
  unchanged and never sample visit randomization;
- golden client manifests pass schema validation and secret/private-field
  scanning;
- unknown fields, unsupported capabilities, unpinned executable content,
  unserializable scientific values, duplicate stable keys, missing references,
  and manifest-placement violations fail compilation;
- restart scenarios recover the already committed materialized visit plan rather
  than rebuilding authoring objects; and
- publication proves immutable content binding, identical-publication
  idempotency, conflicting-publication rejection, and separation from deployment
  revisions.

These gates validate functional outcomes through vNext APIs. They do not run old
experiment code.

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-20 | `0.2 correction` | Folded ADR 0015 into the parity target: re-homed privacy/secret mechanics to the shared kernel and API-02, evidence to API-10, and every environment/controller/renderer/callback capability to pinned ordinary study code implementing a closed MUG-owned typed protocol; removed the retired framework and governance ownership assumptions without changing the parity floor |
| 2026-07-18 | `0.2` | Aligned with the F-1/ADR 0013 git-native model: removed draft-mutation phrasing in favor of git-source/publish semantics; no capability-evidence changes |
| 2026-07-17 | `0.1` | Initial current-repository capability, ownership, and compiler-hazard map |
