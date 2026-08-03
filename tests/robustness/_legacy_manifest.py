"""Every test the legacy end-to-end suite ran, and what covers it now.

``tests/e2e`` is the suite the legacy platform was trusted on: two real browsers, a
real Flask server, injected latency and packet loss, twelve concurrent
participants, and an offline comparison of the two players' exported data. The
rewrite must be at least as well covered before that suite can be removed, and
"at least as well covered" is a claim, so it is written down here and checked.

Each entry names a legacy test, the capability it really proved (not its title),
and the module on the new stack that proves the same thing. ``test_legacy_coverage``
fails when an entry names a module that does not exist, when a legacy test is
missing from this list, or when an entry claims a replacement with no test in it.

**A replacement is not always the same test.** Two peers used to write two files
that had to match; the rewrite records one agreed run, so the claim becomes "the
peers agreed and the record is what they agreed on". Where the shape changed, the
entry says so in ``note``.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LEGACY = REPO / "tests" / "e2e"


@dataclass(frozen=True)
class Covered:
    """One legacy test, what it proved, and where that is proven now."""

    legacy: str
    proves: str
    now: tuple[str, ...]
    note: str = ""


COVERAGE: tuple[Covered, ...] = (
    # -- infrastructure and the basic run ------------------------------------------
    Covered(
        legacy="test_infrastructure.py::test_server_starts_and_contexts_connect",
        proves="a server starts and two isolated browsers reach it",
        now=("tests/e2e_native/test_server_game_browser.py",),
    ),
    Covered(
        legacy="test_multiplayer_basic.py::test_two_players_connect_and_complete_episode",
        proves="two people play one peer-to-peer episode to the end",
        now=(
            "tests/e2e_native/test_browser_mesh_browser.py",
            "tests/e2e_native/test_browser_mesh_e2e.py",
        ),
    ),
    Covered(
        legacy="test_multiplayer_basic.py::test_matchmaking_pairs_two_players",
        proves="the waiting room pairs two arrivals into one room",
        now=("tests/parity/test_fixture_06_concurrent_matches.py",),
    ),
    Covered(
        legacy="test_p2p_regression.py::test_p2p_two_players_still_work",
        proves="peer-to-peer still works beside the server-stepped mode",
        now=(
            "tests/parity/test_fixture_04_p2p_under_fault.py",
            "tests/parity/test_fixture_05_server_authoritative.py",
        ),
    ),
    Covered(
        legacy="test_server_auth_basic.py::test_server_auth_two_players_complete_episode",
        proves="two people complete an episode the server steps and pushes",
        now=("tests/parity/test_fixture_05_server_authoritative.py",),
    ),
    # -- what was recorded ---------------------------------------------------------
    Covered(
        legacy="test_data_comparison.py::test_export_parity_basic",
        proves="what the run recorded is what the run produced",
        now=("tests/robustness/test_recorded_data.py",),
        note=(
            "two peers wrote two files that had to match; the rewrite records one"
            " agreed run, so the claim is that the peers agreed and the record is"
            " what they agreed on"
        ),
    ),
    Covered(
        legacy="test_data_comparison.py::test_export_parity_with_latency",
        proves="a slow link changes nothing about what is recorded",
        now=(
            "tests/parity/test_fixture_04_p2p_under_fault.py",
            "tests/e2e_native/test_browser_mesh_e2e.py",
        ),
    ),
    Covered(
        legacy="test_data_comparison.py::test_active_input_parity",
        proves="real key presses reach the record, and both sides see the same ones",
        now=(
            "tests/e2e_native/test_examples_render_browser.py",
            "tests/robustness/test_recorded_data.py",
        ),
    ),
    Covered(
        legacy="test_data_comparison.py::test_focus_loss_mid_episode_parity",
        proves="a hidden tab does not split the record in two",
        now=("tests/parity/test_fixture_04_p2p_under_fault.py",),
    ),
    Covered(
        legacy="test_focus_loss_data_parity.py::test_focus_loss_episode_boundary_parity",
        proves="a hidden tab across an episode boundary keeps one record",
        now=("tests/e2e_native/test_browser_mesh_e2e.py",),
    ),
    Covered(
        legacy="test_slimevb.py::test_slimevb_human_ai_exports_data",
        proves="a study with a policy partner records what it played",
        now=("tests/robustness/test_recorded_data.py",),
    ),
    # -- the network --------------------------------------------------------------
    Covered(
        legacy="test_latency_injection.py::test_episode_completion_under_fixed_latency",
        proves="an episode completes under a fixed delay on the link",
        now=("tests/e2e_native/test_browser_mesh_e2e.py",),
    ),
    Covered(
        legacy="test_latency_injection.py::test_episode_completion_under_asymmetric_latency",
        proves="an episode completes when one direction is slower than the other",
        now=("tests/e2e_native/test_browser_mesh_e2e.py",),
    ),
    Covered(
        legacy="test_latency_injection.py::test_episode_completion_under_jitter",
        proves="an episode completes when the delay itself varies",
        now=("tests/e2e_native/test_browser_mesh_e2e.py",),
    ),
    Covered(
        legacy="test_latency_injection.py::test_active_input_with_latency",
        proves="input under delay still reaches the run",
        now=("tests/parity/test_fixture_04_p2p_under_fault.py",),
    ),
    Covered(
        legacy="test_network_disruption.py::test_packet_loss_triggers_rollback",
        proves="a lost packet is corrected by a rollback rather than a divergence",
        now=(
            "tests/e2e_native/test_browser_mesh_e2e.py",
            "tests/parity/test_fixture_04_p2p_under_fault.py",
        ),
    ),
    Covered(
        legacy="test_network_disruption.py::test_tab_visibility_triggers_fast_forward",
        proves="a backgrounded tab catches up rather than falling behind",
        now=("tests/e2e_native/test_browser_mesh_e2e.py",),
    ),
    Covered(
        legacy="test_network_disruption.py::test_active_input_with_packet_loss",
        proves="input survives a lossy link",
        now=("tests/parity/test_fixture_04_p2p_under_fault.py",),
    ),
    Covered(
        legacy="test_network_disruption.py::test_deep_rollback_via_tab_hide",
        proves="a long silence unwinds further than the input delay and recovers",
        now=("tests/parity/test_fixture_04_p2p_under_fault.py",),
    ),
    # -- many people at once -------------------------------------------------------
    Covered(
        legacy="test_multi_participant.py::test_three_simultaneous_games",
        proves="several games run at once without reaching into each other",
        now=("tests/robustness/test_concurrent_participants.py",),
    ),
    Covered(
        legacy="test_multi_participant.py::test_staggered_participant_arrival",
        proves="people who arrive at different times are still paired",
        now=(
            "tests/robustness/test_lifecycle.py",
            "tests/parity/test_fixture_06_concurrent_matches.py",
        ),
    ),
    Covered(
        legacy="test_waitroom_stress.py::test_12_clients_low_latency_all_match",
        proves="twelve arrivals become six rooms, and every room agrees with itself",
        now=("tests/robustness/test_concurrent_participants.py",),
    ),
    Covered(
        legacy="test_waitroom_stress.py::test_mixed_latency_probe_filtering",
        proves="a connection too poor to play is refused before it is paired",
        now=("tests/parity/test_fixture_06_concurrent_matches.py",),
    ),
    Covered(
        legacy="test_waitroom_stress.py::test_no_duplicate_probes",
        proves="nobody is handed to two rooms at once",
        now=("tests/robustness/test_concurrent_participants.py",),
    ),
    Covered(
        legacy="test_waitroom_stress.py::test_interleaved_latency_retry_resolution",
        proves="a crowd arriving out of order is still resolved into rooms",
        now=("tests/robustness/test_concurrent_participants.py",),
    ),
    # -- how people behave ---------------------------------------------------------
    Covered(
        legacy="test_lifecycle_stress.py::test_multi_episode_completion",
        proves="two rounds back to back, with no state carried between them",
        now=("tests/robustness/test_lifecycle.py",),
    ),
    Covered(
        legacy="test_lifecycle_stress.py::test_mid_game_disconnect",
        proves="a participant who leaves mid-game is handled and the partner is told",
        now=(
            "tests/e2e_native/test_browser_mesh_e2e.py",
            "tests/parity/test_fixture_05_server_authoritative.py",
        ),
    ),
    Covered(
        legacy="test_lifecycle_stress.py::test_waitroom_disconnect_isolation",
        proves="somebody leaving the waiting room does not hold up anybody else",
        now=(
            "tests/robustness/test_lifecycle.py",
            "tests/e2e_native/test_browser_mesh_e2e.py",
        ),
    ),
    Covered(
        legacy="test_lifecycle_stress.py::test_focus_loss_timeout",
        proves="a participant who stops responding ends their own run and no other",
        now=("tests/parity/test_fixture_05_server_authoritative.py",),
        note=(
            "the rewrite has no client-side focus timer: an empty seat holds no key"
            " and the run goes on, which is what the legacy timeout was protecting"
            " the other participant from"
        ),
    ),
    Covered(
        legacy="test_lifecycle_stress.py::test_mixed_lifecycle_scenarios",
        proves="normal and faulty runs in one deployment, and the good ones still hold",
        now=("tests/robustness/test_lifecycle.py",),
    ),
    Covered(
        legacy="test_scene_isolation.py::test_partner_exit_on_survey_no_overlay",
        proves="a partner leaving after the game does not disturb the survey",
        now=("tests/robustness/test_lifecycle.py",),
    ),
    # -- the policies a study plays against ----------------------------------------
    Covered(
        legacy="test_heuristic_policy.py::test_heuristic_policy_episode_completes",
        proves="a policy written in Python plays a seat in both execution modes",
        now=("tests/parity/test_fixture_03_heuristic_both_modes.py",),
    ),
    Covered(
        legacy="test_onnx_inference.py::test_onnx_inference_episode_completes",
        proves="an exported network plays a seat and the run completes",
        now=("tests/robustness/test_exported_policy.py",),
    ),
    Covered(
        legacy="test_slimevb.py::test_slimevb_human_ai_episode_completes",
        proves="a study environment plays against a policy in a browser",
        now=("tests/e2e_native/test_examples_render_browser.py",),
        note=(
            "the legacy test watched for fatal script errors; the replacement reads"
            " the pixels the browser drew, which is a stronger claim about the same"
            " run"
        ),
    ),
    Covered(
        legacy="test_slimevb.py::test_slimevb_human_human_episode_completes",
        proves="a study environment plays two people peer to peer",
        now=("tests/unit/test_examples_build.py",),
        note=(
            "the environment is shipped to both browsers, so what has to be proven"
            " is that the bundle builds a replica and draws it with nothing else in"
            " scope"
        ),
    ),
)


def legacy_tests() -> set[str]:
    """Return every test the legacy end-to-end suite defines, as module::name."""
    found: set[str] = set()
    for path in sorted(LEGACY.glob("test_*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            for start in ("def test_", "async def test_"):
                if line.startswith(start):
                    name = line[len(start) - 5 :].split("(")[0]
                    found.add(f"{path.name}::{name}")
    return found


__all__ = ["COVERAGE", "LEGACY", "REPO", "Covered", "legacy_tests"]
