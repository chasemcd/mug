"""The contract-freeze ledger: what each family pins, and how it is rebuilt.

A family is frozen when its contract bytes are pinned to a recorded digest and
the running code loads those same bytes. Before this ledger, the corpus kept its
digests *consistent* -- a schema edit restamped every fixture that pointed at it
-- but nothing kept them *fixed*, so a contract could move without anyone
seeing it. The ledger is the missing half: it records the bytes as they stand,
and `test_contract_freeze.py` refuses a later change that is not recorded here.

The ledger holds only facts a machine can recompute:

- the digest of the schema bundle, as the running loader computes it;
- the digest of the fixture manifest;
- the record names the fixtures exercise, which is the family's contract surface;
- the runtime package that implements the family, and the accessor through which
  it loads the same bundle;
- the conformance suite that binds each record to a running model.

It holds no judgement. The gates that need a human -- the adversarial review
panel and the accountable owner's sign-off -- are recorded per family as an
open field, never as a tick this file can write for itself.

Rebuild the ledger and the tracker after a deliberate contract change:

    uv run python tests/architecture/_freeze.py

Read the difference before you commit it. A digest that moves is a contract that
moved, and the reason belongs in the family's review record.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import rfc8785

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PHASE_0_ROOT = REPOSITORY_ROOT / "docs" / "architecture" / "phase-0"
LEDGER_PATH = PHASE_0_ROOT / "contract-freeze.json"
TRACKER_PATH = PHASE_0_ROOT / "contract-freeze.md"

LEDGER_SCHEMA = "mug.contract-freeze/1"

# Corpus convention: a definition with this prefix types the evidence, not the
# contract. The contract-fixture suites validate against it directly.
SCAFFOLD_PREFIX = "Fixture"


@dataclass(frozen=True)
class Bundle:
    """One contract bundle and the code that implements it.

    A human declares this map: which runtime package owns a family, and which
    accessor loads its bundle. Everything else in the ledger is measured.

    `registry` names the mapping in the conformance suite that binds a record
    name to the model behind it. A family suite calls it `_VALIDATORS`; the
    command-results bundle has no fixture corpus and carries payloads instead.
    """

    family: str
    title: str
    runtime: str
    accessor: str
    conformance: str | None
    registry: str = "_VALIDATORS"


# The corpus, in catalog order. `conformance` is the suite that binds every
# record the family pins to a running model.
BUNDLES: tuple[Bundle, ...] = (
    Bundle(
        "shared-kernel",
        "Shared kernel",
        "mug.kernel",
        "load_shared_kernel_schema",
        "tests/unit/kernel/test_kernel_conformance.py",
    ),
    Bundle(
        "api-01",
        "Study authoring, compilation, and publication",
        "mug.authoring",
        "authoring_schema",
        "tests/unit/authoring/test_authoring_conformance.py",
    ),
    Bundle(
        "api-02",
        "Platform composition and deployment",
        "mug.platform",
        "platform_schema",
        "tests/unit/platform/test_platform_conformance.py",
    ),
    Bundle(
        "api-03",
        "Identity, launch, and enrollment",
        "mug.identity",
        "identity_schema",
        "tests/unit/identity/test_identity_conformance.py",
    ),
    Bundle(
        "api-04",
        "Visit plans, flow, treatment, exposure, and state",
        "mug.visits",
        "visits_schema",
        "tests/unit/visits/test_visits_conformance.py",
    ),
    Bundle(
        "api-05",
        "Seats, actor instances, capabilities, and controller bindings",
        "mug.casting",
        "casting_schema",
        "tests/unit/casting/test_casting_conformance.py",
    ),
    Bundle(
        "api-06",
        "Interactions, channels, membership, matchmaking, and leases",
        "mug.interactions",
        "interactions_schema",
        "tests/unit/interactions/test_interactions_conformance.py",
    ),
    Bundle(
        "api-07",
        "Environment, game, input, rendering, and execution modes",
        "mug.game",
        "game_schema",
        "tests/unit/game/test_game_conformance.py",
    ),
    Bundle(
        "api-08",
        "Conversation, routing, history, streaming, and delivery",
        "mug.conversation",
        "conversation_schema",
        "tests/unit/conversation/test_conversation_conformance.py",
    ),
    Bundle(
        "api-09",
        "Participant client, realtime, browser P2P, HTTP, and uploads",
        "mug.client",
        "client_schema",
        "tests/unit/client/test_client_conformance.py",
    ),
    Bundle(
        "api-10",
        "Events, capture, provenance, and projections",
        "mug.events",
        "events_schema",
        "tests/unit/events/test_events_conformance.py",
    ),
    Bundle(
        "api-11",
        "Storage, artifacts, repositories, transactions, and outbox",
        "mug.storage",
        "storage_schema",
        "tests/unit/storage/test_storage_conformance.py",
    ),
    Bundle(
        "api-12",
        "Automated controllers, scheduling, and execution",
        "mug.scheduling",
        "scheduling_schema",
        "tests/unit/scheduling/test_scheduling_conformance.py",
    ),
    Bundle(
        "api-13",
        "Model providers, content, usage, and errors",
        "mug.providers",
        "providers_schema",
        "tests/unit/providers/test_providers_conformance.py",
    ),
    Bundle(
        "api-14",
        "Tools, approval, and environment commands",
        "mug.tools",
        "tools_schema",
        "tests/unit/tools/test_tools_conformance.py",
    ),
    Bundle(
        "api-15",
        "Experimental agent memory",
        "mug.memory",
        "memory_schema",
        "tests/unit/memory/test_memory_conformance.py",
    ),
    Bundle(
        "api-16",
        "Replay capture, bundles, validation, reading, and branching",
        "mug.replay",
        "replay_schema",
        "tests/unit/replay/test_replay_conformance.py",
    ),
    Bundle(
        "api-17",
        "Content, forms, presentation, and accessible UI components",
        "mug.content",
        "content_schema",
        "tests/unit/content/test_content_conformance.py",
    ),
    Bundle(
        "api-18",
        "Preferences, annotation, quality, and adjudication",
        "mug.preferences",
        "preferences_schema",
        "tests/unit/preferences/test_preferences_conformance.py",
    ),
    Bundle(
        "api-19",
        "Dataset query, export, lineage, and external annotation",
        "mug.export",
        "export_schema",
        "tests/unit/export/test_export_conformance.py",
    ),
    Bundle(
        "api-22",
        "Durable background jobs and workers",
        "mug.jobs",
        "jobs_schema",
        "tests/unit/jobs/test_jobs_conformance.py",
    ),
    Bundle(
        "command-results",
        "Command-result payloads (runtime layer)",
        "mug.runtime",
        "command_results_schema",
        "tests/unit/runtime/test_command_results.py",
        registry="_CASES",
    ),
)

# The two families the decision ledger removed. They keep tombstone documents
# and no bytes, so they can never carry a freeze record.
TOMBSTONES: tuple[str, ...] = ("api-20", "api-21")


def canonical_digest(value: Any) -> str:
    """The RFC 8785 SHA-256 hex of a JSON value, the corpus digest everywhere."""
    from hashlib import sha256

    return sha256(rfc8785.dumps(value)).hexdigest()


def corpus_families() -> tuple[str, ...]:
    """Every phase-0 directory that carries schema bytes, in name order."""
    found: list[str] = []
    for path in sorted(PHASE_0_ROOT.iterdir()):
        if path.is_dir() and (path / "schemas" / "v0").is_dir():
            found.append(path.name)
    return tuple(found)


def schema_path(family: str) -> Path:
    """The one `*.schema.json` bundle a family owns."""
    schemas = sorted((PHASE_0_ROOT / family / "schemas" / "v0").glob("*.schema.json"))
    if len(schemas) != 1:
        raise ValueError(f"{family} must own exactly one schema bundle")
    return schemas[0]


def manifest_path(family: str) -> Path | None:
    """The family's fixture manifest, when it has a fixture corpus."""
    path = PHASE_0_ROOT / family / "fixtures" / "v0" / "manifest.json"
    return path if path.exists() else None


def fixture_corpus_digest(family: str) -> str | None:
    """The digest over the bytes of every fixture the family holds.

    The manifest is the index of the evidence; this is the evidence itself.
    Without it a fixture's bytes could change with nothing recording the move,
    which is the same hole the schema pin closes for the contract.
    """
    root = PHASE_0_ROOT / family / "fixtures" / "v0"
    if not root.exists():
        return None
    by_path = {
        str(path.relative_to(root)): canonical_digest(
            json.loads(path.read_text(encoding="utf-8"))
        )
        for directory in ("valid", "invalid")
        for path in sorted((root / directory).glob("*.json"))
    }
    return canonical_digest(by_path)


def contract_revision(family: str) -> str | None:
    """The revision the family's review record states, when it has one."""
    record = PHASE_0_ROOT / family / "review-record.md"
    if not record.exists():
        return None
    for line in record.read_text(encoding="utf-8").splitlines():
        if line.startswith("| Contract revision "):
            return line.split("`")[1]
    return None


def schema_document(family: str) -> dict[str, Any]:
    """The family's raw schema bundle."""
    document: dict[str, Any] = json.loads(
        schema_path(family).read_text(encoding="utf-8")
    )
    return document


def fixture_records(family: str) -> tuple[str, ...]:
    """The record names the family's fixtures exercise: its contract surface.

    A bundle with no fixture corpus of its own -- command-results -- declares no
    record it does not own, so every definition it holds is its surface.
    """
    path = manifest_path(family)
    if path is None:
        return tuple(sorted(schema_document(family).get("$defs", {})))
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = manifest["cases"]
    names = {
        str(case["schema_ref"]).split("#/$defs/", 1)[1]
        for case in cases
        if "#/$defs/" in str(case["schema_ref"])
    }
    return tuple(sorted(names))


def _outbound_refs(
    node: Any, family: str, by_id: dict[str, str]
) -> set[tuple[str, str]]:
    """Every `$defs` target a schema node points at, across bundles.

    A family bundle `$ref`s into the shared kernel, so a reference carries the
    bundle it lands in as well as the definition name.
    """
    found: set[tuple[str, str]] = set()
    if isinstance(node, dict):
        node_map = cast("dict[str, Any]", node)
        ref = node_map.get("$ref")
        if isinstance(ref, str) and "#/$defs/" in ref:
            base, name = ref.split("#/$defs/", 1)
            found.add((by_id.get(base, family) if base else family, name))
        for value in node_map.values():
            found |= _outbound_refs(value, family, by_id)
    elif isinstance(node, list):
        for value in cast("list[Any]", node):
            found |= _outbound_refs(value, family, by_id)
    return found


def unevidenced_records() -> dict[str, tuple[str, ...]]:
    """Definitions no fixture reaches, in any bundle, by any reference.

    A fixture is the evidence that a contract record is real. Start from every
    definition a fixture case names and walk every `$ref`, across bundles -- a
    family bundle refers into the shared kernel, so a definition can be evidenced
    from a family that does not own it. What the walk never reaches is contract
    surface with no golden evidence behind it. The runtime may well implement it;
    nothing proves the two agree.

    Definitions named `Fixture...` are left out. Through the whole corpus that
    prefix marks fixture scaffolding -- the manifest's own shape, and the types a
    fixture's embedded typed objects validate against -- which the contract-
    fixture suites exercise directly. They describe the evidence, not the
    contract.
    """
    families = corpus_families()
    documents = {family: schema_document(family) for family in families}
    by_id = {str(document["$id"]): family for family, document in documents.items()}

    seeds: set[tuple[str, str]] = set()
    for family in families:
        for name in fixture_records(family):
            seeds.add((family, name))

    seen: set[tuple[str, str]] = set()
    pending = list(seeds)
    while pending:
        family, name = pending.pop()
        if (family, name) in seen:
            continue
        definitions: dict[str, Any] = documents.get(family, {}).get("$defs", {})
        if name not in definitions:
            continue
        seen.add((family, name))
        pending += [
            target
            for target in _outbound_refs(definitions[name], family, by_id)
            if target not in seen
        ]

    return {
        family: tuple(
            sorted(
                name
                for name in documents[family].get("$defs", {})
                if (family, name) not in seen and not name.startswith(SCAFFOLD_PREFIX)
            )
        )
        for family in families
    }


def loaded_bundle_digest(bundle: Bundle) -> str:
    """The bundle digest the *running code* computes through its own accessor.

    This is the point of the check. The ledger does not re-implement the digest;
    it asks the package that serves the contract at run time what it holds.
    """
    module: ModuleType = importlib.import_module(bundle.runtime)
    accessor: Any = getattr(module, bundle.accessor)
    digest: str = accessor().bundle_digest
    return digest


def conformance_records(bundle: Bundle) -> frozenset[str]:
    """The record names the family's conformance suite binds to a model.

    The suite's own registry is the single source of truth, so this reads it
    rather than restating the map and letting the two drift.
    """
    if bundle.conformance is None:
        return frozenset()
    path = REPOSITORY_ROOT / bundle.conformance
    spec = importlib.util.spec_from_file_location(f"_freeze_{bundle.family}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {bundle.conformance}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    registry: dict[str, Any] = getattr(module, bundle.registry)
    return frozenset(registry)


def measure(bundle: Bundle, unevidenced: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    """Read one bundle's freeze facts off the corpus and the running code."""
    schema = schema_path(bundle.family)
    manifest = manifest_path(bundle.family)
    return {
        "family": bundle.family,
        "title": bundle.title,
        "contract_revision": contract_revision(bundle.family),
        "schema_path": str(schema.relative_to(REPOSITORY_ROOT)),
        "bundle_digest": loaded_bundle_digest(bundle),
        "fixture_manifest_path": (
            str(manifest.relative_to(REPOSITORY_ROOT)) if manifest else None
        ),
        "fixture_manifest_digest": (
            canonical_digest(json.loads(manifest.read_text(encoding="utf-8")))
            if manifest
            else None
        ),
        "fixture_corpus_digest": fixture_corpus_digest(bundle.family),
        "runtime": bundle.runtime,
        "accessor": bundle.accessor,
        "conformance": bundle.conformance,
        "registry": bundle.registry,
        "records": list(fixture_records(bundle.family)),
        "unevidenced_records": list(unevidenced[bundle.family]),
    }


def build_ledger(pinned_on: str, previous: dict[str, Any] | None) -> dict[str, Any]:
    """Measure every bundle and carry the human fields forward unchanged.

    `owner_sign_off` is the accountable owner's record that the family's review
    is complete. This tool never writes it: a machine cannot sign off a review.
    """
    prior = {
        str(entry["family"]): entry for entry in (previous or {}).get("families", [])
    }
    unevidenced = unevidenced_records()
    families: list[dict[str, Any]] = []
    for bundle in BUNDLES:
        entry = measure(bundle, unevidenced)
        before = prior.get(bundle.family, {})
        unchanged = (
            before.get("bundle_digest") == entry["bundle_digest"]
            and before.get("fixture_manifest_digest")
            == entry["fixture_manifest_digest"]
            and before.get("fixture_corpus_digest") == entry["fixture_corpus_digest"]
        )
        entry["pinned_on"] = (
            before.get("pinned_on", pinned_on) if unchanged else pinned_on
        )
        entry["owner_sign_off"] = before.get("owner_sign_off")
        families.append(entry)
    return {
        "schema": LEDGER_SCHEMA,
        "corpus": "docs/architecture/phase-0",
        "tombstones": list(TOMBSTONES),
        "families": families,
    }


def read_ledger() -> dict[str, Any]:
    """Read the recorded ledger."""
    ledger: dict[str, Any] = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    return ledger


def render_tracker(ledger: dict[str, Any]) -> str:
    """Render the human tracker from the ledger, so the two cannot disagree."""
    families: list[dict[str, Any]] = ledger["families"]
    signed = sum(1 for entry in families if entry["owner_sign_off"])
    open_records = sum(len(entry["unevidenced_records"]) for entry in families)
    lines = [
        "# Contract freeze tracker",
        "",
        "| Field | Value |",
        "| --- | --- |",
        "| Status | Bytes pinned for all "
        f"{len(families)} bundles; owner sign-off recorded for {signed} |",
        "| Source of truth | `contract-freeze.json` |",
        "| Purpose | Record what each contract bundle pins, and what it still needs |",
        "",
        "> **This file is generated.** Rebuild it with",
        "> `uv run python tests/architecture/_freeze.py`. Do not edit it by hand:",
        "> `tests/architecture/test_contract_freeze.py` compares it to the ledger,",
        "> and the ledger to the bytes on disk and the running code.",
        "",
        "## What a freeze means here",
        "",
        "Phase 0 closed with each family's byte-freeze deferred to the",
        "implementation phase, to be run against code rather than against a",
        "design. The mechanical half of that gate is now enforced:",
        "",
        "1. **The bytes are pinned.** The digest below is the digest the running",
        "   loader computes for the bundle. A schema edit that is not recorded",
        "   here fails the gate.",
        "2. **The fixtures are pinned.** The manifest carries its own digest, and",
        "   so do the fixture bytes it indexes, so the evidence cannot move under",
        "   the schema either.",
        "3. **The surface is pinned.** The records column is every `$defs` name",
        "   the fixtures exercise. A new record in the contract fails the gate",
        "   until the freeze is amended.",
        "4. **The running code holds the same bytes.** The digest is read through",
        "   the runtime package's own accessor, not recomputed beside it.",
        "5. **Every record has a model.** The conformance suite binds each record",
        "   name to a model that accepts what the schema accepts and refuses what",
        "   it refuses.",
        "",
        "The remaining half needs a person. The Phase-0 ladder ends with an",
        "adversarial review panel and the accountable owner's sign-off, and no",
        "tool can write those. `owner_sign_off` stays empty until a human records",
        "it, and this table shows it empty rather than assuming it.",
        "",
        "## What is still open",
        "",
    ]
    if open_records:
        lines += [
            f"**{open_records} declared records have no fixture behind them.** A walk",
            "of every `$ref` in the corpus, from every definition a fixture case",
            "names, does not reach them. Each has a running model, so the contract",
            "and the code both hold the record; what is missing is the golden",
            "evidence that the two agree. The list is pinned per bundle below, so it",
            "can only shrink on purpose. Definitions named `Fixture...` are left out:",
            "through the corpus that prefix types the evidence rather than the",
            "contract.",
        ]
    else:
        lines += [
            "**Every declared record has a fixture behind it.** A walk of every",
            "`$ref` in the corpus, from every definition a fixture case names,",
            "reaches every record every bundle declares, so no record is held by the",
            "contract and the code alone. The count is pinned per bundle below, so a",
            "new record that nothing exercises fails the gate. Definitions named",
            "`Fixture...` are left out: through the corpus that prefix types the",
            "evidence rather than the contract.",
        ]
    lines += [
        "",
        "**No bundle carries an owner sign-off.** The mechanical gates say the",
        "bytes and the code match. They say nothing about whether the contract is",
        "the right contract, which is what the review panel was for.",
        "",
        "## Bundles",
        "",
        "| Bundle | Rev | Bundle digest | Records | No fixture | Runtime | Pinned |"
        " Owner sign-off |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entry in families:
        revision = entry["contract_revision"] or "—"
        digest = str(entry["bundle_digest"])[:8]
        records = len(entry["records"]) or "—"
        open_here = len(entry["unevidenced_records"]) or "—"
        sign_off = entry["owner_sign_off"] or "—"
        lines.append(
            f"| `{entry['family']}` {entry['title']} | {revision} | `{digest}…` |"
            f" {records} | {open_here} | `{entry['runtime']}` | {entry['pinned_on']} |"
            f" {sign_off} |"
        )
    lines += [
        "",
        "Tombstones carry no bytes and can hold no freeze record: "
        + ", ".join(f"`{name}`" for name in ledger["tombstones"])
        + ".",
        "",
        "## What each bundle pins",
        "",
    ]
    for entry in families:
        lines.append(f"### `{entry['family']}` — {entry['title']}")
        lines.append("")
        lines.append(f"- Schema: `{entry['schema_path']}`")
        lines.append(f"- Bundle digest: `{entry['bundle_digest']}`")
        if entry["fixture_manifest_path"]:
            lines.append(f"- Fixtures: `{entry['fixture_manifest_path']}`")
            lines.append(f"- Fixture digest: `{entry['fixture_manifest_digest']}`")
            lines.append(f"- Fixture bytes: `{entry['fixture_corpus_digest']}`")
        else:
            lines.append("- Fixtures: none; the bundle is exercised through its users")
        lines.append(f"- Runtime: `{entry['runtime']}.{entry['accessor']}()`")
        if entry["conformance"]:
            lines.append(f"- Conformance: `{entry['conformance']}`")
        if entry["records"]:
            joined = ", ".join(f"`{name}`" for name in entry["records"])
            lines.append(f"- Records ({len(entry['records'])}): {joined}")
        if entry["unevidenced_records"]:
            joined = ", ".join(f"`{name}`" for name in entry["unevidenced_records"])
            lines.append(f"- No fixture reaches: {joined}")
        lines.append("")
    return "\n".join(lines)


def write(pinned_on: str) -> None:
    """Rebuild the ledger and the tracker from the corpus and the running code."""
    previous = read_ledger() if LEDGER_PATH.exists() else None
    ledger = build_ledger(pinned_on, previous)
    LEDGER_PATH.write_text(
        json.dumps(ledger, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    TRACKER_PATH.write_text(render_tracker(ledger) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import sys
    from datetime import date

    write(sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat())
    print(f"wrote {LEDGER_PATH.relative_to(REPOSITORY_ROOT)}")
    print(f"wrote {TRACKER_PATH.relative_to(REPOSITORY_ROOT)}")
