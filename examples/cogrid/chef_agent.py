"""The partner that cooks and talks, and reads both out of one reply.

The model makes **macro** decisions. It does not press arrow keys. It chooses one
of a handful of jobs -- fetch an onion, plate the soup, deliver it, stand by -- and
the study's own route planner turns the standing job into one grid move a frame,
for as many frames as the job takes.

That is what lets the kitchen run at the speed it ships at. The trained partner in
``overcooked_human_ai.py`` is scored in under a millisecond, so it decides every
fifth frame of thirty a second. A language model answers in one to five seconds.
Choosing grid moves it would make about ten of them in a 600 frame round and would
not be a teammate; choosing jobs it makes about ten **decisions**, and ten jobs is a
whole shift's cooking.

One model call gives three things: the job, the words the participant reads, and
the plan carried to the next decision. So a partner that talks costs no more calls
than one that does not, and it talks on the cadence it decides at rather than once a
frame.

THE ONE THING THAT MUST NOT BE GOT WRONG
========================================

``LLMAgent.parse_reply`` defaults to "the last name anywhere in the reply". That is
right for an agent that only plays and **wrong** for one that talks::

    SAY: I will go and get a plate
    JOB: FETCH_ONION

The default would read ``FETCH_ONION`` correctly here by luck. Let the model write
its sentence after the job, or name a job inside the sentence, and what the partner
**says** decides what it **does**. A study would see a partner that contradicts its
own words and would blame the model.

So the two lines are read apart, and neither is read out of the whole reply.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from typing import Any

from examples.cogrid.env import NOOP, caught_up, chef_at
from examples.cogrid.kitchen_text import POT_HOLDS, kitchen_as_text
from examples.cogrid.partners import Chef
from mug.authoring import Fallback, History, LLMAgent, Provider, Thoughts, Transcript

# The jobs the model decides among. THIS IS THE MODEL'S OWN ACTION SET and it is not
# the environment's: the kitchen steps seven cardinal moves, and the model never
# names one of them.
JOBS = (
    "FETCH_ONION",
    "FILL_POT",
    "FETCH_PLATE",
    "PLATE_SOUP",
    "DELIVER",
    "STAND_BY",
)

# The environment's own seven, in the order CoGrid steps them. The model never sees
# this list. It is what the run is **recorded** in, so a history reads "your partner
# moved left" rather than "your partner did 2".
MOVES = ("UP", "DOWN", "LEFT", "RIGHT", "INTERACT", "TOGGLE", "WAIT")

# EVERYTHING THAT CHANGES IS AT THE END, AND THAT IS NOT A STYLE CHOICE.
#
# A runner reuses its cached attention for the longest **prefix** this call shares
# with the last one. The kitchen changes every decision, so a kitchen near the top
# means almost nothing after it can be reused and the whole prompt is read again.
#
# Measured on llama3.2 with a kitchen that changes every call: reading the prompt
# cost 824 ms with the kitchen where it used to be and 333 ms with it at the end --
# half a second off every decision the chef makes, for moving the same words. The
# reply keeps its shape either way.
#
# So: the rules first, because they never change; the kitchen, the talk and the
# plan last, because they change every time.
PROMPT = """You are one of two chefs in an Overcooked kitchen. You and your partner
cook onion soup together and you are scored together: {holds} onions into a pot,
wait for it to cook, carry a clean plate to the pot to collect the soup, then carry
the soup to the serving hatch.

You do not steer. You choose a job and you keep doing it until you choose another
one, so choose the job that is worth the next few seconds. Your partner is a person
and cannot read your mind; if you want them to do something, say so.

Answer in exactly this shape, three lines, and nothing else:

JOB: one of {jobs}
SAY: one short sentence to your partner, or the word NOTHING
PLAN: one short sentence to remind yourself next turn

Say something only when it is worth reading -- when you want your partner to do
something, when you are about to get in their way, or when they asked you a
question. A partner who talks every few seconds is one nobody reads.

{kitchen}

What you and your partner have said to each other:
{talk}

What you told yourself to do last time:
{plan}
"""


class TalkingChef(LLMAgent):
    """A chef that cooks beside a person and talks to them while it cooks.

    ``decides_every`` is 30 -- at most one decision a second. A decision starts only
    when none is in flight, so the real cadence is the provider's own latency; this
    is the floor, and it stops a fast local model re-choosing a job it has not
    started yet. A message from the participant overrides it: somebody who typed a
    question is answered as soon as the seat is free.

    ``on_timeout`` is ``WAIT``, which leaves the seat with **no** job rather than
    with the idle move. ``carry_out`` is told so and stands the chef still for that
    decision, which is what a partner that could not think of anything does.

    ``answers_within`` is what makes this study run at all. It was fixed at one
    second before a study could say otherwise, and no real provider answers a
    kitchen prompt in one second -- so every decision would have fallen back, the
    participant would have seen a partner that never chose anything, and nothing
    anywhere would have said the model was never waited for.
    """

    provider = Provider.OLLAMA
    model = "llama3.2"
    decides_every = 30
    on_timeout = Fallback.WAIT
    answers_within = 20.0
    temperature = 0.7

    def available_actions(self, env: Any, agent_id: str) -> list[str]:
        """Return the kitchen's own seven moves, in the order it steps them.

        This is the **environment's** vocabulary, which is what it is documented to
        be: it is how the runtime names what every seat did when it writes this
        agent's history. It is written out rather than read off the environment
        because no environment API states what an action is called.
        """
        return list(MOVES)

    def decides_among(self, env: Any, agent_id: str) -> list[str]:
        """Return the jobs this chef chooses between."""
        return list(JOBS)

    def carry_out(self, env: Any, agent_id: str, chosen: int | None) -> int | None:
        """Return one grid move that carries the chosen job forward, this frame.

        The planner is the shipped one: ``partners.Chef`` already walks a kitchen
        full of counters to a job and does it, and it is what ``scripted_chef`` is
        made of. The only thing that changes under a model is **who chooses the
        job** -- so this asks it for the squares a named job means instead of the
        squares its own recipe would have chosen.

        A job with nowhere to go -- plating a soup nobody has cooked -- is answered
        with no move, and the chef stands where it is.
        """
        if chosen is None or not 0 <= chosen < len(JOBS):
            return None  # nobody has said what to do, so stand still
        job = JOBS[chosen]
        if job == "STAND_BY":
            return None
        kitchen = caught_up(getattr(env, "env", env))
        chef = chef_at(kitchen, agent_id)
        if chef is None:
            return None
        planner = Chef(reach=_ANYWHERE)
        return planner.towards(kitchen, chef, planner.squares_for(kitchen, chef, job))

    def get_prompt(
        self,
        env: Any,
        agent_id: str,
        history: History,
        chat: Transcript,
        thoughts: Thoughts,
    ) -> str:
        """Return the whole prompt: the kitchen, what was said, and the last plan."""
        # Every message here is somebody else's: a seat is never delivered its own
        # words. This kitchen holds one person and this chef, so "your partner" is
        # exact rather than a simplification.
        #
        # It matters more than it looks. A message carries its author as an **actor
        # id**, which is a pseudonymous identifier and no kind of name. Written into
        # the prompt as it stands, a small model copies it into what it says next --
        # and the participant reads "Actor_019fb5bb-becb-74e4-...: pot is ready" in
        # the pane beside their kitchen.
        said = chat.last(_HEARS)
        talk = "\n".join(f"Your partner: {one.text}" for one in said)
        return PROMPT.format(
            holds=POT_HOLDS,
            kitchen=kitchen_as_text(env, agent_id),
            talk=talk or "(nothing yet)",
            plan=thoughts.latest or "(nothing yet)",
            jobs=", ".join(JOBS),
        )

    def parse_reply(self, reply: str, env: Any, agent_id: str) -> int | None:
        """Return the job, read **only** off the JOB line.

        Reading the whole reply is what lets the words the partner says decide where
        it walks. So the line is found first and the rest of the reply is never
        looked at.
        """
        line = _line(reply, "JOB:")
        if line is None:
            return None
        wanted = line.upper()
        for index, name in enumerate(JOBS):
            if name in wanted:
                return index
        return None

    def say(self, reply: str, env: Any, agent_id: str) -> str | None:
        """Return what to say, read only off the SAY line."""
        line = _line(reply, "SAY:")
        if line is None or line.upper() in ("", "NOTHING", "NONE", "-"):
            return None
        return line

    def reflect(self, reply: str, env: Any, agent_id: str) -> str | None:
        """Carry the plan forward, not the whole reply.

        The default carries everything, which would put the last job and the last
        spoken sentence back into the next prompt and invite the model to repeat
        both. One sentence is what a plan is.
        """
        return _line(reply, "PLAN:")


# How far the planner will walk for a job. This partner works the whole kitchen,
# because it was told which job to do and refusing to walk to it would be answering
# a different question from the one the model asked.
_ANYWHERE = 99

# How much of the conversation goes into one prompt. It is what a partner can
# usefully hold in mind, not the whole transcript: the participant can see all of
# their own.
_HEARS = 8


def _line(reply: str, label: str) -> str | None:
    """Return the text after one labelled line of the reply, or nothing.

    It is generous about the line -- any case, any surrounding space, and a label a
    model wrapped in asterisks -- and strict about **which** line, which is the
    whole point. A reply whose job is unreadable is a fallback, and a fallback is a
    chef that stands still for one decision.
    """
    for line in str(reply).splitlines():
        stripped = line.strip().lstrip("*# -")
        if stripped.upper().startswith(label):
            return stripped[len(label) :].strip().strip("*").strip()
    return None


__all__ = ["JOBS", "MOVES", "NOOP", "PROMPT", "TalkingChef"]
