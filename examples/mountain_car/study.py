"""The MountainCar study: the smallest whole study a researcher can copy.

One person, one classic control task, and the activities around it that make a
run a study rather than a demo: consent, instructions, the game, a short survey,
and a debrief with a completion code.

The same study runs under either execution mode. ``native_demo`` steps the
environment on the server; ``browser_demo`` ships it to the participant's browser
and runs it there through Pyodide. Nothing in this file changes between the two,
which is the point: where an environment runs is a deployment decision, not a
study one.
"""

from __future__ import annotations

import functools

import gymnasium

from examples.mountain_car.native_env import render
from mug.content import Choice, Form, Game, Human, Likert, Page, Study, Text

INSTRUCTIONS = """
# Drive the car

The car is in a valley and its engine is too weak to climb straight out. Rock it
backwards and forwards to build up enough speed to reach the flag.

- **Left arrow** pushes left.
- **Right arrow** pushes right.

You will have one attempt.
"""

DEBRIEF = """
# Thank you

That is the end of the study. MountainCar is a classic control task: the car
cannot reach the flag by driving at it, so the only way out is to go the wrong way
first.
"""


# The environment, bound the way its author builds it. It takes no arguments, so
# whatever this environment needs is settled here rather than passed in by the
# platform -- and one bound call is a thing that can rebuild itself somewhere else,
# which is what a browser run needs.
make_car = functools.partial(gymnasium.make, "MountainCar-v0")


def mountain_car_study() -> Study:
    """Return the ordered activities one participant walks through."""
    return Study(
        Form(
            "consent",
            Choice(
                "agree",
                "I have read the information sheet and agree to take part.",
                ["yes", "no"],
            ),
        ),
        Page("instructions", INSTRUCTIONS),
        # The whole game: the environment this study trained against, who is in it,
        # and how it is drawn. The agents, the action set, the key bindings, the frame
        # rate, the episode bound, and the package a browser would install are all read
        # off the environment itself, so none of them is written here.
        Game("play", make_car, seats={"agent": Human()}, render=render),
        Form(
            "post-survey",
            Likert("difficulty", "How hard did you find the task?", scale=7),
            Likert("control", "How well did the controls respond?", scale=7),
            Text("strategy", "What did you try? (optional)", required=False),
        ),
        Page("debrief", DEBRIEF),
    )


__all__ = ["mountain_car_study"]
