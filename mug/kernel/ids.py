"""Typed identifiers and the active kind registry.

A MUG identifier is ``<kind>_<canonical lowercase UUIDv7>``. The kind prefix
names the resource type. The UUIDv7 body gives database locality only; it is
never a trusted event time, order, or entropy source.

The registry below is the authority for the active kind set. A test cross-checks
it against the ``RegisteredMugId`` pattern in the frozen schema.
"""

from __future__ import annotations

from typing import Annotated, NamedTuple, TypeAlias

from pydantic import Field

# The canonical UUIDv7 body: version nibble 7, variant nibble 8/9/a/b.
UUIDV7 = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"


class IdKind(NamedTuple):
    """One row of the active identifier registry."""

    prefix: str
    type_name: str
    resource_class: str
    owner: str


# The 55 active kinds (identifiers-and-resource-hierarchy.md). Order follows the
# documented registry table.
ID_KIND_REGISTRY: tuple[IdKind, ...] = (
    IdKind("study", "StudyId", "definition", "API-01"),
    IdKind("studyver", "StudyVersionId", "immutable-version", "API-01"),
    IdKind("flownode", "FlowNodeDefinitionId", "definition", "API-01/04"),
    IdKind("deploy", "DeploymentId", "mutable-resource", "API-02"),
    IdKind("deployrev", "DeploymentRevisionId", "immutable-version", "API-02"),
    IdKind("participant", "ParticipantPrincipalId", "principal", "API-03"),
    IdKind("service", "ServicePrincipalId", "principal", "kernel"),
    IdKind("system", "SystemPrincipalId", "principal", "kernel"),
    IdKind("researcher", "ResearcherPrincipalId", "principal", "API-03"),
    IdKind("enrollment", "EnrollmentId", "mutable-resource", "API-03"),
    IdKind("visit", "VisitId", "runtime-occurrence", "API-04"),
    IdKind("visitplan", "VisitPlanId", "immutable-materialization", "API-04"),
    IdKind("activitydef", "ActivityDefinitionId", "definition", "API-01/04"),
    IdKind("activity", "ActivityOccurrenceId", "runtime-occurrence", "API-04"),
    IdKind("seatdef", "SeatDefinitionId", "definition", "API-05"),
    IdKind("actor", "ActorInstanceId", "runtime-occurrence", "API-05"),
    IdKind("controller", "ControllerBindingId", "runtime-occurrence", "API-05"),
    IdKind("interaction", "InteractionId", "runtime-occurrence", "API-06"),
    IdKind("group", "GroupId", "runtime-occurrence", "API-06"),
    IdKind("channeldef", "ChannelDefinitionId", "definition", "API-06"),
    IdKind("channel", "ChannelInstanceId", "runtime-occurrence", "API-06"),
    IdKind("lease", "LeaseId", "runtime-occurrence", "API-06"),
    IdKind("leaseepoch", "LeaseNamespaceEpochId", "runtime-occurrence", "API-06"),
    IdKind("prodepoch", "ProducerEpochId", "runtime-occurrence", "API-09/10"),
    IdKind("clockepoch", "ClockEpochId", "runtime-occurrence", "kernel"),
    IdKind("correlation", "CorrelationId", "runtime-occurrence", "kernel"),
    IdKind("episode", "EpisodeId", "runtime-occurrence", "API-07"),
    IdKind("message", "MessageId", "runtime-occurrence", "API-08"),
    IdKind("stream", "StreamId", "mutable-append-resource", "API-10"),
    IdKind("event", "EventId", "runtime-occurrence", "API-10"),
    IdKind("artifact", "ArtifactId", "runtime-occurrence", "API-11"),
    IdKind("upload", "UploadId", "runtime-occurrence", "API-11"),
    IdKind("agentdef", "AgentDefinitionId", "definition", "API-12"),
    IdKind("agentver", "AgentVersionId", "immutable-version", "API-12"),
    IdKind("agentrun", "AgentRunId", "runtime-occurrence", "API-12"),
    IdKind("promptdef", "PromptTemplateDefinitionId", "definition", "API-12"),
    IdKind("promptver", "PromptTemplateVersionId", "immutable-version", "API-12"),
    IdKind("decision", "DecisionId", "runtime-occurrence", "API-12"),
    IdKind("modelcall", "ModelInvocationId", "runtime-occurrence", "API-13"),
    IdKind("generation", "ModelGenerationId", "runtime-occurrence", "API-13"),
    IdKind("tooldef", "ToolDefinitionId", "definition", "API-14"),
    IdKind("toolver", "ToolVersionId", "immutable-version", "API-14"),
    IdKind("toolcall", "ToolCallId", "runtime-occurrence", "API-14"),
    IdKind("memory", "MemorySnapshotId", "immutable-materialization", "API-15"),
    IdKind("prefdef", "PreferenceProtocolDefinitionId", "definition", "API-18"),
    IdKind("prefver", "PreferenceProtocolVersionId", "immutable-version", "API-18"),
    IdKind("prefquery", "PreferenceQueryId", "runtime-occurrence", "API-18"),
    IdKind("prefassign", "PreferenceAssignmentId", "runtime-occurrence", "API-18"),
    IdKind("prefresponse", "PreferenceResponseId", "runtime-occurrence", "API-18"),
    IdKind("secret", "SecretBindingId", "mutable-resource", "API-02"),
    IdKind("job", "JobId", "runtime-occurrence", "API-22"),
    IdKind("command", "CommandId", "runtime-occurrence", "kernel"),
    IdKind("request", "RequestId", "runtime-occurrence", "kernel"),
    IdKind("receipt", "ReceiptId", "runtime-occurrence", "kernel"),
    IdKind("error", "ErrorId", "runtime-occurrence", "kernel"),
)

ACTIVE_ID_PREFIXES: frozenset[str] = frozenset(k.prefix for k in ID_KIND_REGISTRY)

# Prefixes retired by ADR-0013/0014/0015. They are reserved forever: never
# reissued, never valid on the wire.
RESERVED_ID_PREFIXES: frozenset[str] = frozenset(
    {
        "studydraft",
        "draftrev",
        "account",
        "authsession",
        "wavedef",
        "retpolicy",
        "retpolicyver",
    }
)


def id_pattern(prefix: str) -> str:
    """Return the anchored regular expression for one kind of identifier."""
    return f"^{prefix}_{UUIDV7}$"


# The union of every active prefix (schema `RegisteredMugId`).
_REGISTERED_ID_PATTERN = (
    "^(?:" + "|".join(k.prefix for k in ID_KIND_REGISTRY) + f")_{UUIDV7}$"
)
RegisteredMugId: TypeAlias = Annotated[
    str, Field(pattern=_REGISTERED_ID_PATTERN, max_length=61)
]

# Named identifier types used by the kernel wire objects. Each is a string that
# matches one kind's ``<prefix>_<uuidv7>`` pattern.
CommandId: TypeAlias = Annotated[str, Field(pattern=id_pattern("command"))]
RequestId: TypeAlias = Annotated[str, Field(pattern=id_pattern("request"))]
ReceiptId: TypeAlias = Annotated[str, Field(pattern=id_pattern("receipt"))]
ErrorId: TypeAlias = Annotated[str, Field(pattern=id_pattern("error"))]
ArtifactId: TypeAlias = Annotated[str, Field(pattern=id_pattern("artifact"))]
UploadId: TypeAlias = Annotated[str, Field(pattern=id_pattern("upload"))]
EventId: TypeAlias = Annotated[str, Field(pattern=id_pattern("event"))]
JobId: TypeAlias = Annotated[str, Field(pattern=id_pattern("job"))]
SecretBindingId: TypeAlias = Annotated[str, Field(pattern=id_pattern("secret"))]
StreamId: TypeAlias = Annotated[str, Field(pattern=id_pattern("stream"))]
ProducerEpochId: TypeAlias = Annotated[str, Field(pattern=id_pattern("prodepoch"))]
LeaseId: TypeAlias = Annotated[str, Field(pattern=id_pattern("lease"))]
LeaseNamespaceEpochId: TypeAlias = Annotated[
    str, Field(pattern=id_pattern("leaseepoch"))
]
StudyId: TypeAlias = Annotated[str, Field(pattern=id_pattern("study"))]
StudyVersionId: TypeAlias = Annotated[str, Field(pattern=id_pattern("studyver"))]
DeploymentId: TypeAlias = Annotated[str, Field(pattern=id_pattern("deploy"))]
DeploymentRevisionId: TypeAlias = Annotated[str, Field(pattern=id_pattern("deployrev"))]
FlowNodeDefinitionId: TypeAlias = Annotated[str, Field(pattern=id_pattern("flownode"))]
ParticipantPrincipalId: TypeAlias = Annotated[
    str, Field(pattern=id_pattern("participant"))
]
ServicePrincipalId: TypeAlias = Annotated[str, Field(pattern=id_pattern("service"))]
SystemPrincipalId: TypeAlias = Annotated[str, Field(pattern=id_pattern("system"))]
ResearcherPrincipalId: TypeAlias = Annotated[
    str, Field(pattern=id_pattern("researcher"))
]
EnrollmentId: TypeAlias = Annotated[str, Field(pattern=id_pattern("enrollment"))]
VisitId: TypeAlias = Annotated[str, Field(pattern=id_pattern("visit"))]
VisitPlanId: TypeAlias = Annotated[str, Field(pattern=id_pattern("visitplan"))]
ActivityDefinitionId: TypeAlias = Annotated[
    str, Field(pattern=id_pattern("activitydef"))
]
ActivityOccurrenceId: TypeAlias = Annotated[
    str, Field(pattern=id_pattern("activity"))
]
SeatDefinitionId: TypeAlias = Annotated[str, Field(pattern=id_pattern("seatdef"))]
ActorInstanceId: TypeAlias = Annotated[str, Field(pattern=id_pattern("actor"))]
ControllerBindingId: TypeAlias = Annotated[str, Field(pattern=id_pattern("controller"))]
InteractionId: TypeAlias = Annotated[str, Field(pattern=id_pattern("interaction"))]
GroupId: TypeAlias = Annotated[str, Field(pattern=id_pattern("group"))]
ChannelDefinitionId: TypeAlias = Annotated[str, Field(pattern=id_pattern("channeldef"))]
ChannelInstanceId: TypeAlias = Annotated[str, Field(pattern=id_pattern("channel"))]
ClockEpochId: TypeAlias = Annotated[str, Field(pattern=id_pattern("clockepoch"))]
CorrelationId: TypeAlias = Annotated[str, Field(pattern=id_pattern("correlation"))]
EpisodeId: TypeAlias = Annotated[str, Field(pattern=id_pattern("episode"))]
MessageId: TypeAlias = Annotated[str, Field(pattern=id_pattern("message"))]
AgentDefinitionId: TypeAlias = Annotated[str, Field(pattern=id_pattern("agentdef"))]
AgentVersionId: TypeAlias = Annotated[str, Field(pattern=id_pattern("agentver"))]
AgentRunId: TypeAlias = Annotated[str, Field(pattern=id_pattern("agentrun"))]
PromptTemplateDefinitionId: TypeAlias = Annotated[
    str, Field(pattern=id_pattern("promptdef"))
]
PromptTemplateVersionId: TypeAlias = Annotated[
    str, Field(pattern=id_pattern("promptver"))
]
DecisionId: TypeAlias = Annotated[str, Field(pattern=id_pattern("decision"))]
ModelInvocationId: TypeAlias = Annotated[str, Field(pattern=id_pattern("modelcall"))]
ModelGenerationId: TypeAlias = Annotated[str, Field(pattern=id_pattern("generation"))]
ToolDefinitionId: TypeAlias = Annotated[str, Field(pattern=id_pattern("tooldef"))]
ToolVersionId: TypeAlias = Annotated[str, Field(pattern=id_pattern("toolver"))]
ToolCallId: TypeAlias = Annotated[str, Field(pattern=id_pattern("toolcall"))]
MemorySnapshotId: TypeAlias = Annotated[str, Field(pattern=id_pattern("memory"))]
PreferenceProtocolDefinitionId: TypeAlias = Annotated[
    str, Field(pattern=id_pattern("prefdef"))
]
PreferenceProtocolVersionId: TypeAlias = Annotated[
    str, Field(pattern=id_pattern("prefver"))
]
PreferenceQueryId: TypeAlias = Annotated[str, Field(pattern=id_pattern("prefquery"))]
PreferenceAssignmentId: TypeAlias = Annotated[
    str, Field(pattern=id_pattern("prefassign"))
]
PreferenceResponseId: TypeAlias = Annotated[
    str, Field(pattern=id_pattern("prefresponse"))
]
