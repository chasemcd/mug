"""What a participant reads in an Overcooked study, with the pictures back in it.

Every study here shows the same task, so it explains it the same way and the words
live in one place. The pages are markdown, and a picture is written the way
markdown writes one::

    ![Chef with a blue hat](blue-chef =24x32)

``blue-chef`` is a **declared study asset** (``sprites.overcooked_assets``), not a
path and not an address. The client resolves the name against the same collection
the renderer resolves a sprite against, so what a page can show is exactly what
the study said it ships. The size after the name is optional and is the one thing
a page needs to say about a picture: the same chef is a line-height icon in a
sentence and a labelled figure in a legend.

The legacy study kept these as HTML files under ``html_pages/``. They are markdown
now for one reason: markdown is what a participant reads on every other screen the
platform draws, and a study that wrote HTML for one screen and markdown for the
next would need the client to run both.
"""

from __future__ import annotations

# What a chef does, in the order they do it. Every study repeats this, so it is
# written once.
HOW_TO_COOK = """
1. Pick up onions and put three of them in a pot.
2. Wait for the soup to cook. The number on the pot counts down.
3. Pick up a plate, collect the soup, and take it to the grey serving square.
"""

# The controls, with the keys shown rather than named. A participant who is told
# "press W" has to find W; a participant who is shown the key has found it.
CONTROLS = """
### The controls

![The four arrow keys](arrow-keys =110x110) move your chef.

![The W key](w-key =40x40) picks up what you are facing, and puts down what you
are holding.
"""

# Who is who. The legacy study showed both chefs side by side on every screen that
# could, because "you are the blue one" is the single thing a participant most
# needs and most often forgets.
WHO_IS_WHO = """
### Who is who

![Chef with a blue hat](blue-chef =36x48) is **you**.

![Chef with a green hat](green-chef =36x48) is your partner.
"""

# The line beside the game itself, while it is being played. It is short on
# purpose: it sits next to a running kitchen, and a participant reads it once.
IN_GAME = (
    "You are ![Chef with a blue hat](blue-chef =20x27). Your partner is "
    "![Chef with a green hat](green-chef =20x27). Move with "
    "![The arrow keys](arrow-keys =44x44) and pick up or put down with "
    "![The W key](w-key =22x22)."
)


# The line beside a kitchen the participant can also talk in. It is the ordinary
# one plus the one sentence that is different, because a participant who is not
# told the box is for their partner will not use it.
IN_GAME_WITH_TALK = IN_GAME + " Type to your partner in the box beside the kitchen."


def instructions(*, partner: str, rounds: str = "") -> str:
    """Return the instruction page for a study, by who the participant cooks with.

    ``partner`` is the sentence that says who is on the other side of the kitchen,
    because that is the one thing these studies really differ on and it is the one
    thing a participant must be told truthfully.
    """
    return f"""
# Overcooked

{partner}

Make onion soup and deliver as much of it as you can before the time runs out.

{HOW_TO_COOK}
{WHO_IS_WHO}
{CONTROLS}

### The kitchen

![The kitchen you cook in](cramped-room =315x270)

{rounds}
"""


HUMAN_AI = "You and an AI partner run a kitchen together."
TALKING_AI = (
    "You and an AI partner run a kitchen together, and **you can talk to each "
    "other while you cook**. Your partner reads what you write and can write back."
)
HUMAN_HUMAN = (
    "You and another participant run a kitchen together. You will wait a moment "
    "while we find you a partner."
)

TWO_ROUNDS = """
You will cook two rounds, each with a **different** partner, and then we will ask
you about them.
"""

BETWEEN_PARTNERS = """
# Round two

You will now cook with a **different** partner on the same kitchen.

![Chef with a blue hat](blue-chef =36x48) is still you.

Press continue when you are ready.
"""

BETWEEN_ROUNDS = "Take a moment, then start the next round."

# The rest between rounds of the talking study. It says the one thing that makes
# three rounds worth playing rather than one played three times: what the pair
# worked out is still there in the next round.
BETWEEN_ROUNDS_TALKING = """
# Take a moment

Your partner remembers what you said, and you can carry on the same conversation in
the next round.

Press continue when you are ready.
"""

THREE_ROUNDS = """
You will cook three rounds with the **same** partner. Anything you agree with them
carries into the next round.
"""

DEBRIEF_TALKING = """
# Thank you

Your partner was a language model. It could see the kitchen and read what you wrote,
and it chose what to do about once a second; the walking between those choices was
done by a simple route planner rather than by the model.

It could not see what you were about to do, and it did not learn from your round.
What carried from one round to the next was the conversation and its own notes to
itself.
"""

DEBRIEF_PARTNERS = """
# Thank you

Your two partners were different policies. Neither of them could see what you were
about to do, and neither learned from the round before.
"""

DEBRIEF_PEOPLE = """
# Thank you

You cooked with another real participant.
"""

__all__ = [
    "BETWEEN_PARTNERS",
    "BETWEEN_ROUNDS",
    "BETWEEN_ROUNDS_TALKING",
    "CONTROLS",
    "DEBRIEF_PARTNERS",
    "DEBRIEF_PEOPLE",
    "DEBRIEF_TALKING",
    "HOW_TO_COOK",
    "HUMAN_AI",
    "HUMAN_HUMAN",
    "IN_GAME",
    "IN_GAME_WITH_TALK",
    "TALKING_AI",
    "THREE_ROUNDS",
    "TWO_ROUNDS",
    "WHO_IS_WHO",
    "instructions",
]
