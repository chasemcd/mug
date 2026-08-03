"""Run the single-participant MountainCar study, stepped on the server.

This is the study entrypoint, and there is nothing left in it but the study. The
environment is named on the game activity (``examples.mountain_car.study``), so the
application is given the study and reads the rest off it: no ``GameSpec``, no frame
rate, no episode bound, no key bindings, and no package pin.

Run with::

    uvicorn examples.mountain_car.native_demo:app
"""

from __future__ import annotations

from examples.mountain_car.study import mountain_car_study
from mug.app import build_app_from_env

# Set ``MUG_PG_DSN`` to run on Postgres (visits persist across restarts); unset,
# it runs on the in-memory store.
app = build_app_from_env(study=mountain_car_study())
