"""The contract-freeze gate: the bytes cannot move without the ledger moving.

Phase 0 closed with each family's byte-freeze deferred to the implementation
phase, so that a family freezes when its code proves the shape. The code is now
here, and this is the gate. `docs/architecture/phase-0/contract-freeze.json`
records what every contract bundle pins; each test below compares one part of
that record against the bytes on disk or against the running code.

The corpus already kept its digests *consistent*: edit a schema and the fixtures
that point at it must be restamped. That catches an inconsistent corpus, not a
moving contract -- restamping makes the suite green again. These tests close
that hole. After a deliberate contract change, rebuild the ledger with
`uv run python tests/architecture/_freeze.py`, read the digests that moved, and
record why in the family's review record.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from _freeze import (
    BUNDLES,
    LEDGER_SCHEMA,
    PHASE_0_ROOT,
    REPOSITORY_ROOT,
    TOMBSTONES,
    TRACKER_PATH,
    Bundle,
    canonical_digest,
    conformance_records,
    corpus_families,
    fixture_corpus_digest,
    fixture_records,
    loaded_bundle_digest,
    manifest_path,
    read_ledger,
    render_tracker,
    schema_path,
    unevidenced_records,
)

_UNEVIDENCED = unevidenced_records()

_LEDGER = read_ledger()
_ENTRIES: dict[str, dict[str, Any]] = {
    str(entry["family"]): entry for entry in _LEDGER["families"]
}
_BY_FAMILY: dict[str, Bundle] = {bundle.family: bundle for bundle in BUNDLES}
_IDS = [bundle.family for bundle in BUNDLES]


def _entry(family: str) -> dict[str, Any]:
    return _ENTRIES[family]


def test_the_ledger_declares_its_own_schema() -> None:
    """A ledger from another shape is refused rather than half-read."""
    assert _LEDGER["schema"] == LEDGER_SCHEMA


def test_every_contract_bundle_in_the_corpus_has_one_freeze_record() -> None:
    """No bundle can be added to the corpus, or dropped, without the ledger.

    The corpus is discovered from the directories that carry schema bytes, so a
    new family is a failure here until someone pins it.
    """
    assert set(corpus_families()) == set(_ENTRIES)
    assert set(_BY_FAMILY) == set(_ENTRIES)
    assert [entry["family"] for entry in _LEDGER["families"]] == _IDS


def test_the_tombstoned_families_carry_no_bytes_to_freeze() -> None:
    """API-20 and API-21 were removed and retracted; they own no contract."""
    assert tuple(_LEDGER["tombstones"]) == TOMBSTONES
    for family in TOMBSTONES:
        assert family not in _ENTRIES
        assert not (PHASE_0_ROOT / family / "schemas").exists()
        assert not (PHASE_0_ROOT / family / "fixtures").exists()


@pytest.mark.parametrize("bundle", BUNDLES, ids=_IDS)
def test_the_running_code_loads_the_frozen_bytes(bundle: Bundle) -> None:
    """The runtime package's own accessor returns the pinned bundle digest.

    This is the sentence "the contract bytes are frozen against the running
    code", made checkable: the digest is read out of the package that serves the
    contract at run time, not recomputed beside it.
    """
    assert loaded_bundle_digest(bundle) == _entry(bundle.family)["bundle_digest"]


@pytest.mark.parametrize("bundle", BUNDLES, ids=_IDS)
def test_the_pinned_digest_is_the_digest_of_the_pinned_file(bundle: Bundle) -> None:
    """The schema file the ledger names hashes to the digest the ledger pins.

    Together with the test above, this binds three things into one value: the
    file on disk, the record in the ledger, and the bundle the runtime loads. A
    package that quietly read some other file would part them.
    """
    entry = _entry(bundle.family)
    path = schema_path(bundle.family)
    assert str(path.relative_to(REPOSITORY_ROOT)) == entry["schema_path"]
    document: Any = json.loads(path.read_text(encoding="utf-8"))
    assert canonical_digest(document) == entry["bundle_digest"]


@pytest.mark.parametrize("bundle", BUNDLES, ids=_IDS)
def test_the_fixture_corpus_is_pinned_too(bundle: Bundle) -> None:
    """The fixture manifest carries its own digest, so cases cannot move either.

    A family may add a fixture without touching its schema. That is still a
    change to the contract's evidence, so it moves a digest.
    """
    entry = _entry(bundle.family)
    path = manifest_path(bundle.family)
    if path is None:
        assert entry["fixture_manifest_path"] is None
        assert entry["fixture_manifest_digest"] is None
        return
    assert str(path.relative_to(REPOSITORY_ROOT)) == entry["fixture_manifest_path"]
    manifest: Any = json.loads(path.read_text(encoding="utf-8"))
    assert canonical_digest(manifest) == entry["fixture_manifest_digest"]


@pytest.mark.parametrize("bundle", BUNDLES, ids=_IDS)
def test_the_fixture_bytes_are_pinned_not_only_their_index(bundle: Bundle) -> None:
    """The evidence itself is pinned, not only the manifest that indexes it.

    The manifest names the cases; it does not carry their content. Edit a
    fixture in place and the manifest digest does not move, so the bytes of
    every fixture are digested here as well.
    """
    entry = _entry(bundle.family)
    assert fixture_corpus_digest(bundle.family) == entry["fixture_corpus_digest"]


@pytest.mark.parametrize("bundle", BUNDLES, ids=_IDS)
def test_the_frozen_record_surface_is_exactly_what_the_fixtures_exercise(
    bundle: Bundle,
) -> None:
    """The pinned records are the family's contract surface, with no drift.

    A record added to the schema and given a fixture widens the surface, and the
    freeze must be amended to say so. A record that loses its fixture narrows it,
    which is the more dangerous direction: evidence quietly stops being kept.
    """
    assert list(fixture_records(bundle.family)) == _entry(bundle.family)["records"]


@pytest.mark.parametrize("bundle", BUNDLES, ids=_IDS)
def test_every_frozen_record_is_bound_to_a_running_model(bundle: Bundle) -> None:
    """The family's conformance suite binds each pinned record to a model.

    The suite proves the two agree, case by case: what the schema accepts the
    model parses, and what the schema refuses the model refuses. This test proves
    the suite covers the whole frozen surface, so no record is pinned with
    nothing running behind it.
    """
    entry = _entry(bundle.family)
    if bundle.conformance is None:
        assert not entry["records"], "a family with records needs a conformance suite"
        return
    assert (REPOSITORY_ROOT / bundle.conformance).exists()
    assert entry["conformance"] == bundle.conformance
    assert entry["registry"] == bundle.registry
    missing = set(entry["records"]) - conformance_records(bundle)
    assert not missing, f"{bundle.family} pins records with no model: {sorted(missing)}"


@pytest.mark.parametrize("bundle", BUNDLES, ids=_IDS)
def test_the_surface_with_no_fixture_behind_it_is_pinned_as_well(
    bundle: Bundle,
) -> None:
    """The records no fixture reaches are recorded, so the list cannot grow.

    This is the freeze's honest column. A definition that no fixture case names,
    and that no reference from a named one reaches, is contract surface with no
    golden evidence. Recording it means a later contract cannot add another one
    quietly, and closing one is a deliberate edit to this list.
    """
    assert (
        list(_UNEVIDENCED[bundle.family])
        == _entry(bundle.family)["unevidenced_records"]
    )


@pytest.mark.parametrize("bundle", BUNDLES, ids=_IDS)
def test_a_record_is_evidenced_or_open_but_never_both(bundle: Bundle) -> None:
    """The two record lists partition the surface; nothing falls between them."""
    entry = _entry(bundle.family)
    assert not set(entry["records"]) & set(entry["unevidenced_records"])


@pytest.mark.parametrize("bundle", BUNDLES, ids=_IDS)
def test_the_pinned_revision_matches_the_family_review_record(bundle: Bundle) -> None:
    """The ledger and the review record name the same contract revision."""
    entry = _entry(bundle.family)
    record = PHASE_0_ROOT / bundle.family / "review-record.md"
    if not record.exists():
        assert entry["contract_revision"] is None
        return
    stated = [
        line.split("`")[1]
        for line in record.read_text(encoding="utf-8").splitlines()
        if line.startswith("| Contract revision ")
    ]
    assert stated == [entry["contract_revision"]]


@pytest.mark.parametrize("bundle", BUNDLES, ids=_IDS)
def test_no_family_claims_a_sign_off_this_tool_could_write(bundle: Bundle) -> None:
    """`owner_sign_off` is a person's record, so it is a date or it is empty.

    The mechanical gates above are what a machine can prove. The Phase-0 ladder
    ends with an adversarial review panel and the accountable owner's sign-off,
    and neither is in reach of this file. The field stays empty until a human
    fills it, rather than being ticked by the tool that would benefit.
    """
    sign_off: Any = _entry(bundle.family)["owner_sign_off"]
    assert sign_off is None or (isinstance(sign_off, str) and len(sign_off) == 10)


def test_the_tracker_document_is_the_ledger_rendered() -> None:
    """The human tracker cannot drift from the record it reports.

    §12k of the plan asks for a tracker. A hand-kept table is how the state was
    lost the first time, so the table is generated and this test holds it to the
    ledger.
    """
    assert TRACKER_PATH.read_text(encoding="utf-8") == render_tracker(_LEDGER) + "\n"


def test_the_gate_reads_the_ledger_from_the_corpus_it_freezes() -> None:
    """The ledger sits with the contract it pins, not with the code that reads it."""
    assert Path(_LEDGER["corpus"]) == PHASE_0_ROOT.relative_to(REPOSITORY_ROOT)
