"""The author-facing preference comparison (a surface of the authoring API).

A study author asks participants to compare recorded runs by writing one small
object: a ``Comparison``. It names the question and the options, and nothing else is
required -- MUG blinds the options, shuffles their order per participant, records the
choice once, and keeps it reproducible. The author never writes an id, a seed, a
handle, a protocol object, or a service call; all of that lives in the runtime above
this layer (``mug.preferences``), which reads this definition and drives it.

Like the ``LLMAgent`` definition, a ``Comparison`` is *pure*: it is immutable and
versioned with the study, holds no per-participant state, and imports no runtime, so
it sits in the authoring layer and is imported as
``from mug.authoring import Comparison``. The runtime (``mug.preferences``) compiles
it into the blinded, randomized records the annotation loop drives.

The author writes the labels for their own analysis (which option is which policy,
model, or condition). When ``blind`` is set -- the default -- MUG hides those labels
from the participant behind neutral display handles, so the choice carries no signal
from the label. The labels stay in the recorded data for the researcher.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

# What a comparison asks a participant to do. ``compare`` shows the options side by
# side and asks them to pick the better one; ``rate`` asks them to rate each. These
# map onto the internal pairwise / rating task kinds in the runtime.
Style = str
# What kind of recorded thing the options are: whole runs, single model outputs,
# chat messages, conversation segments, or media. The default fits comparing runs.
OptionKind = str

# The kinds an author may write, mapped to the one name the record carries. An
# author writes the word they would say -- ``model_output``, ``message`` -- and the
# platform writes the contract's spelling, so a study is not asked to know both.
_OPTION_KINDS: dict[str, str] = {
    "trajectory": "trajectory",
    "run": "trajectory",
    "model_output": "model-output",
    "model-output": "model-output",
    "message": "chat-message",
    "chat_message": "chat-message",
    "chat-message": "chat-message",
    "conversation_segment": "conversation-segment",
    "conversation-segment": "conversation-segment",
    "media": "media",
}


class Axis:
    """One more thing to ask about a comparison, beside "which one is better".

    A plain axis is a slider between the two options: *much more helpful*,
    *slightly more helpful*, *the same*, and the two on the other side. That is
    what most studies want, so it is what you get.

    ```python
    Axis("helpful", "Which reply is more helpful?")
    Axis("safe", "Which reply is safer?", pick=True)      # two buttons, no middle
    Axis("wordy", "How wordy is each reply?", each=True)  # rate each, not compare
    ```

    ``points`` widens the scale: for a comparison it is how many steps there are to
    each side (the default 2 gives the five positions above), and for ``each=True``
    it is how long that rating scale is. ``low`` and ``high`` name the ends when the
    default words do not fit.

    **What is recorded is the option, never the side of the screen.** MUG shuffles
    which option is shown first, so an answer that meant "the left one" could not be
    read back. Every answer names the option it is about.
    """

    def __init__(
        self,
        key: str,
        ask: str,
        *,
        each: bool = False,
        pick: bool = False,
        points: int | None = None,
        low: str | None = None,
        high: str | None = None,
    ) -> None:
        if not ask.strip():
            raise ValueError(f"the axis {key!r} asks nothing")
        if pick and each:
            raise ValueError("an axis that rates each option is not a pick")
        if pick and points is not None:
            raise ValueError("a pick has one step, so it takes no points")
        steps = points if points is not None else (5 if each else 2)
        if not 1 <= steps <= 10:
            raise ValueError("an axis has between 1 and 10 points")
        self._key = key
        self._ask = ask
        self._each = each
        self._points = 1 if pick else steps
        self._low = low
        self._high = high

    @property
    def key(self) -> str:
        """The axis key: what the recorded answer is filed under."""
        return self._key

    @property
    def ask(self) -> str:
        """The question the participant is shown for this axis."""
        return self._ask

    @property
    def scope(self) -> str:
        """``each`` when every option is rated on its own, else ``pair``."""
        return "each" if self._each else "pair"

    @property
    def points(self) -> int:
        """How far this axis's scale goes, read by its scope."""
        return self._points

    @property
    def low(self) -> str | None:
        """The word at the low end of the scale, when the author wrote one."""
        return self._low

    @property
    def high(self) -> str | None:
        """The word at the high end of the scale, when the author wrote one."""
        return self._high


def _axes(on: Sequence[Axis | str]) -> tuple[Axis, ...]:
    """Read the axes an author wrote, accepting a bare question as a pick."""
    axes = tuple(
        item if isinstance(item, Axis) else Axis(_key_of(item), item, pick=True)
        for item in on
    )
    keys = [axis.key for axis in axes]
    if len(set(keys)) != len(keys):
        raise ValueError("each axis must have its own key")
    return axes


def _key_of(question: str) -> str:
    """Turn a bare question into the key its answers are filed under."""
    lowered = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")
    if not lowered or not lowered[0].isalpha():
        lowered = f"axis-{lowered}".strip("-")
    return lowered[:128].rstrip("-")


class Elicit:
    """Ask for a preference inside a live conversation. One line, no plumbing.

    The model writes more than one reply to the participant's message, the
    participant picks the one they would rather have had, and **the conversation
    goes on from the reply they picked**. The one they did not pick is kept as
    data, with everything MUG knows about where it came from.

    ```python
    Transcript(seat=partner, elicit_preference=Elicit.replies())
    Elicit.replies(n=3, ties=True, on=[Axis("helpful", "Which is more helpful?")])
    Elicit.between("partner", "rival")        # two models answer, one is picked
    ```

    ``sample`` elicits only a fraction of the turns (``0.3`` is about a third), and
    which turns those are is decided from the study and the message, so the same
    conversation always elicits at the same places. ``skippable`` lets a participant
    pass; a passed turn goes on with the first reply and records no preference.
    """

    def __init__(
        self,
        *,
        n: int = 2,
        seats: Sequence[str] = (),
        ask: str | None = None,
        ties: bool = False,
        on: Sequence[Axis | str] = (),
        sample: float = 1.0,
        skippable: bool = True,
    ) -> None:
        if seats:
            if len(seats) < 2:
                raise ValueError("a comparison between seats needs at least two")
            if len(set(seats)) != len(seats):
                raise ValueError("each seat may answer once")
        elif not 2 <= n <= 16:
            raise ValueError("a turn presents between 2 and 16 candidate replies")
        if not 0.0 < sample <= 1.0:
            raise ValueError("sample is a fraction of the turns, above 0 and up to 1")
        self._n = len(seats) if seats else n
        self._seats = tuple(seats)
        self._ask = ask or "Which reply would you rather have had?"
        self._ties = ties
        self._axes = _axes(on)
        self._sample = sample
        self._skippable = skippable

    @staticmethod
    def replies(
        *,
        n: int = 2,
        ask: str | None = None,
        ties: bool = False,
        on: Sequence[Axis | str] = (),
        sample: float = 1.0,
        skippable: bool = True,
    ) -> Elicit:
        """Ask the one model for ``n`` replies, and let the participant pick one."""
        return Elicit(
            n=n, ask=ask, ties=ties, on=on, sample=sample, skippable=skippable
        )

    @staticmethod
    def between(
        *seats: str,
        ask: str | None = None,
        ties: bool = False,
        on: Sequence[Axis | str] = (),
        sample: float = 1.0,
        skippable: bool = True,
    ) -> Elicit:
        """Let one reply from each named model seat compete for the same turn."""
        return Elicit(
            seats=seats,
            ask=ask,
            ties=ties,
            on=on,
            sample=sample,
            skippable=skippable,
        )

    @property
    def n(self) -> int:
        """How many replies compete for one turn."""
        return self._n

    @property
    def seats(self) -> tuple[str, ...]:
        """The model seats that each answer once, or empty for one model's samples."""
        return self._seats

    @property
    def ask(self) -> str:
        """The question shown above the candidate replies."""
        return self._ask

    @property
    def ties(self) -> bool:
        """Whether the participant may say the replies are the same, or both bad."""
        return self._ties

    @property
    def axes(self) -> tuple[Axis, ...]:
        """The further axes each elicited turn is answered on."""
        return self._axes

    @property
    def sample(self) -> float:
        """The fraction of turns that are elicited."""
        return self._sample

    @property
    def skippable(self) -> bool:
        """Whether a participant may pass without picking."""
        return self._skippable


class Comparison:
    """Ask participants to compare recorded runs. One object, no plumbing.

    You give the question and the options -- a label for each recorded run -- and
    MUG does the rest: it blinds the labels, shuffles the order per participant,
    shows the question, records the one choice, and keeps it reproducible.

    ```python
    Comparison(
        key="which-chef",
        ask="Which chef cooked better?",
        options={"Policy A": run_a, "Policy B": run_b},
    )
    ```

    ``options`` maps your own label to something your study already recorded. What
    an option names follows from ``of``:

    - ``of="trajectory"`` (the default) -- one of your study's own game activities,
      so each option is the run this participant made for it.
    - ``of="model_output"`` -- one of the generations your study recorded before
      its participants arrived, by the key you gave it. No provider is contacted
      while a participant answers, and the provider's identity is not in what they
      are shown.

    You need at least two options, each a distinct recorded thing. Everything else
    has a sensible default: the comparison is blinded and shuffled, and it asks the
    participant to pick one.
    """

    def __init__(
        self,
        *,
        key: str,
        ask: str,
        options: Mapping[str, object],
        style: Style = "compare",
        of: OptionKind = "trajectory",
        blind: bool = True,
        shuffle: bool = True,
        ties: bool = False,
        on: Sequence[Axis | str] = (),
    ) -> None:
        if not ask.strip():
            raise ValueError("a comparison must ask a question")
        if len(options) < 2:
            raise ValueError("a comparison needs at least two options")
        runs = list(options.values())
        if len(set(id(run) for run in runs)) != len(runs):
            raise ValueError("each option must be a distinct recorded run")
        if style not in ("compare", "rate"):
            raise ValueError("style is 'compare' (pick one) or 'rate' (rate each)")
        if of not in _OPTION_KINDS:
            written = ", ".join(sorted(_OPTION_KINDS))
            raise ValueError(f"a comparison is of one of: {written}")
        self._key = key
        self._ask = ask
        self._options = dict(options)
        self._style = style
        self._of = _OPTION_KINDS[of]
        self._blind = blind
        self._shuffle = shuffle
        self._ties = ties
        self._axes = _axes(on)

    @property
    def key(self) -> str:
        """The comparison's key: the flow step and the analysis label."""
        return self._key

    @property
    def ties(self) -> bool:
        """Whether the participant may say the options are the same, or both bad."""
        return self._ties

    @property
    def axes(self) -> tuple[Axis, ...]:
        """The further axes this comparison is answered on."""
        return self._axes

    @property
    def ask(self) -> str:
        """The question the participant is shown above the options."""
        return self._ask

    @property
    def options(self) -> dict[str, object]:
        """The author's labels mapped to the recorded runs they name."""
        return dict(self._options)

    @property
    def style(self) -> Style:
        """How the participant answers: ``compare`` (pick one) or ``rate``."""
        return self._style

    @property
    def of(self) -> OptionKind:
        """What kind of recorded thing the options are (default a whole run).

        This is the contract's own name for the kind, whichever of the accepted
        spellings the author wrote: ``model_output`` and ``model-output`` are both
        read as ``model-output``, and ``message`` is read as ``chat-message``.
        """
        return self._of

    @property
    def blind(self) -> bool:
        """Whether MUG hides the author's labels from the participant."""
        return self._blind

    @property
    def shuffle(self) -> bool:
        """Whether MUG randomizes the option order per participant."""
        return self._shuffle


__all__ = ["Axis", "Comparison", "Elicit", "OptionKind", "Style"]
