"""The authoring command service: the publish handler.

``publish_study`` gates a compiled candidate, mints an immutable study version,
assembles the ``PublishedStudyVersion``, and hands the state and its result to the
runtime spine, which appends the event and commits. It answers with the durable
commit-class receipt, or a rejected receipt when the candidate does not publish.

The command carries the domain input. The runtime ``CommandContext`` carries the
authority a verified gateway derived: the minted identifiers, the principal, the
target stream, the producer position, and the wall-clock instant.
"""

from __future__ import annotations

from mug.authoring.publication import publication_refusal
from mug.authoring.types import (
    ClientProjectionArtifact,
    CompiledStudyCandidate,
    DiagnosticAcknowledgment,
    GitProvenance,
    ManifestArtifact,
    PublishedStudyVersion,
    StudyPublicationResult,
    VersionString,
    authoring_schema,
)
from mug.kernel import (
    ArtifactRef,
    CommandReceipt,
    CommandTypeRef,
    Digest,
    ResourceRef,
    SchemaRef,
    TypedObject,
    compute_digest,
)
from mug.kernel._base import KernelModel
from mug.kernel.errors import ErrorCategory
from mug.kernel.refs import PositiveSafeInteger, StudyVersionRef
from mug.runtime import CommandContext, commit_command, reject_command
from mug.storage import Store

_PUBLISH_COMMAND = CommandTypeRef(name="study.publish", version=0)
_RESULT_SCHEMA_NAME = "mug.api-01.study-publication-result"

# A gate refusal maps to a stable error code, a category, and a safe message.
_REFUSAL: dict[str, tuple[str, ErrorCategory, str]] = {
    "candidate_unpublishable": (
        "command.state_conflict",
        "conflict",
        "the study candidate is not a release candidate",
    ),
    "acknowledgment_mismatch": (
        "schema.validation_failed",
        "validation",
        "an acknowledgment does not bind to this candidate",
    ),
}


class PublishStudyCommand(KernelModel):
    """The domain input to publish one compiled study candidate."""

    study_id: str
    version_number: PositiveSafeInteger
    version_string: VersionString
    candidate: CompiledStudyCandidate
    candidate_artifact: ArtifactRef
    git_provenance: GitProvenance
    scientific: ManifestArtifact
    clients: list[ClientProjectionArtifact]
    server: ManifestArtifact
    provenance: ManifestArtifact
    warning_acknowledgments: list[DiagnosticAcknowledgment]


async def publish_study(
    command: PublishStudyCommand,
    *,
    context: CommandContext,
    store: Store,
) -> CommandReceipt:
    """Publish one compiled study candidate and return a durable receipt."""
    candidate_digest = compute_digest(
        command.candidate.model_dump(mode="json", exclude_none=True)
    )
    refusal = publication_refusal(
        command.candidate, candidate_digest, command.warning_acknowledgments
    )
    if refusal is not None:
        code, category, message = _REFUSAL[refusal]
        return reject_command(
            context,
            command=_PUBLISH_COMMAND,
            code=code,
            category=category,
            message=message,
            retry="never",
        )

    study_version = StudyVersionRef(
        study_id=command.study_id,
        study_version_id=context.aggregate_id,
        version_number=command.version_number,
        manifest_digest=command.candidate.scientific_manifest_digest,
    )
    published = PublishedStudyVersion(
        study_version=study_version,
        version_string=command.version_string,
        git_provenance=command.git_provenance,
        candidate=command.candidate_artifact,
        scientific=command.scientific,
        clients=command.clients,
        server=command.server,
        provenance=command.provenance,
        warning_acknowledgments=command.warning_acknowledgments,
        publication_command=ResourceRef(id=context.command_id),
        publication_receipt=ResourceRef(id=context.receipt_id),
        published_at=context.recorded_at,
        published_by=context.principal,
    )

    already_present = store.revision_of(context.aggregate_id) is not None
    result = StudyPublicationResult(
        outcome="resolved_existing" if already_present else "created",
        study_version=study_version,
        version_string=command.version_string,
        candidate_digest=candidate_digest,
    )
    return await commit_command(
        context,
        command=_PUBLISH_COMMAND,
        new_state=published.model_dump(mode="json", exclude_none=True),
        result=TypedObject(
            schema=SchemaRef(
                name=_RESULT_SCHEMA_NAME,
                version=0,
                digest=Digest(
                    algorithm="sha-256", hex=authoring_schema().bundle_digest
                ),
            ),
            data=result.model_dump(mode="json", exclude_none=True),
        ),
        store=store,
    )
