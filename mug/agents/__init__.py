"""The LLM agent runtime (layer above providers and scheduling).

The author-facing definition lives in ``mug.authoring`` (``LLMAgent`` and the
``History``/``Thoughts`` views). This package is the runtime that drives it: it
composes the built ``ModelProvider`` (API-13) and ``Scheduler`` (API-12) -- which are
siblings and cannot import each other -- behind the author's ``get_prompt`` /
``parse_reply`` / ``reflect`` methods.

``LLMController.decide`` is the ``AsyncController`` the scheduler awaits;
``compile_agent`` pins an ``LLMAgent`` definition into the frozen ``AgentVersion`` the
provider needs. ``AgentEpisode`` drives one LLM seat through a full episode: it
samples the seat every frame, fires a decision at the agent's cadence, and feeds
the agent's history and chat.

``mug.agents.adapters`` ships the real provider adapters the provider runtime drives
-- ``OllamaAdapter`` (local, free), ``AnthropicAdapter``, and ``OpenAIAdapter`` --
each behind the same injected ``ProviderAdapter`` seam. ``adapter_for`` picks one by
the provider name an ``AgentVersion`` carries, so a study author only sets the
provider on the agent.
"""

from __future__ import annotations

from mug.agents.adapters import (
    AnthropicAdapter,
    ChatAdapter,
    HttpRequest,
    HttpResponse,
    HttpTransport,
    OllamaAdapter,
    OpenAIAdapter,
    TransportFailure,
    adapter_for,
    httpx_transport,
)
from mug.agents.chat import (
    ChatAgent,
    ChatReply,
    ChatTurn,
    ComposePrompt,
    PendingReply,
)
from mug.agents.episode import AgentEpisode, AgentEpisodeResult
from mug.agents.game import (
    AgentGameSpec,
    AgentSeatSpec,
    BotSeatSpec,
    HumanSeatSpec,
    TurnBasedGameSpec,
    build_agent_episode,
    build_turnbased_episode,
)
from mug.agents.generation import (
    GenerationSet,
    ModelUnderTest,
    RecordedGeneration,
    generation_id_for,
    input_digest_of,
    record_generations,
    recorded_generation,
)
from mug.agents.multiseat_episode import (
    AgentSeat,
    AgentSeatResult,
    LocalSeat,
    MultiAgentEpisode,
    MultiAgentEpisodeResult,
)
from mug.agents.runtime import (
    LOCAL_NO_KEY,
    AgentIds,
    ControllerDecodeMiss,
    LLMController,
    compile_agent,
    timeout_fallback,
)
from mug.agents.turnbased_episode import (
    TurnBasedAgentEpisode,
    TurnBasedAgentEpisodeResult,
)

__all__ = [
    "LOCAL_NO_KEY",
    "AgentEpisode",
    "AgentEpisodeResult",
    "AgentGameSpec",
    "AgentIds",
    "AgentSeat",
    "AgentSeatResult",
    "AgentSeatSpec",
    "AnthropicAdapter",
    "BotSeatSpec",
    "ChatAdapter",
    "ChatAgent",
    "ChatReply",
    "ChatTurn",
    "ComposePrompt",
    "ControllerDecodeMiss",
    "GenerationSet",
    "HttpRequest",
    "HttpResponse",
    "HttpTransport",
    "HumanSeatSpec",
    "LLMController",
    "LocalSeat",
    "ModelUnderTest",
    "MultiAgentEpisode",
    "MultiAgentEpisodeResult",
    "OllamaAdapter",
    "OpenAIAdapter",
    "PendingReply",
    "RecordedGeneration",
    "TransportFailure",
    "TurnBasedAgentEpisode",
    "TurnBasedAgentEpisodeResult",
    "TurnBasedGameSpec",
    "adapter_for",
    "build_agent_episode",
    "build_turnbased_episode",
    "compile_agent",
    "generation_id_for",
    "httpx_transport",
    "input_digest_of",
    "record_generations",
    "recorded_generation",
    "timeout_fallback",
]
