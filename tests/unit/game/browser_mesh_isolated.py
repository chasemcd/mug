"""Run the shipped browser bundle the way a participant's browser runs it.

This script is started by ``test_browser_mesh.py`` in an isolated interpreter
(``python -I``) whose import path cannot reach this repository. It reads the
bundle on standard input, runs it, plays a short two-peer mesh, and reports the
result on standard output as json.

It exists as a file rather than as inline source because that is what makes the
isolation real: the test cannot accidentally hand it a platform import.
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    """Run one bundle from standard input and report what it produced."""
    bundle = json.loads(sys.stdin.read())
    scope: dict[str, object] = {}
    exec(compile(bundle["prelude"], "<prelude>", "exec"), scope)
    install = scope["_mug_install_module"]
    for module in bundle["modules"]:
        install(module["name"], module["source"])  # pyright: ignore[reportCallIssue]
    driver_module = sys.modules["mug.game.browser_mesh_driver"]

    study: dict[str, object] = {}
    exec(compile(bundle["study"], "<study>", "exec"), study)

    handles = tuple(bundle["handles"])
    drivers = {
        handle: driver_module.boot_mesh_driver(
            json.dumps(
                {
                    "local_actor_id": handle,
                    "peer_actor_ids": list(handles),
                    "channel_key": "isolated",
                    "room_handle": "room_isolated",
                    "negotiation_generation": 1,
                    "seed": 3,
                    "input_delay": 1,
                    "max_steps": 12,
                }
            ),
            study["make_replica"],
            study.get("draw"),
        )
        for handle in handles
    }

    inbox: dict[str, list[tuple[str, str]]] = {handle: [] for handle in handles}
    for _ in range(200):
        for handle, driver in drivers.items():
            for remote, text in inbox[handle]:
                driver.receive(remote, text)
            inbox[handle] = []
        for handle, driver in drivers.items():
            for text in driver.tick(1):
                for other in handles:
                    if other != handle:
                        inbox[other].append((handle, text))
        if all(driver.ready_to_finalize() for driver in drivers.values()):
            break
    for driver in drivers.values():
        driver.finalize()

    reference = drivers[handles[0]]
    agreed = all(
        driver.frame_hashes() == reference.frame_hashes()
        for driver in drivers.values()
    )
    # Every module named ``mug`` must be one the prelude built in memory. A file
    # behind one would mean this interpreter reached the repository after all.
    platform_files = [
        name
        for name, module in sys.modules.items()
        if name.split(".")[0] == "mug" and getattr(module, "__file__", None)
    ]
    print(
        json.dumps(
            {
                "agreed": agreed,
                "frames": reference.frame_count(),
                "platform_files": platform_files,
            }
        )
    )


main()
