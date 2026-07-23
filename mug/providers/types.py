"""The four objects that API-13 owns: agent versions, requests, responses, errors.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``providers_schema`` loads it for the conformance test.

An agent version names its provider and model but never carries the secret; a
``secret_name`` references the credential by name (a ``SecretRef`` authoring key).
No object in this family models raw secret material.

One invariant is not expressible in JSON Schema and lives here as a validator:

- a completed response must carry the digest of its output.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from mug.kernel import (
    Digest,
    SchemaBundle,
    SchemaRef,
    UtcInstant,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import (
    AgentDefinitionId,
    AgentVersionId,
    ModelGenerationId,
    ModelInvocationId,
    PromptTemplateVersionId,
    ToolVersionId,
)
from mug.kernel.refs import NonNegativeSafeInteger, PositiveSafeInteger

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-13/schemas/v0/provider.schema.json"
)


@lru_cache(maxsize=1)
def providers_schema() -> SchemaBundle:
    """Return the loaded API-13 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=providers_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


_AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]
_ModelSelector = Annotated[
    str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$", max_length=200)
]
Provider = Literal["openai", "anthropic", "oss", "http"]


class AgentVersion(KernelModel):
    """An immutable agent build: provider, model, prompt, tools, and parameters."""

    # 'schema' is the contract field name; it shadows BaseModel.schema.
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-13.agent-version")
    )
    agent_version_id: AgentVersionId
    agent_definition_id: AgentDefinitionId
    agent_key: _AuthoringKey
    version_number: PositiveSafeInteger
    provider: Provider
    model_selector: _ModelSelector
    prompt_version_id: PromptTemplateVersionId
    parameters_digest: Digest
    tool_version_ids: Annotated[list[ToolVersionId], Field(max_length=128)]
    fallback_policy_key: _AuthoringKey
    secret_name: _AuthoringKey | None = None


class ProviderRequest(KernelModel):
    """One dispatch to a provider: the request digest and the secret it uses."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-13.provider-request")
    )
    modelcall_id: ModelInvocationId
    agent_version_id: AgentVersionId
    request_digest: Digest
    secret_name: _AuthoringKey
    submitted_at: UtcInstant


class Usage(KernelModel):
    """Token counts and cost for one model call, in tokens and micro-units."""

    input_tokens: NonNegativeSafeInteger
    output_tokens: NonNegativeSafeInteger
    cost_micros: NonNegativeSafeInteger


class ProviderResponse(KernelModel):
    """The outcome of one model call: how it ended, the model, and its usage."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-13.provider-response")
    )
    modelcall_id: ModelInvocationId
    generation_id: ModelGenerationId
    outcome: Literal["completed", "refused", "error"]
    resolved_model: _ModelSelector
    usage: Usage
    output_digest: Digest | None = None
    completed_at: UtcInstant

    @model_validator(mode="after")
    def _completed_carries_output(self) -> ProviderResponse:
        if self.outcome == "completed" and self.output_digest is None:
            raise ValueError("a completed response must carry its output digest")
        return self


class ProviderError(KernelModel):
    """A failed model call, classified and marked retryable or not."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-13.provider-error")
    )
    modelcall_id: ModelInvocationId
    error_class: Literal["timeout", "rate-limit", "provider-error", "content-filter"]
    retryable: bool
