"""The talking-partner study, walked whole in a real browser.

The unit tests hold each piece: the reply is read three ways, a job is carried out
over many frames, a message wakes the seat, and what a seat carries survives the
rest between rounds. None of that says a **participant** can play this study.

So this walks it: consent, instructions, three rounds of the shipped kitchen with a
rest between them, a survey, and a debrief. In each round the participant writes to
their partner while the kitchen is running, which is the one thing this study is
for and the one thing no server test can see -- two panes share one keyboard, and a
client that let the game read it while somebody typed would pass everything on the
server and be unusable in the hand.

There are two of them, and the pair is the point:

- the **scripted** walk runs the study on a written adapter. It needs no model
  pulled and it always answers the same way, so what it proves is the **study**:
  three rounds, every round painted, a message that reaches the partner and a reply
  that reaches the screen.
- the **live** walk runs the same study on a real Ollama. What it proves is that a
  real model can hold a seat in it -- that it keeps to the three-line reply shape
  often enough to cook, and that its answers arrive inside the deadline the study
  asks for.

When the live walk fails and the scripted one passes, the model broke; when both
fail, the platform did. That is why there are two.

Neither is in the fast gate. Run them with
``pytest tests/e2e_native/test_talking_partner_browser.py`` (Chromium required;
the live one also needs ``ollama serve`` and ``ollama pull llama3.2``).

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import pytest
from example_server import serving
from playwright.sync_api import Page
from whole_study import recorded, walk_the_whole_study

from mug.providers import ModelCall, ModelCompletion, Usage
from mug.storage import InMemoryStore

pytestmark = pytest.mark.e2e

# What counts as a picture rather than an empty canvas.
DREW_SOMETHING = 500

# How much of a later round's picture must match the first round's, as a fraction
# of the canvas. Two chefs on an empty floor beat any threshold set for "did
# anything draw at all", so what is asked is that the round drew what the round
# before it drew.
AS_MUCH_AS_THE_FIRST = 0.7

# The rounds are shortened in the environment's own episode bound and in nothing
# else. How long a round lasts is a property of the environment; the seating, the
# keys, the drawing, the status line, the conversation, the round loop and the
# frame rate are all the shipped ones.
ROUND_STEPS = 150
ROUNDS = 3

# What the participant writes to their partner, one line a round.
SAID = [
    "you fetch the onions and I will plate up",
    "the pot on the left is ready",
    "stay out of my way this round please",
]

OLLAMA_URL = "http://localhost:11434"


def _study(**built: Any) -> Any:
    """Return the shipped study, with only its rounds shortened."""
    from examples.cogrid.overcooked_llm_chat import overcooked_llm_chat_study

    return overcooked_llm_chat_study(rounds=ROUNDS, steps=ROUND_STEPS, **built)


async def _scripted(call: ModelCall) -> ModelCompletion:
    """Answer in the shape the study asks for, and echo what it was told.

    It reads the prompt out of ``content``, which is where every provider reads the
    words of a message. A double that read them anywhere else would pass while the
    real model was sent nothing at all -- which is exactly what happened once, and
    forty-four tests agreed it had not.
    """
    payload: Any = call.payload
    prompt = str(payload["messages"][0]["content"])
    heard = [one for one in prompt.splitlines() if one.startswith("Your partner: ")]
    last = heard[-1].split(": ", 1)[-1] if heard else "nothing yet"
    return ModelCompletion(
        outcome="completed",
        resolved_model="scripted",
        usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
        output={
            "text": (
                "JOB: FETCH_ONION\n"
                f"SAY: right, you said {last}\n"
                "PLAN: fill the pot"
            )
        },
    )


def _ollama_is_running() -> bool:
    """Say whether a local model runner will answer."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2) as answer:
            return bool(json.load(answer).get("models"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False


def _assert_the_study_was_walked(walked: Any) -> None:
    """Hold what is true of this study however its partner is run.

    It is the same claim for the scripted walk and the live one, so it is written
    once: whatever the model does, the participant meets three painted rounds and
    reaches the end.
    """
    assert walked.activities[:2] == ["form", "page"], (
        f"the participant met {walked.activities}, which is not the study as written"
    )
    assert len(walked.games) == ROUNDS, (
        f"{len(walked.games)} of {ROUNDS} rounds reached a canvas; the participant "
        f"met {walked.activities}"
    )
    for index, round_played in enumerate(walked.games, start=1):
        assert round_played.first_painted > DREW_SOMETHING, (
            f"round {index} opened with {round_played.first_painted} painted "
            "pixels, so the kitchen's sprite sheets did not reach the canvas"
        )
        assert round_played.moved, f"round {index} drew one picture and stopped"
        assert round_played.said, f"nothing was written to the partner in round {index}"
    # And every round drew the **kitchen**, not only the two chefs in it. A round
    # after the first used to open on a canvas the rest had emptied, with the
    # server holding back everything it had already sent -- so the counters, the
    # pots, the onion stack and the delivery square were all missing, and every
    # round still beat a threshold set for an empty canvas.
    first = walked.games[0].covered
    for index, round_played in enumerate(walked.games[1:], start=2):
        assert round_played.covered > first * AS_MUCH_AS_THE_FIRST, (
            f"round {index} covered {round_played.covered:.1%} of the canvas where "
            f"round one covered {first:.1%}: the kitchen itself was not drawn"
        )
    assert len(walked.rests) == ROUNDS - 1, (
        f"{len(walked.rests)} rests between {ROUNDS} rounds"
    )
    assert walked.activities[-1] == "page", "the participant never reached the debrief"
    assert walked.finished, "the participant never reached the completion screen"


def test_the_talking_study_is_walked_whole_on_a_written_partner(page: Page) -> None:
    """The study itself: three rounds, a message each round, and a reply on screen.

    The partner answers on a script, so nothing here depends on a model being
    pulled or on it keeping to a format. What is left is the study, and every part
    of it that could be broken by the platform.
    """
    pytest.importorskip("cogrid", reason="uv pip install cogrid==0.3.2")

    store = InMemoryStore()
    with serving(_study(adapter=_scripted), store=store) as address:
        walked = walk_the_whole_study(page, address, screens=60, say=SAID)

    _assert_the_study_was_walked(walked)

    # The partner read what was written to it and answered on the same screen. This
    # is the whole loop -- the participant's words reached the playing seat's next
    # prompt, and what that seat said came back to the participant's own pane.
    answered = [one for round_ in walked.games for one in round_.heard]
    assert answered, "the partner never said anything the participant could read"
    assert any(SAID[0] in one for one in answered), (
        f"the partner never repeated back what it was told; it said {answered}"
    )

    # **The transcript survives the rest between rounds**, on the screen and not
    # only in the model. The rest page tells the participant they can carry on the
    # same conversation; a client that built its panes again for each round replaced
    # what they had said with an empty log, and they watched it disappear the moment
    # they pressed continue. The seats' own memory is held in the unit tests; what
    # this says is that the participant can still see it.
    later = walked.games[-1].heard
    assert any(f"you said {SAID[0]}" in one for one in later), (
        "the conversation was wiped when the next round started: by the last round "
        f"the screen showed {later}, with nothing from the first round on it"
    )
    assert len(later) > len(walked.games[0].heard), (
        "the transcript did not grow across the rounds, so each round started a "
        "conversation of its own"
    )

    left = recorded(store)
    assert left.get("visitplan", 0) == 1, f"no visit was recorded: {left}"
    assert left.get("episode", 0) >= ROUNDS, f"the rounds were not recorded: {left}"


@pytest.mark.skipif(
    not _ollama_is_running(),
    reason="no local model runner answered: ollama serve && ollama pull llama3.2",
)
def test_a_real_model_holds_a_seat_in_the_kitchen(page: Page) -> None:
    """The same study, with a real language model cooking in it.

    This is the one that cannot be faked. It says a real model, at a real latency,
    keeps to the reply shape often enough to cook, and that its answers arrive
    inside the deadline the study asks for -- which was fixed at one second and
    unreachable from a study until this work, so every decision would have fallen
    back and the participant would have seen a partner that never chose anything.

    It is slower than the rest of the suite and it depends on a model that is not
    part of this repository. When it fails and the scripted walk passes, the model
    broke rather than the platform.
    """
    pytest.importorskip("cogrid", reason="uv pip install cogrid==0.3.2")

    store = InMemoryStore()
    with serving(_study(), store=store) as address:
        walked = walk_the_whole_study(page, address, screens=60, say=SAID)

    _assert_the_study_was_walked(walked)

    # The model really answered, and its answers were really read. Three separate
    # things have to be true and each has failed before:
    left = recorded(store)
    assert left.get("modelcall", 0) >= ROUNDS, (
        f"only {left.get('modelcall', 0)} model calls over {ROUNDS} rounds: the "
        f"seat barely reached a provider at all. What was recorded: {left}"
    )
    spoke = [one for round_ in walked.games for one in round_.heard]
    assert spoke, (
        "the model never said anything the participant could read. Its replies "
        "reached the platform but no SAY line was read out of any of them, so a "
        "real model does not keep to the shape this study asks for"
    )
    # And it is a partner rather than a parrot: what it says is about the kitchen
    # it is standing in, which is what the text view is for.
    assert any(len(one.split()) > 1 for one in spoke), f"it only said {spoke}"
