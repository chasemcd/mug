"""Record a model generation as a durable candidate a participant can compare.

A preference over model outputs is not a preference over a live model. NS-02 says
it plainly: a candidate-generation job records the generations, and an *independent*
annotator compares them later, without running the original interaction and without
contacting either provider. So the generation and the annotation are two separate
pieces of work, and everything the annotation needs must already be on disk when it
starts.

This module is the generation side. Given one versioned input and the models under
test, it runs each model once through the recorded provider path
(``mug.providers.runtime``), writes the completed output in its three forms
(``mug.providers.durable_tape``), writes the provider and model identity into a
private provenance artifact beside them, and commits one *generation record* naming
all four. The record is the address a comparison resolves an option to.

Three properties make it usable by a study rather than only by a script:

- **It runs once.** The generation identifier derives from the option key and the
  digest of the input, so re-running the same set finds the recorded generation and
  contacts no provider. That is what lets a deployment call this on every start.
- **The provider is not in the candidate.** The three output forms name no provider
  and no model; the provenance artifact names both and is classified so it never
  reaches a browser. A comparison is blinded because the evidence is separated, not
  because a screen remembers to hide a field.
- **The record is bound to the ledger.** The commit's payload digest is the digest
  of the generation record, so the four artifact references are checkable against
  the event stream rather than trusted beside it.

An option in an author's ``Comparison`` names the generation key, which is the one
name the author wrote. The comparison mount resolves it to the visible form.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

from mug.agents.runtime import AgentIds, compile_agent
from mug.authoring import LLMAgent
from mug.kernel import ArtifactRef, CommandTypeRef, DataHandlingRef, TypedObject
from mug.kernel import compute_digest as _digest
from mug.providers import (
    AgentVersion,
    ModelProvider,
    ProviderAdapter,
    SecretResolver,
)
from mug.providers.durable_tape import (
    ArtifactOutputTape,
    Normalize,
    RenderVisible,
)
from mug.providers.runtime import NewContext, Payload
from mug.runtime import CommandContext, commit_command
from mug.storage import ArtifactStore, Store, json_bytes, stage_artifact

# Mint one runtime-occurrence id of the named kind, and derive one from a seed.
NewId = Callable[[str], str]
DeriveId = Callable[[str, str], str]

_RECORD = CommandTypeRef(name="generation.record", version=0)

# The command's result is the provider response the generation is, so the committed
# event carries the API-13 response schema and its payload digest binds the whole
# generation record beside it.

# The provider, the model, and what the call cost. It is the audit trail, so it is
# the strictest classification and it is never sent to a client.
_PRIVATE = DataHandlingRef(privacy_labels=["research", "sensitive"])
_JSON = "application/json"

# The version and fallback a generation build carries. A generation answers one
# input once and never falls back to a previous action, so both are fixed here
# rather than asked of the author.
_VERSION_NUMBER = 1
_FALLBACK_POLICY = "generation-no-fallback"

# The canonical wire form of an instant, shared with the provider runtime.
_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _instant(now: Callable[[], datetime]) -> str:
    """Return the current instant in the canonical wire form."""
    return now().astimezone(timezone.utc).strftime(_INSTANT)


@dataclass(frozen=True)
class ModelUnderTest:
    """One model whose generation a study compares: the definition and its provider.

    ``agent`` is the author's own ``LLMAgent``, so a model under test is written the
    same way a playing or chatting agent is. ``adapter`` runs its calls, because the
    core imports no vendor SDK; ``resolve_secret`` resolves the agent's credential at
    call time and is unset for a keyless local runner.

    ``normalize`` and ``render`` are the two seams for a provider that answers in a
    shape the defaults do not read: one produces the provider-independent generation,
    the other the text a participant is shown.
    """

    agent: LLMAgent
    adapter: ProviderAdapter
    resolve_secret: SecretResolver | None = None
    normalize: Normalize | None = None
    render: RenderVisible | None = None


@dataclass(frozen=True)
class GenerationSet:
    """The candidate generations a study records before its annotators arrive.

    ``input`` is the one versioned input every model answers -- the same input, so
    the comparison is between the models and not between two questions. ``models``
    maps the key an author writes in a ``Comparison`` option to the model that
    answers it.
    """

    input: Payload
    models: Mapping[str, ModelUnderTest]

    def __post_init__(self) -> None:
        if len(self.models) < 1:
            raise ValueError("a generation set needs at least one model")


@dataclass(frozen=True)
class RecordedGeneration:
    """One recorded generation: what it answered, and where its four forms live.

    ``visible`` is the only form a participant is shown. ``raw`` is what the provider
    returned, ``normalized`` is the same generation with the vendor out of it, and
    ``provenance`` names the provider and the model -- so a blinded comparison and a
    full audit read the same generation and see different parts of it.
    """

    generation_id: str
    generation_key: str
    input_digest: str
    modelcall_id: str
    raw: ArtifactRef
    normalized: ArtifactRef
    visible: ArtifactRef
    provenance: ArtifactRef


def input_digest_of(payload: Payload) -> str:
    """Return the version of one generation input: the digest of the input itself."""
    return _digest(payload).hex


def generation_id_for(derive: DeriveId, key: str, input_digest: str) -> str:
    """Return the one generation identifier this option key and input always give."""
    return derive("generation", f"generation:{key}:{input_digest}")


def recorded_generation(store: Store, generation_id: str) -> RecordedGeneration | None:
    """Return the generation this identifier recorded, or None when none is recorded.

    The record is the head of its own aggregate, so a reader that holds the key and
    the input holds the address, and no index is kept beside the ledger.
    """
    state = store.load_aggregate(generation_id)
    if not isinstance(state, dict):
        return None
    body = cast("dict[str, Any]", state)
    try:
        return RecordedGeneration(
            generation_id=cast("str", body["generation_id"]),
            generation_key=cast("str", body["generation_key"]),
            input_digest=cast("str", body["input_digest"]),
            modelcall_id=cast("str", body["modelcall_id"]),
            raw=ArtifactRef.model_validate(body["raw"]),
            normalized=ArtifactRef.model_validate(body["normalized"]),
            visible=ArtifactRef.model_validate(body["visible"]),
            provenance=ArtifactRef.model_validate(body["provenance"]),
        )
    except (KeyError, ValueError):
        return None


async def record_generations(
    spec: GenerationSet,
    *,
    store: Store,
    artifacts: ArtifactStore,
    derive: DeriveId,
    new_context: NewContext,
    new_id: NewId,
    now: Callable[[], datetime],
) -> dict[str, RecordedGeneration]:
    """Record every model's generation for one input, and return them by key.

    A generation that is already recorded is returned as it stands and its provider
    is not called, so this is safe to run on every start of a deployment and a
    restart costs nothing. A call that errors or is refused records no generation:
    the option then has no candidate behind it, and the comparison that names it
    declines to run rather than compare an answer against a gap.
    """
    recorded: dict[str, RecordedGeneration] = {}
    version = input_digest_of(spec.input)
    for key, model in spec.models.items():
        generation_id = generation_id_for(derive, key, version)
        existing = recorded_generation(store, generation_id)
        if existing is not None:
            recorded[key] = existing
            continue
        made = await _record_one(
            key,
            model,
            spec.input,
            generation_id=generation_id,
            input_digest=version,
            store=store,
            artifacts=artifacts,
            derive=derive,
            new_context=new_context,
            new_id=new_id,
            now=now,
        )
        if made is not None:
            recorded[key] = made
    return recorded


async def _record_one(
    key: str,
    model: ModelUnderTest,
    payload: Payload,
    *,
    generation_id: str,
    input_digest: str,
    store: Store,
    artifacts: ArtifactStore,
    derive: DeriveId,
    new_context: NewContext,
    new_id: NewId,
    now: Callable[[], datetime],
) -> RecordedGeneration | None:
    """Run one model once, write its four artifacts, and commit its record."""
    modelcall_id = derive("modelcall", f"generation:{key}:{input_digest}")
    build = compile_agent(model.agent, ids=_agent_ids(derive, key))
    tape = ArtifactOutputTape(
        artifacts,
        artifact_id_for=lambda seed: derive("artifact", seed),
        new_upload_id=lambda: new_id("upload"),
        now=lambda: _instant(now),
        normalize=model.normalize,
        render=model.render,
    )
    provider = ModelProvider(
        store=store,
        adapter=model.adapter,
        now=now,
        new_generation_id=lambda: new_id("generation"),
    )
    result = await provider.invoke(
        modelcall_id=modelcall_id,
        agent_version=build,
        payload=payload,
        new_context=new_context,
        resolve_secret=model.resolve_secret,
    )
    response = result.response
    if response is None or response.output_digest is None or result.output is None:
        return None
    forms = await tape.stage(response.output_digest, result.output)
    provenance = await _stage_provenance(
        artifacts,
        build=build,
        modelcall_id=modelcall_id,
        generation_id=generation_id,
        resolved_model=response.resolved_model,
        usage=response.usage.model_dump(mode="json"),
        artifact_id=derive("artifact", f"generation-provenance:{generation_id}"),
        new_upload_id=lambda: new_id("upload"),
        now=lambda: _instant(now),
    )
    record = RecordedGeneration(
        generation_id=generation_id,
        generation_key=key,
        input_digest=input_digest,
        modelcall_id=modelcall_id,
        raw=forms.raw,
        normalized=forms.normalized,
        visible=forms.visible,
        provenance=provenance,
    )
    receipt = await commit_command(
        new_context(generation_id),
        command=_RECORD,
        new_state=_state(record),
        result=TypedObject(
            schema=response.schema,
            data=response.model_dump(mode="json", exclude_none=True),
        ),
        store=store,
    )
    return record if receipt.outcome == "accepted" else None


def _agent_ids(derive: DeriveId, key: str) -> AgentIds:
    """Derive the pinned build identifiers for one model under test.

    A published study takes these from its agent catalog. A generation set names its
    models by the author's own key, so the identifiers derive from that key and the
    author writes none of them.
    """
    return AgentIds(
        agent_version_id=derive("agentver", f"generation:{key}"),
        agent_definition_id=derive("agentdef", f"generation:{key}"),
        agent_key=key,
        version_number=_VERSION_NUMBER,
        prompt_version_id=derive("promptver", f"generation:{key}"),
        fallback_policy_key=_FALLBACK_POLICY,
    )


async def _stage_provenance(
    artifacts: ArtifactStore,
    *,
    build: AgentVersion,
    modelcall_id: str,
    generation_id: str,
    resolved_model: str,
    usage: dict[str, Any],
    artifact_id: str,
    new_upload_id: Callable[[], str],
    now: Callable[[], str],
) -> ArtifactRef:
    """Write the private provenance of one generation: who answered, and at what cost.

    This is the only place the provider and the model are written down beside the
    generation. It is classified ``research, sensitive``, so a blinded comparison can
    never carry it to a browser, and a researcher who is entitled to it reads the
    same generation unblinded.
    """
    body = {
        "generation_id": generation_id,
        "modelcall_id": modelcall_id,
        "provider": build.provider,
        "model_selector": build.model_selector,
        "resolved_model": resolved_model,
        "agent_version_id": build.agent_version_id,
        "secret_name": build.secret_name,
        "usage": usage,
    }
    return await stage_artifact(
        artifacts,
        data=json_bytes(body) + b"\n",
        media_type=_JSON,
        new_artifact_id=lambda: artifact_id,
        new_upload_id=new_upload_id,
        now=now,
        data_handling=_PRIVATE,
    )


async def record_reply(
    *,
    generation_id: str,
    generation_key: str,
    input_digest: str,
    modelcall_id: str,
    build: AgentVersion,
    response: Any,
    forms: Any,
    artifacts: ArtifactStore,
    artifact_id_for: Callable[[str], str],
    new_upload_id: Callable[[], str],
    now: Callable[[], str],
    context: CommandContext,
    store: Store,
) -> RecordedGeneration | None:
    """Record one already-produced model output as a durable generation.

    ``record_generations`` runs the model itself, before anyone arrives. This one
    takes an output that has *already* been produced -- a live chat reply the
    participant has read -- and gives it the same four artifacts and the same
    record, so a live conversation can supply the candidates a preference activity
    asks about (W16, W19). The provenance is written here and nowhere else, and it
    stays private exactly as it does for a pre-recorded generation.
    """
    provenance = await _stage_provenance(
        artifacts,
        build=build,
        modelcall_id=modelcall_id,
        generation_id=generation_id,
        resolved_model=response.resolved_model,
        usage=response.usage.model_dump(mode="json"),
        artifact_id=artifact_id_for(f"generation-provenance:{generation_id}"),
        new_upload_id=new_upload_id,
        now=now,
    )
    record = RecordedGeneration(
        generation_id=generation_id,
        generation_key=generation_key,
        input_digest=input_digest,
        modelcall_id=modelcall_id,
        raw=forms.raw,
        normalized=forms.normalized,
        visible=forms.visible,
        provenance=provenance,
    )
    receipt = await commit_command(
        context,
        command=_RECORD,
        new_state=_state(record),
        result=TypedObject(
            schema=response.schema,
            data=response.model_dump(mode="json", exclude_none=True),
        ),
        store=store,
    )
    return record if receipt.outcome == "accepted" else None


def _state(record: RecordedGeneration) -> dict[str, Any]:
    """Draft the generation aggregate state one record commits."""
    return {
        "generation_id": record.generation_id,
        "generation_key": record.generation_key,
        "input_digest": record.input_digest,
        "modelcall_id": record.modelcall_id,
        "raw": record.raw.model_dump(mode="json", exclude_none=True),
        "normalized": record.normalized.model_dump(mode="json", exclude_none=True),
        "visible": record.visible.model_dump(mode="json", exclude_none=True),
        "provenance": record.provenance.model_dump(mode="json", exclude_none=True),
    }


__all__ = [
    "DeriveId",
    "GenerationSet",
    "ModelUnderTest",
    "RecordedGeneration",
    "generation_id_for",
    "input_digest_of",
    "record_generations",
    "record_reply",
    "recorded_generation",
]
