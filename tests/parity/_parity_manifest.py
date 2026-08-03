"""The ten required reference fixtures, and what proves each one.

``docs/architecture/functional-parity.md`` lists the fixtures the rewrite must
supply before the legacy runtime can go. That list is prose, so nothing held the
code to it: a fixture could be missing and no test would say so.

This module is the machine-readable half of that list, and
``test_parity_manifest.py`` reads the document and holds the two together. A
fixture the document requires and this manifest does not name is a failure. A
fixture this manifest names and the document does not require is also a failure,
because a fixture nobody asked for is a fixture nobody reviewed.

**A fixture is proven or it is withdrawn, and there is no third state.** A proven
fixture names the module that walks a participant or an operator through the
capability. A withdrawn fixture names the ADR that removes it, and the parity gate
does not pass while that ADR is still open. The gate wants a decision *approved by
the product owner*, so ``decision_status`` reads the status out of the ADR itself:
the gate opens because the document says ``Accepted`` and shuts again if the word
changes. No test can write that word, and no tool can forge it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
PARITY_DOC: Final[Path] = REPO_ROOT / "docs/architecture/functional-parity.md"


@dataclass(frozen=True)
class Fixture:
    """One required reference fixture, and the evidence that closes it.

    ``requirement`` is a phrase that must appear in the document's own wording, so
    a requirement that is reworded fails here rather than drifting quietly away
    from what the fixture actually proves.

    ``module`` is the test module that proves it, relative to ``tests/parity``. A
    withdrawn fixture has none, and names ``adr`` instead.
    """

    number: int
    title: str
    requirement: str
    module: str | None = None
    adr: str | None = None

    @property
    def withdrawn(self) -> bool:
        """Return whether this capability is removed by a decision record."""
        return self.module is None


FIXTURES: Final[tuple[Fixture, ...]] = (
    Fixture(
        number=1,
        title="A single human in a browser environment",
        requirement="single human running a browser/Pyodide Gymnasium environment",
        module="test_fixture_01_single_human.py",
    ),
    Fixture(
        number=2,
        title="A human and a browser-side policy",
        requirement="browser-side ONNX or deterministic policy sharing an",
        module="test_fixture_02_browser_policy.py",
    ),
    Fixture(
        number=3,
        title="A heuristic policy in both execution modes",
        requirement="heuristic policy in both browser and server execution",
        module="test_fixture_03_heuristic_both_modes.py",
    ),
    Fixture(
        number=4,
        title="Two humans peer-to-peer under fault",
        requirement="rollback-enabled P2P game under latency, packet",
        module="test_fixture_04_p2p_under_fault.py",
    ),
    Fixture(
        number=5,
        title="Two humans server-authoritative, with reconnect",
        requirement="server-authoritative game with reconnect behavior",
        module="test_fixture_05_server_authoritative.py",
    ),
    Fixture(
        number=6,
        title="Concurrent matches, waiting room, and eligibility",
        requirement="concurrent matches with waiting-room and eligibility",
        module="test_fixture_06_concurrent_matches.py",
    ),
    Fixture(
        number=7,
        title="A composed flow, start to completion",
        requirement="randomization, repeated activities, participant",
        module="test_fixture_07_composed_flow.py",
    ),
    Fixture(
        number=8,
        title="Surface-rendering conformance",
        requirement="conformance scene covering every logical primitive",
        module="test_fixture_08_render_conformance.py",
    ),
    Fixture(
        number=9,
        title="An external-client activity",
        requirement="Unity/external-client activity or an explicitly accepted",
        adr="docs/architecture/decisions/0016-external-client-activity.md",
    ),
    Fixture(
        number=10,
        title="An operator watching, with identity absent",
        requirement="observing live and completed interactions",
        module="test_fixture_10_operator_visibility.py",
    ),
)


def decision_status(adr: str) -> str:
    """Return the first word of the status a decision record gives itself.

    A decision record opens with a table whose first row is its status. This
    reads that row, so the parity gate follows the document. An ADR that goes
    back to ``Proposed`` shuts the gate again with no test change.
    """
    for line in (REPO_ROOT / adr).read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) > 2 and cells[1] == "Status":
            words = cells[2].replace("*", " ").split()
            if not words:
                break
            return words[0].rstrip(",;:")
    raise AssertionError(f"{adr} states no status")


def required_fixture_text() -> list[str]:
    """Return the numbered fixture entries the parity document requires.

    Each entry is one list item with its continuation lines joined, so a
    requirement that wraps over three lines is one string to search.
    """
    lines = PARITY_DOC.read_text(encoding="utf-8").splitlines()
    start = lines.index("## Required reference fixtures")
    entries: list[str] = []
    for line in lines[start:]:
        if line.startswith("## ") and entries:
            break
        stripped = line.strip()
        if not stripped:
            continue
        if stripped[:1].isdigit() and ". " in stripped[:4]:
            entries.append(stripped.split(". ", 1)[1])
        elif entries and not stripped.startswith("#"):
            entries[-1] = f"{entries[-1]} {stripped}"
    return entries


__all__ = [
    "FIXTURES",
    "PARITY_DOC",
    "REPO_ROOT",
    "Fixture",
    "decision_status",
    "required_fixture_text",
]
