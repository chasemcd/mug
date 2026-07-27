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
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from mug.authoring import Axis, Comparison
from mug.kernel import ArtifactRef, PublicHandle
from mug.preferences.runtime import candidate_from_artifact
from mug.preferences.types import (
    CandidateRef,
    ComparisonTask,
    Dimension,
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
    key_for: Callable[[str, object], str] | None = None,
) -> CompiledComparison:
    """Compile one author ``Comparison`` into a protocol and its candidate refs.

    The protocol carries the author's question and their blind/shuffle choices; each
    option becomes a candidate over the artifact ``resolve`` maps it to, shown behind
    a fresh blinded handle. The candidate keys are id-safe slugs of the author's
    labels, so two options must not slug to the same key.

    ``key_for`` replaces that keying when the caller has a better name for the
    candidate than the author's label. A comparison of runs a participant made names
    each candidate by the run itself, because the recorded choice then says which
    run was preferred and a reader needs nothing beside it to know.
    """
    key_of: Callable[[str, object], str] = key_for or _key_from_label
    task = comparison_task(
        kind=_STYLE_TASK[comparison.style],
        prompt=comparison.ask,
        ties=comparison.ties,
        axes=comparison.axes,
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
        key = key_of(label, run)
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


def comparison_task(
    *,
    kind: str,
    prompt: str,
    ties: bool,
    axes: Sequence[Axis],
) -> ComparisonTask:
    """Build the task a protocol asks: the question, the tie policy, and the axes.

    ``ties`` is recorded even when nobody ties, because an absent tie has two
    readings -- none was chosen, or none was on offer -- and only the record can
    tell them apart. The author's axes become the dimensions each answer carries.
    """
    return ComparisonTask(
        kind=kind,  # pyright: ignore[reportArgumentType]
        prompt=prompt,
        allow_tie=ties or None,
        dimensions=[_dimension(axis) for axis in axes] or None,
    )


def _dimension(axis: Axis) -> Dimension:
    """Turn one author axis into the dimension its answers are recorded under."""
    return Dimension(
        key=axis.key,
        label=axis.ask,
        scope=axis.scope,  # pyright: ignore[reportArgumentType]
        points=axis.points,
        low_label=axis.low,
        high_label=axis.high,
    )


def _key_from_label(label: str, _run: object) -> str:
    """Name one candidate by the author's own label, which is the default."""
    return candidate_key_for(label)


def candidate_key_for(label: str) -> str:
    """Turn an author's label into an id-safe candidate key.

    Lower-cases, replaces each run of non-alphanumerics with a single hyphen, and
    trims to the authoring-key shape (starts with a letter, hyphen-separated).
    """
    lowered = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    if not lowered or not lowered[0].isalpha():
        lowered = f"option-{lowered}".strip("-")
    return lowered


__all__ = [
    "ComparisonIds",
    "CompiledComparison",
    "candidate_key_for",
    "comparison_task",
    "compile_comparison",
]
