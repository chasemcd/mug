"""Environment, game, rendering, and execution (API-07, layer L1).

This family owns six record types: the ``EnvFactory`` that names a study
environment factory, the ``ExecutionMode`` that fixes the run contract, the
normalized ``GameTransition`` that every runtime produces, the ``RenderPacket``
that ships surface commands to a seat, the ``EpisodeBoundary`` that closes an
episode, and the ``P2PFrameFinality`` that records mesh agreement. Each record
references the kernel (L0) types.

The ``surface``, ``env``, and ``runtime`` submodules add the server-authoritative
stepping loop. They stay out of this package import, because ``env`` needs the
optional ``game`` extra (Gymnasium); import them directly where the extra is
installed.
"""

from __future__ import annotations

from mug.game.types import (
    EnvFactory,
    EpisodeBoundary,
    ExecutionMode,
    GameTransition,
    P2PFrameFinality,
    RenderPacket,
    game_schema,
)

__all__ = [
    "EnvFactory",
    "EpisodeBoundary",
    "ExecutionMode",
    "GameTransition",
    "P2PFrameFinality",
    "RenderPacket",
    "game_schema",
]
