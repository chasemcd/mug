"""Every shipped example builds its study, or says which package it wants.

An example is what a researcher copies, so a broken one is worse than none. The
2026-07-26 requirements audit's standard applies here too: an example is done when
somebody can run it, not when it has been written.

The environments some examples need -- ``cogrid``, ``slime_volleyball``,
``onnxruntime`` -- are not dependencies of this repository, so an example that
needs one is checked as far as it can be and no further. That is deliberate. What
is checked without the package is the part the platform owns: the study composes,
its activities are named once, its keys and assets are declared. What needs the
package is the environment itself, and it says so plainly rather than failing
somewhere further in.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from mug.content import Study

# Every example that composes a study, and the study function to call. An example
# added without a row here is an example nothing checks.
STUDIES = [
    ("examples.mountain_car.study", "mountain_car_study"),
    ("examples.tandem.study", "tandem_study"),
    ("examples.render_conformance.scene", "conformance_study"),
    ("examples.slime_volleyball.human_heuristic", "slime_heuristic_study"),
    ("examples.slime_volleyball.human_ai", "slime_ai_study"),
    ("examples.slime_volleyball.human_human", "slime_human_study"),
    ("examples.cogrid.overcooked_human_ai", "overcooked_human_ai_study"),
    (
        "examples.cogrid.overcooked_human_ai_browser",
        "overcooked_human_ai_browser_study",
    ),
    ("examples.cogrid.overcooked_llm_chat", "overcooked_llm_chat_study"),
    ("examples.cogrid.overcooked_human_human", "overcooked_human_human_study"),
    ("examples.cogrid.overcooked_server_auth", "overcooked_server_auth_study"),
    ("examples.preference_chat.study", "preference_chat_study"),
]


def _built(module_name: str, function_name: str) -> Study:
    """Import one example and build its study."""
    module = importlib.import_module(module_name)
    return getattr(module, function_name)()


@pytest.mark.parametrize(("module_name", "function_name"), STUDIES)
def test_an_example_composes_a_study(module_name: str, function_name: str) -> None:
    """It builds, it has activities, and it names each of them once."""
    study = _built(module_name, function_name)

    assert study.activities, f"{module_name} composes a study with nothing in it"
    keys = [one.key for one in study.activities]
    assert len(set(keys)) == len(keys)


@pytest.mark.parametrize(("module_name", "function_name"), STUDIES)
def test_an_example_ends_somewhere_a_participant_can_stop(
    module_name: str, function_name: str
) -> None:
    """A study that ends on a game leaves the participant on a canvas.

    Every example here ends on a page, because the last thing a participant should
    see is a debrief and a completion code rather than the frame the environment
    happened to stop on.
    """
    study = _built(module_name, function_name)
    assert study.activities[-1].kind == "content"


def test_every_example_with_a_game_says_which_keys_play_it() -> None:
    """A game nobody can supply an input to is a game nobody can play."""
    from examples.cogrid.env import ACTION_BINDINGS as KITCHEN
    from examples.mountain_car.native_env import mountain_car_spec
    from examples.slime_volleyball.env import ACTION_BINDINGS as COURT

    assert mountain_car_spec().action_bindings
    assert KITCHEN and COURT


def test_the_slime_volleyball_bindings_include_the_diagonal_jumps() -> None:
    """The example that needed chorded keys declares them, as sequences of keys.

    This is a regression guard on a real gap: the legacy runtime bound key chords
    and the rewrite resolved only the first bound key, so a port of this study
    would have quietly lost its diagonal jump.

    A chord is written as the **sequence of keys** it is. It was once one name with
    a ``+`` in it, which hid a sequence inside a string and put a character with a
    meaning into a key name -- something the platform's own key-name rule forbids.
    """
    from examples.slime_volleyball.env import ACTION_BINDINGS, UPLEFT, UPRIGHT

    held = {
        binding: action
        for binding, action in ACTION_BINDINGS.items()
        if isinstance(binding, tuple)
    }
    assert set(held.values()) == {UPLEFT, UPRIGHT}
    assert not any(isinstance(one, str) and "+" in one for one in ACTION_BINDINGS), (
        "a chord is a sequence of keys, not a key name with a separator in it"
    )
    for binding in held:
        assert all(key in ACTION_BINDINGS for key in binding), (
            "a chord must be made of keys the study also binds on their own"
        )


def test_an_example_that_needs_a_missing_package_says_which_one() -> None:
    """A researcher is told what to install, rather than shown a stack trace."""
    from examples.cogrid.env import CoGridMissing, make_kitchen
    from examples.slime_volleyball.env import SlimeVolleyballMissing

    for missing, build, wanted in (
        (CoGridMissing, lambda: make_kitchen(), "cogrid"),
        (SlimeVolleyballMissing, _court, "slime_volleyball"),
    ):
        try:
            build()
        except missing as said:
            assert wanted in str(said)
            assert "install" in str(said)
        except ImportError:  # pragma: no cover - the package is installed here
            pytest.fail(f"{wanted} raised a bare ImportError instead of saying so")
        else:  # pragma: no cover - the package is installed on this machine
            pytest.skip(f"{wanted} is installed, so nothing is missing to report")


def test_a_browser_study_builds_with_no_environment_beside_the_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The kitchen runs in the browser, so the server needs no kitchen package.

    ``cogrid`` is not a dependency of this repository. A study that steps the
    environment in the participant's browser must therefore compose on a machine
    that does not have it: the wheel is installed into Pyodide, not beside the
    application. This holds the browser study to that, by making the environment
    package unavailable in the way a missing install is.
    """
    from examples.cogrid import env

    def refuse() -> Any:
        raise env.CoGridMissing("pretend cogrid is not installed")

    monkeypatch.setattr(env, "_cogrid", refuse)

    spec = env.overcooked_browser()

    assert "FEATURES = " in spec.source_bundle
    assert env.COGRID in spec.requires, (
        "the browser gets the environment package, even though the server does not"
    )


def _court() -> Any:
    """Build the Slime Volleyball environment, which needs its own package."""
    from examples.slime_volleyball.env import slime_court

    return slime_court()


def test_the_overcooked_sprite_sheets_declare_the_frames_the_drawing_names() -> None:
    """The drawing says ``counter.png``; the sheet it names must have packed one.

    The platform reads each atlas, so the frames are on the declared asset and this
    check needs nothing from the study but the declaration. It is the check that naming
    a frame makes possible at all: with an index there is nothing to verify, because
    every index is a valid number.
    """
    from pathlib import Path

    from examples.cogrid.sprites import overcooked_assets

    root = Path(__file__).resolve().parents[2]
    packed = {
        one.name: set(one.resolved(root=root).frames) for one in overcooked_assets()
    }

    for named in ("counter.png", "serve.png", "dishes.png", "onions.png", "pot.png"):
        assert named in packed["terrain"], f"the terrain sheet has no {named}"

    for named in ("onion.png", "dish.png", "soup-onion-dish.png"):
        assert named in packed["objects"], f"the objects sheet has no {named}"
    for count in (1, 2, 3):
        assert f"soup-onion-{count}-cooking.png" in packed["objects"]
    assert "soup-onion-cooked.png" in packed["objects"]

    for facing in ("EAST", "SOUTH", "WEST", "NORTH"):
        assert f"{facing}.png" in packed["chefs"]
        assert f"{facing}-bluehat.png" in packed["chefs"]
        assert f"{facing}-greenhat.png" in packed["chefs"]
        for carried in ("-onion", "-soup-onion", "-dish"):
            assert f"{facing}{carried}.png" in packed["chefs"]


def test_the_preference_chat_examples_are_one_study_on_two_backends() -> None:
    """The pair exists to show that a preference study is not tied to a provider.

    Both entry points build the same conversation with the same judgement, and
    differ in the model and in whether a credential is needed at all. If one of
    them drifted, the comparison the pair is for would quietly stop being true.
    """
    from examples.preference_chat.anthropic import hosted_study
    from examples.preference_chat.ollama import local_study

    local, hosted = local_study(), hosted_study()
    assert set(local.talks) == set(hosted.talks) == {"counsel"}
    assert local.talks["counsel"].elicit is not None
    assert hosted.talks["counsel"].elicit is not None
    said, hired = local.talks["counsel"], hosted.talks["counsel"]
    assert said.speakers[0].resolve_secret is None, "a local runner needs no key"
    assert hired.speakers[0].resolve_secret is not None, "a hosted model needs one"


def test_a_chat_study_writes_a_model_rather_than_six_identifiers() -> None:
    """The author surface a conversation gets, and the reason it was added.

    Before this, a chat activity's model seat needed an agent version id, a
    definition id, a prompt version id, a fallback key, and an actor id, all
    hand-written. A game activity never did -- it wrote `Model(agent)` and the
    mount derived the rest -- so a conversation was the one place a study had to
    carry platform plumbing.
    """
    from examples.preference_chat.ollama import local_study
    from mug.gateway import Gateway
    from mug.mounts import chat_for

    written = local_study().talks["counsel"]
    assert len(written.speakers) == 1

    compiled = chat_for(written, derived_id=Gateway().derived_id)
    assert compiled.speaker is None, "the author's spelling is consumed"
    seat = compiled.seats[0]
    assert seat.ids.agent_key
    assert seat.actor_id.startswith("actor_")
    assert type(seat.adapter).__name__ == "OllamaAdapter", "the provider decides it"


# Every example's server-stepped game, and the smallest thing its drawing must put
# on the canvas for one frame. An example added without a row here is an example
# nothing plays.
#
# Each row names the **study** and the activity in it, because that is what an example
# is now: a study names its environment and the platform resolves which runtime steps
# it. So this plays what a participant would be given, not a specification written
# beside it.
PLAYABLE = [
    (
        "render_conformance",
        "examples.render_conformance.scene",
        "conformance_study",
        "play",
        6,
        None,
    ),
    (
        "mountain_car",
        "examples.mountain_car.study",
        "mountain_car_study",
        "play",
        3,
        None,
    ),
    (
        "slime_volleyball",
        "examples.slime_volleyball.human_heuristic",
        "slime_heuristic_study",
        "play",
        7,
        "slime_volleyball",
    ),
    (
        "slime_volleyball_onnx",
        "examples.slime_volleyball.human_ai",
        "slime_ai_study",
        "play",
        7,
        "slime_volleyball,onnxruntime",
    ),
    (
        "overcooked",
        "examples.cogrid.overcooked_human_ai",
        "overcooked_human_ai_study",
        "round-two",
        10,
        "cogrid",
    ),
    (
        "overcooked_onnx",
        "examples.cogrid.overcooked_human_ai",
        "overcooked_human_ai_study",
        "round-one",
        10,
        "cogrid,onnxruntime",
    ),
    (
        "overcooked_llm_chat",
        "examples.cogrid.overcooked_llm_chat",
        "overcooked_llm_chat_study",
        "cook",
        10,
        "cogrid",
    ),
    (
        "overcooked_two_people",
        "examples.cogrid.overcooked_server_auth",
        "overcooked_server_auth_study",
        "play",
        10,
        "cogrid",
    ),
]

# The written specifications the examples still keep, for the tests that are about the
# drawing contract itself rather than about what a participant is given.
BARE = [
    ("render_conformance", "examples.render_conformance.scene", "conformance_spec", 6),
    ("mountain_car", "examples.mountain_car.native_env", "mountain_car_spec", 3),
]


def _played(spec: Any, frames: int = 6) -> list[Any]:
    """Run one single-seat game through the real loop and return its packets."""
    import asyncio

    from mug.game.env import GymEnv
    from mug.game.runtime import InputState, run_episode

    packets: list[Any] = []

    async def sink(packet: Any) -> None:
        packets.append(packet)

    async def play() -> None:
        await run_episode(
            GymEnv(spec.make_env),
            render=spec.render,
            channel_key=spec.channel_key,
            episode_id="episode_019b6000-0000-7000-8000-00000000000a",
            interaction_id="interaction_019b6000-0000-7000-8000-00000000000b",
            seat_key="player",
            input_state=InputState(dict(spec.action_bindings), spec.default_action),
            sink=sink,
            now=lambda: "2026-07-28T00:00:00.000000Z",
            fps=0,
            max_steps=frames,
            countdown_seconds=0,
            hud=spec.hud,
        )

    asyncio.run(play())
    return packets


def _played_seated(mount: Any, frames: int = 6) -> list[Any]:
    """Play one seated game the way the server plays it, and return its packets.

    Every seat is read through its own source -- a person's held keys, a bot's
    controller -- so a partner that needs a view of the environment is exercised here
    rather than stubbed out. The drawing is called on each stepped frame with what the
    first person watching would see.
    """
    import asyncio

    from mug.game.runtime import render_packet, watched_state
    from mug.game.server_session import ServerSeat, ServerSeatSession
    from mug.game.surface import Surface

    spec = mount.server_game or mount.agent_game
    people, bots = _seat_sources(spec)
    seats = [
        ServerSeat(
            seat_key=named,
            actor_id=f"actor-{named}",
            agent_id=agent,
            source=source,
            kind=kind,
        )
        for agent, named, source, kind in [*people, *bots]
    ]
    watching, named_seat = people[0][0], people[0][1]
    surface = Surface()
    packets: list[Any] = []

    async def on_step(info: Any) -> None:
        packets.append(
            render_packet(
                surface,
                spec.render,
                watched_state(info.result, watching),
                "episode_019b6000-0000-7000-8000-00000000000a",
                named_seat,
                info.frame,
                spec.hud,
            )
        )

    async def play() -> None:
        await ServerSeatSession(
            seats=seats,
            env=spec.make_env(),
            channel_key=spec.channel_key,
            interaction_id="interaction_019b6000-0000-7000-8000-00000000000b",
            episode_id="episode_019b6000-0000-7000-8000-00000000000a",
            now=lambda: "2026-07-28T00:00:00.000000Z",
            fps=0,
            max_steps=frames,
        ).run(on_step=on_step)

    asyncio.run(play())
    return packets


def _seat_sources(spec: Any) -> tuple[list[Any], list[Any]]:
    """Return each seat's action source, for whichever seated mount this is."""
    from mug.game.runtime import InputState

    bindings = dict(spec.action_bindings)
    idle = spec.default_action
    if hasattr(spec, "human_agent_id"):
        people = [
            (
                spec.human_agent_id,
                spec.human_seat_key,
                InputState(bindings, idle),
                "human",
            )
        ]
        bots = [
            (one.agent_id, one.seat_key, one.controller, "bot") for one in spec.bots
        ]
        return people, bots
    people = [
        (one.agent_id, one.seat_key, InputState(bindings, idle), "human")
        for one in spec.human_seats
    ]
    # A model seat is driven here as the platform drives it **before its first
    # decision**: it holds the game's own idle action. It is not stubbed out and it
    # is not skipped -- a seat left out of the action set is an environment stepped
    # with an agent missing, which CoGrid refuses on the first frame.
    #
    # No provider is reached, because this test is about the drawing. What the model
    # decides, and what carrying that out looks like, is held where it belongs
    # (``tests/unit/examples/test_talking_chef.py``).
    standing = [
        (one.agent_id, one.seat_key, _Standing(idle), "bot") for one in spec.seats
    ]
    return people, standing


class _Standing:
    """A seat that holds the game's idle action, as a model seat does at frame one."""

    def __init__(self, idle: int) -> None:
        self._idle = int(idle)

    def decide(self, observation: object) -> int:
        """Return the idle action, whatever the seat is shown."""
        return self._idle


@pytest.mark.parametrize(("name", "module", "factory", "least"), BARE)
def test_a_written_specification_still_steps_and_draws(
    name: str, module: str, factory: str, least: int
) -> None:
    """The conformance scene names no environment, so it is played as it is written."""
    spec = getattr(importlib.import_module(module), factory)()

    _assert_drawn(name, _played(spec), least)


@pytest.mark.parametrize(
    ("name", "module", "factory", "activity", "least", "needs"), PLAYABLE
)
def test_an_example_game_steps_and_draws(
    name: str,
    module: str,
    factory: str,
    activity: str,
    least: int,
    needs: str | None,
) -> None:
    """The example runs, and every frame of it puts something on the canvas.

    This is the test three shipped examples would have failed. Composing a study
    proved only that the study composed: one of these raised on its first step, and
    all of them drew an empty canvas for as long as they ran, because the frame's
    own metrics -- where the drawing reads the board from -- were dropped before the
    drawing was called.

    It plays the activity the study wrote, through the runtime the platform resolves
    for it. So a study whose mount resolved to the wrong runtime fails here rather
    than in front of a participant.
    """
    from mug.gateway import Gateway
    from mug.mounts import mount_for

    for wanted in (needs or "").split(","):
        if wanted:
            pytest.importorskip(wanted, reason=f"this example needs {wanted}")
    study = getattr(importlib.import_module(module), factory)()
    mount = mount_for(
        study.game_activities[activity], derived_id=Gateway().derived_id
    )

    played = _played(mount.game) if mount.game else _played_seated(mount)

    _assert_drawn(name, played, least)


def _assert_drawn(name: str, packets: list[Any], least: int) -> None:
    """Assert that a played example drew a moving picture on every frame."""
    assert len(packets) >= 4, f"{name} stopped almost at once"
    assert len(packets[0].commands) >= least, (
        f"{name} opened with {len(packets[0].commands)} drawing commands, so the "
        "participant was shown an all but empty canvas"
    )
    assert all(one.commands for one in packets), (
        f"{name} pushed a frame with nothing drawn on it"
    )
    assert len({one.render_digest.hex for one in packets}) > 1, (
        f"{name} drew the same picture on every frame, so the environment did not "
        "step or the drawing did not read it"
    )


# Every example whose environment is shipped to the browser, and the package the
# browser installs to run it. The source is all a peer gets, so it must build the
# environment itself.
MESHES = [
    ("tandem", "examples.tandem.browser_mesh_env", "tandem_mesh_spec", None),
    (
        "slime_volleyball",
        "examples.slime_volleyball.env",
        "slime_volleyball_mesh",
        "slime_volleyball",
    ),
    ("overcooked", "examples.cogrid.env", "overcooked_mesh", "cogrid"),
]


@pytest.mark.parametrize(("name", "module", "factory", "needs"), MESHES)
def test_a_shipped_mesh_bundle_draws_commands_a_renderer_can_read(
    name: str, module: str, factory: str, needs: str | None
) -> None:
    """What a bundle draws must validate as the drawing contract itself.

    Every peer-to-peer bundle in this repository once wrote ``width`` and
    ``height`` where the contract says ``w`` and ``h``. The commands were produced,
    counted, and drawn -- onto a rectangle of no size. Both clients showed an empty
    canvas, and nothing said so, because the only check was that commands existed.
    """
    from mug.game.types import SurfaceCommand

    if needs is not None:
        pytest.importorskip(needs, reason=f"this example needs {needs}")
    spec = getattr(importlib.import_module(module), factory)()
    namespace: dict[str, Any] = {}
    exec(spec.source_bundle, namespace)
    replica = namespace["make_replica"](["peer-a", "peer-b"], 7)

    commands = namespace["draw"](replica)

    assert commands, f"{name} drew nothing"
    for command in commands:
        # A field the contract does not name is refused, so a misspelt one is a
        # failure here rather than a rectangle of no size on a participant's screen.
        SurfaceCommand.model_validate(command)
    sized = [one for one in commands if one.get("op") in ("rect", "image")]
    assert sized, f"{name} drew nothing with a size"
    assert all(
        float(one.get("w") or 0) > 0 and float(one.get("h") or 0) > 0 for one in sized
    ), f"{name} drew a shape of no size, which paints nothing at all"


@pytest.mark.parametrize(("name", "module", "factory", "needs"), MESHES)
def test_a_shipped_mesh_bundle_builds_a_replica_and_draws_it(
    name: str, module: str, factory: str, needs: str | None
) -> None:
    """The peer-to-peer source runs on its own, because in a browser it has to.

    A mesh bundle is executed by both participants' browsers under Pyodide with
    nothing else in scope. A bundle that named an environment the **server** had
    registered, or seated its peers under names the environment does not use, builds
    nothing there and there is no server to fall back to.
    """
    for wanted in (needs or "").split(","):
        if wanted:
            pytest.importorskip(wanted, reason=f"this example needs {wanted}")
    spec = getattr(importlib.import_module(module), factory)()

    scope: dict[str, Any] = {}
    # This is the scope a browser gives the bundle, and nothing else is in it.
    exec(spec.source_bundle, scope)
    peers = ["actor_019b6000-0000-7000-8000-00000000000a", "actor_b"]
    replica = scope["make_replica"](peers, 7)

    opening = scope["draw"](replica)
    assert opening, f"{name} drew nothing on its opening frame"
    for _ in range(5):
        replica.step(dict.fromkeys(peers, spec.default_action))
    after = scope["draw"](replica)

    assert len(after) == len(opening), f"{name} changed what it draws mid-run"
    assert all("op" in one and "id" in one for one in after), (
        f"{name} drew a command with no operation or no identity"
    )


def test_the_browser_bundle_steps_and_draws_what_the_server_would() -> None:
    """The Pyodide bundle is the same game, and it is checked the same way.

    A browser run is verified by re-executing it on the server, so this bundle is
    not a second implementation that may drift -- it is the one the participant's
    machine runs, and a study is unplayable there for the same reasons it is
    unplayable here.
    """
    from examples.mountain_car.browser_env import mountain_car_browser_spec

    spec = mountain_car_browser_spec()
    scope: dict[str, Any] = {}
    # This is the scope Pyodide gives the bundle, and nothing else is in it.
    exec(spec.source_bundle, scope)

    env = scope["make_env"]()
    observation, _info = env.reset(seed=spec.seed)
    opening = scope["draw"](observation)
    for _ in range(20):
        observation, _reward, _done, _cut, _info = env.step(spec.default_action)
    after = scope["draw"](observation)

    assert len(opening) >= 4, "the browser drew almost nothing"
    assert opening != after, "the car never moved, or the drawing never read it"


# The examples whose environment runs in the participant's browser. Each still hands
# the application a Python bundle, because a browser run supplies the program it runs
# and the platform does not write that program for a named environment yet.
CARRY_A_BUNDLE = {
    "examples/cogrid/overcooked_human_ai_browser.py",
    "examples/cogrid/overcooked_human_human.py",
    "examples/mountain_car/browser_demo.py",
    "examples/slime_volleyball/human_human.py",
    "examples/tandem/study.py",
}


def test_a_server_run_example_hands_over_the_study_and_nothing_else() -> None:
    """The whole claim of the redesign, checked against every example that ships.

    A study names its environment and the platform resolves the rest, so an example
    that runs on the server passes ``study=`` and no second keyword. The five that do
    pass one are the browser and peer-to-peer studies, and they are named here rather
    than allowed silently -- so an example that quietly went back to writing a
    specification fails, and one that is ported is noticed here.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    written: dict[str, set[str]] = {}
    for path in sorted((root / "examples").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            called = getattr(node, "func", None)
            if not isinstance(node, ast.Call) or not isinstance(called, ast.Name):
                continue
            if called.id != "build_app_from_env":
                continue
            named = {one.arg for one in node.keywords if one.arg}
            written.setdefault(str(path.relative_to(root)), set()).update(named)

    assert written, "no example builds an application at all"
    beside_the_study = {
        name: sorted(keywords - {"study", "require_launch"})
        for name, keywords in written.items()
        if keywords - {"study", "require_launch"}
    }
    assert set(beside_the_study) == CARRY_A_BUNDLE, (
        "an example passes something beside its study: "
        f"{beside_the_study}. A server-run study names its environment on the "
        "activity, so there is nothing left to mount beside it."
    )
