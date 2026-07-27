"""The durable output tape: an output survives the process that produced it.

``InMemoryOutputTape`` makes a replay exact inside one process. That is not enough
for a preference candidate, which a different process opens later with the provider
offline. These tests drive ``ArtifactOutputTape`` over the real object store and
check what the durability is for: the output comes back after the tape that wrote
it is gone, one output always lands at one address, and the three forms are three
artifacts with three classifications.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mug.gateway import Gateway
from mug.kernel import compute_digest
from mug.providers import (
    ArtifactOutputTape,
    FakeProvider,
    ModelProvider,
    normalize_output,
    read_generation_form,
    render_visible,
)
from mug.providers.types import AgentVersion
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_OUTPUT = {"text": "the sky is blue", "vendor_trace": "provider-internal-9"}
_UUID = "019b6000-0000-7000-8000-{:012x}"


def _tape(store: InMemoryStore, gateway: Gateway, **seams: Any) -> ArtifactOutputTape:
    """Build a tape over one store, addressed through one gateway's derivation."""
    return ArtifactOutputTape(
        store,
        artifact_id_for=lambda seed: gateway.derived_id("artifact", seed),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=lambda: "2026-07-26T00:00:00.000000Z",
        **seams,
    )


async def test_an_output_comes_back_after_the_tape_that_wrote_it_is_gone() -> None:
    """The point of the durable tape: a second tape over the store reads it back."""
    store, gateway = InMemoryStore(), Gateway(secret=b"one deployment")
    digest = compute_digest(_OUTPUT)
    await _tape(store, gateway).put(digest, _OUTPUT)

    # A new tape, as a restarted process would build: it holds nothing of its own.
    assert await _tape(store, Gateway(secret=b"one deployment")).get(digest) == _OUTPUT


async def test_an_output_the_tape_never_recorded_reads_back_as_nothing() -> None:
    """A partial tape degrades to recorded-by-digest rather than failing."""
    store, gateway = InMemoryStore(), Gateway()
    assert await _tape(store, gateway).get(compute_digest({"text": "never"})) is None


async def test_one_output_always_lands_at_one_address() -> None:
    """Re-recording the same output overwrites, so a retry grows no second copy."""
    store, gateway = InMemoryStore(), Gateway(secret=b"one deployment")
    digest = compute_digest(_OUTPUT)
    first = await _tape(store, gateway).stage(digest, _OUTPUT)
    again = await _tape(store, gateway).stage(digest, _OUTPUT)

    assert first == again
    # Three forms, one copy of each: the identical second write overwrote them.
    written = {ref.artifact_id for ref in (first.raw, first.normalized, first.visible)}
    assert len(written) == 3
    for ref in (again.raw, again.normalized, again.visible):
        assert await store.read_artifact(ref.artifact_id)


async def test_the_three_forms_are_three_artifacts_with_three_classifications() -> None:
    """Distinct references is the NS-02 property, so the identifiers are read."""
    store, gateway = InMemoryStore(), Gateway()
    forms = await _tape(store, gateway).stage(compute_digest(_OUTPUT), _OUTPUT)

    ids = {form.artifact_id for form in (forms.raw, forms.normalized, forms.visible)}
    assert len(ids) == 3
    assert forms.raw.data_handling.privacy_labels == ["research", "sensitive"]
    assert forms.normalized.data_handling.privacy_labels == ["research"]
    assert forms.visible.data_handling.privacy_labels == ["public"]
    assert forms.of("visible") == forms.visible


async def test_the_visible_form_carries_the_text_and_nothing_the_vendor_added() -> None:
    """A comparison screen sends this form, so this form is what must be clean."""
    store, gateway = InMemoryStore(), Gateway()
    forms = await _tape(store, gateway).stage(compute_digest(_OUTPUT), _OUTPUT)

    assert await read_generation_form(store, forms.raw) == _OUTPUT
    visible = await read_generation_form(store, forms.visible)
    assert visible == {"text": "the sky is blue"}
    normalized = await read_generation_form(store, forms.normalized)
    assert normalized == {"text": "the sky is blue", "parts": ["the sky is blue"]}


async def test_a_study_replaces_how_its_provider_is_read() -> None:
    """A provider that answers in another shape needs no change to the tape."""
    store, gateway = InMemoryStore(), Gateway()
    output = {"choices": [{"message": "hello there"}]}

    def normalize(raw: Any) -> dict[str, Any]:
        return {"text": raw["choices"][0]["message"], "parts": []}

    def render(raw: Any) -> str:
        return raw["choices"][0]["message"]

    forms = await _tape(store, gateway, normalize=normalize, render=render).stage(
        compute_digest(output), output
    )
    assert await read_generation_form(store, forms.visible) == {"text": "hello there"}


def test_an_output_the_defaults_cannot_read_renders_as_nothing() -> None:
    """A vendor shape must not reach a participant just because it was unreadable."""
    assert render_visible({"unexpected": [1, 2, 3]}) == ""
    assert normalize_output({"unexpected": [1, 2, 3]})["value"] == {
        "unexpected": [1, 2, 3]
    }
    assert render_visible("a bare string") == "a bare string"


async def test_a_provider_replays_its_output_through_the_durable_tape() -> None:
    """The tape is the seam it claims to be: the provider takes it unchanged."""
    store, gateway = InMemoryStore(), Gateway(secret=b"one deployment")
    tape = _tape(store, gateway)
    provider = ModelProvider(
        store=store,
        adapter=FakeProvider(lambda _payload: _OUTPUT),
        now=lambda: datetime(2026, 7, 26, tzinfo=timezone.utc),
        new_generation_id=lambda: gateway.new_id("generation"),
        output_tape=tape,
    )
    modelcall_id = "modelcall_" + _UUID.format(0x900)
    first = await provider.invoke(
        modelcall_id=modelcall_id,
        agent_version=_build(),
        payload={"prompt": "why is the sky blue"},
        new_context=lambda aggregate_id: _context(gateway, aggregate_id),
    )
    assert first.output == _OUTPUT

    # The same call again: the store replays the terminal head, and the tape -- not
    # the provider -- is what returns the text.
    replayed = await provider.invoke(
        modelcall_id=modelcall_id,
        agent_version=_build(),
        payload={"prompt": "why is the sky blue"},
        new_context=lambda aggregate_id: _context(gateway, aggregate_id),
    )
    assert replayed.replayed is True
    assert replayed.output == _OUTPUT


def _build() -> AgentVersion:
    """The pinned build one recorded call names."""
    return AgentVersion(
        agent_version_id="agentver_" + _UUID.format(0x910),
        agent_definition_id="agentdef_" + _UUID.format(0x911),
        agent_key="writer",
        version_number=1,
        provider="oss",
        model_selector="fake-local",
        prompt_version_id="promptver_" + _UUID.format(0x912),
        parameters_digest=compute_digest({"model": "fake-local"}),
        tool_version_ids=[],
        fallback_policy_key="none",
        secret_name="local-no-key",
    )


def _context(gateway: Gateway, aggregate_id: str) -> CommandContext:
    """Mint one command context on an aggregate's stream, as a mount would."""
    from mug.kernel import DataHandlingRef, Digest, PrincipalRef, WireCommandEnvelope

    zero = Digest(algorithm="sha-256", hex="0" * 64).model_dump(mode="json")
    envelope = WireCommandEnvelope.model_validate(
        {
            "schema": {"name": "mug.command-envelope", "version": 0, "digest": zero},
            "protocol_version": "0.1.0",
            "command": {"name": "provider.submit", "version": 0},
            "request_id": "request_" + _UUID.format(0x920),
            "idempotency_key": "idem_" + gateway.new_id("request").split("_", 1)[1]
            .replace("-", "")[:21] + "A",
            "target": {"id": aggregate_id},
            "payload": {
                "schema": {"name": "mug.edge.payload", "version": 0, "digest": zero},
                "data": {"aggregate_id": aggregate_id},
            },
        }
    )
    return gateway.mint(
        envelope,
        principal=PrincipalRef(kind="service", id="service_" + _UUID.format(0x930)),
        data_handling=DataHandlingRef(privacy_labels=["research"]),
    )
