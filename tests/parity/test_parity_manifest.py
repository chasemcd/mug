"""Hold the parity fixture suite to the document that requires it.

Without this, ``docs/architecture/functional-parity.md`` is a list of intentions:
a required fixture could have no test and the suite would still be green, which is
the exact failure the 2026-07-26 requirements audit found three times over. So the
document is read here, and the suite must answer it item for item.
"""

from __future__ import annotations

from _parity_manifest import (
    FIXTURES,
    PARITY_DOC,
    decision_status,
    required_fixture_text,
)

_HERE = PARITY_DOC.parent.parent.parent / "tests/parity"


def test_the_manifest_answers_every_fixture_the_document_requires() -> None:
    """Each numbered requirement has one fixture, in the document's own words."""
    required = required_fixture_text()

    assert len(required) == len(FIXTURES), (
        f"the document requires {len(required)} fixtures and the manifest names "
        f"{len(FIXTURES)}"
    )
    for fixture, text in zip(FIXTURES, required, strict=True):
        assert fixture.requirement in text, (
            f"fixture {fixture.number} claims to prove {fixture.requirement!r}, "
            f"which the document does not say: {text!r}"
        )


def test_every_fixture_numbers_itself_in_order() -> None:
    """The manifest is read beside the document, so the order is the document's."""
    assert [one.number for one in FIXTURES] == list(range(1, len(FIXTURES) + 1))


def test_every_proven_fixture_names_a_module_that_exists() -> None:
    """A fixture that claims a module must have one, with a test in it."""
    for fixture in FIXTURES:
        if fixture.withdrawn:
            continue
        assert fixture.module is not None
        path = _HERE / fixture.module
        assert path.exists(), f"fixture {fixture.number} names a missing {path}"
        body = path.read_text(encoding="utf-8")
        assert "def test_" in body, f"fixture {fixture.number} has no test in it"


def test_every_withdrawn_fixture_names_a_decision_record() -> None:
    """A capability that is not built is an owner's decision, written down."""
    for fixture in FIXTURES:
        if not fixture.withdrawn:
            continue
        assert fixture.adr is not None, (
            f"fixture {fixture.number} is neither proven nor withdrawn by an ADR"
        )
        path = PARITY_DOC.parent.parent.parent / fixture.adr
        assert path.exists(), f"fixture {fixture.number} names a missing {path}"


def test_no_module_claims_a_fixture_the_manifest_does_not_name() -> None:
    """A fixture module nobody mapped is a fixture nobody reviewed."""
    named = {one.module for one in FIXTURES if one.module is not None}
    found = {path.name for path in _HERE.glob("test_fixture_*.py")}
    assert found == named, f"unmapped fixture modules: {sorted(found - named)}"


def test_the_parity_gate_is_settled() -> None:
    """Every capability is proven or withdrawn, and fixture 9 is the withdrawal.

    ``functional-parity.md`` passes the gate only when every capability is
    accepted, replaced, or removed **by an ADR approved by the product owner**.
    Fixture 9 is the one removal (ADR-0016, accepted 2026-07-29: no Unity or
    WebGL activity in v0). This test records that set, so it can never grow or
    shrink by accident.
    """
    withdrawn = [one for one in FIXTURES if one.withdrawn]
    assert [one.number for one in withdrawn] == [9], (
        "the set of withdrawn capabilities changed; update the parity gate status "
        "in docs/architecture/functional-parity.md before changing this test"
    )


def test_a_capability_is_withdrawn_only_by_an_accepted_decision() -> None:
    """The gate opens because the ADR says so, not because a test says so.

    A capability is removed from the parity list by an owner's decision. This
    reads the status out of the decision record itself, so an ADR that is still
    proposed, or one that goes back to proposed, shuts the gate again with no
    change here. That is the whole guard: a test can not approve a removal.
    """
    for fixture in FIXTURES:
        if not fixture.withdrawn:
            continue
        assert fixture.adr is not None
        status = decision_status(fixture.adr)
        assert status == "Accepted", (
            f"fixture {fixture.number} is withdrawn on {fixture.adr}, which is "
            f"{status!r}; the parity gate is shut until the product owner "
            "accepts it"
        )


def test_a_fixture_states_what_it_proves() -> None:
    """Every fixture module opens with a docstring naming its requirement."""
    for fixture in FIXTURES:
        if fixture.withdrawn:
            continue
        assert fixture.module is not None
        body = (_HERE / fixture.module).read_text(encoding="utf-8")
        assert body.startswith('"""'), (
            f"fixture {fixture.number} does not say what it proves"
        )
        head = body.split('"""')[1]
        assert f"Fixture {fixture.number}" in head, (
            f"fixture {fixture.number}'s docstring does not name its number"
        )
