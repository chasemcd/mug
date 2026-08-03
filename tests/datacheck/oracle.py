"""The bench run: one deterministic environment, one fixed sequence of actions.

This is the reference the platform is checked against. It is deliberately simple,
exactly reproducible, and defined **once**, so that "what should have been recorded"
is a fact rather than something the platform computes about itself.

The environment's state is integer modular arithmetic. That matters for three
reasons: it is exact, so nothing here depends on floating point; it is bounded, so a
long run does not overflow; and every frame depends on the **whole** history of
actions before it, so a run that lost a frame, repeated one, or put two out of order
diverges immediately rather than agreeing by luck.

The action sequence is a stated rule rather than a random draw, so it is the same
sequence on every machine and in every language.

``BENCH_FRAMES`` is not a multiple of the reporting cadence on purpose: a run that
divides evenly and one that does not close differently, and both must record the
same data.
"""

from __future__ import annotations

# The environment, as source. One definition serves the browser bundle and the
# server's own re-execution, so the two can never be different environments.
BENCH_BUNDLE = '''
_MOD = 100003


class _Bench:
    """A tiny exact environment whose every frame depends on all the frames before."""

    def reset(self, seed=None):
        self.at = 1 if seed is None else (int(seed) % _MOD)
        self.frame = 0
        return [float(self.at), 0.0, 0.0], {}

    def step(self, action):
        self.frame += 1
        self.at = (self.at * 7 + int(action) * 13 + 1) % _MOD
        return (
            [float(self.at), float(self.frame), float(int(action))],
            float(int(action)),
            False,
            False,
            {"at": self.at},
        )


def make_env():
    return _Bench()


def draw(observation):
    return [
        {
            "op": "rect",
            "id": "bench",
            "relative": True,
            "color": "#204060",
            "x": 0.0,
            "y": 0.0,
            "w": 1.0,
            "h": 1.0,
        }
    ]
'''

# The seed the run starts from, and how long it runs. 137 is prime and is not a
# multiple of the reporting cadence, so the closing report carries frames.
BENCH_SEED = 7
BENCH_FRAMES = 137

# The largest action the bench accepts. The rule below is what makes the sequence a
# constant: no generator, no seed, no draw.
_ACTIONS = 5


def bench_actions(frames: int = BENCH_FRAMES) -> list[int]:
    """Return the fixed action sequence, by the rule that defines it."""
    return [(index * 7 + 3) % _ACTIONS for index in range(frames)]


def bench_observations(
    frames: int = BENCH_FRAMES, seed: int = BENCH_SEED
) -> list[list[float]]:
    """Return what the environment must answer, computed here and nowhere else.

    This is the oracle. It repeats the environment's arithmetic rather than running
    the environment, because a check that ran the environment would only be asking
    the environment whether it agrees with itself.
    """
    modulus = 100003
    at = seed % modulus
    observed: list[list[float]] = []
    for index, action in enumerate(bench_actions(frames), start=1):
        at = (at * 7 + action * 13 + 1) % modulus
        observed.append([float(at), float(index), float(action)])
    return observed


__all__ = [
    "BENCH_BUNDLE",
    "BENCH_FRAMES",
    "BENCH_SEED",
    "bench_actions",
    "bench_observations",
]
