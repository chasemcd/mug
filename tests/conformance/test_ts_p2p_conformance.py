"""The browser P2P edge holds in TypeScript, under the same gate as the server.

``ts/conformance/p2p.ts`` drives the TypeScript participant edge with fake RTC
connections and a fake control socket: it parses the API-09 inbound frames,
negotiates every pair, reports readiness, and redeems an ICE grant, all with no
browser. Without this test that runner is a script nobody runs; with it, the
browser half of the vertical fails the maintained gate when it breaks, exactly
as the Python half does.

Like the other cross-language tests, it builds the ``ts/`` workspace on demand
and skips cleanly when ``node`` or the build is absent.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
_TS_ROOT = _REPO_ROOT / "ts"
_RUNNER = _TS_ROOT / "dist" / "conformance" / "p2p.js"


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


def test_the_ts_browser_p2p_edge_passes_its_conformance_scenarios() -> None:
    """Every browser-side P2P scenario passes with no browser and no network."""
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
    assert "browser P2P conformance" in result.stdout
