"""Run the native single-participant demo with MountainCar in the browser.

This is the study entrypoint: it supplies the MountainCar ``GameSpec`` to the
platform application and exposes the ASGI app. The platform stays generic -- the
environment lives here, with the study.

Run with::

    uvicorn examples.mountain_car.native_demo:app
"""

from __future__ import annotations

from examples.mountain_car.native_env import mountain_car_spec
from mug.app import build_app_from_env

# Set ``MUG_PG_DSN`` to run on Postgres (visits persist across restarts); unset,
# it runs on the in-memory store.
app = build_app_from_env(game=mountain_car_spec())
