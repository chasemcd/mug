"""Compile an author's ``Comparison`` into the blinded records the loop drives.

The study author writes a ``Comparison`` (``mug.authoring``): a question and a set
of labelled recorded runs. This module turns that one small object into the records
the annotation runtime needs -- a ``PreferenceProtocol`` and one ``CandidateRef``
per option -- so the author never writes an id, a handle, a protocol object, or a
task kind. It mirrors ``compile_agent``: the author's definition lives in the
authoring layer, and this compile step (one layer up) reads it and mints the
runtime records behind it.

Compiling is the one entropy-and-clock boundary here, so the caller injects it: a
``resolve`` that maps each option's recorded run to the content-addressed artifact
it lives in (a replay bundle's trajectory, a model-output blob), and a
``new_handle`` that mints the blinded public handle each candidate is shown behind.
The author's labels are carried through to ``labels`` for the researcher's analysis;
the participant sees only the handles.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from mug.authoring import Comparison
from mug.kernel import ArtifactRef, PublicHandle
from mug.preferences.runtime import candidate_from_artifact
from mug.preferences.types import (
    CandidateRef,
    ComparisonTask,
    PreferenceProtocol,
)

_STYLE_TASK = {"compare": "pairwise", "rate": "rating"}


@dataclass(frozen=True)
class ComparisonIds:
    """The versioned ids the compiled protocol is pinned by (minted by the caller)."""

    protocol_version_id: str
    protocol_definition_id: str


@dataclass(frozen=True)
class CompiledComparison:
    """The records one ``Comparison`` compiles into, ready for the annotation loop.

    ``protocol`` is the blinded, randomized comparison protocol. ``candidates`` is
    one blinded ``CandidateRef`` per option, in the author's order. ``candidate_keys``
    is those candidate keys (the id-safe slugs of the author's labels), and
    ``labels`` maps each candidate key back to the author's label for analysis.
    """

    protocol: PreferenceProtocol
    candidates: list[CandidateRef]
    candidate_keys: list[str]
    labels: dict[str, str]


def compile_comparison(
    comparison: Comparison,
    *,
    ids: ComparisonIds,
    resolve: Callable[[object], ArtifactRef],
    new_handle: Callable[[], PublicHandle],
) -> CompiledComparison:
    """Compile one author ``Comparison`` into a protocol and its candidate refs.

    The protocol carries the author's question and their blind/shuffle choices; each
    option becomes a candidate over the artifact ``resolve`` maps it to, shown behind
    a fresh blinded handle. The candidate keys are id-safe slugs of the author's
    labels, so two options must not slug to the same key.
    """
    task = ComparisonTask(
        kind=_STYLE_TASK[comparison.style],  # pyright: ignore[reportArgumentType]
        prompt=comparison.ask,
    )
    protocol = PreferenceProtocol(
        protocol_version_id=ids.protocol_version_id,
        protocol_definition_id=ids.protocol_definition_id,
        candidate_kind=comparison.of,  # pyright: ignore[reportArgumentType]
        task=task,
        blinded=comparison.blind,
        randomize_order=comparison.shuffle,
    )
    candidates: list[CandidateRef] = []
    keys: list[str] = []
    labels: dict[str, str] = {}
    for label, run in comparison.options.items():
        key = _slug(label)
        if key in labels:
            raise ValueError(f"two options slug to the same key: {key!r}")
        candidates.append(
            candidate_from_artifact(
                candidate_key=key,
                kind=comparison.of,
                artifact=resolve(run),
                display_handle=new_handle(),
            )
        )
        keys.append(key)
        labels[key] = label
    return CompiledComparison(
        protocol=protocol,
        candidates=candidates,
        candidate_keys=keys,
        labels=labels,
    )


def _slug(label: str) -> str:
    """Turn an author's label into an id-safe candidate key.

    Lower-cases, replaces each run of non-alphanumerics with a single hyphen, and
    trims to the authoring-key shape (starts with a letter, hyphen-separated).
    """
    lowered = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    if not lowered or not lowered[0].isalpha():
        lowered = f"option-{lowered}".strip("-")
    return lowered


__all__ = ["ComparisonIds", "CompiledComparison", "compile_comparison"]
