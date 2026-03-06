from __future__ import annotations

import math

import slime_volleyball.slimevolley_env as slimevolley_env
from slime_volleyball.core import constants

from mug.rendering import Surface

Y_OFFSET = 0.018


def to_x(x):
    return x / constants.REF_W + 0.5


def to_y(y):
    return 1 - y / constants.REF_W


class SlimeVBEnvIG(slimevolley_env.SlimeVolleyEnv):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.surface = Surface(width=600, height=250)

    def reset(self, *args, **kwargs):
        result = super().reset(*args, **kwargs)
        self.surface.reset()
        return result

    def _draw_agent(
        self,
        identifier: str,
        x: int,
        y: int,
        dir: int,
        radius: int,
        color: str,
        resolution: int = 30,
    ) -> None:
        """Draw a slime agent (body polygon + eyes) onto the surface."""
        # Semi-circle body
        points = []
        for i in range(resolution + 1):
            ang = math.pi - math.pi * i / resolution
            points.append(
                (to_x(math.cos(ang) * radius + x), to_y(math.sin(ang) * radius + y))
            )

        self.surface.polygon(
            id=f"{identifier}_body",
            color=color,
            points=points,
            depth=-1,
            relative=True,
        )

        # Eyes that track the ball
        angle = math.pi * 60 / 180
        if dir == 1:
            angle = math.pi * 120 / 180

        c = math.cos(angle)
        s = math.sin(angle)
        ballX = self.game.ball.x - (x + 0.6 * radius * c)
        ballY = self.game.ball.y - (y + 0.6 * radius * s)
        dist = math.sqrt(ballX * ballX + ballY * ballY)
        eyeX = ballX / dist
        eyeY = ballY / dist

        self.surface.circle(
            id=f"{identifier}_eye_white",
            x=to_x(x + 0.6 * radius * c),
            y=to_y(y + 0.6 * radius * s),
            color="#FFFFFF",
            radius=radius * 4,
            depth=1,
            relative=True,
        )

        self.surface.circle(
            id=f"{identifier}_eye_pupil",
            x=to_x(x + 0.6 * radius * c + eyeX * 0.15 * radius),
            y=to_y(y + 0.6 * radius * s + eyeY * 0.15 * radius),
            color="#000000",
            radius=radius * 2,
            depth=2,
            relative=True,
        )

    def render(self):
        # Persistent objects -- drawn every frame, Surface handles deltas
        self.surface.line(
            id="fence",
            color="#000000",
            points=[
                (
                    to_x(self.game.fence.x),
                    to_y(self.game.fence.y + self.game.fence.h / 2),
                ),
                (
                    to_x(self.game.fence.x),
                    to_y(self.game.fence.y - self.game.fence.h / 2),
                ),
            ],
            width=self.game.fence.w * 600 / constants.REF_W,
            persistent=True,
            relative=True,
        )

        self.surface.circle(
            id="fence_stub",
            color="#000000",
            x=to_x(self.game.fence_stub.x),
            y=to_y(self.game.fence_stub.y),
            radius=self.game.fence_stub.r * 600 / constants.REF_W,
            persistent=True,
            relative=True,
        )

        self.surface.line(
            id="ground",
            color="#747275",
            points=[
                (
                    0,
                    1
                    - self.game.ground.y / constants.REF_W
                    - constants.REF_U / constants.REF_W / 2,
                ),
                (
                    1,
                    1
                    - self.game.ground.y / constants.REF_W
                    - constants.REF_U / constants.REF_W / 2,
                ),
            ],
            fill_below=True,
            width=self.game.ground.w / constants.REF_W,
            depth=-1,
            persistent=True,
            relative=True,
        )

        # Dynamic objects -- agents and ball
        self._draw_agent(
            "agent_left",
            x=self.game.agent_left.x,
            y=self.game.agent_left.y,
            dir=self.game.agent_left.dir,
            radius=self.game.agent_left.r,
            color="#FF0000",
        )

        self._draw_agent(
            "agent_right",
            x=self.game.agent_right.x,
            y=self.game.agent_right.y,
            dir=self.game.agent_right.dir,
            radius=self.game.agent_right.r,
            color="#0000FF",
        )

        terminateds, _ = self.get_terminateds_truncateds()
        self.surface.circle(
            id="ball",
            color="#000000" if not terminateds["__all__"] else "#AAFF00",
            x=self.game.ball.x / constants.REF_W + 0.5,
            y=1 - self.game.ball.y / constants.REF_W,
            radius=self.game.ball.r * 600 / constants.REF_W,
            relative=True,
        )

        return self.surface.commit().to_dict()

    def get_state(self) -> dict[str, int | float | str]:
        """Return the state that fully describes the game for state syncing.

        :return: State that fully describes the game for state syncing.
        :rtype: dict
        """
        return {
            # Timestep
            "t": self.t,
            # Delay screen state (countdown before ball starts moving)
            "delay_screen_life": self.game.delay_screen.life,
            # Ball State
            "ball_x": self.game.ball.x,
            "ball_y": self.game.ball.y,
            "ball_prev_x": self.game.ball.prev_x,
            "ball_prev_y": self.game.ball.prev_y,
            "ball_vx": self.game.ball.vx,
            "ball_vy": self.game.ball.vy,
            "ball_r": self.game.ball.r,
            "ball_c": self.game.ball.c,
            # Agent Left State
            "agent_left_dir": self.game.agent_left.dir,
            "agent_left_x": self.game.agent_left.x,
            "agent_left_y": self.game.agent_left.y,
            "agent_left_r": self.game.agent_left.r,
            "agent_left_c": self.game.agent_left.c,
            "agent_left_vx": self.game.agent_left.vx,
            "agent_left_vy": self.game.agent_left.vy,
            "agent_left_desired_vx": self.game.agent_left.desired_vx,
            "agent_left_desired_vy": self.game.agent_left.desired_vy,
            "agent_left_powerups_available": self.game.agent_left.powerups_available,
            "agent_left_powered_up_timer": self.game.agent_left.powered_up_timer,
            "agent_left_emotion": self.game.agent_left.emotion,
            "agent_left_life": self.game.agent_left.life,
            "agent_left_should_powerup": self.game.agent_left.should_powerup,
            # Agent Right State
            "agent_right_dir": self.game.agent_right.dir,
            "agent_right_x": self.game.agent_right.x,
            "agent_right_y": self.game.agent_right.y,
            "agent_right_r": self.game.agent_right.r,
            "agent_right_c": self.game.agent_right.c,
            "agent_right_vx": self.game.agent_right.vx,
            "agent_right_vy": self.game.agent_right.vy,
            "agent_right_desired_vx": self.game.agent_right.desired_vx,
            "agent_right_desired_vy": self.game.agent_right.desired_vy,
            "agent_right_powerups_available": self.game.agent_right.powerups_available,
            "agent_right_powered_up_timer": self.game.agent_right.powered_up_timer,
            "agent_right_emotion": self.game.agent_right.emotion,
            "agent_right_life": self.game.agent_right.life,
            "agent_right_should_powerup": self.game.agent_right.should_powerup,
        }

    def set_state(self, state: dict[str, int | float | str]) -> None:
        """Set the state of the environment from a state dictionary.

        :param state: State dictionary containing the state of the environment.
        :type state: dict[str, int | float | str]
        """
        # Timestep
        self.t = state["t"]
        # Delay screen state (countdown before ball starts moving)
        self.game.delay_screen.life = state["delay_screen_life"]
        # Ball State
        self.game.ball.x = state["ball_x"]
        self.game.ball.y = state["ball_y"]
        self.game.ball.prev_x = state["ball_prev_x"]
        self.game.ball.prev_y = state["ball_prev_y"]
        self.game.ball.vx = state["ball_vx"]
        self.game.ball.vy = state["ball_vy"]
        self.game.ball.r = state["ball_r"]
        self.game.ball.c = state["ball_c"]
        # Agent Left State
        self.game.agent_left.dir = state["agent_left_dir"]
        self.game.agent_left.x = state["agent_left_x"]
        self.game.agent_left.y = state["agent_left_y"]
        self.game.agent_left.r = state["agent_left_r"]
        self.game.agent_left.c = state["agent_left_c"]
        self.game.agent_left.vx = state["agent_left_vx"]
        self.game.agent_left.vy = state["agent_left_vy"]
        self.game.agent_left.desired_vx = state["agent_left_desired_vx"]
        self.game.agent_left.desired_vy = state["agent_left_desired_vy"]
        self.game.agent_left.powerups_available = state["agent_left_powerups_available"]
        self.game.agent_left.powered_up_timer = state["agent_left_powered_up_timer"]
        self.game.agent_left.emotion = state["agent_left_emotion"]
        self.game.agent_left.life = state["agent_left_life"]
        self.game.agent_left.should_powerup = state["agent_left_should_powerup"]
        # Agent Right State
        self.game.agent_right.dir = state["agent_right_dir"]
        self.game.agent_right.x = state["agent_right_x"]
        self.game.agent_right.y = state["agent_right_y"]
        self.game.agent_right.r = state["agent_right_r"]
        self.game.agent_right.c = state["agent_right_c"]
        self.game.agent_right.vx = state["agent_right_vx"]
        self.game.agent_right.vy = state["agent_right_vy"]
        self.game.agent_right.desired_vx = state["agent_right_desired_vx"]
        self.game.agent_right.desired_vy = state["agent_right_desired_vy"]
        self.game.agent_right.powerups_available = state["agent_right_powerups_available"]
        self.game.agent_right.powered_up_timer = state["agent_right_powered_up_timer"]
        self.game.agent_right.emotion = state["agent_right_emotion"]
        self.game.agent_right.life = state["agent_right_life"]
        self.game.agent_right.should_powerup = state["agent_right_should_powerup"]

# Initialize the environment for use in the browser. SlimeVB uses a seed only in initialization
# rather than on reset() so that each episode isn't identical; we want the sequence of episodes to
# be identical.
env = SlimeVBEnvIG(config={"human_inputs": True, "seed": 42}, render_mode="mug")
