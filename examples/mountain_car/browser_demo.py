"""Run the browser (Pyodide) single-participant demo with MountainCar.

This is the study entrypoint for the browser execution mode: the environment
runs in the participant browser through Pyodide, and the client reports its run
under browser authority. It supplies the MountainCar ``BrowserGameSpec`` to the
platform application. The platform stays generic -- the environment lives here.

Run with::

    uvicorn examples.mountain_car.browser_demo:app
"""

from __future__ import annotations

from examples.mountain_car.browser_env import mountain_car_browser_spec
from examples.mountain_car.study import mountain_car_study
from mug.app import build_app_from_env

# Set ``MUG_PG_DSN`` to run on Postgres (visits persist across restarts); unset,
# it runs on the in-memory store.
app = build_app_from_env(
    study=mountain_car_study(), browser_game=mountain_car_browser_spec()
)
