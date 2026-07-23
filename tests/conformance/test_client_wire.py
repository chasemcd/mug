"""Cross-language client-wire conformance: the TS client emits frames the server takes.

The TypeScript participant client mints its command frames from the kernel twin.
This test runs the TypeScript session with a fake socket (no browser), captures
every frame it sends, and proves each one is a frame the real server accepts:

- Each command validates against the live ``RealtimeCommand`` model, so the
  header the browser mints passes the same check the transport applies.
- Each command's ``payload_digest`` equals the Python digest of the same payload,
  so the whole value -> canonical bytes -> digest path matches byte for byte, on a
  real wire payload rather than a fixed vector.

Like the kernel-twin test, it builds the ``ts/`` workspace on demand and skips
cleanly when ``node`` or the build is absent.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from mug.client.types import RealtimeCommand
from mug.kernel import sha256_hex

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
_TS_ROOT = _REPO_ROOT / "ts"
_RUNNER = _TS_ROOT / "dist" / "conformance" / "client_wire.js"


def _ensure_built() -> None:
    """Build the ts/ workspace when its dependencies are present but dist is not.

    A build failure is tolerated, not fatal: the current TypeScript needs a modern
    node (see ``ts/.nvmrc``), so on a shell that still resolves an old system node
    the build simply produces no ``dist``, and the caller skips.
    """
    if _RUNNER.exists():
        return
    tsc = _TS_ROOT / "node_modules" / ".bin" / "tsc"
    if not tsc.exists():
        return
    subprocess.run(
        [str(tsc), "-p", "tsconfig.json"],
        cwd=_TS_ROOT,
        capture_output=True,
        check=False,
        timeout=180,
    )


def _run_client() -> dict[str, Any]:
    if subprocess.run(["which", "node"], capture_output=True).returncode != 0:
        pytest.skip("node is not on the path")
    _ensure_built()
    if not _RUNNER.exists():
        pytest.skip("ts/ workspace is not built; run `npm ci && npm run build` in ts/")
    result = subprocess.run(
        ["node", str(_RUNNER)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report: dict[str, Any] = json.loads(result.stdout)
    return report


def _frames(report: dict[str, Any]) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = report["frames"]
    return frames


def test_the_ts_client_opens_the_session_with_the_cursor_and_ticket() -> None:
    """The connection url carries the resume cursor and the launch ticket."""
    report = _run_client()
    assert report["url"] == "ws://test.local/ws?resume_from=0&ticket=ticket-abc"


def test_the_ts_client_persists_the_signed_resume_token() -> None:
    """The handshake token is stored, so a reconnection resumes the same visit."""
    report = _run_client()
    assert report["stored_resume_token"] == "signed-token.mac"


def test_every_ts_command_validates_against_the_realtime_command_model() -> None:
    """Each command the TS client mints is a frame the server's model accepts."""
    commands = [f for f in _frames(_run_client()) if f["type"] == "command"]
    assert commands, "the client sent no command frames"
    for frame in commands:
        # The real server model validates the header; a bad id, key, or instant
        # would raise here.
        RealtimeCommand.model_validate(frame["command"])
        assert frame["command"]["channel_key"] in {"flow.advance", "game.capture"}
        assert "payload" in frame


def test_ts_payload_digests_match_the_python_digest_byte_for_byte() -> None:
    """The header's payload digest equals the Python digest of the same payload."""
    for frame in _frames(_run_client()):
        if frame["type"] != "command":
            continue
        expected = sha256_hex(frame["payload"])
        assert frame["command"]["payload_digest"]["hex"] == expected


def test_the_ts_client_advances_the_flow_and_reports_input() -> None:
    """The flow advances carry answers and the input frame carries the keys."""
    frames = _frames(_run_client())
    advances = [
        f
        for f in frames
        if f["type"] == "command" and f["command"]["channel_key"] == "flow.advance"
    ]
    assert advances and all("answers" in f["payload"] for f in advances)
    inputs = [f for f in frames if f["type"] == "input"]
    assert inputs == [{"type": "input", "keys": ["ArrowLeft"]}]
