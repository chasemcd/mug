"""Study authoring, compilation, and publication (API-01, layer L1).

This family owns the ``AuthoringDocument`` a researcher writes, the four compiled
manifests (``ScientificManifest``, ``ClientManifest``, ``StudyServerManifest``,
``ProvenanceManifest``), their ``ManifestSet`` closure, the ``ValidationReport``,
and the immutable ``PublishedStudyVersion``. It also owns the value objects the
corpus validates on their own -- ``FlowSpec``, ``GitProvenance``,
``CodePackageRef``, ``SecretRequirement``, ``CapabilityRequirement``,
``ServerRuntimeBindingBase``, ``Diagnostic``, and ``ManifestArtifact``. Each
record references the kernel (L0) types; the family adds no runtime.
"""

from __future__ import annotations

from mug.authoring.agents import (
    Fallback,
    History,
    LLMAgent,
    Message,
    Provider,
    Step,
    Thoughts,
    Transcript,
)
from mug.authoring.preferences import Axis, Comparison, Elicit
from mug.authoring.service import PublishStudyCommand, publish_study
from mug.authoring.types import (
    AuthoringDocument,
    CapabilityRequirement,
    ClientManifest,
    CodePackageRef,
    CompilationInputs,
    CompiledStudyCandidate,
    Diagnostic,
    DiagnosticAcknowledgment,
    FlowSpec,
    GitProvenance,
    ManifestArtifact,
    ManifestSet,
    ProvenanceManifest,
    PublishedStudyVersion,
    ScientificManifest,
    SecretRequirement,
    ServerRuntimeBindingBase,
    StudyPublicationResult,
    StudyServerManifest,
    ValidationReport,
    authoring_schema,
)

__all__ = [
    "AuthoringDocument",
    "Axis",
    "CapabilityRequirement",
    "ClientManifest",
    "CodePackageRef",
    "Comparison",
    "CompilationInputs",
    "CompiledStudyCandidate",
    "Diagnostic",
    "DiagnosticAcknowledgment",
    "Elicit",
    "Fallback",
    "FlowSpec",
    "GitProvenance",
    "History",
    "LLMAgent",
    "ManifestArtifact",
    "ManifestSet",
    "Message",
    "ProvenanceManifest",
    "Provider",
    "PublishStudyCommand",
    "PublishedStudyVersion",
    "ScientificManifest",
    "SecretRequirement",
    "ServerRuntimeBindingBase",
    "Step",
    "StudyPublicationResult",
    "StudyServerManifest",
    "Thoughts",
    "Transcript",
    "ValidationReport",
    "authoring_schema",
    "publish_study",
]
