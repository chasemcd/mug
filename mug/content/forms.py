"""Record what a participant answered, not only that they answered.

A form was the one activity that recorded nothing. ``advance_flow`` checked every
answer against the form the author wrote and then committed a flow head saying
``{"key": "consent", "kind": "form", "status": "completed"}``. The values reached no
aggregate, no event, and no artifact, so a study that asked for consent, a mood
rating, and a free-text comment kept none of the three. `FormResponse`
(``mug.api-17.form-response``) was frozen with fixtures and had no producer.

This module is that producer, and it follows the rule the trajectory and the model
generation already follow: **the record binds the values by digest, and the values
live in one content-addressed artifact beside it**. The frozen ``FormResponse``
carries an ``answers_digest`` and no answers, which is the same records-only shape
every family has; the artifact is what a researcher opens, and re-digesting it
reproduces the digest the ledger bound. An answer that cannot be checked against the
ledger is not evidence.

The occurrence is the aggregate. Its identifier derives from the visit and the
activity key, so one form activity of one visit has one response however many times
a participant retries: the store coalesces an identical retry, and a second, different
submission of the same form reads the same expected revision and is fenced as stale.
A participant answers once, and a dropped receipt costs them nothing.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, cast

from mug.content.types import FormResponse, FormSpec
from mug.kernel import (
    ArtifactRef,
    CommandReceipt,
    CommandTypeRef,
    DataHandlingRef,
    TypedObject,
    compute_digest,
)
from mug.runtime import CommandContext, commit_command
from mug.storage import ArtifactStore, Store, json_bytes, stage_artifact

_SUBMIT = CommandTypeRef(name="form.submit", version=0)

# A form answer is what a participant said about themselves, so it is research data
# and never public. A study whose form asks for anything identifying passes its own
# stricter classification.
_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_JSON = "application/json"

# The schema name a form-response aggregate head carries, so a reader tells one from
# any other aggregate on the same visit.
FORM_RESPONSE_SCHEMA = "mug.api-17.form-response"


def answers_body(form: FormSpec, answers: Mapping[str, Any]) -> dict[str, Any]:
    """Draft what the answers artifact holds for one submitted form.

    The form key and its version travel with the answers, because an answer means
    nothing without the question that was asked: a study that revises a form between
    waves must be able to say which wording each response answered.
    """
    return {
        "form_key": form.form_key,
        "form_version": form.version,
        "answers": {key: answers[key] for key in sorted(answers)},
    }


async def record_form_answers(
    *,
    form: FormSpec,
    answers: Mapping[str, Any],
    visit_id: str,
    occurrence_id: str,
    submitted_at: str,
    context: CommandContext,
    store: Store,
    artifacts: ArtifactStore,
    new_artifact_id: Callable[[], str],
    new_upload_id: Callable[[], str],
    now: Callable[[], str],
    data_handling: DataHandlingRef = _RESEARCH,
) -> tuple[CommandReceipt, FormResponse | None]:
    """Write one submitted form's answers and commit the record that binds them.

    The values are staged first and the record second, so a crash between the two
    leaves an unreferenced artifact rather than a record that names values nobody
    wrote. The commit's payload digest binds the whole aggregate, and the record's
    ``answers_digest`` binds the artifact, so a reader checks the answers against the
    ledger without trusting the file beside it.
    """
    body = answers_body(form, answers)
    artifact = await stage_artifact(
        artifacts,
        data=json_bytes(body) + b"\n",
        media_type=_JSON,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
        data_handling=data_handling,
    )
    response = FormResponse(
        form_key=form.form_key,
        visit_id=visit_id,
        occurrence_id=occurrence_id,
        answers_digest=compute_digest(body),
        receipt_required=True,
        submitted_at=submitted_at,
    )
    state = _state(response, artifact)
    receipt = await commit_command(
        context,
        command=_SUBMIT,
        new_state=state,
        result=TypedObject(
            schema=response.schema,
            data=response.model_dump(mode="json", exclude_none=True),
        ),
        store=store,
    )
    return receipt, (response if receipt.outcome == "accepted" else None)


def recorded_answers(store: Store, occurrence_id: str) -> ArtifactRef | None:
    """Return the artifact holding what was answered here, or None for none."""
    state = store.load_aggregate(occurrence_id)
    if not isinstance(state, dict):
        return None
    named = cast("dict[str, Any]", state).get("answers")
    if not isinstance(named, dict):
        return None
    try:
        return ArtifactRef.model_validate(named)
    except ValueError:
        return None


def recorded_form_response(store: Store, occurrence_id: str) -> FormResponse | None:
    """Return the response recorded for one occurrence, or None when none is."""
    state = store.load_aggregate(occurrence_id)
    if not isinstance(state, dict):
        return None
    body = {
        key: value
        for key, value in cast("dict[str, Any]", state).items()
        if key != "answers"
    }
    try:
        return FormResponse.model_validate(body)
    except ValueError:
        return None


def read_answers(data: bytes) -> dict[str, Any]:
    """Read one answers artifact back into the body it holds."""
    return cast("dict[str, Any]", json.loads(data.decode("utf-8").splitlines()[0]))


def _state(response: FormResponse, artifact: ArtifactRef) -> dict[str, Any]:
    """Draft the aggregate state one submitted form commits.

    The frozen record has no artifact field -- it binds the answers by digest alone --
    so the reference sits beside it on the aggregate, exactly as an episode names its
    trajectory. The record is still readable from the head by dropping that one key.
    """
    return {
        **response.model_dump(mode="json", exclude_none=True),
        "answers": artifact.model_dump(mode="json", exclude_none=True),
    }


__all__ = [
    "FORM_RESPONSE_SCHEMA",
    "answers_body",
    "read_answers",
    "record_form_answers",
    "recorded_answers",
    "recorded_form_response",
]
