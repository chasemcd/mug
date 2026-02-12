from mug.examples.mountain_car.mountain_car_rgb_env import (
    MountainCarRGBEnv,
)
import matplotlib.pyplot as plt

env = MountainCarRGBEnv(render_mode="rgb_array")

env.reset()

arr = env.render()
plt.imshow(arr)
plt.show()
