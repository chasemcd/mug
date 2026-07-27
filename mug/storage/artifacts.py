"""Stage bytes into the content-addressed object store, and serialize them for it.

Any producer that keeps evidence too large for the ledger writes it here: a replay
bundle's streams, an episode's recorded trajectory, a run's render packets. The
helpers are storage's own, not one caller's, because the game layer records a
trajectory and sits below the replay layer that records a bundle.

The two serializers fix the bytes a producer writes. Newline-delimited JSON with
sorted keys is the one export and stream format (D13-1); a single object is written
the same canonical way. Both are deterministic, so the same recorded data always
gives the same artifact digest.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from mug.kernel import ArtifactRef, DataHandlingRef
from mug.storage.ports import ArtifactStore
from mug.storage.store import digest_of
from mug.storage.types import ArtifactStaging


async def stage_artifact(
    artifacts: ArtifactStore,
    *,
    data: bytes,
    media_type: str,
    new_artifact_id: Callable[[], str],
    new_upload_id: Callable[[], str],
    now: Callable[[], str],
    data_handling: DataHandlingRef,
) -> ArtifactRef:
    """Stage one blob against its own digest and finalize it into the object store.

    The intended digest and size come from the bytes, so the object store's
    integrity check finalizes only bytes that match. Returns the finalized reference
    the caller records.
    """
    staging = ArtifactStaging(
        upload_id=new_upload_id(),
        intended_digest=digest_of(data),
        size_bytes=len(data),
        media_type=media_type,
        data_handling=data_handling,
    )
    finalized = await artifacts.finalize_artifact(
        staging, data, artifact_id=new_artifact_id(), finalized_at=now()
    )
    return finalized.artifact


def jsonl_bytes(records: Sequence[dict[str, Any]]) -> bytes:
    """Serialize records to newline-delimited JSON with sorted keys (D13-1)."""
    lines = [
        json.dumps(record, separators=(",", ":"), sort_keys=True) for record in records
    ]
    return "".join(f"{line}\n" for line in lines).encode("utf-8")


def json_bytes(obj: object) -> bytes:
    """Serialize one object to canonical, sorted-key JSON bytes."""
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")


def read_jsonl(data: bytes) -> list[dict[str, Any]]:
    """Read newline-delimited JSON back into its records, in order."""
    return [
        json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()
    ]


__all__ = ["json_bytes", "jsonl_bytes", "read_jsonl", "stage_artifact"]
