"""One longitudinal study lifecycle, driven end to end through the real edge.

This test walks acceptance scenario NS-08 (durable longitudinal) and NS-10
(idempotent submission) across every command family the edge exposes. It drives
the real FastAPI edge with FastAPI's test client, over ONE shared in-memory store
and ONE deterministic gateway (a fixed clock and counter entropy). Each command
is a plain HTTP POST of an untrusted ``WireCommandEnvelope``; verified auth
resolves the acting principal from a request header, so the wire never carries a
principal.

The six commands chain by dataflow, not by coincidence: the study version that
``study.publish`` mints becomes the ``platform.deploy`` input; the deployment
revision that deploy mints becomes the ``launch.issue`` and ``visit.start`` input;
the enrollment that ``enrollment.enroll`` mints becomes the ``visit.start`` input;
and the visit that start mints is the one ``visit.advance`` moves. The enforced
cross-aggregate reads (launch reads the deployment, start reads the enrollment,
advance reads the visit) all go through the one shared store, so the walk proves
the families compose over a single durable substrate.

The heavy sub-objects (the compiled candidate, the deploy requirement and its
bindings) come from the frozen phase-0 fixtures, so the payloads are real
contract records, not hand-waved ones.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import Request
from fastapi.testclient import TestClient

from mug.edge import build_app
from mug.gateway import Gateway
from mug.kernel import PrincipalRef
from mug.storage import InMemoryStore

_ROOT = Path(__file__).resolve().parents[3] / "docs/architecture/phase-0"
_API01 = _ROOT / "api-01/fixtures/v0/valid/published-version.minimal-static.json"
_API02 = _ROOT / "api-02/fixtures/v0/valid"
_API04 = _ROOT / "api-04/fixtures/v0/valid/visit.minimal-static.json"

_UUID = "019b6000-0000-7000-8000-0000000000{:02x}"
_DIGEST = {"algorithm": "sha-256", "hex": "a" * 64}

# The compiler and policy that make the compiled candidate a release candidate;
# these mirror the frozen api-01 publish fixture builder.
_COMPILER = {
    "name": "mug-study-compiler",
    "version": "0.1.0",
    "artifact_digest": {"algorithm": "sha-256", "hex": "b" * 64},
    "contract": {
        "name": "mug.study.compiler-contract",
        "version": 0,
        "digest": _DIGEST,
    },
    "normalization_profile": "mug-normalization-v0",
}
_POLICY = {
    "unknown_fields": "reject",
    "warnings": "reject",
    "executable_content": "packaged_only",
    "hermetic_build": "required",
    "reproducibility_check": "required",
    "client_disclosure_check": "required",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _stream(aggregate_id: str) -> str:
    """Derive the event stream identifier the gateway assigns to an aggregate."""
    return "stream_" + aggregate_id.split("_", 1)[1]


# --- the fixed aggregate identifiers the walk targets ------------------------
_STUDY_VERSION = _load(_API01)["study_version"]
_SV_ID: str = _STUDY_VERSION["study_version_id"]
_STUDY_ID: str = _STUDY_VERSION["study_id"]
_D_ID: str = _load(_API02 / "deployment-revision.minimal-static.json")[
    "deployment_revision_id"
]
_E_ID: str = _load(_API04)["enrollment_id"]
_V_ID: str = _load(_API04)["visit_id"]


# --- deterministic clock and entropy ----------------------------------------
class _Entropy:
    """A deterministic entropy source: each call yields fresh, distinct bytes."""

    def __init__(self) -> None:
        self._n = 0

    def __call__(self, size: int) -> bytes:
        self._n += 1
        return bytes([self._n % 256]) * size


def _clock() -> datetime:
    return datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)


def _authenticate(request: Request) -> PrincipalRef:
    """Resolve the acting principal from the verified ``x-actor`` header."""
    actor = request.headers.get("x-actor")
    if actor == "researcher":
        return PrincipalRef(kind="researcher", id="researcher_" + _UUID.format(0x09))
    if actor == "participant":
        return PrincipalRef(kind="participant", id="participant_" + _UUID.format(0x80))
    raise PermissionError("unknown actor")


def _new_client() -> tuple[httpx.Client, InMemoryStore]:
    """Build the edge over one fresh store and a deterministic gateway."""
    store = InMemoryStore()
    app = build_app(
        store,
        gateway=Gateway(clock=_clock, entropy=_Entropy()),
        authenticate=_authenticate,
    )
    # starlette's TestClient is an httpx.Client; the base type is fully typed.
    return TestClient(app), store


# --- envelope and payload builders -------------------------------------------
def _idem(n: int) -> str:
    """One distinct, valid idempotency key per command in the walk."""
    return "idem_" + f"cmd{n:018d}" + "A"


def _request(n: int) -> str:
    return "request_" + _UUID.format(n)


def _envelope(
    command_type: str, *, target: str, data: dict[str, Any], step: int
) -> dict[str, Any]:
    return {
        "schema": {"name": "mug.command-envelope", "version": 0, "digest": _DIGEST},
        "protocol_version": "0.1.0",
        "command": {"name": command_type, "version": 0},
        "request_id": _request(step),
        "idempotency_key": _idem(step),
        "target": {"id": target},
        "payload": {
            "schema": {"name": "mug.edge.payload", "version": 0, "digest": _DIGEST},
            "data": data,
        },
    }


def _publish_payload() -> dict[str, Any]:
    version = _load(_API01)
    candidate = {
        "input_fingerprint": _DIGEST,
        "inputs": {
            "git_provenance": version["git_provenance"],
            "source": version["candidate"],
            "compiler": _COMPILER,
            "schema_registry_digest": _DIGEST,
            "build_context_digest": _DIGEST,
            "target_platform_contract": _COMPILER["contract"],
            "compilation_policy": _POLICY,
        },
        "manifest_set": version["scientific"],
        "validation_report": version["candidate"],
        "scientific_manifest_digest": version["study_version"]["manifest_digest"],
        "release_eligibility": "release_candidate",
    }
    return {
        "study_id": version["study_version"]["study_id"],
        "version_number": version["study_version"]["version_number"],
        "version_string": version["version_string"],
        "candidate": candidate,
        "candidate_artifact": version["candidate"],
        "git_provenance": version["git_provenance"],
        "scientific": version["scientific"],
        "clients": version["clients"],
        "server": version["server"],
        "provenance": version["provenance"],
        "warning_acknowledgments": version["warning_acknowledgments"],
    }


def _deploy_payload(study_version: dict[str, Any]) -> dict[str, Any]:
    revision = _load(_API02 / "deployment-revision.minimal-static.json")
    requirement = _load(_API02 / "deployment-requirement.minimal-static.json")
    return {
        "deployment_id": revision["deployment_id"],
        "revision_number": revision["revision_number"],
        # The study version comes from the publish that ran a moment ago, not
        # from the deploy fixture, so the walk deploys the version it published.
        "study_version": study_version,
        "requirement": {"data": requirement["data"]},
        "server_build": revision["server_build"],
        "client_builds": revision["client_builds"],
        "execution_bindings": revision["execution_bindings"],
        "provider_bindings": revision["provider_bindings"],
        "secret_bindings": revision["secret_bindings"],
        "region": revision["region"],
        "endpoints": revision["endpoints"],
        "data_handling": revision["server_build"]["data_handling"],
    }


# --- one POST per command ----------------------------------------------------
def _post(
    client: httpx.Client,
    command_type: str,
    *,
    target: str,
    data: dict[str, Any],
    step: int,
    actor: str,
) -> httpx.Response:
    return client.post(
        f"/commands/{command_type}",
        json=_envelope(command_type, target=target, data=data, step=step),
        headers={"x-actor": actor},
    )


def _accepted(response: httpx.Response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["outcome"] == "accepted", body
    return body


def test_longitudinal_lifecycle_walkthrough() -> None:
    """Publish, deploy, enrol, launch, start, and advance compose over one store."""
    client, store = _new_client()

    # 1. A researcher publishes a study version.
    publish = _accepted(
        _post(
            client,
            "study.publish",
            target=_SV_ID,
            data=_publish_payload(),
            step=1,
            actor="researcher",
        )
    )
    assert publish["receipt_class"] == "commit"
    assert publish["resource"]["id"] == _SV_ID
    study_version = publish["result"]["data"]["study_version"]
    assert study_version["study_version_id"] == _SV_ID

    # 2. The researcher deploys exactly the version just published.
    deploy = _accepted(
        _post(
            client,
            "platform.deploy",
            target=_D_ID,
            data=_deploy_payload(study_version),
            step=2,
            actor="researcher",
        )
    )
    assert deploy["result"]["data"]["satisfied"] is True
    deployment = deploy["result"]["data"]["deployment_revision"]
    assert deployment["deployment_revision_id"] == _D_ID
    assert deployment["study_version"]["study_version_id"] == _SV_ID

    # 3. A participant enrols in the study.
    enroll = _accepted(
        _post(
            client,
            "enrollment.enroll",
            target=_E_ID,
            data={"study_id": _STUDY_ID},
            step=3,
            actor="participant",
        )
    )
    enrollment_id = enroll["result"]["data"]["enrollment_id"]
    assert enrollment_id == _E_ID
    assert enroll["result"]["data"]["status"] == "active"

    # 4. The platform issues a launch ticket against the live deployment.
    launch = _accepted(
        _post(
            client,
            "launch.issue",
            target=_D_ID,
            data={"study_id": _STUDY_ID, "deployment": deployment, "ttl_seconds": 3600},
            step=4,
            actor="researcher",
        )
    )
    handle = launch["result"]["data"]["ticket_handle"]
    assert launch["result"]["data"]["outcome"] == "issued"
    # A token has no version stamp; its identity is the opaque handle.
    assert "version_stamp" not in launch

    # 5. The participant starts a visit for the active enrollment.
    start = _accepted(
        _post(
            client,
            "visit.start",
            target=_V_ID,
            data={
                "enrollment_id": enrollment_id,
                "study_id": _STUDY_ID,
                "study_version": study_version,
                "deployment": deployment,
            },
            step=5,
            actor="participant",
        )
    )
    assert start["result"]["data"]["status"] == "created"
    assert start["version_stamp"]["revision"] == 1

    # 6. The participant advances the visit to in-progress at the next revision.
    advance = _accepted(
        _post(
            client,
            "visit.advance",
            target=_V_ID,
            data={"target_status": "in-progress", "expected_revision": 1},
            step=6,
            actor="participant",
        )
    )
    assert advance["result"]["data"]["status"] == "in-progress"
    assert advance["version_stamp"]["revision"] == 2

    # The durable substrate holds every aggregate the walk created, each on its
    # own stream. The deployment stream carries two events: the deploy and the
    # launch ticket issued against it.
    assert store.revision_of(_SV_ID) == 1
    assert store.revision_of(_D_ID) == 1
    assert store.revision_of(_E_ID) == 1
    assert store.revision_of(_V_ID) == 2
    assert store.load_token(handle) is not None
    assert store.stream_head(_stream(_SV_ID)) == 1
    assert store.stream_head(_stream(_D_ID)) == 2
    assert store.stream_head(_stream(_E_ID)) == 1
    assert store.stream_head(_stream(_V_ID)) == 2
    # Six commits appended six distinct events to the canonical ledger.
    events = store.committed_event_ids()
    assert len(events) == 6
    assert len(set(events)) == 6


def test_a_replayed_submission_is_idempotent() -> None:
    """NS-10: an identical retry returns the original receipt with no second effect.

    End to end this holds because the gateway content-addresses the command
    identifiers from the client idempotency key and the payload, so the retry
    re-mints identical identifiers and the store replays rather than conflicts.
    """
    client, store = _new_client()
    _accepted(
        _post(
            client,
            "study.publish",
            target=_SV_ID,
            data=_publish_payload(),
            step=1,
            actor="researcher",
        )
    )
    first = _accepted(
        _post(
            client,
            "enrollment.enroll",
            target=_E_ID,
            data={"study_id": _STUDY_ID},
            step=3,
            actor="participant",
        )
    )
    events_before = store.committed_event_ids()

    # The same envelope (same idempotency key and content) resubmitted, as a
    # refresh or a retry would send it. NS-10 pass condition 1: this returns the
    # original receipt, not a conflict.
    again = _accepted(
        _post(
            client,
            "enrollment.enroll",
            target=_E_ID,
            data={"study_id": _STUDY_ID},
            step=3,
            actor="participant",
        )
    )

    assert again["resource"]["id"] == first["resource"]["id"]
    assert again["stream_positions"] == first["stream_positions"]
    assert again["version_stamp"] == first["version_stamp"]
    # No second effect: the enrollment stays at revision 1 and no event is added.
    assert store.revision_of(_E_ID) == 1
    assert store.committed_event_ids() == events_before

    # NS-10 condition 2: the same key with a conflicting payload still conflicts,
    # so the content-addressing distinguishes a replay from a colliding command.
    conflict = _post(
        client,
        "enrollment.enroll",
        target=_E_ID,
        data={"study_id": "study_" + _UUID.format(0x99)},
        step=3,
        actor="participant",
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "command.idempotency_conflict"
    # Still no second effect from the rejected conflict.
    assert store.committed_event_ids() == events_before


def test_a_rejected_command_maps_to_its_http_status() -> None:
    """Advancing a visit that was never started rejects as a safe 404 at the edge."""
    client, store = _new_client()

    response = _post(
        client,
        "visit.advance",
        target=_V_ID,
        data={"target_status": "in-progress", "expected_revision": 1},
        step=6,
        actor="participant",
    )

    assert response.status_code == 404
    body = response.json()
    assert body["outcome"] == "rejected"
    assert body["error"]["code"] == "resource.not_found"
    # No effect: the visit was never created.
    assert store.revision_of(_V_ID) is None
