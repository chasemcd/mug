"""The command-line verbs, each thin wiring over one family runtime.

Every verb opens no new path into a family: a publish and a deploy drive the
shared ``dispatch_command`` the edge drives; a simulate composes the durable job
runtime and drains its queue; an export and a replay call the same export and
replay runtime a deployment calls. A verb gathers inputs, calls one runtime, and
reports the result. It holds no domain logic.
"""

from __future__ import annotations

import importlib
import json
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from mug.cli.session import CliSession, git_provenance, load_envelope
from mug.edge import dispatch_command
from mug.export import export_study_dataset
from mug.export.dataset import DatasetExport
from mug.export.types import GitProvenanceRef
from mug.kernel import CommandReceipt
from mug.kernel.refs import StudyVersionRef
from mug.replay import ReplayBundle, build_replay_bundle
from mug.storage import ArtifactStore, Store
from mug.workers import JobQueue, JobRunner, WorkerPool, WorkHandler

if TYPE_CHECKING:
    from mug.kernel.privacy import DataHandlingRef

_RESEARCH_LABELS = ["research"]


class CliError(Exception):
    """A user-facing failure the command line reports and exits on."""


def _research() -> DataHandlingRef:
    from mug.kernel.privacy import DataHandlingRef

    return DataHandlingRef(privacy_labels=_RESEARCH_LABELS)


# --- publish / deploy: drive the shared command spine -----------------------


async def run_publish(session: CliSession, envelope_path: Path) -> CommandReceipt:
    """Publish a compiled study by driving ``study.publish`` through the spine.

    The command line loads the prepared command envelope the study compiler emits
    and dispatches it through the one command path the edge uses, so a publish from
    the command line and a publish from a client reach the authoring runtime the
    same way.
    """
    return await dispatch_command(
        "study.publish",
        load_envelope(envelope_path),
        gateway=session.gateway,
        store=session.store,
        principal=session.principal,
    )


async def run_deploy(session: CliSession, envelope_path: Path) -> CommandReceipt:
    """Deploy a published study version by driving ``platform.deploy``."""
    return await dispatch_command(
        "platform.deploy",
        load_envelope(envelope_path),
        gateway=session.gateway,
        store=session.store,
        principal=session.principal,
    )


def run_stop() -> CommandReceipt:
    """Report that no stop handler exists yet (a known platform gap).

    The platform models a deployment as an append-only chain of immutable
    revisions; it has no stop or teardown command handler. The command line does
    not invent a second path, so ``mug stop`` fails with a clear, honest message
    until the platform grows a stop command.
    """
    raise CliError(
        "mug stop is not available: the platform has no stop command yet "
        "(a deployment is an append-only chain of revisions). Deploy a new "
        "revision to change what is served."
    )


# --- export: read the whole ledger, one bundle per dataset kind -------------


def discover_study_version(store: Store) -> StudyVersionRef:
    """Find the one published study version in the store, or fail clearly.

    An export names the study version it exports. When a store holds exactly one
    published version, the command line reads it, so the common case needs no
    flag. Zero or many published versions fail with a message that asks for the
    ``--study-version`` file, so the export is never ambiguous.
    """
    from mug.authoring import PublishedStudyVersion

    found: list[StudyVersionRef] = []
    for aggregate_id, state in store.scan_aggregates():
        if not aggregate_id.startswith("studyver_"):
            continue
        found.append(PublishedStudyVersion.model_validate(state).study_version)
    if len(found) == 1:
        return found[0]
    if not found:
        raise CliError(
            "no published study version in the store; pass --study-version FILE"
        )
    raise CliError(
        f"{len(found)} published study versions in the store; "
        "pass --study-version FILE to name the one to export"
    )


def _load_study_version(path: Path) -> StudyVersionRef:
    return StudyVersionRef.model_validate_json(path.read_text(encoding="utf-8"))


async def run_export(
    session: CliSession,
    out_dir: Path,
    *,
    kinds: list[str] | None = None,
    study_version_path: Path | None = None,
    export_key: str = "dataset",
    provenance: GitProvenanceRef | None = None,
) -> DatasetExport:
    """Export a study's whole ledger as one ndjson file per non-empty kind.

    The command line resolves the study version (a flag, else the one published
    version in the store), reads the working tree's git provenance, and runs the
    export runtime. It then writes each bundle's ndjson to ``out_dir`` and a
    ``manifest.json`` that names the bundles, their lineage, and the row schema.
    """
    study_version = (
        _load_study_version(study_version_path)
        if study_version_path is not None
        else discover_study_version(session.store)
    )
    git = provenance if provenance is not None else git_provenance()
    export = await export_study_dataset(
        store=session.store,
        artifacts=session.store,
        study_version=study_version,
        git_provenance=git,
        new_artifact_id=lambda: session.gateway.new_id("artifact"),
        new_upload_id=lambda: session.gateway.new_id("upload"),
        now=session.now,
        kinds=kinds if kinds is not None else _default_kinds(),
        export_key=export_key,
    )
    await _write_export(session.store, out_dir, export)
    return export


def _default_kinds() -> list[str]:
    from mug.export.dataset import DATASET_KINDS

    return list(DATASET_KINDS)


async def _write_export(
    store: ArtifactStore, out_dir: Path, export: DatasetExport
) -> None:
    """Write each bundle's ndjson and a manifest of the whole export."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for bundle in export.bundles:
        data = await store.read_artifact(bundle.artifact.artifact_id)
        (out_dir / f"{bundle.dataset_kind}.ndjson").write_bytes(data)
    manifest = {
        "bundles": [
            b.model_dump(mode="json", exclude_none=True) for b in export.bundles
        ],
        "lineage": [
            r.model_dump(mode="json", exclude_none=True) for r in export.lineage
        ],
        "bindings": [
            b.model_dump(mode="json", exclude_none=True) for b in export.bindings
        ],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


# --- replay: assemble one interaction's replay bundle -----------------------


async def run_replay(
    session: CliSession,
    out_dir: Path,
    *,
    interaction_id: str,
    stream_ids: list[str],
) -> ReplayBundle:
    """Assemble a replay bundle for one interaction's canonical streams.

    The command line reads the named streams from the store, builds the bundle
    through the replay runtime (artifacts land in the store), and writes the
    manifest to ``out_dir``, so a reviewer can validate the recorded run.
    """
    if not stream_ids:
        raise CliError("mug replay needs at least one --stream to assemble")
    bundle = await build_replay_bundle(
        store=session.store,
        artifacts=session.store,
        interaction_id=interaction_id,
        stream_ids=stream_ids,
        new_artifact_id=lambda: session.gateway.new_id("artifact"),
        new_upload_id=lambda: session.gateway.new_id("upload"),
        now=session.now,
        data_handling=_research(),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "replay-manifest.json").write_text(
        json.dumps(
            bundle.manifest.model_dump(mode="json", exclude_none=True),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return bundle


# --- simulate: drain the durable job queue ----------------------------------


def resolve_handler(spec: str) -> WorkHandler:
    """Resolve a ``module:function`` work handler a study provides.

    A simulation's work -- run an episode, compile a candidate -- is the study's,
    not the command line's. The study names its handler as ``module:function`` and
    the command line imports it, so no simulation logic lives in the tool.
    """
    module_name, separator, attribute = spec.partition(":")
    if not separator or not attribute:
        raise CliError(
            f"a job handler is 'module:function', not {spec!r}"
        )
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise CliError(
            f"cannot import handler module {module_name!r}: {error}"
        ) from error
    handler = getattr(module, attribute, None)
    if handler is None:
        raise CliError(f"handler {attribute!r} not found in {module_name!r}")
    return handler


async def run_simulate(
    session: CliSession,
    *,
    handler: WorkHandler,
    workers: int = 1,
    lease_ttl_seconds: float = 30.0,
) -> int:
    """Rediscover queued jobs in the store and drain them, returning the count.

    The command line composes the durable job runtime -- a fenced ``JobRunner``, a
    ``JobQueue`` rebuilt from the committed store, and a ``WorkerPool`` -- and
    drains the queue over the study's handler. Every claim and completion mints its
    context from the one gateway boundary, so the batch runs on the same command
    spine a live worker uses. A restart rediscovers the same queued work.
    """
    runner = JobRunner(
        store=session.store,
        now=session.gateway.clock,
        lease_ttl=timedelta(seconds=lease_ttl_seconds),
        lease_epoch_id=session.gateway.new_id("leaseepoch"),
        new_lease_id=lambda: session.gateway.new_id("lease"),
    )
    queue = JobQueue()
    queue.rebuild(session.store)
    pool = WorkerPool(
        runner=runner,
        queue=queue,
        store=session.store,
        handler=handler,
        new_context=lambda job_id: session.mint_context(
            command="job.step", target_id=job_id
        ),
        workers=workers,
    )
    return await pool.drain()


__all__ = [
    "CliError",
    "discover_study_version",
    "resolve_handler",
    "run_deploy",
    "run_export",
    "run_publish",
    "run_replay",
    "run_simulate",
    "run_stop",
]
