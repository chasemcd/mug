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

from collections.abc import Mapping

# What a comparison asks a participant to do. ``compare`` shows the options side by
# side and asks them to pick the better one; ``rate`` asks them to rate each. These
# map onto the internal pairwise / rating task kinds in the runtime.
Style = str
# What kind of recorded thing the options are: whole runs, single model outputs,
# chat messages, conversation segments, or media. The default fits comparing runs.
OptionKind = str


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

    ``options`` maps your own label to a recorded run (a value your study already
    produced -- a captured episode or a replay bundle the runtime resolves). You
    need at least two, each a distinct run. Everything else has a sensible default:
    the comparison is blinded and shuffled, and it asks the participant to pick one.
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
        self._key = key
        self._ask = ask
        self._options = dict(options)
        self._style = style
        self._of = of
        self._blind = blind
        self._shuffle = shuffle

    @property
    def key(self) -> str:
        """The comparison's key: the flow step and the analysis label."""
        return self._key

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
        """What kind of recorded thing the options are (default a whole run)."""
        return self._of

    @property
    def blind(self) -> bool:
        """Whether MUG hides the author's labels from the participant."""
        return self._blind

    @property
    def shuffle(self) -> bool:
        """Whether MUG randomizes the option order per participant."""
        return self._shuffle


__all__ = ["Comparison", "OptionKind", "Style"]
