"""The command line drives each family through the same spine the edge drives.

These tests exercise the command functions over an in-memory store: a publish and
a deploy reach their handler through the shared ``dispatch_command`` path (the same
commit receipt the edge returns), an export reads the whole ledger and writes one
ndjson file per kind, a simulate drains a durable job the store rediscovers, a
replay assembles a bundle from a captured episode, and the stop verb reports the
platform gap. The store is injected, so the command line touches no real database.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from mug.cli.commands import (
    CliError,
    discover_study_version,
    run_deploy,
    run_export,
    run_publish,
    run_replay,
    run_simulate,
    run_stop,
)
from mug.cli.main import build_parser, main
from mug.cli.session import CliSession, DurableStore, git_provenance
from mug.export.types import GitProvenanceRef
from mug.game.capture import capture_episode
from mug.game.env import EnvFactory, GymEnv
from mug.game.runtime import EpisodeSummary, InputState, run_episode
from mug.game.surface import Surface
from mug.gateway import Gateway
from mug.kernel import Digest, WireCommandEnvelope
from mug.storage import InMemoryStore
from mug.workers import JobRunner, WorkOutcome

_ROOT = Path(__file__).resolve().parents[3]
_API01 = _ROOT / "docs/architecture/phase-0/api-01/fixtures/v0/valid"
_API02 = _ROOT / "docs/architecture/phase-0/api-02/fixtures/v0/valid"
_DIGEST = {"algorithm": "sha-256", "hex": "a" * 64}
_FIXED = datetime(2026, 7, 23, 0, 0, 0, tzinfo=timezone.utc)
_GIT = GitProvenanceRef(commit="0" * 40, branch="main", dirty=False)
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


def _session(store: DurableStore | None = None) -> CliSession:
    """Open a session with a fixed clock, so exports carry stable timestamps."""
    resolved = store if store is not None else cast("DurableStore", InMemoryStore())
    return CliSession.open(store=resolved, gateway=Gateway(clock=lambda: _FIXED))


def _wire(command: str, target_id: str, data: dict[str, Any]) -> WireCommandEnvelope:
    """Build one wire envelope, the same bytes a client posts to the edge."""
    return WireCommandEnvelope.model_validate(
        {
            "schema": {"name": "mug.command-envelope", "version": 0, "digest": _DIGEST},
            "protocol_version": "0.1.0",
            "command": {"name": command, "version": 0},
            "request_id": "request_019b6000-0000-7000-8000-000000000001",
            "idempotency_key": "idem_0123456789abcdefghijkA",
            "target": {"id": target_id},
            "payload": {
                "schema": {"name": "mug.edge.payload", "version": 0, "digest": _DIGEST},
                "data": data,
            },
        }
    )


def _publish_envelope() -> WireCommandEnvelope:
    version = json.loads((_API01 / "published-version.minimal-static.json").read_text())
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
    data = {
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
    return _wire("study.publish", version["study_version"]["study_version_id"], data)


def _deploy_envelope() -> WireCommandEnvelope:
    revision = json.loads(
        (_API02 / "deployment-revision.minimal-static.json").read_text()
    )
    requirement = json.loads(
        (_API02 / "deployment-requirement.minimal-static.json").read_text()
    )
    data = {
        "deployment_id": revision["deployment_id"],
        "revision_number": revision["revision_number"],
        "study_version": revision["study_version"],
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
    return _wire("platform.deploy", revision["deployment_revision_id"], data)


def _write(path: Path, envelope: WireCommandEnvelope) -> Path:
    path.write_text(envelope.model_dump_json(exclude_none=True), encoding="utf-8")
    return path


async def test_publish_drives_the_shared_command_spine(tmp_path: Path) -> None:
    """A publish from the command line returns the same commit receipt the edge does."""
    session = _session()
    path = _write(tmp_path / "publish.json", _publish_envelope())

    receipt = await run_publish(session, path)

    assert receipt.outcome == "accepted"
    assert receipt.receipt_class == "commit"
    assert receipt.result is not None
    assert receipt.result.data["outcome"] == "created"
    # The effect is durable: the published version is in the store.
    assert len(receipt.stream_positions) == 1


async def test_deploy_drives_the_shared_command_spine(tmp_path: Path) -> None:
    """A deploy from the command line commits a satisfied revision."""
    session = _session()
    path = _write(tmp_path / "deploy.json", _deploy_envelope())

    receipt = await run_deploy(session, path)

    assert receipt.outcome == "accepted"
    assert receipt.receipt_class == "commit"
    assert receipt.result is not None
    assert receipt.result.data["satisfied"] is True


async def test_export_discovers_the_single_published_version(tmp_path: Path) -> None:
    """With one published version in the store, an export needs no flag."""
    session = _session()
    await run_publish(session, _write(tmp_path / "publish.json", _publish_envelope()))

    out = tmp_path / "dataset"
    export = await run_export(session, out, provenance=_GIT)

    assert [b.dataset_kind for b in export.bundles] == ["events"]
    events = out / "events.ndjson"
    assert events.exists()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["lineage"][0]["git_provenance"]["commit"] == "0" * 40
    # Each row is a payload-free canonical envelope: a digest, never a raw value.
    rows = [json.loads(line) for line in events.read_text().splitlines()]
    assert rows and all("payload_digest" in row for row in rows)
    assert all("candidate" not in row for row in rows)


async def test_export_is_reproducible_from_the_ledger(tmp_path: Path) -> None:
    """The same ledger and the same fixed clock reproduce identical bundle digests."""
    session = _session()
    await run_publish(session, _write(tmp_path / "publish.json", _publish_envelope()))

    first = await run_export(session, tmp_path / "a", provenance=_GIT)
    second = await run_export(session, tmp_path / "b", provenance=_GIT)

    assert first.bundles[0].bundle_digest == second.bundles[0].bundle_digest
    assert (tmp_path / "a/events.ndjson").read_bytes() == (
        tmp_path / "b/events.ndjson"
    ).read_bytes()


async def test_export_without_a_published_version_asks_for_the_flag() -> None:
    """An export over a store with no published version fails with a clear message."""
    session = _session()
    with pytest.raises(CliError, match="no published study version"):
        discover_study_version(session.store)


async def test_stop_reports_the_platform_gap() -> None:
    """The stop verb reports that no stop handler exists, rather than inventing one."""
    with pytest.raises(CliError, match="not available"):
        run_stop()


def test_git_provenance_reads_the_working_tree() -> None:
    """The provenance reader turns git output into a provenance ref."""
    replies = {
        ("rev-parse", "HEAD"): "f" * 40,
        ("rev-parse", "--abbrev-ref", "HEAD"): "feature/x",
        ("status", "--porcelain"): " M file.py",
        ("diff", "HEAD"): "diff --git a/file.py b/file.py\n+change\n",
    }
    provenance = git_provenance(run=lambda argv: replies[tuple(argv)])
    assert provenance.commit == "f" * 40
    assert provenance.branch == "feature/x"
    assert provenance.dirty is True
    # A dirty tree names a digest of its diff, so the change is accountable.
    assert provenance.patch_digest is not None


async def test_simulate_drains_a_rediscovered_job() -> None:
    """A queued job the store holds is rediscovered and drained to success."""
    store = InMemoryStore()
    session = _session(store)
    runner = JobRunner(
        store=store,
        now=lambda: _FIXED,
        lease_ttl=timedelta(seconds=30),
        lease_epoch_id=session.gateway.new_id("leaseepoch"),
        new_lease_id=lambda: session.gateway.new_id("lease"),
    )
    job_id = "job_019b6000-0000-7000-8000-0000000000f1"
    work_key = Digest(algorithm="sha-256", hex="c" * 64)
    receipt, _ = await runner.submit(
        context=session.mint_context(command="job.submit", target_id=job_id),
        job_kind="simulate-batch",
        work_key=work_key,
        submitted_at="2026-07-23T00:00:00.000000Z",
    )
    assert receipt.outcome == "accepted"

    async def handler(_: object) -> WorkOutcome:
        return WorkOutcome(outcome="success")

    # A fresh session (a "restart") rediscovers the queued job from the store.
    drained = await run_simulate(_session(store), handler=handler)
    assert drained == 1


def _render(surface: Surface, _state: object) -> None:
    surface.circle(x=0.5, y=0.5, radius=0.02, color="#f00", object_id="dot")


class _FakeEnv:
    def __init__(self) -> None:
        self._t = 0

    def reset(self, *, seed: int | None = None) -> tuple[list[float], dict[str, Any]]:
        self._t = 0
        return [0.0], {}

    def step(
        self, action: int
    ) -> tuple[list[float], float, bool, bool, dict[str, Any]]:
        self._t += 1
        return [float(self._t)], -1.0, self._t >= 3, False, {}


async def _play(episode_id: str, interaction_id: str) -> EpisodeSummary:
    async def sink(_packet: object) -> None:
        return None

    return await run_episode(
        GymEnv(cast("EnvFactory", lambda: _FakeEnv())),
        render=_render,
        channel_key="fake-game",
        episode_id=episode_id,
        interaction_id=interaction_id,
        seat_key="player",
        input_state=InputState({"Go": 1}, 0),
        sink=sink,
        now=lambda: "2026-07-23T00:00:00.000000Z",
        fps=0,
        max_steps=10,
    )


async def test_replay_assembles_a_bundle_from_an_episode(tmp_path: Path) -> None:
    """A replay reads a captured episode's stream and writes a bundle manifest."""
    store = InMemoryStore()
    session = _session(store)
    episode_id = "episode_019b6000-0000-7000-8000-0000000000e1"
    interaction_id = "interaction_019b6000-0000-7000-8000-0000000000f0"
    summary = await _play(episode_id, interaction_id)
    context = session.mint_context(command="episode.capture", target_id=episode_id)
    await capture_episode(
        summary,
        visit_id="visit_019b6000-0000-7000-8000-0000000000b0",
        context=context,
        store=store,
    )

    bundle = await run_replay(
        session,
        tmp_path / "replay",
        interaction_id=interaction_id,
        stream_ids=[context.stream_id],
    )

    assert bundle.event_count > 0
    assert (tmp_path / "replay/replay-manifest.json").exists()


async def test_replay_needs_at_least_one_stream(tmp_path: Path) -> None:
    """A replay with no stream fails with a clear message."""
    with pytest.raises(CliError, match="at least one --stream"):
        await run_replay(
            _session(), tmp_path / "r", interaction_id="interaction_x", stream_ids=[]
        )


def test_the_parser_exposes_every_verb() -> None:
    """The parser knows each command verb."""
    for verb in ("publish", "deploy", "stop", "export", "replay", "simulate"):
        assert build_parser().parse_args([verb, *_verb_args(verb)]).verb == verb


def _verb_args(verb: str) -> list[str]:
    fillers = {
        "publish": ["x.json"],
        "deploy": ["x.json"],
        "export": ["out"],
        "replay": ["out", "--interaction", "i"],
        "simulate": ["--handler", "m:f"],
    }
    return fillers.get(verb, [])


def test_main_maps_the_stop_gap_to_a_nonzero_exit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The entry point maps the stop gap to a non-zero exit and a clear message."""
    code = main(["stop"])
    assert code == 1
    assert "not available" in capsys.readouterr().err
