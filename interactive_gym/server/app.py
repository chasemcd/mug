from __future__ import annotations

import atexit
import dataclasses
import logging
import os
import secrets
import threading
import time
import uuid
import msgpack
import pandas as pd
import os
import flatten_dict
import json
import socket
import urllib.request

import flask
import flask_socketio

from interactive_gym.utils.typing import SubjectID, SceneID
from interactive_gym.scenes import gym_scene
from interactive_gym.server import game_manager as gm

from interactive_gym.configurations import remote_config
from interactive_gym.server import utils
from interactive_gym.scenes import stager
from interactive_gym.server import game_manager as gm
from interactive_gym.scenes import unity_scene
from interactive_gym.server import pyodide_game_coordinator
from interactive_gym.server import player_pairing_manager


@dataclasses.dataclass
class ParticipantSession:
    """
    Stores session state for a participant to enable session restoration
    after disconnection/page refresh.
    """

    subject_id: str
    stager_state: dict | None  # Serialized stager state (current_scene_index, etc.)
    interactive_gym_globals: dict  # Client-side metadata (interactiveGymGlobals)
    current_scene_id: str | None  # ID of the current scene
    socket_id: str | None  # Current socket ID if connected
    is_connected: bool  # Whether currently connected
    created_at: float = dataclasses.field(default_factory=time.time)
    last_updated_at: float = dataclasses.field(default_factory=time.time)


def setup_logger(name, log_file, level=logging.INFO):
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler = logging.FileHandler(log_file)
    handler.setFormatter(formatter)

    # Create console handler with a higher log level
    ch = logging.StreamHandler()
    ch.setFormatter(
        formatter
    )  # Setting the formatter for the console handler as well

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.addHandler(ch)
    logger.propagate = False

    return logger


logger = setup_logger(__name__, "./iglog.log", level=logging.DEBUG)

CONFIG = remote_config.RemoteConfig()


# Generic stager is the "base" Stager that we'll build for each
# participant that connects to the server. This is the base instance
# that defines the generic experiment flow.
GENERIC_STAGER: stager.Stager = None  # Instantiate on run()

# Each participant has their own instance of the Stager to manage
# their progression through the experiment.
STAGERS: dict[SubjectID, stager.Stager] = utils.ThreadSafeDict()

# Data structure to save subjects by their socket id
SUBJECTS = utils.ThreadSafeDict()

# Game managers handle all the game logic, connection, and waiting room for a given scene
GAME_MANAGERS: dict[SceneID, gm.GameManager] = utils.ThreadSafeDict()

# Pyodide multiplayer game coordinator
PYODIDE_COORDINATOR: pyodide_game_coordinator.PyodideGameCoordinator | None = None

# Player group manager for tracking player relationships across scenes
# Supports groups of any size (2 or more players)
GROUP_MANAGER: player_pairing_manager.PlayerGroupManager | None = None

# Mapping of users to locks associated with the ID. Enforces user-level serialization
USER_LOCKS = utils.ThreadSafeDict()


# Session ID to participant ID map
SESSION_ID_TO_SUBJECT_ID = utils.ThreadSafeDict()

# Participant session storage for session restoration after disconnect
# Maps subject_id -> ParticipantSession
PARTICIPANT_SESSIONS: dict[SubjectID, ParticipantSession] = utils.ThreadSafeDict()


def get_subject_id_from_session_id(session_id: str) -> SubjectID:
    subject_id = SESSION_ID_TO_SUBJECT_ID.get(session_id, None)
    return subject_id


# List of subject names that have entered a game (collected on end_game)
PROCESSED_SUBJECT_NAMES = []

# Number of games allowed
MAX_CONCURRENT_SESSIONS: int | None = 1

# Generate a unique identifier for the server session
SERVER_SESSION_ID = secrets.token_urlsafe(16)


#######################
# Flask Configuration #
#######################

app = flask.Flask(__name__, template_folder=os.path.join("static", "templates"))
app.config["SECRET_KEY"] = "secret!"

app.config["DEBUG"] = os.getenv("FLASK_ENV", "production") == "development"

socketio = flask_socketio.SocketIO(
    app,
    cors_allowed_origins="*",
    logger=app.config["DEBUG"],
    # engineio_logger=False,
)

#######################
# Flask Configuration #
#######################


@app.route("/")
def index(*args):
    """If no subject ID provided, generate a UUID and re-route them."""
    subject_id = str(uuid.uuid4())
    return flask.redirect(flask.url_for("user_index", subject_id=subject_id))


@app.route("/<subject_id>")
def user_index(subject_id):
    global STAGERS, SESSION_ID_TO_SUBJECT_ID, SUBJECTS, PARTICIPANT_SESSIONS

    if subject_id in PROCESSED_SUBJECT_NAMES:
        return (
            "Error: You have already completed the experiment with this ID!",
            404,
        )

    SUBJECTS[subject_id] = threading.Lock()

    # Check if this is a returning participant with a saved session
    existing_session = PARTICIPANT_SESSIONS.get(subject_id)
    if existing_session is not None and existing_session.stager_state is not None:
        # Returning participant - restore their stager from saved state
        logger.info(
            f"Returning participant detected: {subject_id}, "
            f"restoring session from scene index {existing_session.stager_state.get('current_scene_index')}"
        )
        participant_stager = GENERIC_STAGER.build_instance()
        participant_stager.set_state(existing_session.stager_state)
        STAGERS[subject_id] = participant_stager
    else:
        # New participant - create fresh stager
        participant_stager = GENERIC_STAGER.build_instance()
        STAGERS[subject_id] = participant_stager

        # Create initial session entry
        PARTICIPANT_SESSIONS[subject_id] = ParticipantSession(
            subject_id=subject_id,
            stager_state=None,
            interactive_gym_globals={"subjectName": subject_id},
            current_scene_id=None,
            socket_id=None,
            is_connected=False,
        )

    return flask.render_template(
        "index.html",
        async_mode=socketio.async_mode,
        subject_id=subject_id,
    )


@socketio.on("register_subject")
def register_subject(data):
    global SESSION_ID_TO_SUBJECT_ID, PARTICIPANT_SESSIONS
    """
    Ties the subject name in the URL to the flask request sid.

    Also handles session restoration for returning participants.
    Prevents multiple simultaneous connections from the same participant.
    """
    subject_id = data["subject_id"]
    sid = flask.request.sid
    flask.session["subject_id"] = subject_id

    # Check for existing active connection from this participant
    existing_session = PARTICIPANT_SESSIONS.get(subject_id)
    if existing_session is not None and existing_session.is_connected:
        old_socket_id = existing_session.socket_id
        if old_socket_id and old_socket_id != sid:
            logger.warning(
                f"Participant {subject_id} already has active connection {old_socket_id}. "
                f"Rejecting new connection {sid}."
            )
            # Emit error to the new connection and reject it
            flask_socketio.emit(
                "duplicate_session",
                {
                    "message": "You already have an active session open in another tab or window. "
                               "Please close this tab and return to your existing session."
                },
                room=sid,
            )
            return

    SESSION_ID_TO_SUBJECT_ID[sid] = subject_id
    logger.info(f"Registered session ID {sid} with subject {subject_id}")

    # Get client-sent interactiveGymGlobals (if any)
    client_globals = data.get("interactiveGymGlobals", {})

    # Send server session ID to client
    flask_socketio.emit(
        "server_session_id",
        {"session_id": SERVER_SESSION_ID},
        room=sid,
    )

    participant_stager = STAGERS.get(subject_id)
    if participant_stager is None:
        logger.error(f"No stager found for subject {subject_id} during registration")
        return

    # Check if this is a session restoration
    existing_session = PARTICIPANT_SESSIONS.get(subject_id)
    is_restored_session = (
        existing_session is not None
        and existing_session.stager_state is not None
    )

    if is_restored_session:
        # Returning participant - merge globals (server wins for conflicts)
        # Start with client globals, then overlay server-stored globals
        merged_globals = {**client_globals, **existing_session.interactive_gym_globals}

        # Update session state
        existing_session.socket_id = sid
        existing_session.is_connected = True
        existing_session.last_updated_at = time.time()
        existing_session.interactive_gym_globals = merged_globals

        logger.info(
            f"Session restored for {subject_id}, "
            f"scene index: {existing_session.stager_state.get('current_scene_index')}"
        )

        # Send session_restored event with server globals
        flask_socketio.emit(
            "session_restored",
            {
                "interactiveGymGlobals": merged_globals,
                "scene_id": existing_session.current_scene_id,
                "is_restored": True,
            },
            room=sid,
        )

        # Resume the stager at the current scene (instead of starting fresh)
        participant_stager.resume(socketio, room=sid)
    else:
        # New participant - normal start flow
        # Update session with client globals and connection info
        if existing_session is not None:
            existing_session.socket_id = sid
            existing_session.is_connected = True
            existing_session.last_updated_at = time.time()
            # Merge client globals into the session
            existing_session.interactive_gym_globals.update(client_globals)

        participant_stager.start(socketio, room=sid)

    participant_stager.current_scene.export_metadata(subject_id)


@socketio.on("sync_globals")
def sync_globals(data):
    """
    Receive and store interactiveGymGlobals from the client.

    This is called periodically by the client to keep the server-side
    session state in sync with client-side globals.
    """
    global PARTICIPANT_SESSIONS

    subject_id = get_subject_id_from_session_id(flask.request.sid)
    if subject_id is None:
        return

    client_globals = data.get("interactiveGymGlobals", {})
    session = PARTICIPANT_SESSIONS.get(subject_id)

    if session is not None:
        # Update the stored globals with client values
        session.interactive_gym_globals.update(client_globals)
        session.last_updated_at = time.time()
        logger.debug(f"Synced globals for {subject_id}: {list(client_globals.keys())}")


# @socketio.on("connect")
# def on_connect():
#     global SESSION_ID_TO_SUBJECT_ID

#     subject_id = get_subject_id_from_session_id(flask.request.sid)

#     if subject_id in SUBJECTS:
#         return

#     SUBJECTS[subject_id] = threading.Lock()

#     # TODO(chase): reenable session checkings
#     # Send the current server session ID to the client
#     # flask_socketio.emit(
#     #     "server_session_id",
#     #     {"server_session_id": SERVER_SESSION_ID},
#     #     room=subject_id,
#     # )


@socketio.on("advance_scene")
def advance_scene(data):
    global GAME_MANAGERS, PARTICIPANT_SESSIONS
    """Advance the scene to the next one."""
    subject_id = get_subject_id_from_session_id(flask.request.sid)

    participant_stager: stager.Stager | None = STAGERS.get(subject_id, None)
    if participant_stager is None:
        raise ValueError(f"No stager found for subject {subject_id}")
    participant_stager.advance(socketio, room=flask.request.sid)

    # If the current scene is a GymScene, we'll instantiate a
    # corresponding GameManager to handle game logic, connections,
    # and waiting rooms.
    current_scene = participant_stager.get_current_scene()
    logger.info(
        f"Advanced to scene: {current_scene.scene_id}. Metadata export: {current_scene.should_export_metadata}"
    )

    # Update session state with new scene position for session restoration
    session = PARTICIPANT_SESSIONS.get(subject_id)
    if session is not None:
        session.stager_state = participant_stager.get_state()
        session.current_scene_id = current_scene.scene_id if current_scene else None
        session.last_updated_at = time.time()
        logger.debug(
            f"Updated session state for {subject_id} after advance: "
            f"scene_index={session.stager_state.get('current_scene_index')}, "
            f"scene_id={session.current_scene_id}"
        )

    # Update the subject's current scene in the group manager
    if GROUP_MANAGER:
        GROUP_MANAGER.update_subject_scene(subject_id, current_scene.scene_id)
    if isinstance(current_scene, gym_scene.GymScene):
        # Only create a GameManager if one doesn't already exist for this scene
        if current_scene.scene_id not in GAME_MANAGERS:
            logger.info(
                f"Instantiating game manager for scene {current_scene.scene_id}"
            )
            game_manager = gm.GameManager(
                scene=current_scene,
                experiment_config=CONFIG,
                sio=socketio,
                pyodide_coordinator=PYODIDE_COORDINATOR,
                pairing_manager=GROUP_MANAGER,
            )
            GAME_MANAGERS[current_scene.scene_id] = game_manager
        else:
            logger.info(
                f"Game manager already exists for scene {current_scene.scene_id}, reusing it"
            )

    if current_scene.should_export_metadata:
        current_scene.export_metadata(subject_id)


@socketio.on("join_game")
def join_game(data):

    subject_id = get_subject_id_from_session_id(flask.request.sid)
    client_session_id = data.get("session_id")  # Client sends "session_id"

    # Validate session
    # if not is_valid_session(client_session_id, subject_id, "join_game"):
    #     return

    with SUBJECTS[subject_id]:

        # If the participant doesn't have a Stager, something is wrong at this point.
        participant_stager = STAGERS.get(subject_id, None)
        if participant_stager is None:
            logger.error(
                f"Subject {subject_id} tried to join a game but they don't have a stager."
            )
            return

        # Get the current scene and game manager to determine where to send the participant
        current_scene = participant_stager.current_scene
        game_manager = GAME_MANAGERS.get(current_scene.scene_id, None)

        if game_manager is None:
            logger.error(
                f"Subject {subject_id} tried to join a game but no game manager was found for scene {current_scene.scene_id}."
            )
            return

        # Check if the participant is already in a game in this scene, they should not be.
        if game_manager.subject_in_game(subject_id):
            logger.error(
                f"Subject {subject_id} in a game in scene {current_scene.scene_id} but attempted to join another."
            )
            return

        game = game_manager.add_subject_to_game(subject_id)
        logger.info(
            f"Successfully added subject {subject_id} to game {game.game_id}."
        )


def is_valid_session(
    client_session_id: str, subject_id: SubjectID, context: str
) -> bool:
    valid_session = client_session_id == SERVER_SESSION_ID

    if not valid_session:
        logger.warning(
            f"Invalid session for {subject_id} in {context}. Got {client_session_id} but expected {SERVER_SESSION_ID}"
        )
        flask_socketio.emit(
            "invalid_session",
            {"message": "Session is invalid. Please reconnect."},
            room=flask.request.sid,
        )

    return valid_session


@socketio.on("leave_game")
def leave_game(data):
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    logger.info(f"Participant {subject_id} leaving game.")

    # Validate session
    client_reported_session_id = data.get("session_id")
    # if not is_valid_session(
    #     client_reported_session_id, subject_id, "leave_game"
    # ):
    #     return

    with SUBJECTS[subject_id]:
        # If the participant doesn't have a Stager, something is wrong at this point.
        participant_stager = STAGERS.get(subject_id, None)
        if participant_stager is None:
            logger.error(
                f"Subject {subject_id} tried to leave a game but they don't have a stager."
            )
            return

        # Get the current scene and game manager to determine where to send the participant
        current_scene = participant_stager.current_scene
        game_manager = GAME_MANAGERS.get(current_scene.scene_id, None)

        game_manager.leave_game(subject_id=subject_id)
        PROCESSED_SUBJECT_NAMES.append(subject_id)


# @socketio.on("disconnect")
# def on_disconnect():
#     global SUBJECTS
#     subject_id = get_subject_id_from_session_id(flask.request.sid)

#     participant_stager = STAGERS.get(subject_id, None)
#     if participant_stager is None:
#         logger.error(
#             f"Subject {subject_id} tried to join a game but they don't have a Stager."
#         )
#         return

#     current_scene = participant_stager.current_scene
#     game_manager = GAME_MANAGERS.get(current_scene.scene_id, None)

#     # Get the current game for the participant, if any.
#     game = game_manager.get_subject_game(subject_id)

#     if game is None:
#         logger.info(
#             f"Subject {subject_id} disconnected with no coresponding game."
#         )
#     else:
#         logger.info(
#             f"Subject {subject_id} disconnected, Game ID: {game.game_id}.",
#         )

#     with SUBJECTS[subject_id]:
#         game_manager.leave_game(subject_id=subject_id)

#     del SUBJECTS[subject_id]
#     if subject_id in SUBJECTS:
#         logger.warning(
#             f"Tried to remove {subject_id} but it's still in SUBJECTS."
#         )


@socketio.on("send_pressed_keys")
def send_pressed_keys(data):
    """
    Translate pressed keys into game action and add them to the pending_actions queue.
    """
    # return
    # sess_id = flask.request.sid
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    # Fallback to flask.session if needed
    if subject_id is None:
        subject_id = flask.session.get("subject_id")

    # Skip if no subject_id (can happen in Pyodide games that don't use pressed keys)
    if subject_id is None:
        return

    # # TODO(chase): figure out why we're getting a different session ID here...
    participant_stager = STAGERS.get(subject_id, None)
    if participant_stager is None:
        logger.warning(
            f"Pressed keys requested for {subject_id} but they don't have a Stager."
        )
        return

    current_scene = participant_stager.current_scene
    game_manager = GAME_MANAGERS.get(current_scene.scene_id, None)
    # game = game_manager.get_subject_game(subject_id)

    client_reported_server_session_id = data.get("server_session_id")
    # print(client_reported_server_session_id, "send_pressed_keys")
    # print(sess_id, subject_id, "send_pressed_keys")
    # if not is_valid_session(
    #     client_reported_server_session_id, subject_id, "send_pressed_keys"
    # ):
    #     return

    pressed_keys = data["pressed_keys"]

    game_manager.process_pressed_keys(
        subject_id=subject_id, pressed_keys=pressed_keys
    )


@socketio.on("reset_complete")
def handle_reset_complete(data):
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    client_session_id = data.get("session_id")

    # if not is_valid_session(client_session_id, subject_id, "reset_complete"):
    #     return

    participant_stager = STAGERS.get(subject_id, None)
    game_manager = GAME_MANAGERS.get(
        participant_stager.current_scene.scene_id, None
    )

    game_manager.trigger_reset(subject_id)


@socketio.on("ping")
def pong(data):
    socketio.emit(
        "pong",
        {
            "max_latency": CONFIG.max_ping,
            "min_ping_measurements": CONFIG.min_ping_measurements,
        },
        room=flask.request.sid,
    )

    # TODO(chase): when data tracking is reimplemented, we'll want to track the ping/focus status here.
    # also track if the user isn't focused on their window.
    # game = _get_existing_game(sid)
    # if game is None:
    #     return

    # document_in_focus = data["document_in_focus"]
    # ping_ms = data["ping_ms"]
    # player_name = SUBJECT_ID_MAP[sid]
    # game.update_ping(
    #     player_identifier=player_name,
    #     hidden_status=document_in_focus,
    #     ping=ping_ms,
    # )


@socketio.on("unityEpisodeEnd")
def on_unity_episode_end(data):
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    participant_stager = STAGERS.get(subject_id, None)
    current_scene = participant_stager.current_scene

    if not isinstance(current_scene, unity_scene.UnityScene):
        return

    current_scene.on_unity_episode_end(
        data,
        sio=socketio,
        room=flask.request.sid,
    )

    # (Potentially) save the data
    scene_id = current_scene.scene_id
    cur_episode = current_scene.episodes_completed
    wrapped_data = {}
    wrapped_data["scene_id"] = f"{scene_id}_{cur_episode}"
    wrapped_data["data"] = data

    # TODO(chase): Make sure the globals are propagated here
    # so we don't have to fill it.
    wrapped_data["interactiveGymGlobals"] = {}

    data_emission(wrapped_data)


@socketio.on("unityEpisodeStart")
def on_unity_episode_start(data):


    subject_id = get_subject_id_from_session_id(flask.request.sid)
    participant_stager = STAGERS.get(subject_id, None)
    current_scene = participant_stager.current_scene



    if not isinstance(current_scene, unity_scene.UnityScene):
        return

    current_scene.on_unity_episode_start(
        data,
        sio=socketio,
        room=flask.request.sid,
    )


@socketio.on("request_redirect")
def on_request_redirect(data):
    waitroom_timeout = data.get("waitroom_timeout", False)
    if waitroom_timeout:
        redirect_url = CONFIG.waitroom_timeout_redirect_url
    else:
        redirect_url = CONFIG.experiment_end_redirect_url

    if CONFIG.append_subject_id_to_redirect:
        redirect_url += get_subject_id_from_session_id(flask.request.sid)

    socketio.emit(
        "redirect",
        {
            "redirect_url": redirect_url,
            "redirect_timeout": CONFIG.redirect_timeout,
        },
        room=flask.request.sid,
    )


@socketio.on("client_callback")
def on_client_callback(data):
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    participant_stager = STAGERS.get(subject_id, None)
    if participant_stager is None:
        logger.error(
            f"Client callback requested for {subject_id} but they don't have a Stager."
        )
        return

    current_scene = participant_stager.current_scene
    current_scene.on_client_callback(data, sio=socketio, room=flask.request.sid)


def on_exit():
    # Force-terminate all games on server termination
    for game_manager in GAME_MANAGERS.values():
        game_manager.tear_down()

    for game_manager in GAME_MANAGERS.values():
        game_manager.tear_down()


@socketio.on("static_scene_data_emission")
def data_emission(data):
    """Save the static scene data to a csv file."""
    global PARTICIPANT_SESSIONS

    subject_id = get_subject_id_from_session_id(flask.request.sid)

    # Sync interactiveGymGlobals to session for persistence
    client_globals = data.get("interactiveGymGlobals", {})
    session = PARTICIPANT_SESSIONS.get(subject_id)
    if session is not None and client_globals:
        session.interactive_gym_globals.update(client_globals)
        session.last_updated_at = time.time()

    if not CONFIG.save_experiment_data:
        return

    # Save to a csv in data/{scene_id}/{subject_id}.csv
    # Save the static scene data to a csv file.
    scene_id = data.get("scene_id")
    if not scene_id:
        logger.error("Scene ID is required to save data.")
        return

    # Create a directory for the CSV files if it doesn't exist
    os.makedirs(f"data/{scene_id}/", exist_ok=True)

    # Generate a unique filename
    filename = f"data/{scene_id}/{subject_id}.csv"
    globals_filename = f"data/{scene_id}/{subject_id}_globals.json"

    # Save as CSV
    logger.info(f"Saving {filename}")

    # convert to a list so we can save it as a csv
    for k, v in data["data"].items():
        data["data"][k] = [v]

    df = pd.DataFrame(data["data"])

    df["timestamp"] = pd.to_datetime("now")

    if CONFIG.save_experiment_data:
        df.to_csv(filename, index=False)

        with open(globals_filename, "w") as f:
            json.dump(data["interactiveGymGlobals"], f)


@socketio.on("emit_remote_game_data")
def receive_remote_game_data(data):
    global PARTICIPANT_SESSIONS

    subject_id = get_subject_id_from_session_id(flask.request.sid)

    # Sync interactiveGymGlobals to session for persistence
    client_globals = data.get("interactiveGymGlobals", {})
    session = PARTICIPANT_SESSIONS.get(subject_id)
    if session is not None and client_globals:
        session.interactive_gym_globals.update(client_globals)
        session.last_updated_at = time.time()

    if not CONFIG.save_experiment_data:
        return

    # Decode the msgpack data
    decoded_data = msgpack.unpackb(data["data"])

    # Flatten any nested dictionaries
    flattened_data = flatten_dict.flatten(decoded_data, reducer="dot")

    # Find the maximum length among all values
    max_length = max(
        len(value) if isinstance(value, list) else 1
        for value in flattened_data.values()
    )

    # Pad shorter lists with None and convert non-list values to lists
    padded_data = {}
    for key, value in flattened_data.items():
        if not isinstance(value, list):
            padded_data[key] = [value] + [None] * (max_length - 1)
        else:
            padded_data[key] = value + [None] * (max_length - len(value))

    # Convert to DataFrame
    df = pd.DataFrame(padded_data)

    # Create a directory for the CSV files if it doesn't exist
    os.makedirs(f"data/{data['scene_id']}/", exist_ok=True)

    # Generate a unique filename
    filename = f"data/{data['scene_id']}/{subject_id}.csv"
    globals_filename = f"data/{data['scene_id']}/{subject_id}_globals.json"

    # Save as CSV
    logger.info(f"Saving {filename}")

    if CONFIG.save_experiment_data:
        df.to_csv(filename, index=False)
        with open(globals_filename, "w") as f:
            json.dump(data["interactiveGymGlobals"], f)

    # Also get the current scene for this participant and save the metadata
    # TODO(chase): this has issues where the data may not be received before the
    # scene is advanced, which results in this getting the metadata for the _next_
    # scene.

    # participant_stager = STAGERS.get(subject_id, None)
    # if participant_stager is None:
    #     logger.error(
    #         f"Subject {subject_id} tried to save data but they don't have a Stager."
    #     )
    #     return

    # current_scene = participant_stager.current_scene
    # current_scene_metadata = current_scene.get_complete_scene_metadata()

    # # save the metadata to a json file
    # with open(f"data/{data['scene_id']}/{subject_id}_metadata.json", "w") as f:
    #     json.dump(current_scene_metadata, f)


#####################################
# Pyodide Multiplayer Event Handlers
#####################################


@socketio.on("pyodide_player_action")
def on_pyodide_player_action(data):
    """
    Receive action from a player in a Pyodide multiplayer game.

    The coordinator collects actions from all players and broadcasts
    when all actions are received for the current frame.

    Args:
        data: {
            'game_id': str,
            'player_id': str | int,
            'action': Any (int, dict, etc.),
            'frame_number': int,
            'timestamp': float
        }
    """
    global PYODIDE_COORDINATOR

    if PYODIDE_COORDINATOR is None:
        logger.error("Pyodide coordinator not initialized")
        return

    game_id = data.get("game_id")
    player_id = data.get("player_id")
    action = data.get("action")
    frame_number = data.get("frame_number")

    # logger.debug(
    #     f"Received action from player {player_id} in game {game_id} "
    #     f"for frame {frame_number}: {action}"
    # )

    PYODIDE_COORDINATOR.receive_action(
        game_id=game_id,
        player_id=player_id,
        action=action,
        frame_number=frame_number
    )


@socketio.on("pyodide_hud_update")
def on_pyodide_hud_update(data):
    """
    Receive HUD text from host and broadcast to all players in the game.

    This ensures HUD stays synchronized across all clients, even after
    state resyncs where local HUD computation might diverge.

    Args:
        data: {
            'game_id': str,
            'hud_text': str
        }
    """
    game_id = data.get("game_id")
    hud_text = data.get("hud_text")

    # Broadcast to all players in the game room (including sender for consistency)
    socketio.emit(
        "pyodide_hud_sync",
        {"hud_text": hud_text},
        room=game_id
    )


@socketio.on("pyodide_state_hash")
def on_pyodide_state_hash(data):
    """
    Receive state hash from a player for verification.

    The coordinator collects hashes from all players and verifies
    they match (detecting desyncs).

    In server-authoritative mode, state hashes are ignored since
    the server broadcasts authoritative state instead.

    Args:
        data: {
            'game_id': str,
            'player_id': str | int,
            'hash': str (SHA256 hex),
            'frame_number': int
        }
    """
    global PYODIDE_COORDINATOR

    if PYODIDE_COORDINATOR is None:
        logger.error("Pyodide coordinator not initialized")
        return

    game_id = data.get("game_id")
    player_id = data.get("player_id")
    state_hash = data.get("hash")
    frame_number = data.get("frame_number")

    # Skip early if game is in server-authoritative mode
    game = PYODIDE_COORDINATOR.games.get(game_id)
    if game and game.server_authoritative:
        logger.debug(
            f"Ignoring state hash from player {player_id} in game {game_id} "
            f"(server-authoritative mode)"
        )
        return

    logger.debug(
        f"Received state hash from player {player_id} in game {game_id} "
        f"for frame {frame_number}: {state_hash[:8]}..."
    )

    PYODIDE_COORDINATOR.receive_state_hash(
        game_id=game_id,
        player_id=player_id,
        state_hash=state_hash,
        frame_number=frame_number
    )


@socketio.on("pyodide_send_full_state")
def on_pyodide_send_full_state(data):
    """
    Receive full state from host for resync after desync.

    Host sends serialized game state which is broadcast to
    non-host clients to restore synchronization.

    Args:
        data: {
            'game_id': str,
            'state': dict (serialized game state from host)
        }
    """
    global PYODIDE_COORDINATOR

    if PYODIDE_COORDINATOR is None:
        logger.error("Pyodide coordinator not initialized")
        return

    game_id = data.get("game_id")
    full_state = data.get("state")

    logger.info(f"Received full state from host for game {game_id}")

    PYODIDE_COORDINATOR.receive_full_state(
        game_id=game_id,
        full_state=full_state
    )


@socketio.on("disconnect")
def on_disconnect():
    """
    Handle player disconnection.

    For Pyodide multiplayer games: If host disconnects, elect new host and trigger resync.
    For regular games: Notify remaining players and clean up the game.
    If all players disconnect, remove game.

    Scene-aware disconnect handling:
    - Only notify group members if they're in the same active game
    - If player is in a different scene (e.g., survey), remove quietly without notification

    Session persistence:
    - Saves stager state and interactiveGymGlobals to PARTICIPANT_SESSIONS
    - Allows session restoration if participant reconnects with same URL
    """
    global PYODIDE_COORDINATOR, GROUP_MANAGER, PARTICIPANT_SESSIONS

    subject_id = get_subject_id_from_session_id(flask.request.sid)
    logger.info(f"Disconnect event received for socket {flask.request.sid}, subject_id: {subject_id}")

    if subject_id is None:
        logger.info("No subject_id found for disconnecting socket")
        return

    participant_stager = STAGERS.get(subject_id, None)
    if participant_stager is None:
        logger.info(f"No stager found for subject {subject_id}")
        # Still clean up group manager
        if GROUP_MANAGER:
            GROUP_MANAGER.cleanup_subject(subject_id)
        return

    current_scene = participant_stager.current_scene
    logger.info(f"Subject {subject_id} disconnected, current scene: {current_scene.scene_id if current_scene else 'None'}")

    # Save session state for potential reconnection
    session = PARTICIPANT_SESSIONS.get(subject_id)
    if session is not None:
        session.stager_state = participant_stager.get_state()
        session.current_scene_id = current_scene.scene_id if current_scene else None
        session.socket_id = None
        session.is_connected = False
        session.last_updated_at = time.time()
        logger.info(
            f"Saved session state for {subject_id}: "
            f"scene_index={session.stager_state.get('current_scene_index')}, "
            f"scene_id={session.current_scene_id}"
        )

    # Check if this is a GymScene and if player is in an active game
    is_in_active_gym_scene = False
    if isinstance(current_scene, gym_scene.GymScene):
        game_manager = GAME_MANAGERS.get(current_scene.scene_id, None)
        if game_manager and game_manager.is_subject_in_active_game(subject_id):
            is_in_active_gym_scene = True
        # Also check if player is in a group waitroom
        if game_manager:
            game_manager.remove_from_group_waitroom(subject_id)

    # Handle Pyodide multiplayer games
    if PYODIDE_COORDINATOR is not None:
        # Iterate through all games to find this player
        for game_id, game_state in list(PYODIDE_COORDINATOR.games.items()):
            for player_id, socket_id in game_state.players.items():
                if socket_id == flask.request.sid:
                    logger.info(
                        f"Player {player_id} (subject {subject_id}) disconnected "
                        f"from Pyodide game {game_id}"
                    )
                    # Only notify others if player was in an active game scene
                    PYODIDE_COORDINATOR.remove_player(
                        game_id=game_id,
                        player_id=player_id,
                        notify_others=is_in_active_gym_scene
                    )
                    # Clean up group manager
                    if GROUP_MANAGER:
                        GROUP_MANAGER.cleanup_subject(subject_id)
                    return

    # Handle regular (non-Pyodide) games via GameManager
    # First try the current scene's game manager
    game_manager = GAME_MANAGERS.get(current_scene.scene_id, None) if current_scene else None

    # If not found or subject not in that game, search all game managers
    if game_manager is None or not game_manager.subject_in_game(subject_id):
        logger.info(f"Subject {subject_id} not found in current scene's game manager, searching all managers...")
        for scene_id, gm_instance in GAME_MANAGERS.items():
            if gm_instance.subject_in_game(subject_id):
                game_manager = gm_instance
                logger.info(f"Found subject {subject_id} in game manager for scene {scene_id}")
                break

    if game_manager is None:
        logger.info(
            f"Subject {subject_id} disconnected but no game manager found"
        )
        # Clean up group manager
        if GROUP_MANAGER:
            GROUP_MANAGER.cleanup_subject(subject_id)
        return

    # Check if the subject is in a game
    if not game_manager.subject_in_game(subject_id):
        logger.info(
            f"Subject {subject_id} disconnected with no corresponding game."
        )
        # Clean up group manager
        if GROUP_MANAGER:
            GROUP_MANAGER.cleanup_subject(subject_id)
        return

    # Determine whether to notify group members or remove quietly
    if is_in_active_gym_scene:
        logger.info(
            f"Subject {subject_id} disconnected from active game, triggering leave_game."
        )
        game_manager.leave_game(subject_id=subject_id)
    else:
        # Subject is not in an active game scene (e.g., in a survey)
        # Remove quietly without notifying group members
        logger.info(
            f"Subject {subject_id} disconnected from non-active scene, removing quietly."
        )
        game_manager.remove_subject_quietly(subject_id)

    # Clean up group manager
    if GROUP_MANAGER:
        GROUP_MANAGER.cleanup_subject(subject_id)


def run(config):
    global app, CONFIG, logger, GENERIC_STAGER, PYODIDE_COORDINATOR, GROUP_MANAGER
    CONFIG = config
    GENERIC_STAGER = config.stager

    # Initialize Pyodide coordinator
    PYODIDE_COORDINATOR = pyodide_game_coordinator.PyodideGameCoordinator(socketio)
    logger.info("Initialized Pyodide multiplayer coordinator")

    # Initialize player group manager
    GROUP_MANAGER = player_pairing_manager.PlayerGroupManager()
    logger.info("Initialized player group manager")

    atexit.register(on_exit)



    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "unavailable"

    try:
        public_ip = urllib.request.urlopen("https://api.ipify.org", timeout=3).read().decode()
    except Exception:
        public_ip = "unavailable"

    print("\n" + "="*70)
    print(f"Experiment {config.experiment_id}")
    print("="*70)
    print(f"\nServer starting on:")
    print(f"  Local:   http://localhost:{config.port}")
    print(f"  Network: http://{local_ip}:{config.port}")
    print(f"  Public (if accessible):  http://{public_ip}:{config.port}")
    print("="*70 + "\n")


    socketio.run(
        app,
        log_output=app.config["DEBUG"],
        port=CONFIG.port,
        host=CONFIG.host,
    )
