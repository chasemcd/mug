"""The publication gate: the pure rule that decides if a candidate publishes.

The gate reads only the candidate and the acknowledgments. It runs no I/O and
returns its verdict as data. The service turns a refusal into a domain error and
a durable receipt.
"""

from __future__ import annotations

from collections.abc import Sequence

from mug.authoring.types import CompiledStudyCandidate, DiagnosticAcknowledgment
from mug.kernel import Digest


def publication_refusal(
    candidate: CompiledStudyCandidate,
    candidate_digest: Digest,
    acknowledgments: Sequence[DiagnosticAcknowledgment],
) -> str | None:
    """Return the reason a candidate must not publish, or ``None`` if it may.

    A candidate publishes only when the compiler marked it a release candidate
    (so no blocking error stays open) and every acknowledgment binds to this
    exact candidate by digest.
    """
    if candidate.release_eligibility != "release_candidate":
        return "candidate_unpublishable"
    for ack in acknowledgments:
        if ack.candidate_digest.hex != candidate_digest.hex:
            return "acknowledgment_mismatch"
    return None
