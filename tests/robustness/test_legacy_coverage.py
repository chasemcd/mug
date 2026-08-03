"""The rewrite is at least as well covered as the platform it replaces.

That is a claim, and a claim nobody checks is a hope. This holds the coverage map
in ``_legacy_manifest`` to the legacy suite itself: every test in ``tests/e2e`` must
appear, every replacement must name a file that exists and has tests in it, and no
entry may point at a legacy test that no longer exists.

It fails on the day somebody deletes a replacement, and on the day somebody adds a
legacy test without deciding what covers it. Neither is caught by running either
suite.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from tests.robustness._legacy_manifest import COVERAGE, LEGACY, REPO, legacy_tests


def test_the_legacy_suite_is_still_where_the_map_says_it_is() -> None:
    """Without the old suite there is nothing to be measured against."""
    assert LEGACY.is_dir(), "the legacy end-to-end suite is gone"
    assert legacy_tests(), "the legacy suite defines no tests to be compared with"


def test_every_legacy_test_has_something_that_covers_it() -> None:
    """A legacy test with no entry is a capability nobody decided about.

    It is the one failure that matters here: removal of the old platform is gated
    on this list, so a test that is not on it is a gap that would be removed
    silently.
    """
    mapped = {one.legacy for one in COVERAGE}
    missing = sorted(legacy_tests() - mapped)

    assert not missing, (
        "these legacy tests are not covered by anything on the new stack: "
        + ", ".join(missing)
    )


def test_the_map_does_not_name_a_legacy_test_that_is_gone() -> None:
    """An entry for a test nobody runs any more is a claim about nothing."""
    stale = sorted({one.legacy for one in COVERAGE} - legacy_tests())

    assert not stale, "these entries name legacy tests that do not exist: " + ", ".join(
        stale
    )


def test_every_replacement_exists_and_has_tests_in_it() -> None:
    """A replacement is a file with tests in it, not a file name.

    Naming a module that was deleted, or one that holds only helpers, would let the
    map claim coverage that nobody runs.
    """
    for entry in COVERAGE:
        assert entry.now, f"{entry.legacy} claims no replacement"
        for named in entry.now:
            module = REPO / named
            assert module.is_file(), f"{entry.legacy} names {named}, which is not there"
            body = module.read_text(encoding="utf-8")
            assert "def test_" in body, f"{named} has no tests in it"


def test_every_entry_says_what_it_proves_rather_than_what_it_is_called() -> None:
    """The map is read by somebody deciding whether a capability is safe to drop.

    A title repeats the test's own name; what is wanted is the capability, so that
    a reader can tell whether the replacement really covers it.
    """
    for entry in COVERAGE:
        assert len(entry.proves.split()) >= 5, f"{entry.legacy} says too little"
        assert not entry.proves.startswith("test"), f"{entry.legacy} repeats its name"


def test_a_replacement_that_changed_shape_says_so() -> None:
    """Where the claim is not the same claim, the entry explains the difference.

    Four capabilities are covered differently rather than identically -- the
    two-file comparison, the focus timeout, and the two shipped browser
    environments. Each of them carries a note, because a reader who assumed a
    like-for-like replacement would be wrong.
    """
    explained = [one for one in COVERAGE if one.note]

    assert len(explained) >= 4
    for entry in explained:
        assert len(entry.note.split()) >= 10, f"{entry.legacy} explains too little"
