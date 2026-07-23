"""The frozen command-results bundle validates the emitted result payloads.

Command results that do not mirror a persisted record live in one frozen bundle.
Each handler emits a result whose data must validate against its ``$defs`` entry,
and ``result_ref`` must pin that bundle's digest.
"""

from __future__ import annotations

from mug.runtime import command_results_schema, result_ref

_CASES = {
    "EnrollmentResult": {
        "outcome": "enrolled",
        "enrollment_id": "enrollment_019b6000-0000-7000-8000-000000000050",
        "study_id": "study_019b6000-0000-7000-8000-000000000001",
        "status": "active",
        "revision": 1,
    },
    "LaunchResult": {
        "outcome": "issued",
        "ticket_handle": "handle_AAAAAAAAAAAAAAAAAAAAAA",
        "study_id": "study_019b6000-0000-7000-8000-000000000001",
        "expires_at": "2026-08-02T13:00:00.000000Z",
    },
    "VisitTransitionResult": {
        "outcome": "started",
        "visit_id": "visit_019b6000-0000-7000-8000-000000000090",
        "status": "created",
        "revision": 1,
    },
}


def test_each_result_payload_validates_against_its_frozen_schema() -> None:
    bundle = command_results_schema()
    assert _CASES.keys() <= bundle.def_names()
    for def_name, payload in _CASES.items():
        bundle.validate(def_name, payload)


def test_result_ref_pins_the_command_results_digest() -> None:
    ref = result_ref("mug.command-result.enrollment")
    assert ref.version == 0
    assert ref.digest.hex == command_results_schema().bundle_digest


def test_a_malformed_result_is_rejected() -> None:
    bundle = command_results_schema()
    # An enrollment result at revision 0 breaks the minimum-1 bound.
    malformed = {**_CASES["EnrollmentResult"], "revision": 0}
    assert not bundle.is_valid("EnrollmentResult", malformed)
