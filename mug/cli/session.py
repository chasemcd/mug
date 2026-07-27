"""The command-line front end's boundary to the runtime.

The command line is one more actor on the command spine, beside the HTTP edge. It
opens the same store a deployment opens, holds one ``Gateway`` -- the single
clock-and-entropy boundary -- and drives a command through the exact
``dispatch_command`` path the edge uses. It holds no domain logic; it wires.

``CliSession`` gathers that boundary in one place: the store, the gateway, the
service principal the command line acts as, and the small helpers a command needs
(a wire envelope for context minting, a fresh idempotency key, the deterministic
id minters an export or a replay bundle takes, and the git provenance of the
working tree). A command function takes a session and calls one family runtime.
"""

from __future__ import annotations

import itertools
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from mug.app import gateway_secret_from_env, store_from_env
from mug.export.types import GitProvenanceRef
from mug.gateway import Gateway
from mug.kernel import DataHandlingRef, Digest, PrincipalRef, WireCommandEnvelope
from mug.runtime import CommandContext
from mug.storage import ArtifactStore, Store, digest_of


class DurableStore(Store, ArtifactStore, Protocol):
    """A backend that is both an event store and an artifact store.

    Every concrete backend implements both ports, so one instance drives the
    command spine and holds the export and replay artifacts. The command line
    holds this combined view, so an export or a replay reads and writes artifacts
    over the same store it commits commands to.
    """

# The privacy classification the command line attaches to an event it originates.
_RESEARCH: DataHandlingRef = DataHandlingRef(privacy_labels=["research"])

# The command line acts as one fixed service principal; it never claims a
# participant or a researcher, so its events are always attributed to the tool.
CLI_PRINCIPAL: PrincipalRef = PrincipalRef(
    kind="service", id="service_019b6000-0000-7000-8000-0000000000c1"
)

# A structural digest for the envelope and payload schema references. The gateway
# content-addresses a context from the payload DATA, not from these, so a fixed
# placeholder is enough to make a well-formed envelope for context minting.
_PLACEHOLDER: Digest = Digest(algorithm="sha-256", hex="0" * 64)

_GitRunner = Callable[[list[str]], str]


def _schema(name: str) -> dict[str, object]:
    """Build a structural schema reference dict for an envelope the tool mints."""
    return {"name": name, "version": 0, "digest": _PLACEHOLDER.model_dump(mode="json")}


def _run_git(argv: list[str]) -> str:
    """Run one git command in the working tree and return its stripped output."""
    result = subprocess.run(
        ["git", *argv],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def git_provenance(*, run: _GitRunner = _run_git) -> GitProvenanceRef:
    """Read the working tree's commit, branch, and dirty flag from git.

    The command line knows the code state that produced an export, so it reads it
    from the repository rather than taking it on trust. ``run`` is injected, so a
    test provides a fixed reader instead of shelling out. A dirty tree also names a
    digest of its diff, so an uncommitted change is accountable, not silent.
    """
    commit = run(["rev-parse", "HEAD"])
    branch = run(["rev-parse", "--abbrev-ref", "HEAD"])
    dirty = bool(run(["status", "--porcelain"]))
    patch_digest = digest_of(run(["diff", "HEAD"]).encode("utf-8")) if dirty else None
    return GitProvenanceRef(
        commit=commit, branch=branch, dirty=dirty, patch_digest=patch_digest
    )


@dataclass(slots=True)
class CliSession:
    """The command line's live boundary: a store, a gateway, and a principal."""

    store: DurableStore
    gateway: Gateway
    principal: PrincipalRef = CLI_PRINCIPAL
    _idem: itertools.count[int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        # A per-session counter mints a distinct idempotency key per operation, so
        # two contexts on one aggregate's stream never collide.
        object.__setattr__(self, "_idem", itertools.count(1))

    @classmethod
    def open(
        cls, *, store: DurableStore | None = None, gateway: Gateway | None = None
    ) -> CliSession:
        """Open the session over the deployment store (or an injected one).

        With ``store`` unset it resolves the same store a deployment uses --
        Postgres when ``MUG_PG_DSN`` is set, else the in-memory store. Opening the
        store is synchronous here, before any event loop starts, so a command's
        ``asyncio.run`` never nests the Postgres open loop. Every backend is both an
        event and an artifact store, so the resolved store is the combined view.

        The gateway takes the deployment's own identifier secret when one is set
        (``MUG_GATEWAY_SECRET``), so re-running a command that already committed
        replays its receipt rather than colliding with it. Without one each
        invocation draws its own secret, and a re-run is a conflict, not a replay.
        """
        resolved = (
            store if store is not None else cast("DurableStore", store_from_env())
        )
        return cls(
            store=resolved,
            gateway=gateway or Gateway(secret=gateway_secret_from_env()),
        )

    def next_idempotency_key(self) -> str:
        """Mint the next per-operation idempotency key for this session."""
        return "idem_" + f"{next(self._idem):021d}" + "A"

    def now(self) -> str:
        """Return the current canonical instant from the gateway clock."""
        return self.gateway.clock().strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def mint_context(
        self, *, command: str, target_id: str, data: dict[str, object] | None = None
    ) -> CommandContext:
        """Mint one trusted context on an aggregate's stream through the gateway.

        A command the command line originates -- a job claim, a job completion --
        gets its context from the one gateway boundary, exactly as the edge mints
        one for a client. Each call carries a fresh idempotency key, so repeated
        calls on one job's stream mint distinct, non-colliding contexts.
        """
        envelope = self.envelope(command=command, target_id=target_id, data=data or {})
        return self.gateway.mint(
            envelope, principal=self.principal, data_handling=_RESEARCH
        )

    def envelope(
        self,
        *,
        command: str,
        target_id: str,
        data: dict[str, object],
        idempotency_key: str | None = None,
    ) -> WireCommandEnvelope:
        """Build the wire envelope for a command the command line originates.

        The command line mints the envelope a family runtime needs for a context
        it originates -- a job step, for instance -- exactly as a client mints one
        for the edge. A prepared command from a file is loaded whole and not built
        here.
        """
        return WireCommandEnvelope.model_validate(
            {
                "schema": _schema("mug.command-envelope"),
                "protocol_version": "0.1.0",
                "command": {"name": command, "version": 0},
                "request_id": self.gateway.new_id("request"),
                "idempotency_key": idempotency_key or self.next_idempotency_key(),
                "target": {"id": target_id},
                "payload": {"schema": _schema("mug.cli.payload"), "data": data},
            }
        )


def load_envelope(path: Path) -> WireCommandEnvelope:
    """Load a prepared command envelope from a file (the compiler's output).

    A publish or a deploy carries a large, compiled command. The study toolchain
    writes it as one wire envelope -- the same bytes a client posts to the edge --
    and the command line drives it through the shared spine unchanged.
    """
    return WireCommandEnvelope.model_validate_json(path.read_text(encoding="utf-8"))


__all__ = [
    "CLI_PRINCIPAL",
    "CliSession",
    "DurableStore",
    "git_provenance",
    "load_envelope",
]
