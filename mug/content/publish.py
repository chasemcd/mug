"""Compile the study a participant runs, and publish it.

There were two study surfaces and they never met. A researcher writes
``Study(Form(...), Game(...), Comparison(...))`` and ``build_study_app`` runs that
object directly. Beside it sat the whole API-01 pipeline -- an ``AuthoringDocument``
compiled into a ``ValidationReport`` and a ``ManifestSet``, gated by
``publication_refusal``, published by ``publish_study``, reachable from
``mug publish`` -- with nothing to compile. So nothing pinned what actually ran: the
launch gate minted a ``StudyVersionRef`` whose manifest digest was a literal stub,
and ``mug export`` could not export a study the application had run, because
``discover_study_version`` found no published version in the store.

This module is the missing half. It reads one ``Study`` and produces, in order:

1. the **authoring document** -- the study normalized into the frozen authored
   shape: a flow of nodes, one definition per activity, and the compilation policy;
2. the **validation report** -- every diagnostic the compiler can honestly raise
   over that document, and whether it may publish at all;
3. the four **manifests** -- scientific (the canonical study and the digests of its
   projections), client (what a participant's browser needs, with no internal
   identifier in it), server (what the runtime binds), and provenance (the source,
   the compiler, and every transformation) -- each staged as its own artifact;
4. the **compiled candidate**, content-bound by a fingerprint over its inputs;
5. the **published version**, through the real ``publish_study`` handler.

Two properties make it usable rather than ceremonial. **Every digest is real**: each
manifest is staged, and the digest a record carries is the digest of the bytes that
were staged, so a reader re-derives it. And **publishing is idempotent**: the study
identifier, the version identifier, and every artifact address derive from the
digest of the normalized study, so a restart republishes to the same version and a
changed study publishes a new one. That is what lets ``build_study_app`` publish on
every start.

What this compiler does *not* do is what a full one would: it packages no code, it
resolves no external asset, and it declares no secret requirement, because the
authored ``Study`` states none of those. Each is a field on the frozen document that
stays empty and honest rather than being filled with a plausible value.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from mug.authoring import (
    AuthoringDocument,
    CapabilityRequirement,
    ClientManifest,
    CompiledStudyCandidate,
    GitProvenance,
    ManifestArtifact,
    ProvenanceManifest,
    ScientificManifest,
    StudyServerManifest,
    ValidationReport,
    authoring_schema,
)
from mug.authoring.service import PublishStudyCommand, publish_study
from mug.authoring.types import (
    ActivityNode,
    AuthoredDefinition,
    ClientComponentBinding,
    ClientProjectionArtifact,
    CompilationInputs,
    CompilationPolicy,
    CompilerIdentity,
    Diagnostic,
    DiagnosticCounts,
    FlowNode,
    FlowSpec,
    ManifestSet,
    ProjectionDigestRef,
    ProvenanceProjectionRecord,
    SequenceNode,
    ServerRuntimeBinding,
    ServerRuntimeScope,
    TerminalNode,
    TransformationRecord,
)
from mug.content.assets import resource_slots
from mug.content.components import component_for, profile_floor
from mug.content.plan import declared_treatments, sites, treatments_at
from mug.content.study import Activity, Study
from mug.kernel import (
    ArtifactRef,
    CommandReceipt,
    DataHandlingRef,
    Digest,
    ResourceRef,
    SchemaRef,
    TypedObject,
    compute_digest,
)
from mug.kernel.refs import StudyVersionRef
from mug.runtime import CommandContext
from mug.storage import ArtifactStore, Store, json_bytes, stage_artifact
from mug.visits.assignment import stratifying_field
from mug.visits.design import Scope, Treatment
from mug.visits.eligibility import rule_name

# What this compiler is. The artifact digest names the compiler's own build; there
# is one compiler in one repository, so it is the digest of its identity rather
# than of a separately packaged binary.
COMPILER_NAME = "mug-study-compiler"
COMPILER_VERSION = "0.1.0"
_NORMALIZATION_PROFILE = "mug-normalization-v0"

# The one client audience this platform ships: the participant's own browser.
_CLIENT_PROJECTION = "participant-default"
_CLIENT_BUILD_SLOT = "participant-shell"

# The capability each activity kind needs of a client. These are the platform's own
# capability names, and they are what a client build must satisfy to run the study.
_ACTIVITY_CAPABILITY = {
    "form": "mug.activity.form.v1",
    "content": "mug.activity.content.v1",
    "game": "mug.activity.game.v1",
    "comparison": "mug.activity.comparison.v1",
}

_JSON = "application/json"
_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_SENSITIVE = DataHandlingRef(privacy_labels=["research", "sensitive"])

# The identifier roles. Each derives from the digest of the normalized study, so one
# study always publishes to one version and a changed study to a new one.
_STUDY_ROLE = "study"
_VERSION_ROLE = "studyver"


@dataclass(frozen=True)
class PublishedStudy:
    """What one compile-and-publish produced, for the application to run."""

    study_version: StudyVersionRef
    candidate: CompiledStudyCandidate
    report: ValidationReport
    receipt: CommandReceipt | None = None
    already_published: bool = False

    @property
    def published(self) -> bool:
        """Whether this study is published at this version.

        True when this call published it, and true when an earlier one already had:
        publishing derives its version from the study, so a second publication of an
        unchanged study is a no-op rather than a failure.
        """
        if self.already_published:
            return True
        return self.receipt is not None and self.receipt.outcome == "accepted"


# --- normalizing the study ----------------------------------------------------


def _schema(name: str) -> SchemaRef:
    """Return the pinned reference to one authoring document's frozen schema."""
    return SchemaRef(
        name=name,
        version=0,
        digest=Digest(algorithm="sha-256", hex=authoring_schema().bundle_digest),
    )


def normalized_study(study: Study) -> dict[str, Any]:
    """Return the canonical, id-free description of one study.

    This is what the study *is*, with nothing minted in it: the ordered activities,
    their kinds, and the content each one presents. Every identifier the compiler
    goes on to derive derives from the digest of this, so two runs of one study give
    one study version and an edited study gives another.
    """
    return {
        "activities": [
            {
                "key": activity.key,
                "kind": activity.kind,
                "form": _dump(activity.form),
                "content": _dump(activity.content),
                "content_levels": _content_levels(study, activity),
                "comparison": _comparison_of(study, activity),
                "treatments": _treatments_at(study, activity),
            }
            for activity in study.activities
        ],
        "design": _design_of(study),
        "screen": _screen_of(study),
        "assets": _assets_of(study),
    }


def _assets_of(study: Study) -> list[dict[str, Any]]:
    """Describe the pictures a study declares, in the order it declared them.

    The path is part of it: a study that redraws its sprite sheet is a different
    study, and a version that ignored the file would claim otherwise. The bytes
    themselves are addressed by digest at deployment; what the version binds is
    what was declared.
    """
    return [
        {
            "name": asset.name,
            "path": asset.path,
            "media_type": asset.resolved_media_type(),
            "frames": [frame.as_json() for frame in asset.frames],
        }
        for asset in study.assets
    ]


def _screen_of(study: Study) -> dict[str, Any] | None:
    """Describe the connection a study screens on, and the rule it admits by.

    A study that turns participants away is not the same study as one that keeps
    everybody, so the screen is part of what the version is. The rule is named, not
    inlined: what it does lives in the study's own repository, and the version binds
    the name that was declared.
    """
    if study.screen is None and study.admit is None:
        return None
    return {
        "policy": (
            None
            if study.screen is None
            else study.screen.policy().model_dump(mode="json", exclude_none=True)
        ),
        "at_entry": None if study.screen is None else study.screen.at_entry,
        "admit": None if study.admit is None else rule_name(study.admit),
    }


def _content_levels(study: Study, activity: Activity) -> dict[str, Any] | None:
    """Describe every page one placed content activity may show.

    A page whose text depends on the condition has no single body, so the version
    covers all of them. Leaving them out would give two studies that read
    differently to every participant one identical version.
    """
    placement = study.contents.get(activity.key)
    if placement is None:
        return None
    return {
        level: _dump(placement.value_for(level))
        for level in placement.treatment.level_keys
    }


def _treatments_at(study: Study, activity: Activity) -> list[dict[str, Any]]:
    """Describe the factors that take effect at one activity.

    A study that manipulates something is not the same study as one that does not,
    even when the activities read the same, so the declaration is part of what the
    version is. Two studies whose only difference is a level are two versions.
    """
    return [
        _dump(treatment.spec()) for treatment in treatments_at(study, activity.key)
    ]


def _design_of(study: Study) -> dict[str, Any] | None:
    """Describe the crossing a study asks to be balanced jointly, if it has one."""
    if study.design is None:
        return None
    return {
        "cross": sorted(one.key for one in study.design.cross),
        "assign": study.design.assign.model_dump(mode="json", exclude_none=True),
    }


def _dump(record: Any) -> Any:
    """Dump one optional frozen record to its canonical form, or None."""
    return None if record is None else record.model_dump(mode="json", exclude_none=True)


def _comparison_of(study: Study, activity: Activity) -> dict[str, Any] | None:
    """Describe one comparison step in the canonical, author-facing terms."""
    if activity.kind != "comparison":
        return None
    comparison = study.comparison(activity.key)
    return {
        "ask": comparison.ask,
        "of": comparison.of,
        "style": comparison.style,
        "blind": comparison.blind,
        "shuffle": comparison.shuffle,
        "options": {label: str(run) for label, run in comparison.options.items()},
    }


def study_digest(study: Study) -> Digest:
    """Return the digest of the normalized study: this study's whole identity."""
    return compute_digest(normalized_study(study))


def authoring_document(
    study: Study, *, study_id: str, derive: Callable[[str, str], str], title: str
) -> AuthoringDocument:
    """Normalize one study into the frozen authored document.

    Every node and definition identifier derives from the activity key, so the
    document is a pure function of the study: compiling twice gives identical bytes,
    which is what the reproducibility check in the compilation policy asks for.
    """
    def definition_id(key: str) -> str:
        return derive("activitydef", f"activity:{key}")

    definitions = [
        AuthoredDefinition(
            kind="activity",
            key=activity.key,
            definition=ResourceRef(id=definition_id(activity.key)),
            spec=TypedObject(
                schema=_schema("mug.study.authoring-document"),
                data={"kind": activity.kind, "activity_key": activity.key},
            ),
        )
        for activity in study.activities
    ]
    nodes: list[FlowNode] = [
        ActivityNode(
            node_id=derive("flownode", f"activity:{activity.key}"),
            key=activity.key,
            kind="activity",
            activity_definition_id=definition_id(activity.key),
        )
        for activity in study.activities
    ]
    terminal = TerminalNode(
        node_id=derive("flownode", "terminal"),
        key="finish",
        kind="terminal",
        terminal=TypedObject(
            schema=_schema("mug.study.authoring-document"),
            data={"outcome": "complete"},
        ),
    )
    entry = SequenceNode(
        node_id=derive("flownode", "entry"),
        key="flow",
        kind="sequence",
        children=[node.node_id for node in nodes] + [terminal.node_id],
    )
    return AuthoringDocument(
        study_id=study_id,
        title=title,
        flow=FlowSpec(
            entry_node_id=entry.node_id, nodes=[entry, *nodes, terminal]
        ),
        definitions=definitions,
        secret_requirements=[],
        code_packages=[],
        data_flows=[
            TypedObject(
                schema=_schema("mug.study.authoring-document"),
                data={
                    "source": "participant-browser",
                    "destination": "study-service",
                    "purpose": "activity-progress",
                },
            )
        ],
        deployment_requirements=TypedObject(
            schema=_schema("mug.study.authoring-document"),
            data={"required_capabilities": _capabilities(study)},
        ),
        compilation_policy=CompilationPolicy(
            unknown_fields="reject",
            warnings="explicit_acknowledgment",
            executable_content="packaged_only",
            hermetic_build="required",
            reproducibility_check="required",
            client_disclosure_check="required",
        ),
        data_handling=_SENSITIVE,
    )


def _capabilities(study: Study) -> list[str]:
    """Return the capability every client must have to run this study, in order."""
    seen = {_ACTIVITY_CAPABILITY[activity.kind] for activity in study.activities}
    return sorted(seen)


# --- validating it ------------------------------------------------------------


def diagnose(study: Study) -> list[Diagnostic]:
    """Return every problem the compiler can honestly find in one study.

    These are the mistakes the runtime cannot save a study from, so the compiler
    refuses to publish them instead -- which is where a mistake like this should
    surface, not in the data six weeks later.
    """
    found: list[Diagnostic] = []
    keys = {activity.key for activity in study.activities}
    for activity in study.activities:
        if activity.kind != "comparison":
            continue
        comparison = study.comparison(activity.key)
        if comparison.of != "trajectory":
            continue
        for label, run in comparison.options.items():
            if isinstance(run, str) and run not in keys:
                found.append(
                    _diagnostic(
                        "study.comparison.unknown_activity",
                        "error",
                        f"the comparison {activity.key!r} option {label!r} names "
                        f"{run!r}, which this study does not play",
                    )
                )
    return [*found, *_design_diagnostics(study)]


def _design_diagnostics(study: Study) -> list[Diagnostic]:
    """Return every problem in what a study manipulates.

    Each one is a study that would run and produce data nobody can analyse: a
    factor stratified on an answer the participant gives afterwards, a crossing over
    a factor that is placed nowhere, and a group condition with no group to share it.
    """
    found: list[Diagnostic] = []
    declared = declared_treatments(study)
    ordinals = {activity.key: index for index, activity in enumerate(study.activities)}
    placed_keys = {one.key for one in declared}

    for treatment in declared:
        field = stratifying_field((treatment,))
        if field is not None:
            found.extend(_stratum_diagnostics(study, treatment, field, ordinals))
        if treatment.scope == Scope.GROUP:
            found.append(
                _diagnostic(
                    "study.treatment.group_scope_without_a_group",
                    "error",
                    f"the treatment {treatment.key!r} is group scoped, and this "
                    "platform forms no groups yet, so nothing would share it",
                )
            )

    if study.design is not None:
        for treatment in study.design.cross:
            if treatment.key not in placed_keys or not any(
                treatment is one for one in declared
            ):
                found.append(
                    _diagnostic(
                        "study.design.unplaced_factor",
                        "error",
                        f"the design crosses {treatment.key!r}, which this study "
                        "places nowhere, so it manipulates nothing",
                    )
                )
    return found


def _stratum_diagnostics(
    study: Study,
    treatment: Treatment,
    field: tuple[str, str],
    ordinals: Mapping[str, int],
) -> list[Diagnostic]:
    """Return why one stratified factor could never be assigned in time."""
    activity_key, field_key = field
    if activity_key not in ordinals:
        return [
            _diagnostic(
                "study.treatment.stratifies_on_an_unknown_activity",
                "error",
                f"the treatment {treatment.key!r} stratifies on {activity_key!r}, "
                "which this study does not ask",
            )
        ]
    form = study.activity(activity_key).form
    if form is None or not any(one.field_key == field_key for one in form.fields):
        return [
            _diagnostic(
                "study.treatment.stratifies_on_an_unknown_field",
                "error",
                f"the treatment {treatment.key!r} stratifies on "
                f"{activity_key}.{field_key}, which that activity does not ask",
            )
        ]
    asked = ordinals[activity_key]
    for site_key, placement in sites(study):
        if placement.treatment is treatment and ordinals[site_key] <= asked:
            return [
                _diagnostic(
                    "study.treatment.stratifies_on_a_later_answer",
                    "error",
                    f"the treatment {treatment.key!r} takes effect at {site_key!r} "
                    f"before {activity_key!r} is answered, so it could not be "
                    "stratified in time",
                )
            ]
    return []


def _diagnostic(code: str, severity: str, message: str) -> Diagnostic:
    """Build one diagnostic, fingerprinted by what it says."""
    return Diagnostic(
        fingerprint=compute_digest({"code": code, "message": message}),
        code=code,
        severity=cast("Any", severity),
        stage="flow",
        safe_message=message,
        suppressible=False,
    )


def validation_report(
    study: Study, *, fingerprint: Digest, compiler: CompilerIdentity
) -> ValidationReport:
    """Return the complete verdict of compiling one study."""
    diagnostics = diagnose(study)
    errors = sum(1 for one in diagnostics if one.severity == "error")
    warnings = sum(1 for one in diagnostics if one.severity == "warning")
    return ValidationReport(
        input_fingerprint=fingerprint,
        valid=errors == 0,
        diagnostics=diagnostics,
        counts=DiagnosticCounts(
            error=errors, warning=warnings, info=len(diagnostics) - errors - warnings
        ),
        compiler=compiler,
    )


def compiler_identity() -> CompilerIdentity:
    """Return this compiler's own identity, pinned to the frozen contract."""
    return CompilerIdentity(
        name=COMPILER_NAME,
        version=COMPILER_VERSION,
        artifact_digest=compute_digest(
            {"name": COMPILER_NAME, "version": COMPILER_VERSION}
        ),
        contract=_schema("mug.study.compiler-contract"),
        normalization_profile=_NORMALIZATION_PROFILE,
    )


# --- the projections ----------------------------------------------------------


def client_manifest(study: Study) -> ClientManifest:
    """Return what a participant's client needs, with no internal identifier in it.

    The frozen record refuses any internal id, which is the disclosure check the
    compilation policy requires: what reaches a browser names activity keys and
    capabilities, never a definition, a node, or a version.

    The manifest's accessibility profile is the **floor** of the screens the study
    uses, not the best of them (``mug.content.components``): a study with a game
    canvas is a ``wcag-a`` study however accessible its consent form is, because a
    participant who cannot use the game cannot finish the study.
    """
    capabilities = _capabilities(study)
    return ClientManifest(
        protocol_requirements=["mug.transport.realtime.v1"],
        required_capabilities=capabilities,
        client_build_slot=_CLIENT_BUILD_SLOT,
        components=[
            ClientComponentBinding(
                slot=f"{activity.key}-panel",
                activation_slot=activity.key,
                component_schema=component_for(
                    _component_kind(study, activity)
                ).component_schema,
                config=TypedObject(
                    schema=_schema("mug.study.client-manifest"),
                    data={
                        "kind": activity.kind,
                        "accessibility_profile": component_for(
                            _component_kind(study, activity)
                        ).accessibility_profile,
                    },
                ),
            )
            for activity in study.activities
        ],
        # What a client must load before it can draw: one slot per declared asset,
        # activated by the first activity that could draw it.
        resource_slots=resource_slots(
            study.assets, activation_slot=_activation_slot(study)
        ),
        accessibility_profile=profile_floor(
            [_component_kind(study, activity) for activity in study.activities]
        ),
        locales=["en"],
    )


def _component_kind(study: Study, activity: Activity) -> str:
    """Return the shipped screen one activity is rendered by.

    It is the activity's kind, except for a game the study gave a conversation:
    that is one screen of two panes with its own keyboard rule, so it declares its
    own component rather than borrowing the plain game's.
    """
    if activity.kind == "game" and activity.key in study.chats:
        return "game-chat"
    return activity.kind


def _activation_slot(study: Study) -> str:
    """Return the activity a declared asset must be loaded before.

    A picture is drawn by an environment, so the study's first game activity is
    what activates it. A study with assets and no game activates them at its first
    activity, which is the earliest honest answer.
    """
    keys = study.game_keys
    return keys[0] if keys else study.activities[0].key


def server_manifest(study: Study) -> StudyServerManifest:
    """Return what the server runtime binds for this study, scoped per activity."""
    scopes = [
        ServerRuntimeScope(
            scope_key=f"{activity.key}-runtime",
            selector=TypedObject(
                schema=_schema("mug.study.server-manifest"),
                data={"activity_key": activity.key},
            ),
        )
        for activity in study.activities
    ]
    bindings: list[ServerRuntimeBinding] = [
        cast(
            "ServerRuntimeBinding",
            {
                "binding_key": f"{activity.key}-config",
                "scope_key": f"{activity.key}-runtime",
                "kind": "domain_config",
                "value": TypedObject(
                    schema=_schema("mug.study.server-manifest"),
                    data={"activity_key": activity.key, "kind": activity.kind},
                ).model_dump(mode="json"),
            },
        )
        for activity in study.activities
    ]
    return StudyServerManifest(
        execution_requirements=_capabilities(study),
        scopes=scopes,
        bindings=bindings,
        data_handling=_RESEARCH,
    )


def scientific_manifest(
    study: Study,
    *,
    study_id: str,
    source: ArtifactRef,
    schema_bundle: ArtifactRef,
    compiler: CompilerIdentity,
    client: ProjectionDigestRef,
    server: ProjectionDigestRef,
    provenance: ProjectionDigestRef,
) -> ScientificManifest:
    """Return the canonical study and the digests of its three projections."""
    return ScientificManifest(
        study_id=study_id,
        source_digest=source.digest,
        normalized_study=ManifestArtifact(
            manifest_schema=_schema("mug.study.authoring-document"),
            content_digest=source.digest,
            artifact=source,
        ),
        deployment_requirements=TypedObject(
            schema=_schema("mug.study.scientific-manifest"),
            data={"required_capabilities": _capabilities(study)},
        ),
        capability_closure=_closure(study),
        compiler=compiler,
        schema_bundle=schema_bundle,
        projections={  # pyright: ignore[reportArgumentType]
            "clients": [
                {
                    "projection_key": _CLIENT_PROJECTION,
                    "selector": TypedObject(
                        schema=_schema("mug.study.scientific-manifest"),
                        data={"audience_class": _CLIENT_PROJECTION},
                    ).model_dump(mode="json"),
                    "manifest": client.model_dump(mode="json"),
                }
            ],
            "server": server.model_dump(mode="json"),
            "provenance": provenance.model_dump(mode="json"),
        },
        data_handling=_RESEARCH,
    )


def _closure(study: Study) -> Any:
    """Return the capability closure: every capability the study requires."""
    return {
        "requirements": [
            CapabilityRequirement(
                capability=capability, criticality="required"
            ).model_dump(mode="json", exclude_none=True)
            for capability in _capabilities(study)
        ]
    }


def provenance_manifest(
    *,
    compiler: CompilerIdentity,
    git: GitProvenance,
    source: ArtifactRef,
    schema_bundle: ArtifactRef,
    transformations: Sequence[TransformationRecord],
    client: ProjectionDigestRef,
    server: ProjectionDigestRef,
    limitations: Sequence[str] = (),
) -> ProvenanceManifest:
    """Return the build provenance: the source, the compiler, and every step.

    The frozen record names the client and server projections; the scientific
    manifest is not one of its roles, because the scientific manifest is what names
    *them*. Two projection outputs is the contract's own floor.
    """
    return ProvenanceManifest(
        compiler=compiler,
        source_git=git,
        source_artifacts=[source],
        dependency_artifacts=[],
        schema_bundle=schema_bundle,
        transformations=list(transformations),
        projection_outputs=[
            ProvenanceProjectionRecord(
                role="client",
                projection_key=_CLIENT_PROJECTION,
                projection=client,
                data_handling=DataHandlingRef(privacy_labels=["public"]),
                retention_disposition="retained",
            ),
            ProvenanceProjectionRecord(
                role="server",
                projection=server,
                data_handling=_RESEARCH,
                retention_disposition="retained",
            ),
        ],
        limitations=list(limitations),
        data_handling=_RESEARCH,
    )


# --- compiling and publishing -------------------------------------------------


async def compile_study(
    study: Study,
    *,
    artifacts: ArtifactStore,
    derive: Callable[[str, str], str],
    new_artifact_id: Callable[[str], str],
    new_upload_id: Callable[[], str],
    now: Callable[[], str],
    git: GitProvenance,
    limitations: Sequence[str] = (),
    title: str = "A MUG study",
) -> tuple[CompiledStudyCandidate, ValidationReport, ManifestSet, ArtifactRef]:
    """Compile one study into its candidate, report, manifests, and source artifact.

    Every artifact address derives from the digest of the normalized study and the
    role it plays, so compiling the same study twice writes identical bytes to
    identical addresses and the candidate's fingerprint is unchanged. That is the
    reproducibility check the compilation policy requires, held by construction
    rather than asserted afterwards.
    """
    identity = study_digest(study)
    study_id = derive(_STUDY_ROLE, f"study:{identity.hex}")
    compiler = compiler_identity()
    document = authoring_document(
        study, study_id=study_id, derive=derive, title=title
    )
    source = await _stage(
        artifacts,
        document.model_dump(mode="json", exclude_none=True),
        role="authoring-document",
        identity=identity,
        schema=_schema("mug.study.authoring-document"),
        handling=_SENSITIVE,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
    )
    report = validation_report(
        study, fingerprint=source.digest, compiler=compiler
    )
    report_artifact = await _stage(
        artifacts,
        report.model_dump(mode="json", exclude_none=True),
        role="validation-report",
        identity=identity,
        schema=_schema("mug.study.validation-report"),
        handling=_RESEARCH,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
    )
    bundle = await _stage(
        artifacts,
        {"bundle_digest": authoring_schema().bundle_digest},
        role="schema-bundle",
        identity=identity,
        schema=None,
        handling=_RESEARCH,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
    )

    client = client_manifest(study)
    client_artifact = await _stage(
        artifacts,
        client.model_dump(mode="json", exclude_none=True),
        role="client-manifest",
        identity=identity,
        schema=_schema("mug.study.client-manifest"),
        handling=DataHandlingRef(privacy_labels=["public"]),
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
    )
    server = server_manifest(study)
    server_artifact = await _stage(
        artifacts,
        server.model_dump(mode="json", exclude_none=True),
        role="server-manifest",
        identity=identity,
        schema=_schema("mug.study.server-manifest"),
        handling=_RESEARCH,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
    )
    client_ref = _projection("mug.study.client-manifest", client_artifact)
    server_ref = _projection("mug.study.server-manifest", server_artifact)

    scientific = scientific_manifest(
        study,
        study_id=study_id,
        source=source,
        schema_bundle=bundle,
        compiler=compiler,
        client=client_ref,
        server=server_ref,
        provenance=_projection("mug.study.provenance-manifest", source),
    )
    provenance = provenance_manifest(
        compiler=compiler,
        git=git,
        source=source,
        schema_bundle=bundle,
        transformations=[
            TransformationRecord(
                name="mug.study.normalize",
                version=COMPILER_VERSION,
                input_digest=identity,
                output_digest=source.digest,
            )
        ],
        client=client_ref,
        server=server_ref,
        limitations=limitations,
    )
    provenance_artifact = await _stage(
        artifacts,
        provenance.model_dump(mode="json", exclude_none=True),
        role="provenance-manifest",
        identity=identity,
        schema=_schema("mug.study.provenance-manifest"),
        handling=_RESEARCH,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
    )
    # The scientific manifest names the provenance projection, so it is assembled
    # once the provenance manifest exists and its digest is known.
    scientific = scientific_manifest(
        study,
        study_id=study_id,
        source=source,
        schema_bundle=bundle,
        compiler=compiler,
        client=client_ref,
        server=server_ref,
        provenance=_projection(
            "mug.study.provenance-manifest", provenance_artifact
        ),
    )
    scientific_artifact = await _stage(
        artifacts,
        scientific.model_dump(mode="json", exclude_none=True),
        role="scientific-manifest",
        identity=identity,
        schema=_schema("mug.study.scientific-manifest"),
        handling=_RESEARCH,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
    )
    manifests = ManifestSet(
        scientific=_manifest_artifact(
            "mug.study.scientific-manifest", scientific_artifact
        ),
        clients=[
            ClientProjectionArtifact(
                projection_key=_CLIENT_PROJECTION,
                selector=TypedObject(
                    schema=_schema("mug.study.manifest-set"),
                    data={"audience_class": _CLIENT_PROJECTION},
                ),
                manifest=_manifest_artifact(
                    "mug.study.client-manifest", client_artifact
                ),
            )
        ],
        server=_manifest_artifact("mug.study.server-manifest", server_artifact),
        provenance=_manifest_artifact(
            "mug.study.provenance-manifest", provenance_artifact
        ),
        schema_bundle=bundle,
        validation_report=report_artifact,
    )
    manifest_artifact = await _stage(
        artifacts,
        manifests.model_dump(mode="json", exclude_none=True),
        role="manifest-set",
        identity=identity,
        schema=_schema("mug.study.manifest-set"),
        handling=_RESEARCH,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
    )
    inputs = CompilationInputs(
        git_provenance=git,
        source=source,
        compiler=compiler,
        schema_registry_digest=bundle.digest,
        build_context_digest=identity,
        target_platform_contract=_schema("mug.study.compiler-contract"),
        compilation_policy=document.compilation_policy,
    )
    candidate = CompiledStudyCandidate(
        input_fingerprint=compute_digest(
            inputs.model_dump(mode="json", exclude_none=True)
        ),
        inputs=inputs,
        manifest_set=_manifest_artifact("mug.study.manifest-set", manifest_artifact),
        validation_report=report_artifact,
        scientific_manifest_digest=scientific_artifact.digest,
        release_eligibility=(
            "release_candidate" if report.valid else "design_unpublishable"
        ),
    )
    return candidate, report, manifests, source


async def compile_and_publish(
    study: Study,
    *,
    store: Store,
    artifacts: ArtifactStore,
    derive: Callable[[str, str], str],
    new_context: Callable[[str], CommandContext],
    new_artifact_id: Callable[[str], str],
    new_upload_id: Callable[[], str],
    now: Callable[[], str],
    git: GitProvenance,
    limitations: Sequence[str] = (),
    title: str = "A MUG study",
) -> PublishedStudy:
    """Compile one study and publish it, or report why it did not publish.

    The version identifier derives from the study, so publishing twice replays the
    first publication rather than opening a second version, and an edited study
    publishes a new one. A study whose validation found an error is compiled and
    reported and **not** published -- the candidate is not a release candidate and
    the real publication gate refuses it.
    """
    candidate, report, manifests, source = await compile_study(
        study,
        artifacts=artifacts,
        derive=derive,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
        git=git,
        limitations=limitations,
        title=title,
    )
    identity = study_digest(study)
    study_id = derive(_STUDY_ROLE, f"study:{identity.hex}")
    version_id = derive(_VERSION_ROLE, f"studyver:{identity.hex}")
    study_version = StudyVersionRef(
        study_id=study_id,
        study_version_id=version_id,
        version_number=1,
        manifest_digest=candidate.scientific_manifest_digest,
    )
    if not report.valid:
        return PublishedStudy(
            study_version=study_version, candidate=candidate, report=report
        )
    if store.load_aggregate(version_id) is not None:
        # This study is already published at this version. Publishing is idempotent
        # by derivation, so the first publication stands and this one is a no-op --
        # which is what lets a deployment publish on every start and a researcher
        # publish the same study from the command line without a conflict.
        return PublishedStudy(
            study_version=study_version,
            candidate=candidate,
            report=report,
            already_published=True,
        )
    receipt = await publish_study(
        PublishStudyCommand(
            study_id=study_id,
            version_number=1,
            version_string=f"0.0.0+{identity.hex[:12]}",
            candidate=candidate,
            candidate_artifact=source,
            git_provenance=git,
            scientific=manifests.scientific,
            clients=list(manifests.clients),
            server=manifests.server,
            provenance=manifests.provenance,
            warning_acknowledgments=[],
        ),
        context=new_context(version_id),
        store=store,
    )
    return PublishedStudy(
        study_version=study_version,
        candidate=candidate,
        report=report,
        receipt=receipt,
    )


def _projection(schema_name: str, artifact: ArtifactRef) -> ProjectionDigestRef:
    """Name one staged projection by its schema, its digest, and its size."""
    return ProjectionDigestRef(
        manifest_schema=_schema(schema_name),
        content_digest=artifact.digest,
        size_bytes=artifact.size_bytes,
    )


def _manifest_artifact(schema_name: str, artifact: ArtifactRef) -> ManifestArtifact:
    """Name one staged manifest by its schema, its digest, and the artifact itself."""
    return ManifestArtifact(
        manifest_schema=_schema(schema_name),
        content_digest=artifact.digest,
        artifact=artifact,
    )


async def _stage(
    artifacts: ArtifactStore,
    body: Any,
    *,
    role: str,
    identity: Digest,
    schema: SchemaRef | None,
    handling: DataHandlingRef,
    new_artifact_id: Callable[[str], str],
    new_upload_id: Callable[[], str],
    now: Callable[[], str],
) -> ArtifactRef:
    """Stage one compiled document at the address its study and role always give."""
    artifact_id = new_artifact_id(f"study:{role}:{identity.hex}")
    reference = await stage_artifact(
        artifacts,
        data=json_bytes(body) + b"\n",
        media_type=_JSON,
        new_artifact_id=lambda: artifact_id,
        new_upload_id=new_upload_id,
        now=now,
        data_handling=handling,
    )
    if schema is None:
        return reference
    return reference.model_copy(update={"content_schema": schema})


__all__ = [
    "COMPILER_NAME",
    "COMPILER_VERSION",
    "PublishedStudy",
    "authoring_document",
    "client_manifest",
    "compile_and_publish",
    "compile_study",
    "compiler_identity",
    "diagnose",
    "normalized_study",
    "provenance_manifest",
    "scientific_manifest",
    "server_manifest",
    "study_digest",
    "validation_report",
]
