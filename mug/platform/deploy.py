"""The deploy gate: the pure rule that checks bindings against a requirement.

The gate reads the pinned requirement and the deploy bindings and returns the
gaps as data. The service turns gaps into an unsatisfied report and a rejection,
or, when there are none, mints the revision.
"""

from __future__ import annotations

from collections.abc import Sequence

from mug.platform.types import (
    DeploymentRequirement,
    ExecutionBinding,
    Region,
    SecretBinding,
)


def requirement_gaps(
    requirement: DeploymentRequirement,
    *,
    region: Region,
    secret_bindings: Sequence[SecretBinding],
    execution_bindings: Sequence[ExecutionBinding],
) -> tuple[list[str], list[str], list[Region]]:
    """Return the gaps between a requirement and the bindings, as three lists.

    The lists are the unbound non-optional secret requirements, the unfilled
    execution slots, and the region gap. All three empty means satisfied.
    """
    data = requirement.data
    bound_secrets = {binding.requirement_key for binding in secret_bindings}
    unbound = [
        need.requirement_key
        for need in data.secret_requirements
        if not need.optional and need.requirement_key not in bound_secrets
    ]
    bound_slots = {(binding.slot, binding.runtime) for binding in execution_bindings}
    missing = [
        slot.slot
        for slot in data.execution_slots
        if (slot.slot, slot.runtime) not in bound_slots
    ]
    policy = data.region_policy
    region_gaps: list[Region] = []
    if policy is not None and region not in policy.allowed_regions:
        region_gaps = [region]
    return unbound, missing, region_gaps
