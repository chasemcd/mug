"""Model providers, usage, and errors (API-13, layer L1).

This family owns four record types: the immutable ``AgentVersion`` build, the
``ProviderRequest`` that dispatches one model call, the ``ProviderResponse`` that
records its outcome and usage, and the ``ProviderError`` that classifies a
failure. Each record references the credential by name only; no record models raw
secret material.

``mug.providers.runtime`` adds the model-call runtime over these records: it drives
one call through an injected, vendor-free adapter and records its request and
outcome on the command spine, resolving the credential by name at call time and
never persisting it.
"""

from __future__ import annotations

from mug.providers.durable_tape import (
    GENERATION_FORMS,
    ArtifactOutputTape,
    GenerationForm,
    GenerationForms,
    Normalize,
    RenderVisible,
    normalize_output,
    read_generation_form,
    render_visible,
)
from mug.providers.runtime import (
    FakeProvider,
    ModelCall,
    ModelCallResult,
    ModelCompletion,
    ModelProvider,
    ProviderAdapter,
    SecretResolver,
)
from mug.providers.tape import InMemoryOutputTape, Output, OutputTape
from mug.providers.types import (
    AgentVersion,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    Usage,
    providers_schema,
)

__all__ = [
    "GENERATION_FORMS",
    "AgentVersion",
    "ArtifactOutputTape",
    "FakeProvider",
    "GenerationForm",
    "GenerationForms",
    "InMemoryOutputTape",
    "ModelCall",
    "ModelCallResult",
    "ModelCompletion",
    "ModelProvider",
    "Normalize",
    "Output",
    "OutputTape",
    "ProviderAdapter",
    "ProviderError",
    "ProviderRequest",
    "ProviderResponse",
    "RenderVisible",
    "SecretResolver",
    "Usage",
    "normalize_output",
    "providers_schema",
    "read_generation_form",
    "render_visible",
]
