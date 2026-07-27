"""Project recorded preferences into the shape the field actually trains on.

The canonical records are right and they are not a dataset. A reward model, a DPO
run, and every published preference corpus read one flat row per comparison:
a prompt, the completion that was chosen, and the one that was not. MUG records
that judgement across four aggregates and two families, so a researcher who wanted
to train on their own study would have to write the join themselves -- which is
the same failure as recording that an activity happened without recording what
happened in it.

This module is the join. One row per (chosen, rejected) pair, so a comparison of
two candidates is one row and a comparison of three is two, which is exactly how
the public corpora are shaped. The standard field names are the standard field
names: ``prompt``, ``chosen``, ``rejected``, and a ``messages`` list in the
conversational form.

**And then it carries what nobody else does.** A public preference row is a pair of
strings; it cannot say which arm of an experiment the annotator was in, how long
they took, which side each completion was shown on, what the study asked besides
"which is better", or that the annotator said the two were the same. Every one of
those is recorded here, so the row is a superset of the format rather than a
different one:

- ``verdict`` -- a tie or a both-bad judgement, and ``tie_offered`` so an absent
  tie can be read as "none was chosen" rather than "none could be";
- ``ratings`` -- each authored axis, resolved to whether it favoured the chosen or
  the rejected completion, so a reader never has to know the display order;
- ``shown_first`` -- which of the two was on top, the position bias the randomizer
  exists to remove and that nobody records;
- ``response_time_ms`` -- how long the judgement took;
- the enrollment, the assignment, the response, and every message id, so any row
  can be walked back to the exact evidence it came from.

The text comes from the durable transcript, which is the only record that says
where a message's words live -- and it says so for the candidates that were never
delivered too, which is what makes the untaken branch exportable at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from mug.storage import ArtifactStore, Store

_CANDIDATE_SET = "mug.api-08.candidate-reply-set"
_RESPONSE = "mug.api-18.preference-response"
_QUALITY = "mug.api-18.quality-evidence"
_PROTOCOL = "mug.api-18.preference-protocol"
_ASSIGNMENT = "mug.api-18.preference-assignment"
_MESSAGE = "mug.api-08.chat-message"
_TRANSCRIPT_KEYS = ("messages", "candidates")

# The dataset kind these rows are written under. It is a values-only kind, like the
# form answers, so it needs no place in the frozen four.
PREFERENCE_PAIRS = "preference-pairs"


def _heads(store: Store) -> dict[str, dict[str, Any]]:
    """Return every recorded aggregate head that is a mapping, by its identifier."""
    found: dict[str, dict[str, Any]] = {}
    for aggregate_id, state in store.scan_aggregates():
        if isinstance(state, dict):
            found[aggregate_id] = cast("dict[str, Any]", state)
    return found


def _named(heads: Mapping[str, dict[str, Any]], schema: str) -> list[dict[str, Any]]:
    """Return every head of one schema, in identifier order."""
    return [
        body
        for _id, body in sorted(heads.items())
        if body.get("schema", {}).get("name") == schema
    ]


def _artifact_ids(heads: Mapping[str, dict[str, Any]]) -> dict[str, str]:
    """Map every message this deployment recorded to where its words live.

    A transcript holds the delivered history and, since W19, the candidate replies
    that were never delivered. Both say the artifact, so one pass over the
    transcripts is enough to resolve any message a preference row names.
    """
    where: dict[str, str] = {}
    for body in heads.values():
        if "capture" not in body or "channel_key" not in body:
            continue
        for key in _TRANSCRIPT_KEYS:
            for record in cast("list[Any]", body.get(key) or []):
                if isinstance(record, dict):
                    entry = cast("dict[str, Any]", record)
                    message_id = entry.get("message_id")
                    artifact_id = entry.get("artifact_id")
                    if isinstance(message_id, str) and isinstance(artifact_id, str):
                        where[message_id] = artifact_id
    return where


async def _text_of(
    artifacts: ArtifactStore, where: Mapping[str, str], message_id: str
) -> str:
    """Return one message's words, or an empty string when they are not kept.

    A study that keeps no artifact for a message keeps no words for it, and the row
    says so by carrying none rather than by failing the whole export.
    """
    artifact_id = where.get(message_id)
    if artifact_id is None:
        return ""
    try:
        return (await artifacts.read_artifact(artifact_id)).decode("utf-8")
    except (KeyError, LookupError, ValueError, OSError):
        return ""


def _ratings(
    written: Any, *, chosen: str, rejected: str
) -> list[dict[str, Any]]:
    """Resolve each axis answer to the completion it favoured, by name not position.

    A rating names a candidate key. This turns that key into ``chosen`` or
    ``rejected`` for the pair this row is about, so a reader never has to hold the
    display order in their head to read a dimension. A rating about a third
    candidate belongs to a different row and is left out of this one.
    """
    read: list[dict[str, Any]] = []
    for item in cast("list[Any]", written or []):
        if not isinstance(item, dict):
            continue
        entry = cast("dict[str, Any]", item)
        candidate = entry.get("candidate_key")
        if candidate is None:
            favours = "neither"
        elif candidate == chosen:
            favours = "chosen"
        elif candidate == rejected:
            favours = "rejected"
        else:
            continue
        read.append(
            {
                "dimension": entry.get("dimension_key"),
                "favours": favours,
                "value": entry.get("value"),
            }
        )
    return read


async def collect_preference_rows(
    store: Store, artifacts: ArtifactStore
) -> list[dict[str, Any]]:
    """Return one row per (chosen, rejected) pair this deployment recorded.

    Rows follow the candidate sets in identifier order, and the rejected candidates
    of one set follow the order the participant was shown, so one ledger always
    gives one artifact.
    """
    heads = _heads(store)
    where = _artifact_ids(heads)
    responses = {
        body["response_id"]: body
        for body in _named(heads, _RESPONSE)
        if isinstance(body.get("response_id"), str)
    }
    quality = {
        body["response_id"]: body
        for body in _named(heads, _QUALITY)
        if isinstance(body.get("response_id"), str)
    }
    assignments = {
        body["assignment_id"]: body
        for body in _named(heads, _ASSIGNMENT)
        if isinstance(body.get("assignment_id"), str)
    }
    # A protocol shares its assignment's identifier body, because a frozen
    # assignment names its query and not the protocol it was made under.
    protocols = {
        cast("str", body["protocol_version_id"]).split("_", 1)[1]: body
        for body in _named(heads, _PROTOCOL)
        if isinstance(body.get("protocol_version_id"), str)
    }
    authors = {
        body["message_id"]: body.get("author_actor_id")
        for body in _named(heads, _MESSAGE)
        if isinstance(body.get("message_id"), str)
    }

    rows: list[dict[str, Any]] = []
    for written in _named(heads, _CANDIDATE_SET):
        response = responses.get(cast("str", written.get("preference_response_id")))
        if response is None:
            continue
        order = cast("list[str]", response.get("presented_order") or [])
        chosen = cast("str", written["selected_message_id"])
        prompt_id = cast("str", written["prompt_message_id"])
        prompt = await _text_of(artifacts, where, prompt_id)
        chosen_text = await _text_of(artifacts, where, chosen)
        evidence = quality.get(cast("str", response.get("response_id")), {})
        assignment_id = cast("str", response.get("assignment_id") or "")
        assignment = assignments.get(assignment_id, {})
        protocol = protocols.get(assignment_id.split("_", 1)[-1], {})
        task = cast("dict[str, Any]", protocol.get("task") or {})
        for rejected in order:
            if rejected == chosen:
                continue
            rejected_text = await _text_of(artifacts, where, rejected)
            rows.append(
                {
                    # The three fields every preference corpus is read by.
                    "prompt": prompt,
                    "chosen": chosen_text,
                    "rejected": rejected_text,
                    "messages": [
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": chosen_text},
                    ],
                    # What the participant meant, beyond which one won.
                    "verdict": response.get("verdict", "choice"),
                    "tie_offered": task.get("allow_tie") is True,
                    "ratings": _ratings(
                        response.get("ratings"), chosen=chosen, rejected=rejected
                    ),
                    # The presentation itself, which is a bias and not a detail.
                    "shown_first": (
                        "chosen" if order and order[0] == chosen else "rejected"
                    ),
                    "blinded": assignment.get("blinded"),
                    "response_time_ms": evidence.get("response_time_ms"),
                    "attention_check_passed": evidence.get("attention_check_passed"),
                    # Back to the evidence, for anything this row does not carry.
                    "enrollment_id": assignment.get("enrollment_id"),
                    "assignment_id": response.get("assignment_id"),
                    "response_id": response.get("response_id"),
                    "channel_key": written.get("channel_key"),
                    "prompt_message_id": prompt_id,
                    "prompt_author_actor_id": authors.get(prompt_id),
                    "chosen_message_id": chosen,
                    "rejected_message_id": rejected,
                    "recorded_at": written.get("recorded_at"),
                }
            )
    return rows


__all__ = ["PREFERENCE_PAIRS", "collect_preference_rows"]
