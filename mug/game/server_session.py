"""Host one server-authoritative multi-seat episode, bots beside humans (API-07).

``MeshSession`` hosts the peer-to-peer game: one engine per seat, each over its own
replica, reconciled by rollback. This module hosts the *server-authoritative*
counterpart: one authoritative environment on the server, stepped once per frame,
with every seat -- a human, a local bot controller, or a scheduled agent -- reading
its action through the one ``SeatActionSource`` seam. So a bot seats beside a human
in one interaction, and the server owns the single writer: a seat supplies an
action, never a state.

The stepping and recording is the shared ``run_multiseat_episode`` loop; this module
is the session around it. It binds the seats, declares the ``ExecutionMode.server``
contract the channel runs under (single writer, no per-replica rollback), runs the
one authoritative timeline, and reports one ``EpisodeSummary`` per seat over the
shared transitions -- the same per-seat shape ``MeshSession`` reports, so the capture
path and the matchmaker treat a server-authoritative interaction exactly as they
treat a mesh one. The one authoritative timeline is captured once, from the
reference seat.

The session is environment-neutral and transport-neutral, like the loop it wraps.
The study supplies the ``MultiSeatEnv``; each seat's source is injected (a human's
``InputState``, a controller, or a scheduled agent). So a test drives a bot beside a
human with a scripted controller and a scripted input, with no socket and no clock.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from mug.game.multiseat import MultiSeatEnv, MultiSeatObserver, run_multiseat_episode
from mug.game.runtime import EpisodeSummary
from mug.game.seams import Clock, SeatActionSource
from mug.game.types import ExecutionMode


def server_execution_mode(
    *, snapshot_contract: Literal["none", "keyframe"] = "keyframe"
) -> ExecutionMode:
    """Return the ``ExecutionMode`` a server-authoritative channel runs under.

    The server owns the single writer and runs no per-replica rollback, so the mode
    is ``server`` with the ``single`` writer and no mesh contract. A study picks the
    snapshot contract: ``keyframe`` records periodic keyframes, ``none`` records no
    snapshot.
    """
    return ExecutionMode(
        mode="server",
        snapshot_contract=snapshot_contract,
        writer="single",
        p2p_contract=None,
    )


@dataclass(frozen=True)
class ServerSeat:
    """One seat in a server-authoritative interaction: its identity and its source.

    ``actor_id`` is the participant actor the summary is keyed by; ``agent_id`` is
    the environment agent the loop steps; ``source`` reads the seat's action each
    frame, the one seam a human input, a bot controller, and a scheduled agent all
    satisfy. ``kind`` labels the seat for the execution record; the loop treats every
    seat the same.
    """

    seat_key: str
    actor_id: str
    agent_id: str
    source: SeatActionSource
    kind: Literal["human", "bot"] = "human"


@dataclass(frozen=True)
class ServerEpisode:
    """The outcome of one server-authoritative episode: the per-seat runs.

    ``summaries`` holds one ``EpisodeSummary`` per actor id over the one shared
    authoritative timeline. ``reference_seat`` names the seat whose summary the
    caller captures once for the interaction, and ``frames`` is the frame count.
    """

    summaries: dict[str, EpisodeSummary]
    reference_seat: str
    frames: int
    solved: bool

    def reference_summary(self) -> EpisodeSummary:
        """Return the reference seat's summary, the one run the interaction captures."""
        return self.summaries[self.reference_seat]


class ServerSeatSession:
    """Run one server-authoritative multi-seat episode and report per-seat summaries.

    The session steps one authoritative environment through the shared multi-seat
    loop, reading each seat's action through its injected source. It then reports one
    ``EpisodeSummary`` per seat over the shared transitions, so a server-authoritative
    interaction is captured and matched exactly as a mesh interaction is.
    """

    def __init__(
        self,
        *,
        seats: Sequence[ServerSeat],
        env: MultiSeatEnv,
        channel_key: str,
        interaction_id: str,
        episode_id: str,
        now: Clock,
        fps: int = 30,
        max_steps: int = 200,
    ) -> None:
        if not seats:
            raise ValueError("a server interaction needs at least one seat")
        if len({seat.actor_id for seat in seats}) != len(seats):
            raise ValueError("each seat must hold a distinct actor id")
        if len({seat.agent_id for seat in seats}) != len(seats):
            raise ValueError("each seat must map to a distinct environment agent")
        self._seats = tuple(seats)
        self._env = env
        self._channel_key = channel_key
        self._interaction_id = interaction_id
        self._episode_id = episode_id
        self._now = now
        self._fps = fps
        self._max_steps = max_steps

    def execution_mode(self) -> ExecutionMode:
        """Return the server-authoritative execution contract for the channel."""
        return server_execution_mode()

    async def run(self, *, on_step: MultiSeatObserver | None = None) -> ServerEpisode:
        """Run the authoritative episode and build one summary per seat.

        The one multi-seat loop steps every seat's action into one shared timeline;
        the session keys one ``EpisodeSummary`` per actor over those shared
        transitions, so the reference seat's summary is the one authoritative run.
        """
        summary = await run_multiseat_episode(
            self._env,
            channel_key=self._channel_key,
            episode_id=self._episode_id,
            interaction_id=self._interaction_id,
            agent_ids=[seat.agent_id for seat in self._seats],
            sources={seat.agent_id: seat.source for seat in self._seats},
            now=self._now,
            fps=self._fps,
            max_steps=self._max_steps,
            on_step=on_step,
        )
        summaries = {
            seat.actor_id: EpisodeSummary(
                channel_key=self._channel_key,
                seat_key=seat.actor_id,
                frames=summary.frames,
                transitions=summary.transitions,
                boundary=summary.boundary,
                solved=summary.solved,
            )
            for seat in self._seats
        }
        return ServerEpisode(
            summaries=summaries,
            reference_seat=self._seats[0].actor_id,
            frames=summary.frames,
            solved=summary.solved,
        )


__all__ = [
    "ServerEpisode",
    "ServerSeat",
    "ServerSeatSession",
    "server_execution_mode",
]
