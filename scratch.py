from __future__ import annotations

import matplotlib.pyplot as plt

from mug.examples.mountain_car.mountain_car_rgb_env import MountainCarRGBEnv

env = MountainCarRGBEnv(render_mode="rgb_array")

env.reset()

arr = env.render()
plt.imshow(arr)
plt.show()
