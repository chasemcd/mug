from __future__ import annotations

import dataclasses
import math

import numpy as np
import slime_volleyball.slimevolley_env as slimevolley_env
from slime_volleyball.backend.env_state import EnvState
from slime_volleyball.core import constants

from mug.rendering import Surface


def to_x(x):
    return x / constants.REF_W + 0.5


def to_y(y):
    return 1 - y / constants.REF_W


class SlimeVBEnvIG(slimevolley_env.SlimeVolleyEnv):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.surface = Surface(width=600, height=250)

    def reset(self, *args, **kwargs):
        obs, info = super().reset(*args, **kwargs)
        self.surface.reset()
        # Build legacy game object for rendering (static geometry)
        if self._game is None:
            self._build_legacy_game()
        # Flatten nested obs: {"agent_id": {"obs": array}} -> {"agent_id": array}
        if isinstance(obs, dict):
            obs = {
                k: v["obs"] if isinstance(v, dict) and "obs" in v else v
                for k, v in obs.items()
            }
        return obs, info

    def step(self, actions):
        obs, rewards, terminateds, truncateds, infos = super().step(actions)
        # Flatten nested obs for ONNX compatibility
        if isinstance(obs, dict):
            obs = {
                k: v["obs"] if isinstance(v, dict) and "obs" in v else v
                for k, v in obs.items()
            }
        return obs, rewards, terminateds, truncateds, infos

    def _sync_game_from_state(self):
        """Sync legacy _game object positions from _env_state for rendering."""
        if self._game is None or self._env_state is None:
            return
        s = self._env_state
        self._game.ball.x = float(s.ball_pos[0])
        self._game.ball.y = float(s.ball_pos[1])
        self._game.ball.vx = float(s.ball_vel[0])
        self._game.ball.vy = float(s.ball_vel[1])
        self._game.agent_left.x = float(s.agent_pos[0, 0])
        self._game.agent_left.y = float(s.agent_pos[0, 1])
        self._game.agent_right.x = float(s.agent_pos[1, 0])
        self._game.agent_right.y = float(s.agent_pos[1, 1])

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
        ballX = self._game.ball.x - (x + 0.6 * radius * c)
        ballY = self._game.ball.y - (y + 0.6 * radius * s)
        dist = math.sqrt(ballX * ballX + ballY * ballY)
        eyeX = ballX / dist
        eyeY = ballY / dist

        self.surface.circle(
            id=f"{identifier}_eye_white",
            x=to_x(x + 0.6 * radius * c),
            y=to_y(y + 0.6 * radius * s),
            color="#FFFFFF",
            radius=radius * 0.3 / constants.REF_W,
            depth=1,
            relative=True,
        )

        self.surface.circle(
            id=f"{identifier}_eye_pupil",
            x=to_x(x + 0.6 * radius * c + eyeX * 0.15 * radius),
            y=to_y(y + 0.6 * radius * s + eyeY * 0.15 * radius),
            color="#000000",
            radius=radius * 0.1 / constants.REF_W,
            depth=2,
            relative=True,
        )

    def render(self, *, agent_id=None):
        if self._game is None:
            self._build_legacy_game()
        self._sync_game_from_state()

        # Persistent objects -- drawn every frame, Surface handles deltas
        self.surface.line(
            id="fence",
            color="#000000",
            points=[
                (
                    to_x(self._game.fence.x),
                    to_y(self._game.fence.y + self._game.fence.h / 2),
                ),
                (
                    to_x(self._game.fence.x),
                    to_y(self._game.fence.y - self._game.fence.h / 2),
                ),
            ],
            width=self._game.fence.w * 600 / constants.REF_W,
            persistent=True,
            relative=True,
        )

        self.surface.circle(
            id="fence_stub",
            color="#000000",
            x=to_x(self._game.fence_stub.x),
            y=to_y(self._game.fence_stub.y),
            radius=self._game.fence_stub.r / constants.REF_W,
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
                    - self._game.ground.y / constants.REF_W
                    - constants.REF_U / constants.REF_W / 2,
                ),
                (
                    1,
                    1
                    - self._game.ground.y / constants.REF_W
                    - constants.REF_U / constants.REF_W / 2,
                ),
            ],
            fill_below=True,
            width=self._game.ground.w / constants.REF_W,
            depth=-1,
            persistent=True,
            relative=True,
        )

        # Dynamic objects -- agents and ball
        self._draw_agent(
            "agent_left",
            x=self._game.agent_left.x,
            y=self._game.agent_left.y,
            dir=self._game.agent_left.dir,
            radius=self._game.agent_left.r,
            color="#FF0000",
        )

        self._draw_agent(
            "agent_right",
            x=self._game.agent_right.x,
            y=self._game.agent_right.y,
            dir=self._game.agent_right.dir,
            radius=self._game.agent_right.r,
            color="#0000FF",
        )

        is_done = bool(self._env_state.done) if self._env_state is not None else False
        self.surface.circle(
            id="ball",
            color="#AAFF00" if is_done else "#000000",
            x=self._game.ball.x / constants.REF_W + 0.5,
            y=1 - self._game.ball.y / constants.REF_W,
            radius=self._game.ball.r / constants.REF_W,
            relative=True,
        )

        return self.surface.commit().to_dict()

    def get_state(self) -> dict[str, int | float | str]:
        """Return state dict for multiplayer state sync."""
        s = self._env_state
        return {
            "t": self.t,
            "ball_pos_x": float(s.ball_pos[0]),
            "ball_pos_y": float(s.ball_pos[1]),
            "ball_vel_x": float(s.ball_vel[0]),
            "ball_vel_y": float(s.ball_vel[1]),
            "ball_prev_pos_x": float(s.ball_prev_pos[0]),
            "ball_prev_pos_y": float(s.ball_prev_pos[1]),
            "agent_left_x": float(s.agent_pos[0, 0]),
            "agent_left_y": float(s.agent_pos[0, 1]),
            "agent_right_x": float(s.agent_pos[1, 0]),
            "agent_right_y": float(s.agent_pos[1, 1]),
            "agent_left_vx": float(s.agent_vel[0, 0]),
            "agent_left_vy": float(s.agent_vel[0, 1]),
            "agent_right_vx": float(s.agent_vel[1, 0]),
            "agent_right_vy": float(s.agent_vel[1, 1]),
            "agent_left_desired_vx": float(s.agent_desired_vel[0, 0]),
            "agent_left_desired_vy": float(s.agent_desired_vel[0, 1]),
            "agent_right_desired_vx": float(s.agent_desired_vel[1, 0]),
            "agent_right_desired_vy": float(s.agent_desired_vel[1, 1]),
            "agent_left_life": int(s.agent_life[0]),
            "agent_right_life": int(s.agent_life[1]),
            "delay_life": int(s.delay_life),
            "done": bool(s.done),
        }

    def set_state(self, state: dict[str, int | float | str]) -> None:
        """Restore state from a state dict for multiplayer sync."""
        self.t = state["t"]
        self._env_state = dataclasses.replace(
            self._env_state,
            ball_pos=np.array(
                [state["ball_pos_x"], state["ball_pos_y"]], dtype=np.float32
            ),
            ball_vel=np.array(
                [state["ball_vel_x"], state["ball_vel_y"]], dtype=np.float32
            ),
            ball_prev_pos=np.array(
                [state["ball_prev_pos_x"], state["ball_prev_pos_y"]], dtype=np.float32
            ),
            agent_pos=np.array(
                [
                    [state["agent_left_x"], state["agent_left_y"]],
                    [state["agent_right_x"], state["agent_right_y"]],
                ],
                dtype=np.float32,
            ),
            agent_vel=np.array(
                [
                    [state["agent_left_vx"], state["agent_left_vy"]],
                    [state["agent_right_vx"], state["agent_right_vy"]],
                ],
                dtype=np.float32,
            ),
            agent_desired_vel=np.array(
                [
                    [state["agent_left_desired_vx"], state["agent_left_desired_vy"]],
                    [state["agent_right_desired_vx"], state["agent_right_desired_vy"]],
                ],
                dtype=np.float32,
            ),
            agent_life=np.array(
                [state["agent_left_life"], state["agent_right_life"]], dtype=np.int32
            ),
            delay_life=np.int32(state["delay_life"]),
            time=np.int32(state["t"]),
            done=np.bool_(state["done"]),
        )


# Initialize the environment for use in the browser. SlimeVB uses a seed only in
# initialization rather than on reset() so that each episode isn't identical; we want
# the sequence of episodes to be identical.
env = SlimeVBEnvIG(config={"human_inputs": True, "seed": 42}, render_mode="mug")
