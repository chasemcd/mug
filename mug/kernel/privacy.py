"""Privacy classification and the label lattice.

A ``PrivacyClassification`` is a closed tuple of labels. Exactly one base label
(``public`` or ``research``) leads, then optional additive restrictions in a
fixed order: ``sensitive`` before ``pii``. ``secret`` is never a privacy label;
secret material is referenced only by ``SecretRef``.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator

from mug.kernel._base import KernelModel

# The five allowed classifications, in canonical order (schema
# `PrivacyClassification`). Order is significant.
ALLOWED_PRIVACY_LABELS: tuple[tuple[str, ...], ...] = (
    ("public",),
    ("research",),
    ("research", "sensitive"),
    ("research", "pii"),
    ("research", "sensitive", "pii"),
)

_ALLOWED_SET: frozenset[tuple[str, ...]] = frozenset(ALLOWED_PRIVACY_LABELS)


def _check_classification(labels: list[str]) -> list[str]:
    """Reject a label tuple that is not one of the five canonical forms."""
    if tuple(labels) not in _ALLOWED_SET:
        raise ValueError(f"privacy_labels {labels!r} is not a canonical classification")
    return labels


PrivacyClassification = Annotated[list[str], AfterValidator(_check_classification)]


class DataHandlingRef(KernelModel):
    """The privacy classification attached to a field or an artifact."""

    privacy_labels: PrivacyClassification


def join(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    """Return the least classification at least as strict as both inputs.

    The join takes the stricter base and the union of the restrictions. Any
    restriction promotes the base to ``research``.
    """
    restrictions = ({*left, *right}) - {"public", "research"}
    result: list[str] = [
        "research" if restrictions or "research" in (left + right) else "public"
    ]
    if "sensitive" in restrictions:
        result.append("sensitive")
    if "pii" in restrictions:
        result.append("pii")
    return tuple(result)
