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
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from mug.app import derived_idempotency_key
from mug.authoring import GitProvenance
from mug.cli.session import CliSession, git_provenance, load_envelope
from mug.content import Study
from mug.content.publish import PublishedStudy
from mug.edge import dispatch_command
from mug.export import export_study_dataset
from mug.export.dataset import DatasetExport
from mug.export.types import GitProvenanceRef
from mug.game.capture import recorded_trajectory
from mug.kernel import ArtifactRef, CommandReceipt, DataHandlingRef
from mug.kernel.refs import StudyVersionRef
from mug.platform.deployment import set_disposition
from mug.platform.types import Deployment, DeploymentDisposition
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


def _cli_git_provenance() -> GitProvenance:
    """Return the checkout a command-line publish was made from.

    The command line runs in the repository, so it reads the real commit. A dirty
    tree is declared as a limitation rather than as ``dirty``, because the frozen
    record only marks a dirty tree with the patch that made it dirty and the command
    line stages no patch.
    """
    found = git_provenance()
    return GitProvenance(commit=found.commit, branch=found.branch, dirty=False)


def _cli_git_limitations() -> list[str]:
    """Return what a command-line publish could not establish about its source."""
    return ["provenance.git.dirty_tree"] if git_provenance().dirty else []


def load_study(spec: str) -> Study:
    """Resolve a ``module:attribute`` reference to the study it names.

    A study is Python -- the author writes ``Study(Form(...), Game(...))`` in their
    own module -- so publishing from the command line names that value rather than a
    JSON envelope somebody assembled by hand. The attribute may be the study or a
    callable that returns one, which is how most study modules are written.
    """
    module_name, _, attribute = spec.partition(":")
    if not module_name or not attribute:
        raise CliError("a study is named as 'module:attribute'")
    try:
        module = import_module(module_name)
    except ImportError as error:
        raise CliError(f"no module named {module_name!r}") from error
    found = getattr(module, attribute, None)
    if found is None:
        raise CliError(f"{module_name!r} has no {attribute!r}")
    study = found() if callable(found) else found
    if not isinstance(study, Study):
        raise CliError(f"{spec} is not a Study")
    return study


async def run_publish_study(session: CliSession, spec: str) -> PublishedStudy:
    """Compile the study a module names and publish it through the real handler.

    This is the same compile the application runs on every start, so a study
    published from the command line and a study published by a running deployment
    reach the identical version -- the identifiers derive from the study itself.
    """
    from mug.content.publish import compile_and_publish

    published = await compile_and_publish(
        load_study(spec),
        store=session.store,
        artifacts=session.store,
        derive=session.gateway.derived_id,
        new_context=lambda aggregate_id: session.gateway.mint(
            session.envelope(
                command="study.publish",
                target_id=aggregate_id,
                data={},
                idempotency_key=derived_idempotency_key(
                    session.gateway, f"publish:{aggregate_id}"
                ),
            ),
            principal=session.principal,
            data_handling=DataHandlingRef(privacy_labels=["research"]),
        ),
        new_artifact_id=lambda seed: session.gateway.derived_id("artifact", seed),
        new_upload_id=lambda: session.gateway.new_id("upload"),
        now=session.now,
        git=_cli_git_provenance(),
        limitations=_cli_git_limitations(),
    )
    if not published.published:
        written = "; ".join(one.safe_message for one in published.report.diagnostics)
        raise CliError(
            "the study did not publish: " + (written or "it is no release candidate")
        )
    return published


async def run_deploy(session: CliSession, envelope_path: Path) -> CommandReceipt:
    """Deploy a published study version by driving ``platform.deploy``."""
    return await dispatch_command(
        "platform.deploy",
        load_envelope(envelope_path),
        gateway=session.gateway,
        store=session.store,
        principal=session.principal,
    )


async def run_stop(
    session: CliSession, deployment_id: str, *, start: bool = False
) -> Deployment:
    """Stop a deployment, or start a stopped one again.

    Stopping is not deleting. The revisions stay, the visits already running are not
    touched, and starting it again serves the revision it was serving. What changes
    is that new participants are refused at the door -- which is what a researcher
    means by pausing recruitment.
    """
    disposition: DeploymentDisposition = "live" if start else "stopped"
    _, deployment = await set_disposition(
        deployment_id=deployment_id,
        disposition=disposition,
        context=session.mint_context(
            command="deployment.set-disposition", target_id=deployment_id
        ),
        store=session.store,
    )
    if deployment is None:
        raise CliError(f"no deployment {deployment_id!r} in the store")
    return deployment


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
    export runtime. It then writes each bundle's ndjson to ``out_dir``, a
    ``<kind>.values.ndjson`` per research kind holding what those aggregates
    committed, and a ``manifest.json`` that names the bundles, their lineage, the
    values, and the row schema.
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


def _referenced_artifacts(rows: list[dict[str, Any]]) -> list[str]:
    """Return every artifact a values row points at, in a stable order.

    A values row names its evidence rather than holding it: an episode names its
    trajectory, a generation names its three forms, a form response names its
    answers. Writing the rows and not the things they name would put the reader back
    where the digests-only export left them, so the export follows the references.
    """
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            body = cast("dict[str, Any]", node)
            artifact_id = body.get("artifact_id")
            if isinstance(artifact_id, str) and "digest" in body:
                found.append(artifact_id)
                return
            for value in body.values():
                walk(value)
        elif isinstance(node, list):
            for value in cast("list[Any]", node):
                walk(value)

    walk(rows)
    return sorted(dict.fromkeys(found))


async def _write_export(
    store: ArtifactStore, out_dir: Path, export: DatasetExport
) -> None:
    """Write each bundle, its values, the artifacts they name, and one manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for bundle in export.bundles:
        data = await store.read_artifact(bundle.artifact.artifact_id)
        (out_dir / f"{bundle.dataset_kind}.ndjson").write_bytes(data)
    referenced: list[str] = []
    for values in export.values:
        data = await store.read_artifact(values.artifact.artifact_id)
        (out_dir / f"{values.dataset_kind}.values.ndjson").write_bytes(data)
        rows = [
            cast("dict[str, Any]", json.loads(line))
            for line in data.decode("utf-8").splitlines()
            if line.strip()
        ]
        referenced.extend(_referenced_artifacts(rows))
    written: list[str] = []
    if referenced:
        (out_dir / "artifacts").mkdir(exist_ok=True)
        for artifact_id in sorted(dict.fromkeys(referenced)):
            body = await store.read_artifact(artifact_id)
            (out_dir / "artifacts" / f"{artifact_id}.json").write_bytes(body)
            written.append(artifact_id)
    manifest = {
        "artifacts": written,
        "requests": [
            r.model_dump(mode="json", exclude_none=True) for r in export.requests
        ],
        "bundles": [
            b.model_dump(mode="json", exclude_none=True) for b in export.bundles
        ],
        "lineage": [
            r.model_dump(mode="json", exclude_none=True) for r in export.lineage
        ],
        "bindings": [
            b.model_dump(mode="json", exclude_none=True) for b in export.bindings
        ],
        "values": [
            {
                "dataset_kind": v.dataset_kind,
                "artifact": v.artifact.model_dump(mode="json", exclude_none=True),
                "row_count": v.row_count,
            }
            for v in export.values
        ],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


# --- replay: assemble one interaction's replay bundle -----------------------


def _recorded_trajectory(
    session: CliSession, stream_ids: list[str]
) -> ArtifactRef | None:
    """Return the trajectory the named streams' episode recorded, if there is one."""
    for stream_id in stream_ids:
        episode_id = "episode_" + stream_id.split("_", 1)[1]
        recorded = recorded_trajectory(session.store, episode_id)
        if recorded is not None:
            return recorded
    return None


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

    An episode's stream shares its aggregate's identifier body, so the recorded
    trajectory is found from the stream alone -- a bundle assembled here carries the
    same values a bundle assembled by the transport does, and a run that recorded
    none is refused rather than given a replay it cannot perform.
    """
    if not stream_ids:
        raise CliError("mug replay needs at least one --stream to assemble")
    trajectory = _recorded_trajectory(session, stream_ids)
    bundle = await build_replay_bundle(
        store=session.store,
        artifacts=session.store,
        interaction_id=interaction_id,
        stream_ids=stream_ids,
        new_artifact_id=lambda: session.gateway.new_id("artifact"),
        new_upload_id=lambda: session.gateway.new_id("upload"),
        now=session.now,
        data_handling=_research(),
        trajectory=trajectory,
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
    """Rediscover waiting jobs in the store and drain them, returning the count.

    The command line composes the durable job runtime -- a fenced ``JobRunner``, a
    ``JobQueue`` rebuilt from the committed store, and a ``WorkerPool`` -- and
    drains the queue over the study's handler. Every claim and completion mints its
    context from the one gateway boundary, so the batch runs on the same command
    spine a live worker uses. A restart rediscovers the same waiting work: a job that
    never started, and a job whose earlier worker went away with its lease.
    """
    runner = JobRunner(
        store=session.store,
        now=session.gateway.clock,
        lease_ttl=timedelta(seconds=lease_ttl_seconds),
        lease_epoch_id=session.gateway.new_id("leaseepoch"),
        new_lease_id=lambda: session.gateway.new_id("lease"),
    )
    queue = JobQueue()
    queue.rebuild(session.store, runner)
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
