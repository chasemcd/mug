"""The author-facing LLM agent definition (surface 11 of the authoring API).

A study author defines an LLM player by subclassing ``LLMAgent`` and writing one
method, ``get_prompt``. The class is a *definition*: it is immutable and versioned
with the study, so it holds no per-move state and its methods take the game, the
player, the history, and the model's own thoughts as arguments. The author sees
none of the runtime -- the provider, the scheduler, the deadline, the recording --
which lives above this layer in ``mug.agents`` and drives the definition.

This module is pure and import-light on purpose: it defines the surface a
researcher touches, with no dependency on the provider or scheduler runtime, so it
can sit in the authoring layer and be imported as ``from mug.authoring import
LLMAgent``. The runtime (``mug.agents``) reads these methods and composes the
built ``ModelProvider`` and ``Scheduler`` behind them.

The read-only views the author receives:

- ``history`` -- what happened earlier this episode (states, everyone's moves,
  rewards). MUG records every transition, so this is free and reproducible.
- ``chat`` -- the messages exchanged on the interaction's chat channel, so a human
  partner can instruct the agent (strategy, coordination) and it can read that.
- ``thoughts`` -- the model's *own* earlier reasoning, carried forward so it can
  plan and build a picture of the other players across steps.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from typing import Any


class Provider(Enum):
    """The model provider an agent uses. The value is the internal provider name.

    ``OLLAMA`` is a local model runner (it needs no credential); it shares the
    internal ``oss`` provider name with a self-hosted open-source model.
    """

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OSS = "oss"
    OLLAMA = "oss"  # a friendly alias of OSS: a local Ollama runner
    HTTP = "http"


class Fallback(Enum):
    """What a seat does when a decision misses its deadline or fails.

    ``REPEAT_LAST`` repeats the player's last action; ``WAIT`` uses the seat's
    default (no-op) action. The value is the internal fallback name.
    """

    REPEAT_LAST = "repeat-last"
    WAIT = "default-action"


class Step:
    """One recorded step of the episode: who did what, and the reward it drew.

    A step is read-only. ``action_of`` and ``reward_of`` return ``None`` for a
    player that did not act or drew no reward that step. ``text_view`` returns the
    game as text at that step when the runtime recorded one, else ``None``.
    """

    def __init__(
        self,
        *,
        tick: int,
        actions: dict[str, str],
        rewards: dict[str, float] | None = None,
        views: dict[str, str] | None = None,
    ) -> None:
        self.tick = tick
        self.actions = dict(actions)
        self._rewards = dict(rewards or {})
        self._views = dict(views or {})

    def action_of(self, agent_id: str) -> str | None:
        """Return the action that player took this step, or None."""
        return self.actions.get(agent_id)

    def reward_of(self, agent_id: str) -> float | None:
        """Return the reward that player drew this step, or None."""
        return self._rewards.get(agent_id)

    def text_view(self, agent_id: str) -> str | None:
        """Return the game as text at this step for that player, or None."""
        return self._views.get(agent_id)


class History:
    """The episode so far: a read-only, ordered list of steps the author reads.

    The runtime records every transition and hands the agent this view. ``last``
    returns the most recent steps (oldest first); ``actions_of`` returns one
    player's moves in order.
    """

    def __init__(self, steps: Sequence[Step] | None = None) -> None:
        self._steps: list[Step] = list(steps or [])

    def append(self, step: Step) -> None:
        """Record one more step (the runtime calls this; the author reads)."""
        self._steps.append(step)

    def last(self, n: int) -> list[Step]:
        """Return the last ``n`` steps, oldest first (fewer if the episode is young)."""
        return self._steps[-n:] if n < len(self._steps) else list(self._steps)

    def actions_of(self, agent_id: str) -> list[str | None]:
        """Return every past move by one player, in order."""
        return [step.action_of(agent_id) for step in self._steps]

    def __len__(self) -> int:
        return len(self._steps)


class Message:
    """One chat message: who sent it, what it says, and when.

    ``sender`` is a player id (a human partner or another agent). ``tick`` is the
    game step the message was sent at, or ``None`` when the channel keeps no tick.
    """

    def __init__(self, *, sender: str, text: str, tick: int | None = None) -> None:
        self.sender = sender
        self.text = text
        self.tick = tick


class Transcript:
    """The interaction's chat so far: a read-only, ordered list of messages.

    The runtime records the chat channel and hands the agent this view, so a human
    partner's instructions are available to the model. ``last`` returns the most
    recent messages (oldest first); ``by`` returns the messages from one sender.
    """

    def __init__(self, messages: Sequence[Message] | None = None) -> None:
        self._messages: list[Message] = list(messages or [])

    def append(self, message: Message) -> None:
        """Record one more message (the runtime calls this; the author reads)."""
        self._messages.append(message)

    def last(self, n: int) -> list[Message]:
        """Return the last ``n`` messages, oldest first."""
        return self._messages[-n:] if n < len(self._messages) else list(self._messages)

    def by(self, sender: str) -> list[Message]:
        """Return every message from one sender, in order."""
        return [m for m in self._messages if m.sender == sender]

    def __len__(self) -> int:
        return len(self._messages)


class Thoughts:
    """The model's own reasoning carried across steps, for it to build on.

    The runtime appends the text the model carries forward (see ``LLMAgent.reflect``)
    and hands the agent this read-only view. ``latest`` is the most recent thought;
    ``last`` returns the most recent few.
    """

    def __init__(self, items: Sequence[str] | None = None) -> None:
        self._items: list[str] = list(items or [])

    def append(self, text: str) -> None:
        """Carry one more thought forward (the runtime calls this)."""
        self._items.append(text)

    @property
    def latest(self) -> str | None:
        """Return the most recent thought, or None before the first."""
        return self._items[-1] if self._items else None

    def last(self, n: int) -> list[str]:
        """Return the last ``n`` thoughts, oldest first."""
        return self._items[-n:] if n < len(self._items) else list(self._items)

    def __len__(self) -> int:
        return len(self._items)


class LLMAgent:
    """An LLM player. Subclass it, set the fields, and write ``get_prompt``.

    Set ``provider`` and ``model`` as class attributes. Set ``secret`` (the
    credential name, bound at deploy) for a hosted provider; leave it unset for a
    local provider that needs no key, such as ``Provider.OLLAMA``. ``decides_every``,
    ``on_timeout``, ``answers_within``, and ``temperature`` are optional. Override
    ``get_prompt`` to build the whole prompt. Optionally override
    ``available_actions`` (defaults to the env's legal actions), ``parse_reply``
    (defaults to the last name in the reply), and ``reflect`` (defaults to carrying
    the whole reply forward as the next thought).

    **An agent may decide at a coarser grain than the environment steps.** A model
    that answers in seconds cannot usefully choose one frame of movement, so it
    chooses something that lasts -- "fetch an onion", "take the next exit" -- and
    the study says what carrying that out looks like on any one frame. Two methods
    say the whole of it, and both default to the environment's own actions, so an
    agent that writes neither decides an environment action and holds it:

    - ``decides_among`` -- the names this agent chooses between;
    - ``carry_out`` -- one environment action that carries the choice forward, asked
      once for every frame the seat is read.

    ``available_actions`` is **not** either of those. It stays the environment's own
    action names, because it is what the runtime names every seat's moves with when
    it writes this agent's history. An agent that made it the coarser list would
    have its partner's moves recorded under names that partner never chose.
    """

    provider: Provider
    model: str
    secret: str | None = None
    decides_every: int = 1
    on_timeout: Fallback = Fallback.REPEAT_LAST
    answers_within: float = 1.0
    temperature: float | None = None

    def get_prompt(
        self,
        env: Any,
        agent_id: str,
        history: History,
        chat: Transcript,
        thoughts: Thoughts,
    ) -> str:
        """Return the whole prompt the model sees. MUG sends exactly this string.

        The game, the action list, the history, the chat, and the thoughts appear
        only if you put them in; nothing is added for you. ``env`` is the game now,
        ``agent_id`` is which player the model is, ``history`` is what happened,
        ``chat`` is what was said on the chat channel (so a human can instruct the
        agent), and ``thoughts`` is the model's own earlier reasoning.

        **Put what does not change first, and what changes last.** A model runner
        reuses its cached reading of the longest prefix this prompt shares with the
        last one, so the game state near the top means everything after it is read
        again from nothing on every decision. Moving the state to the end of the
        shipped kitchen prompt took the reading of it from 824 ms to 333 ms on a
        local llama3.2 -- half a second off every decision, for the same words in a
        different order. Your rules, your action list and your answer shape go
        first; the board, the transcript and the carried plan go last.
        """
        raise NotImplementedError("an LLMAgent must implement get_prompt")

    def available_actions(self, env: Any, agent_id: str) -> list[str]:
        """Return the player's legal action names, in the env's action order.

        The default reads them from the environment. The order is the action order:
        the position of a name in this list is the action the environment steps on.
        """
        return list(env.legal_actions(agent_id))

    def decides_among(self, env: Any, agent_id: str) -> list[str]:
        """Return the names this agent chooses between, in the order it chooses them.

        The default is ``available_actions``, so an agent decides one environment
        action, which is what every agent did before a coarser grain was possible.

        Override it to decide something that lasts longer than a frame -- a job, a
        destination, a manoeuvre -- and write ``carry_out`` to say what doing that
        looks like on any one frame. The two go together: a coarser list with no
        ``carry_out`` would be read as environment actions and stepped as whatever
        happened to be at that position.
        """
        return self.available_actions(env, agent_id)

    def carry_out(self, env: Any, agent_id: str, chosen: int | None) -> int | None:
        """Return one environment action that carries the choice forward, this frame.

        It is asked once for every frame the seat is read, against the environment
        the loop is stepping -- so it plans in the run this participant is in and
        never in another's. It is the only place a decision that lasts several
        seconds meets a loop that steps thirty times a second.

        ``chosen`` is the position in ``decides_among`` of what this seat last
        decided. It is ``None`` before the first decision and after one that fell
        back, and both mean the same thing: nobody has told this seat what to do.

        Answering ``None`` means there is nothing to do this frame, and the seat
        takes the game's own ``default_action``. So a study never has to know what
        the idle action is to say "stand still", and the two ``None`` values read
        the same way round: nothing chosen in, nothing to do out.

        The default holds the choice and steps it as an environment action, which is
        right when ``decides_among`` is the environment's own action list, and is
        what every model seat did before a coarser grain was possible.
        """
        return chosen

    def parse_reply(self, reply: str, env: Any, agent_id: str) -> int | None:
        """Turn the model's reply into a choice, or None to fall back.

        The default picks the last name that appears in the reply, so a reply that
        reasons first and ends with its answer just works. It returns that name's
        position in ``decides_among``. Override for a richer format -- and override
        it for certain if the agent also talks, because what it **says** would
        otherwise be read for what it **does**.
        """
        actions = self.decides_among(env, agent_id)
        text = str(reply).upper()
        best_index: int | None = None
        best_pos = -1
        for index, name in enumerate(actions):
            pos = text.rfind(str(name).upper())
            if pos > best_pos:
                best_pos = pos
                best_index = index
        return best_index

    def reflect(self, reply: str, env: Any, agent_id: str) -> str | None:
        """Return the text to carry into the next step, or None to keep nothing.

        The default carries the whole reply, so the model's reasoning is available
        next step. Override to keep only a plan or a summary.
        """
        return reply

    def say(self, reply: str, env: Any, agent_id: str) -> str | None:
        """Return what to say on the chat channel, or None to say nothing.

        One reply is read three ways: ``parse_reply`` takes the action, ``reflect``
        takes the thought the model carries forward, and this takes the words the
        other players read. So an agent that plays and talks costs one model call,
        not two, and it talks on the same cadence it decides on -- which is what
        keeps it from being asked to speak once per frame.

        **What it says and what it does are judged apart.** A reply this reads a
        message out of still publishes that message when ``parse_reply`` can not
        find an action, and the seat falls back on the action alone. A partner that
        says "going left" and then names an action nobody can read has still said
        it, and the participant is owed the message.

        The default says nothing, so an agent is silent until its study writes what
        it should say.
        """
        return None


__all__ = [
    "Fallback",
    "History",
    "LLMAgent",
    "Message",
    "Provider",
    "Step",
    "Thoughts",
    "Transcript",
]
