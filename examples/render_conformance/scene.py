"""The rendering conformance scene: parity fixture 8, as a study anyone can run.

Functional parity asks for one "Surface-rendering conformance scene covering every
logical primitive, assets, deltas, removal, depth, and animation". This is that
scene. It is study code rather than platform code -- it draws pictures and knows
what they mean -- so it lives here with the other examples.

The scene is deliberately readable by a machine. Every shape is a flat block of one
colour at a stated place, so a test can look at the canvas and say which primitive
drew and which did not. A pretty scene would prove the same thing and be
unfalsifiable.

What each frame does:

- **frame 0** draws all eight primitives, the declared image, and one atlas frame;
- **frame 1** moves the persistent marker, which travels as a delta and tweens;
- **frame 2** removes the marker, which makes the frame a keyframe without it;
- throughout, two overlapping blocks prove depth: the deeper one is on top.

Run it with ``uvicorn examples.render_conformance.scene:app``.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, ClassVar, cast

import gymnasium

from mug.content import Choice, Form, Game, Page, Study
from mug.content.assets import Atlas, Image
from mug.game.env import StepResult
from mug.game.spec import GameSpec
from mug.game.surface import Surface

# The colours the test reads back. Each is unmistakable, and none of them is any
# other's neighbour, so a sampled pixel names exactly one shape.
RECT = "#ff0000"
CIRCLE = "#00ff00"
ELLIPSE = "#0000ff"
ARC = "#ff8800"
LINE = "#00ffff"
POLYGON = "#8800ff"
TEXT = "#000000"
UNDER = "#333333"
OVER = "#ffffff"
MARKER = "#ff00ff"

# Where the moving marker starts and where it goes. Both are far from every other
# shape, so a sampled pixel says whether it moved.
MARKER_START = (0.10, 0.90)
MARKER_END = (0.80, 0.90)


def render(surface: Surface, state: StepResult) -> None:
    """Draw the conformance scene for one frame."""
    observed = cast("Any", state.observation)
    step = 0 if observed is None else int(observed[0])

    # -- the eight primitives, each in its own corner of the canvas ---------------
    surface.rect(x=0.02, y=0.02, w=0.12, h=0.12, color=RECT)
    surface.circle(x=0.25, y=0.08, radius=0.05, color=CIRCLE)
    surface.ellipse(x=0.45, y=0.08, rx=0.08, ry=0.04, color=ELLIPSE)
    surface.arc(
        x=0.65,
        y=0.08,
        radius=0.06,
        start_angle=0.0,
        end_angle=math.pi * 2,
        color=ARC,
        fill=True,
    )
    surface.line(points=[(0.02, 0.30), (0.30, 0.30)], color=LINE)
    surface.polygon(
        points=[(0.40, 0.34), (0.50, 0.26), (0.60, 0.34)], color=POLYGON
    )
    surface.text(x=0.05, y=0.45, text="conformance", color=TEXT, font_size=18)

    # -- assets: one declared image, and one frame of a declared atlas ------------
    surface.image(image_name="badge", x=0.80, y=0.02, w=0.14, h=0.14)
    surface.image(image_name="sprites", x=0.80, y=0.22, w=0.14, h=0.14, frame=1)

    # -- depth: the deeper block covers the shallower one ------------------------
    surface.rect(x=0.20, y=0.55, w=0.20, h=0.14, color=UNDER, depth=1)
    surface.rect(x=0.25, y=0.58, w=0.10, h=0.08, color=OVER, depth=2)

    # -- an object with a life: it is introduced, it moves, then it is removed ----
    if step >= 2:
        surface.remove("marker")
    else:
        x, y = MARKER_START if step == 0 else MARKER_END
        surface.rect(
            x=x,
            y=y,
            w=0.08,
            h=0.06,
            color=MARKER,
            object_id="marker",
            persistent=True,
            tween_duration=120,
        )


class _Counter(gymnasium.Env[Any, Any]):
    """The smallest environment that can drive a scene: it counts its own steps.

    The scene is about drawing, so the environment is deliberately nothing. Using a
    real control task here would make the fixture fail for reasons that have nothing
    to do with rendering.
    """

    metadata: ClassVar[dict[str, Any]] = {}

    def __init__(self) -> None:
        self.action_space = gymnasium.spaces.Discrete(2)
        self.observation_space = gymnasium.spaces.Box(low=0, high=1_000, shape=(1,))
        self._step = 0

    def reset(
        self, *, seed: int | None = None, options: Any = None
    ) -> tuple[Any, Any]:
        super().reset(seed=seed)
        self._step = 0
        return [0.0], {}

    def step(self, action: Any) -> tuple[Any, float, bool, bool, Any]:
        self._step += 1
        return [float(self._step)], 0.0, self._step >= 4, False, {}


def conformance_spec() -> GameSpec:
    """Return the game specification that draws the conformance scene."""
    return GameSpec(
        channel_key="render-conformance",
        make_env=_Counter,
        render=render,
        action_bindings={"ArrowLeft": 0, "ArrowRight": 1},
        default_action=0,
        fps=4,
        max_steps=4,
    )


def conformance_study() -> Study:
    """Return the study that walks a participant into the conformance scene."""
    return Study(
        Form("consent", Choice("agree", "Do you consent to take part?", ["yes", "no"])),
        Game("play", conformance_spec()),
        Page("debrief", "# Thank you\n\nYou have finished the study."),
        assets=[
            Image("badge", "assets/badge.png"),
            Atlas(
                "sprites",
                "assets/sprites.png",
                frames=[(0, 0, 16, 16), (16, 0, 16, 16)],
            ),
        ],
        asset_root=str(Path(__file__).resolve().parent),
    )


def build() -> Any:
    """Build the application that serves the conformance scene."""
    from mug.app import build_app_from_env

    return build_app_from_env(study=conformance_study(), game=conformance_spec())
