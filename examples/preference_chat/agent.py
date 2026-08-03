"""The model the participant talks to, and the judgement they are asked for.

One agent definition, used by both studies. `ollama.py` runs it on a model on your
own machine and `anthropic.py` runs it on the Anthropic API, and **nothing in this
file changes between them** -- the provider is one line on the agent, and the
adapter, the credential, and the endpoint follow from it.

The point of both studies is what happens on each turn. The model writes **two**
replies to whatever the participant said. The participant reads both, says which
one they would rather have had, and rates the pair on the axes the study cares
about. The conversation then goes on **from the reply they chose**, and the reply
they did not choose is kept with everything the platform knows about where it came
from.

That is the difference between this and an offline preference set: the judgement is
made by somebody who has to live with it. The reply they pick is the one they get.
"""

from __future__ import annotations

from mug.authoring import (
    Axis,
    Elicit,
    Fallback,
    History,
    LLMAgent,
    Provider,
    Thoughts,
    Transcript,
)

# What the participant is asked, beyond which reply they preferred. The first two
# are a slider between the two replies; `each=True` rates each reply on its own,
# which is the shape a reward model reads as an absolute score rather than a
# comparison.
AXES = [
    Axis("helpful", "Which reply is more helpful?"),
    Axis("honest", "Which reply is more careful about what it does not know?"),
    Axis("tone", "How well does each reply match the tone you wanted?", each=True),
]

PROMPT = """You are helping somebody think through a decision they are facing.

Ask questions before you give advice. Say plainly when you do not know something.
Keep each reply to a short paragraph.

The conversation so far:
{transcript}

Write your next reply, and nothing else."""


class Counsellor(LLMAgent):
    """The model the participant talks to.

    ``provider`` and ``model`` are the only two lines that differ between a local
    run and a hosted one, and each study overrides them rather than editing this
    class -- so the two studies really are the same study with a different backend.

    ``decides_every`` is 1 because a conversation has no frames: the agent answers
    each message. ``on_timeout`` keeps the conversation moving when a provider is
    slow, which matters more here than in a game: a participant who is waiting for
    a reply has nothing else on the screen.
    """

    provider = Provider.OLLAMA
    model = "llama3.2"
    decides_every = 1
    on_timeout = Fallback.WAIT

    def get_prompt(
        self,
        env: object,
        agent_id: str,
        history: History,
        chat: Transcript,
        thoughts: Thoughts,
    ) -> str:
        """Render the transcript into the prompt the provider is sent."""
        said = chat.last(12)
        transcript = "\n".join(f"{one.sender}: {one.text}" for one in said)
        return PROMPT.format(transcript=transcript or "(nothing yet)")


def elicitation() -> Elicit:
    """Return what the participant is asked on each turn.

    ``n=2`` is two replies from the one model, which is the RLHF shape: the same
    model, sampled twice, judged against itself. ``ties=True`` matters more than it
    looks -- without it a participant who thought both replies were equally good
    has to invent a preference, and the data then says they had one.

    ``sample=1.0`` elicits on every turn. A longer study lowers it, and which turns
    are elicited is then derived from the study and the message rather than drawn,
    so the same conversation always elicits at the same places.
    """
    return Elicit.replies(
        n=2,
        ask="Which of these replies would you rather have had?",
        ties=True,
        on=AXES,
        sample=1.0,
        skippable=True,
    )


GREETING = (
    "Hello. Tell me about a decision you are weighing up, and I will help you"
    " think it through. On some turns you will see two possible replies from me --"
    " pick the one you would rather have had, and we will carry on from that one."
)

__all__ = ["AXES", "GREETING", "Counsellor", "elicitation"]
