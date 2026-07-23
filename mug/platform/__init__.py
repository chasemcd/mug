"""Platform deployment records (API-02, layer L1).

This family owns five record types: the composed ``DeploymentRequirement`` a study
version pins, the mutable ``Deployment`` aggregate, the immutable
``DeploymentRevision`` that ``mug deploy`` records, the internal
``SatisfactionReport`` a check produces, and the participant-facing
``ClientDeploymentProjection``. Each record references the kernel (L0) types; the
family adds no runtime. Secret bindings hold only a shared-kernel ``SecretRef``.
"""

from __future__ import annotations

from mug.platform.service import DeployCommand, deploy
from mug.platform.types import (
    ClientDeploymentProjection,
    Deployment,
    DeploymentRequirement,
    DeploymentRevision,
    SatisfactionReport,
    platform_schema,
)

__all__ = [
    "ClientDeploymentProjection",
    "DeployCommand",
    "Deployment",
    "DeploymentRequirement",
    "DeploymentRevision",
    "SatisfactionReport",
    "deploy",
    "platform_schema",
]
