""""
MountainCar renders an environment using libraries that aren't
pure python. Here, we override the rgb_array rendering to 
use pure python in a way that will allow it to be run via Pyodide.
"""

import numpy as np
from gymnasium.envs.classic_control.mountain_car import MountainCarEnv as _BaseMountainCarEnv
from mug.configurations.object_contexts import Polygon, Circle, Line


class MountainCarEnv(_BaseMountainCarEnv):


    def step(self, actions: dict[str, int | float]):
        assert "human" in actions, "Must be using human agent ID!"
        action = actions["human"]
        return super().step(action)

    def render(self):
        assert self.render_mode == "interactive-gym"

        y_offset = 0.05
        min_pos, max_pos = (
            env.unwrapped.min_position,
            env.unwrapped.max_position,
        )
        env_ = self.unwrapped

        def _normalize_x(vals, minn=min_pos, maxx=max_pos):
            vals -= minn
            return vals / (maxx - minn)

        # Get coordinates of the car
        car_x = env_.state[0]

        car_y = 1 - env_._height(car_x) + y_offset
        car_x = _normalize_x(car_x)

        car_sprite = Circle(
            uuid="car",
            color="#000000",
            x=car_x,
            y=car_y,
            radius=16,
        )

        # Get coordinates of the flag
        flagx = env_.goal_position
        flagy1 = 1 - env_._height(env_.goal_position)
        flagy2 = 0.05
        flagx = _normalize_x(flagx)
        flag_pole = Line(
            uuid="flag_line",
            color="#000000",
            points=[(flagx, flagy1), (flagx, flagy2)],
            width=3,
        )

        flag = Polygon(
            uuid="flag",
            color="#00FF00",
            points=[
                (flagx, flagy1),
                (flagx, flagy1 + 0.03),
                (flagx - 0.02, flagy1 + 0.015),
            ],
        )

        # Get line coordinates
        xs = np.linspace(min_pos, max_pos, 100)
        ys = 1 - env_._height(xs) + y_offset
        xs = _normalize_x(xs)
        xys = list(zip((xs), ys))
        line = Line(
            uuid="ground_line",
            color="#964B00",
            points=xys,
            width=1,
            fill_below=True,
        )

        return [
            car_sprite.as_dict(),
            line.as_dict(),
            flag_pole.as_dict(),
            flag.as_dict(),
        ]


env = MountainCarEnv(render_mode="interactive-gym")
env
