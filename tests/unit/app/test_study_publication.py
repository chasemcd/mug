"""The study that runs is the study that was published.

There were two study surfaces and they never met: `build_study_app` ran the
`Study` object directly, and the whole API-01 compile-and-publish pipeline sat
beside it with nothing to compile. So nothing pinned what actually ran -- the
launch gate minted a study version whose manifest digest was a literal stub, and
`mug export` could not export a study the application had run, because
`discover_study_version` found no published version in the store.

These tests drive the real compiler and the real publication handler over studies
the application runs, and check what a published version is for: it is derived from
the study, so it is stable across restarts and changes when the study changes; its
manifest digests are the digests of bytes that were actually staged; what reaches a
client discloses nothing internal; and a study the compiler refuses does not
publish.
"""

from __future__ import annotations

import json
from typing import Any, cast

from fastapi.testclient import TestClient

from mug.app import build_study_app
from mug.authoring import (
    ClientManifest,
    ProvenanceManifest,
    ScientificManifest,
    StudyServerManifest,
)
from mug.authoring.types import PublishedStudyVersion
from mug.cli.commands import discover_study_version
from mug.content import Choice, Comparison, Form, Game, Page, Study
from mug.content.publish import PublishedStudy, study_digest
from mug.gateway import Gateway
from mug.kernel.refs import DeploymentRevisionRef, StudyVersionRef
from mug.storage import InMemoryStore, digest_of

_SECRET = b"a shared deployment secret"


def _study() -> Study:
    """The study under test: a consent form, two rounds, a comparison, a debrief."""
    return Study(
        Form("consent", Choice("agree", "Do you consent to take part?", ["yes", "no"])),
        Game("practice"),
        Game("play"),
        Comparison(
            key="which-was-better",
            ask="Which round went better?",
            options={"Practice": "practice", "Real round": "play"},
        ),
        Page("debrief", "# Thank you"),
    )


def _app(
    store: InMemoryStore, study: Study | None = None, **config: Any
) -> TestClient:
    return TestClient(
        build_study_app(
            study=study or _study(),
            store=store,
            gateway=Gateway(secret=_SECRET),
            **config,
        )
    )


def _published_study(client: TestClient) -> PublishedStudy:
    """Return what the application compiled and published when it was built."""
    return cast("PublishedStudy", getattr(client.app, "state").study)  # noqa: B009


def _version(client: TestClient) -> StudyVersionRef:
    """Return the study version the application is running."""
    return cast("StudyVersionRef", getattr(client.app, "state").study_version)  # noqa: B009


def _deployment(client: TestClient) -> DeploymentRevisionRef:
    """Return the deployment revision the launch ticket admits a participant to."""
    return cast("DeploymentRevisionRef", getattr(client.app, "state").deployment)  # noqa: B009


# -- publishing ------------------------------------------------------------------


def test_the_application_publishes_the_study_it_is_about_to_run() -> None:
    """The whole point: a running application has a published study version."""
    store = InMemoryStore()
    client = _app(store)

    published = _published_study(client)
    assert published.published is True
    assert published.report.valid is True
    # And the shipped command line finds it, which it could not before.
    assert (
        discover_study_version(store).study_version_id
        == published.study_version.study_version_id
    )


def test_the_manifest_digest_is_not_a_stub() -> None:
    """The version names the digest of a manifest that was really staged."""
    store = InMemoryStore()
    client = _app(store)
    version = _version(client)

    assert version.manifest_digest.hex != "a" * 64
    record = _published_record(store)
    artifact_id = record.scientific.artifact.artifact_id
    # Re-digesting the staged bytes reproduces what the version pinned.
    assert digest_of(_bytes(store, artifact_id)).hex == version.manifest_digest.hex
    body = _read(store, artifact_id)
    assert ScientificManifest.model_validate(body).study_id == version.study_id


def test_publishing_twice_publishes_one_version() -> None:
    """A restart republishes the same study, so a store gathers one version."""
    store = InMemoryStore()
    first = _version(_app(store))
    again = _version(_app(store))

    assert first.study_version_id == again.study_version_id
    assert len(_versions(store)) == 1


def test_an_edited_study_publishes_a_new_version() -> None:
    """One question changed is one study changed, and the version says so."""
    store = InMemoryStore()
    first = _version(_app(store))

    edited = Study(
        Form("consent", Choice("agree", "Do you agree to take part?", ["yes", "no"])),
        Game("practice"),
        Game("play"),
        Comparison(
            key="which-was-better",
            ask="Which round went better?",
            options={"Practice": "practice", "Real round": "play"},
        ),
        Page("debrief", "# Thank you"),
    )
    second = _version(_app(store, edited))

    assert second.study_version_id != first.study_version_id
    assert second.manifest_digest.hex != first.manifest_digest.hex
    assert len(_versions(store)) == 2
    assert study_digest(_study()).hex != study_digest(edited).hex


def test_a_study_the_compiler_refuses_does_not_publish() -> None:
    """A comparison over a round the study never plays is a compile-time mistake."""
    store = InMemoryStore()
    broken = Study(
        Game("play"),
        Comparison(
            key="which-was-better",
            ask="Which round went better?",
            options={"Played": "play", "Never played": "missing"},
        ),
    )
    client = _app(store, broken)
    published = _published_study(client)

    assert published.published is False
    assert published.report.valid is False
    codes = {one.code for one in published.report.diagnostics}
    assert codes == {"study.comparison.unknown_activity"}
    # The candidate says so itself, and the publication was never attempted: a
    # refused study must not reach the handler and be turned back at the gate.
    assert published.candidate.release_eligibility == "design_unpublishable"
    assert published.receipt is None
    assert _versions(store) == []
    # The application still serves the study: a compile complaint must not be an
    # outage for a study that is already live.
    assert client.app is not None


# -- what the manifests say ------------------------------------------------------


def test_the_client_manifest_discloses_nothing_internal() -> None:
    """What reaches a browser names activity keys and capabilities, and no id."""
    store = InMemoryStore()
    _app(store)
    record = _published_record(store)
    body = _read(store, record.clients[0].manifest.artifact.artifact_id)

    manifest = ClientManifest.model_validate(body)
    assert {binding.activation_slot for binding in manifest.components} == {
        "consent",
        "practice",
        "play",
        "which-was-better",
        "debrief",
    }
    assert "mug.activity.comparison.v1" in manifest.required_capabilities
    text = json.dumps(body)
    for prefix in ("study_", "studyver_", "activitydef_", "flownode_", "artifact_"):
        assert prefix not in text, f"the client manifest disclosed {prefix}"


def test_the_client_manifest_declares_the_accessibility_a_study_delivers() -> None:
    """The floor, not the best: a study with a game canvas is a ``wcag-a`` study.

    The study under test plays two rounds, and a screen reader has nothing to read
    in a canvas. Reporting the consent form's ``aa`` would make the manifest
    marketing rather than a record (``mug.content.components``).
    """
    store = InMemoryStore()
    _app(store)
    with_game = ClientManifest.model_validate(
        _read(store, _published_record(store).clients[0].manifest.artifact.artifact_id)
    )
    assert with_game.accessibility_profile == "wcag-a"

    forms_only = InMemoryStore()
    _app(
        forms_only,
        Study(
            Form("consent", Choice("agree", "Do you consent?", ["yes", "no"])),
            Page("debrief", "# Thank you"),
        ),
    )
    without_game = ClientManifest.model_validate(
        _read(
            forms_only,
            _published_record(forms_only).clients[0].manifest.artifact.artifact_id,
        )
    )
    assert without_game.accessibility_profile == "wcag-aa"


def test_the_server_manifest_binds_every_activity() -> None:
    """The runtime side names a scope and a binding for each activity."""
    store = InMemoryStore()
    _app(store)
    record = _published_record(store)
    manifest = StudyServerManifest.model_validate(
        _read(store, record.server.artifact.artifact_id)
    )

    assert {scope.scope_key for scope in manifest.scopes} == {
        "consent-runtime",
        "practice-runtime",
        "play-runtime",
        "which-was-better-runtime",
        "debrief-runtime",
    }
    assert len(manifest.bindings) == 5


def test_the_provenance_says_what_the_build_could_not_establish() -> None:
    """An unknown source commit is declared, not papered over with a clean one."""
    store = InMemoryStore()
    _app(store)
    record = _published_record(store)
    manifest = ProvenanceManifest.model_validate(
        _read(store, record.provenance.artifact.artifact_id)
    )

    # The tests do not set MUG_GIT_COMMIT, so the build cannot name its source.
    assert manifest.source_git.commit == "0" * 40
    assert "provenance.git.unknown" in manifest.limitations
    assert {output.role for output in manifest.projection_outputs} == {
        "client",
        "server",
    }


def test_every_manifest_digest_re_derives_from_the_bytes_that_were_staged() -> None:
    """A manifest set of digests nobody can check is not provenance."""
    store = InMemoryStore()
    _app(store)
    record = _published_record(store)

    for manifest in (
        record.scientific,
        record.server,
        record.provenance,
        record.clients[0].manifest,
    ):
        staged = _bytes(store, manifest.artifact.artifact_id)
        assert digest_of(staged).hex == manifest.content_digest.hex
        assert digest_of(staged).hex == manifest.artifact.digest.hex
        assert len(staged) == manifest.artifact.size_bytes


# -- what the rest of the platform sees ------------------------------------------


def test_the_launch_ticket_names_the_published_version() -> None:
    """A gated visit enters against the study that was published, not a stub."""
    store = InMemoryStore()
    client = _app(store, require_launch=True)
    version = _version(client)

    assert getattr(client.app, "state").launch_ticket  # noqa: B009
    deployment = _deployment(client)
    # The ticket admits a participant to *this* study version, not to a stub.
    assert deployment.study_version.study_version_id == version.study_version_id
    assert deployment.study_version.manifest_digest.hex == version.manifest_digest.hex
    assert deployment.manifest_digest.hex != "a" * 64
    assert store.load_aggregate(deployment.deployment_revision_id) is not None


async def test_the_command_line_publishes_the_same_version_the_app_does() -> None:
    """One study, one version -- whoever publishes it.

    A study published from the command line and a study published by a running
    deployment must be the same version, because both derive it from the study.
    Otherwise a researcher's export names a version their participants never ran.
    """
    from mug.cli.commands import run_publish_study
    from mug.cli.session import CliSession, DurableStore

    store = InMemoryStore()
    from_app = _version(_app(store))

    session = CliSession.open(
        store=cast("DurableStore", store), gateway=Gateway(secret=_SECRET)
    )
    published = await run_publish_study(
        session, "tests.unit.app.test_study_publication:_study"
    )

    assert published.study_version.study_version_id == from_app.study_version_id
    assert len(_versions(store)) == 1


# -- reading what was recorded ---------------------------------------------------


def _versions(store: InMemoryStore) -> list[str]:
    """Return every published study version aggregate in the store."""
    return sorted(
        aggregate_id
        for aggregate_id, _ in store.scan_aggregates()
        if aggregate_id.startswith("studyver_")
    )


def _published_record(store: InMemoryStore) -> PublishedStudyVersion:
    """Return the one published study version the store holds."""
    versions = _versions(store)
    assert len(versions) == 1
    return PublishedStudyVersion.model_validate(store.load_aggregate(versions[0]))


def _bytes(store: InMemoryStore, artifact_id: str) -> bytes:
    """Return one staged artifact's bytes (the object store keeps them in memory)."""
    return store._objects[artifact_id]  # pyright: ignore[reportPrivateUsage]


def _read(store: InMemoryStore, artifact_id: str) -> dict[str, Any]:
    """Read one staged manifest back into the object it holds."""
    return cast("dict[str, Any]", json.loads(_bytes(store, artifact_id).decode()))
