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

from flask_login import LoginManager
from interactive_gym.server.admin import admin_bp, AdminUser
from interactive_gym.server.admin.namespace import AdminNamespace
from interactive_gym.server.admin.aggregator import AdminEventAggregator


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
    current_rtt: int | None = None  # Current RTT measurement in ms (for matchmaking)


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

# Admin event aggregator for dashboard state collection
ADMIN_AGGREGATOR: AdminEventAggregator | None = None

# Mapping of users to locks associated with the ID. Enforces user-level serialization
USER_LOCKS = utils.ThreadSafeDict()


# Session ID to participant ID map
SESSION_ID_TO_SUBJECT_ID = utils.ThreadSafeDict()

# Participant session storage for session restoration after disconnect
# Maps subject_id -> ParticipantSession
PARTICIPANT_SESSIONS: dict[SubjectID, ParticipantSession] = utils.ThreadSafeDict()

# Pending multiplayer metrics for aggregation
# Maps (scene_id, game_id) -> {player_id: metrics, ...}
# When both players submit, metrics are aggregated into a comparison file
PENDING_MULTIPLAYER_METRICS: dict[tuple[str, str], dict] = utils.ThreadSafeDict()


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
    # More aggressive ping settings for faster disconnect detection
    ping_interval=2,  # Ping every 2 seconds (default: 25)
    ping_timeout=2,   # Wait 2 seconds for pong before disconnect (default: 5)
)

# Flask-Login setup for admin authentication
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin.login'
login_manager.login_message = 'Please log in to access the admin dashboard.'


@login_manager.user_loader
def load_user(user_id):
    if user_id == 'admin':
        return AdminUser(user_id)
    return None


# Register admin blueprint
app.register_blueprint(admin_bp)

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

    # Ignore browser resource requests that get captured by this route
    if subject_id in ("favicon.ico", "robots.txt", "apple-touch-icon.png"):
        return "", 404

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

        # Track session start for admin dashboard stats
        if ADMIN_AGGREGATOR:
            ADMIN_AGGREGATOR.track_session_start(subject_id)

    return flask.render_template(
        "index.html",
        async_mode=socketio.async_mode,
        subject_id=subject_id,
    )


@app.route("/partner-disconnected")
def partner_disconnected():
    """Page shown when a participant's partner disconnects mid-experiment."""
    return flask.render_template("partner_disconnected.html")


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

    # Log activity for admin dashboard
    if ADMIN_AGGREGATOR:
        ADMIN_AGGREGATOR.log_activity("join", subject_id, {"socket_id": sid})

    # Get client-sent interactiveGymGlobals (if any)
    client_globals = data.get("interactiveGymGlobals", {})

    # Send server session ID to client
    flask_socketio.emit(
        "server_session_id",
        {"session_id": SERVER_SESSION_ID},
        room=sid,
    )

    # Send experiment-level entry screening config to client
    if CONFIG is not None:
        flask_socketio.emit(
            "experiment_config",
            {"entry_screening": CONFIG.get_entry_screening_config()},
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


@socketio.on("request_current_scene")
def request_current_scene(data):
    """
    Re-send the current scene activation to the client.

    This is called when the client completed entry screening but didn't receive
    the activate_scene event (race condition during initial connection).
    """
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    if subject_id is None:
        logger.warning("request_current_scene called but no subject_id found")
        return

    participant_stager = STAGERS.get(subject_id)
    if participant_stager is None:
        logger.error(f"No stager found for subject {subject_id} during request_current_scene")
        return

    logger.info(f"[RequestCurrentScene] Re-sending activate_scene for subject {subject_id}")
    participant_stager.current_scene.activate(socketio, room=flask.request.sid)


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


def _get_subject_rtt(subject_id: str) -> int | None:
    """Get the current RTT measurement for a subject.

    Used by GameManager for RTT-based matchmaking.
    """
    session = PARTICIPANT_SESSIONS.get(subject_id)
    if session is not None:
        return session.current_rtt
    return None


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

    # Log activity for admin dashboard
    if ADMIN_AGGREGATOR:
        ADMIN_AGGREGATOR.log_activity("scene_advance", subject_id, {"scene_id": current_scene.scene_id})

        # Record session completion if participant just reached the final scene
        current_index = participant_stager.current_scene_index
        total_scenes = len(participant_stager.scenes)
        if current_index >= total_scenes - 1:
            session = PARTICIPANT_SESSIONS.get(subject_id)
            if session and subject_id not in ADMIN_AGGREGATOR._completed_sessions:
                ADMIN_AGGREGATOR.record_session_completion(
                    subject_id=subject_id,
                    started_at=session.created_at,
                    completed_at=time.time()
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
                get_subject_rtt=_get_subject_rtt,
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

    # Validate subject_id exists
    if subject_id is None:
        logger.error(
            f"join_game called but no subject_id found for session {flask.request.sid}"
        )
        socketio.emit(
            "join_game_error",
            {"message": "Session not found. Please refresh the page."},
            room=flask.request.sid,
        )
        return

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
            socketio.emit(
                "join_game_error",
                {"message": "Session state not found. Please refresh the page."},
                room=flask.request.sid,
            )
            return

        # Get the current scene and game manager to determine where to send the participant
        current_scene = participant_stager.current_scene
        game_manager = GAME_MANAGERS.get(current_scene.scene_id, None)

        if game_manager is None:
            logger.error(
                f"Subject {subject_id} tried to join a game but no game manager was found for scene {current_scene.scene_id}."
            )
            socketio.emit(
                "join_game_error",
                {"message": "Game not available. Please refresh the page."},
                room=flask.request.sid,
            )
            return

        # Check if the participant is already in a game in this scene.
        # This can happen if a previous session didn't clean up properly (browser crash, network issue, etc.)
        if game_manager.subject_in_game(subject_id):
            logger.warning(
                f"Subject {subject_id} already has a game entry in scene {current_scene.scene_id}. "
                f"Cleaning up stale entry before rejoining."
            )
            # Clean up the stale entry so they can rejoin
            game_manager.remove_subject_quietly(subject_id)

        logger.info(
            f"[JoinGame] Subject {subject_id} clicked start button for scene {current_scene.scene_id}. "
            f"Attempting to add to game..."
        )

        try:
            game = game_manager.add_subject_to_game(subject_id)
            if game is not None:
                logger.info(
                    f"[JoinGame] Subject {subject_id} successfully added to game {game.game_id}. "
                    f"Game starting."
                )
            else:
                # game is None when waiting for group members or in waiting room
                logger.info(
                    f"[JoinGame] Subject {subject_id} added to waiting room for scene {current_scene.scene_id}. "
                    f"Waiting for more players."
                )
        except Exception as e:
            logger.exception(
                f"[JoinGame] Error adding subject {subject_id} to game: {e}"
            )
            socketio.emit(
                "join_game_error",
                {"message": "Failed to join game. Please try again."},
                room=flask.request.sid,
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
    logger.info(f"[LeaveGame] Subject {subject_id} leaving game (likely waitroom timeout or disconnect).")

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

        # Record session completion for admin dashboard stats
        if ADMIN_AGGREGATOR:
            session = PARTICIPANT_SESSIONS.get(subject_id)
            if session:
                ADMIN_AGGREGATOR.record_session_completion(
                    subject_id=subject_id,
                    started_at=session.created_at,
                    completed_at=time.time()
                )
            # Close console log file for completed subject
            ADMIN_AGGREGATOR.close_subject_console_log(subject_id)


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

    # Store RTT for matchmaking purposes
    ping_ms = data.get("ping_ms")
    if ping_ms is not None:
        session_id = flask.request.sid
        subject_id = get_subject_id_from_session_id(session_id)
        if subject_id and subject_id in PARTICIPANT_SESSIONS:
            PARTICIPANT_SESSIONS[subject_id].current_rtt = ping_ms


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


@socketio.on("waitroom_timeout_completion")
def on_waitroom_timeout_completion(data):
    """Log completion code when a participant times out in the waitroom."""
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    completion_code = data.get("completion_code")
    reason = data.get("reason", "waitroom_timeout")

    logger.info(
        f"[WaitroomTimeout] Subject {subject_id} waitroom timed out. "
        f"Completion code: {completion_code}, Reason: {reason}"
    )

    # Save completion code to file if data saving is enabled
    if CONFIG.save_experiment_data:
        completion_data = {
            "subject_id": subject_id,
            "completion_code": completion_code,
            "reason": reason,
            "timestamp": time.time(),
        }

        # Save to data/completion_codes/{subject_id}.json
        completion_dir = os.path.join("data", "completion_codes")
        os.makedirs(completion_dir, exist_ok=True)
        filepath = os.path.join(completion_dir, f"{subject_id}.json")

        with open(filepath, "w") as f:
            json.dump(completion_data, f, indent=2)

        logger.info(f"Saved completion code to {filepath}")


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

    # Check if there's any data to save (may be empty if data was sent per-episode)
    if not decoded_data or not decoded_data.get("t"):
        logger.info(f"No final data to save for scene {data.get('scene_id')} (data was sent per-episode)")
        return

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


@socketio.on("emit_episode_data")
def receive_episode_data(data):
    """
    Receive and save episode data incrementally during gameplay.

    This is called at the end of each episode to send data in manageable chunks,
    avoiding large payloads that can fail to transmit at scene end.

    Data includes:
    - episode_num: The episode number (0-indexed)
    - scene_id: The scene ID for file organization
    - data: msgpack-encoded game data (observations, actions, rewards, etc.)
    """
    global PARTICIPANT_SESSIONS

    subject_id = get_subject_id_from_session_id(flask.request.sid)
    episode_num = data.get("episode_num", 0)

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

    # Check if there's any data to save
    if not decoded_data or not decoded_data.get("t"):
        logger.info(f"No data to save for episode {episode_num}")
        return

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

    # Generate filename with episode number
    filename = f"data/{data['scene_id']}/{subject_id}_ep{episode_num}.csv"

    # Save as CSV
    logger.info(f"Saving episode {episode_num} data: {filename} ({len(df)} rows)")

    df.to_csv(filename, index=False)

    # Also save globals (overwrite each episode to keep latest)
    globals_filename = f"data/{data['scene_id']}/{subject_id}_globals.json"
    with open(globals_filename, "w") as f:
        json.dump(data.get("interactiveGymGlobals", {}), f)


@socketio.on("emit_multiplayer_metrics")
def receive_multiplayer_metrics(data):
    """
    Receive and save multiplayer validation metrics from client.

    Data includes:
    - Session/connection info (gameId, playerId, P2P connection type/health)
    - Sync validation data (frame hashes, verified frames, desync events)
    - Input delivery stats (P2P vs SocketIO counts)
    - Rollback metrics

    Saved as JSON file per subject per scene for research analysis.
    When both players in a game submit, creates aggregated comparison file.
    """
    global PARTICIPANT_SESSIONS, PENDING_MULTIPLAYER_METRICS

    subject_id = get_subject_id_from_session_id(flask.request.sid)

    if not CONFIG.save_experiment_data:
        return

    scene_id = data.get("scene_id")
    metrics = data.get("metrics")

    if not scene_id or not metrics:
        logger.warning(f"Invalid multiplayer metrics data from {subject_id}")
        return

    # Create directory if needed
    os.makedirs(f"data/{scene_id}/", exist_ok=True)

    # Save individual player's metrics
    filename = f"data/{scene_id}/{subject_id}_multiplayer_metrics.json"
    logger.info(f"Saving multiplayer metrics to {filename}")
    with open(filename, "w") as f:
        json.dump(metrics, f, indent=2)

    # Aggregate metrics when both players submit
    game_id = metrics.get("gameId")
    player_id = metrics.get("playerId")

    if game_id and player_id:
        key = (scene_id, game_id)

        # Store this player's metrics
        if key not in PENDING_MULTIPLAYER_METRICS:
            PENDING_MULTIPLAYER_METRICS[key] = {}

        PENDING_MULTIPLAYER_METRICS[key][player_id] = {
            "subjectId": subject_id,
            "metrics": metrics
        }

        # Check if we have metrics from both players
        pending = PENDING_MULTIPLAYER_METRICS[key]
        if len(pending) >= 2:
            # Both players submitted - create aggregated comparison file
            _create_aggregated_metrics(scene_id, game_id, pending)
            # Clean up pending storage
            del PENDING_MULTIPLAYER_METRICS[key]


@socketio.on("client_console_log")
def on_client_console_log(data):
    """
    Receive console log from participant browser for admin dashboard.

    Args:
        data: {
            'level': str (log, info, warn, error),
            'message': str,
            'timestamp': float (optional, Unix timestamp)
        }
    """
    global ADMIN_AGGREGATOR

    subject_id = get_subject_id_from_session_id(flask.request.sid)
    if subject_id is None:
        return

    if ADMIN_AGGREGATOR:
        ADMIN_AGGREGATOR.receive_console_log(
            subject_id=subject_id,
            level=data.get("level", "log"),
            message=data.get("message", ""),
            timestamp=data.get("timestamp")
        )


def _create_aggregated_metrics(scene_id: str, game_id: str, player_metrics: dict):
    """
    Create aggregated comparison file from both players' metrics.

    Combines:
    - Both players' hashes for frame-by-frame comparison
    - Both players' actions for frame-by-frame comparison
    - Both players' episode summaries
    - Desync events from both perspectives
    - Summary statistics for quick verification
    """
    players = list(player_metrics.keys())
    if len(players) < 2:
        logger.warning(f"Cannot aggregate metrics: only {len(players)} player(s)")
        return

    player_a_id = players[0]
    player_b_id = players[1]
    player_a = player_metrics[player_a_id]
    player_b = player_metrics[player_b_id]

    metrics_a = player_a["metrics"]
    metrics_b = player_b["metrics"]

    # Build hash comparison
    hash_comparison = _compare_hashes(
        metrics_a.get("validation", {}).get("allHashes", []),
        metrics_b.get("validation", {}).get("allHashes", []),
        player_a_id,
        player_b_id
    )

    # Build action comparison
    action_comparison = _compare_actions(
        metrics_a.get("validation", {}).get("allActions", []),
        metrics_b.get("validation", {}).get("allActions", []),
        player_a_id,
        player_b_id
    )

    # Compute top-level summary
    hashes_match = hash_comparison["mismatchingFrames"] == 0 and hash_comparison["matchingFrames"] > 0
    actions_match = action_comparison["mismatchingFrames"] == 0 and action_comparison["matchingFrames"] > 0
    fully_synced = hashes_match and actions_match

    # Get first mismatch frames
    first_hash_mismatch = _get_first_mismatch_frame(hash_comparison["frames"])
    first_action_mismatch = _get_first_mismatch_frame(action_comparison["frames"])

    # Get all divergence frames
    hash_divergence_frames = _get_divergence_frames(hash_comparison["frames"])
    action_divergence_frames = _get_divergence_frames(action_comparison["frames"])

    # Build aggregated structure
    aggregated = {
        "gameId": game_id,
        "sceneId": scene_id,
        "aggregatedAt": int(time.time() * 1000),

        # Top-level summary for quick verification
        "summary": {
            "fullySynced": fully_synced,
            "hashesMatch": hashes_match,
            "actionsMatch": actions_match,
            "totalHashesCompared": hash_comparison["matchingFrames"] + hash_comparison["mismatchingFrames"],
            "totalActionsCompared": action_comparison["matchingFrames"] + action_comparison["mismatchingFrames"],
            "firstHashMismatchFrame": first_hash_mismatch,
            "firstActionMismatchFrame": first_action_mismatch,
            "hashDivergenceFrames": hash_divergence_frames,
            "actionDivergenceFrames": action_divergence_frames,
        },

        "players": {
            player_a_id: {
                "subjectId": player_a["subjectId"],
                "playerId": player_a_id,
                "connection": metrics_a.get("connection", {}),
                "inputDelivery": metrics_a.get("inputDelivery", {}),
                "sessionDurationMs": metrics_a.get("sessionDurationMs"),
            },
            player_b_id: {
                "subjectId": player_b["subjectId"],
                "playerId": player_b_id,
                "connection": metrics_b.get("connection", {}),
                "inputDelivery": metrics_b.get("inputDelivery", {}),
                "sessionDurationMs": metrics_b.get("sessionDurationMs"),
            }
        },

        "validation": {
            "hashSummary": {
                "totalFramesCompared": hash_comparison["totalFrames"],
                "matchingFrames": hash_comparison["matchingFrames"],
                "mismatchingFrames": hash_comparison["mismatchingFrames"],
                "playerAOnlyFrames": hash_comparison["playerAOnly"],
                "playerBOnlyFrames": hash_comparison["playerBOnly"],
                "matchRate": hash_comparison["matchRate"],
            },

            "actionSummary": {
                "totalFramesCompared": action_comparison["totalFrames"],
                "matchingFrames": action_comparison["matchingFrames"],
                "mismatchingFrames": action_comparison["mismatchingFrames"],
                "playerAOnlyFrames": action_comparison["playerAOnly"],
                "playerBOnlyFrames": action_comparison["playerBOnly"],
                "matchRate": action_comparison["matchRate"],
            },

            # Episode summaries from both players
            "episodes": {
                player_a_id: metrics_a.get("validation", {}).get("episodes", []),
                player_b_id: metrics_b.get("validation", {}).get("episodes", []),
            },

            # Frame-by-frame hash comparison
            "hashComparison": hash_comparison["frames"],

            # Frame-by-frame action comparison
            "actionComparison": action_comparison["frames"],

            # Desync events from both perspectives
            "desyncEvents": {
                player_a_id: metrics_a.get("validation", {}).get("allDesyncEvents", []),
                player_b_id: metrics_b.get("validation", {}).get("allDesyncEvents", []),
            },

            # Rollback events from both perspectives
            "rollbacks": {
                player_a_id: metrics_a.get("validation", {}).get("allRollbacks", []),
                player_b_id: metrics_b.get("validation", {}).get("allRollbacks", []),
            }
        }
    }

    # Save aggregated file
    filename = f"data/{scene_id}/{game_id}_aggregated_metrics.json"
    logger.info(f"Saving aggregated multiplayer metrics to {filename}")
    with open(filename, "w") as f:
        json.dump(aggregated, f, indent=2)


def _compare_hashes(hashes_a: list, hashes_b: list, player_a_id: str, player_b_id: str) -> dict:
    """
    Compare frame hashes from both players.

    Returns comparison structure with:
    - Per-frame comparison showing both hashes and match status
    - Summary statistics
    """
    # Build lookup by (episode, frame)
    lookup_a = {(h["episode"], h["frame"]): h["hash"] for h in hashes_a}
    lookup_b = {(h["episode"], h["frame"]): h["hash"] for h in hashes_b}

    all_keys = set(lookup_a.keys()) | set(lookup_b.keys())

    frames = []
    matching = 0
    mismatching = 0
    a_only = 0
    b_only = 0

    for key in sorted(all_keys):
        episode, frame = key
        hash_a = lookup_a.get(key)
        hash_b = lookup_b.get(key)

        if hash_a and hash_b:
            match = hash_a == hash_b
            if match:
                matching += 1
            else:
                mismatching += 1
            frames.append({
                "episode": episode,
                "frame": frame,
                player_a_id: hash_a,
                player_b_id: hash_b,
                "match": match
            })
        elif hash_a:
            a_only += 1
            frames.append({
                "episode": episode,
                "frame": frame,
                player_a_id: hash_a,
                player_b_id: None,
                "match": None
            })
        else:
            b_only += 1
            frames.append({
                "episode": episode,
                "frame": frame,
                player_a_id: None,
                player_b_id: hash_b,
                "match": None
            })

    total = matching + mismatching
    match_rate = (matching / total * 100) if total > 0 else None

    return {
        "totalFrames": len(frames),
        "matchingFrames": matching,
        "mismatchingFrames": mismatching,
        "playerAOnly": a_only,
        "playerBOnly": b_only,
        "matchRate": match_rate,
        "frames": frames
    }


def _compare_actions(actions_a: list, actions_b: list, player_a_id: str, player_b_id: str) -> dict:
    """
    Compare actions from both players frame by frame.

    Actions are keyed by (episode, frame, playerId) since each frame has actions
    for both players recorded by each client.

    Returns comparison structure with:
    - Per-frame comparison showing both players' recorded actions and match status
    - Summary statistics
    """
    # Build lookup by (episode, frame, actionPlayerId)
    # Each entry in allActions has: {episode, frame, playerId, action}
    # where playerId is the player who TOOK the action (not who recorded it)
    lookup_a = {}
    for a in actions_a:
        key = (a.get("episode"), a.get("frame"), a.get("playerId"))
        lookup_a[key] = a.get("action")

    lookup_b = {}
    for a in actions_b:
        key = (a.get("episode"), a.get("frame"), a.get("playerId"))
        lookup_b[key] = a.get("action")

    all_keys = set(lookup_a.keys()) | set(lookup_b.keys())

    frames = []
    matching = 0
    mismatching = 0
    a_only = 0
    b_only = 0

    for key in sorted(all_keys):
        episode, frame, action_player_id = key
        action_a = lookup_a.get(key)
        action_b = lookup_b.get(key)

        if action_a is not None and action_b is not None:
            # Compare actions - they should be identical
            match = action_a == action_b
            if match:
                matching += 1
            else:
                mismatching += 1
            frames.append({
                "episode": episode,
                "frame": frame,
                "actionPlayerId": action_player_id,
                f"recordedBy_{player_a_id}": action_a,
                f"recordedBy_{player_b_id}": action_b,
                "match": match
            })
        elif action_a is not None:
            a_only += 1
            frames.append({
                "episode": episode,
                "frame": frame,
                "actionPlayerId": action_player_id,
                f"recordedBy_{player_a_id}": action_a,
                f"recordedBy_{player_b_id}": None,
                "match": None
            })
        else:
            b_only += 1
            frames.append({
                "episode": episode,
                "frame": frame,
                "actionPlayerId": action_player_id,
                f"recordedBy_{player_a_id}": None,
                f"recordedBy_{player_b_id}": action_b,
                "match": None
            })

    total = matching + mismatching
    match_rate = (matching / total * 100) if total > 0 else None

    return {
        "totalFrames": len(frames),
        "matchingFrames": matching,
        "mismatchingFrames": mismatching,
        "playerAOnly": a_only,
        "playerBOnly": b_only,
        "matchRate": match_rate,
        "frames": frames
    }


def _get_first_mismatch_frame(frames: list) -> dict | None:
    """
    Find the first frame where match is False.

    Returns dict with episode and frame number, or None if all match.
    """
    for f in frames:
        if f.get("match") is False:
            return {"episode": f.get("episode"), "frame": f.get("frame")}
    return None


def _get_divergence_frames(frames: list) -> list:
    """
    Get all frames where match is False.

    Returns list of {episode, frame} dicts for divergent frames.
    """
    divergent = []
    for f in frames:
        if f.get("match") is False:
            divergent.append({"episode": f.get("episode"), "frame": f.get("frame")})
    return divergent


#####################################
# Pyodide Multiplayer Event Handlers
#####################################


@socketio.on('webrtc_signal')
def handle_webrtc_signal(data):
    """
    Relay WebRTC signaling messages between peers.

    Routes SDP offers/answers and ICE candidates through the server
    since peers cannot communicate directly until WebRTC is established.
    """
    if PYODIDE_COORDINATOR is None:
        logger.warning("WebRTC signal received but no coordinator")
        return

    game_id = data.get('game_id')
    target_player_id = data.get('target_player_id')
    signal_type = data.get('type')
    payload = data.get('payload')
    sender_socket_id = flask.request.sid

    PYODIDE_COORDINATOR.handle_webrtc_signal(
        game_id=game_id,
        target_player_id=target_player_id,
        signal_type=signal_type,
        payload=payload,
        sender_socket_id=sender_socket_id
    )


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
    sync_epoch = data.get("sync_epoch")  # May be None for backwards compatibility

    # logger.debug(
    #     f"Received action from player {player_id} in game {game_id} "
    #     f"for frame {frame_number}: {action}"
    # )

    PYODIDE_COORDINATOR.receive_action(
        game_id=game_id,
        player_id=player_id,
        action=action,
        frame_number=frame_number,
        sync_epoch=sync_epoch
    )


@socketio.on('mid_game_exclusion')
def on_mid_game_exclusion(data):
    """
    Handle mid-game exclusion from continuous monitoring.

    Called when a player is excluded due to sustained ping violations
    or tab visibility issues during gameplay.

    Args:
        data: {
            'game_id': str,
            'player_id': str | int,
            'reason': str ('sustained_ping', 'tab_hidden'),
            'frame_number': int,
            'timestamp': float
        }
    """
    global PYODIDE_COORDINATOR

    if PYODIDE_COORDINATOR is None:
        logger.error("Pyodide coordinator not initialized for mid_game_exclusion")
        return

    game_id = data.get("game_id")
    excluded_player_id = data.get("player_id")
    reason = data.get("reason")
    frame_number = data.get("frame_number")

    logger.info(
        f"Mid-game exclusion: player {excluded_player_id} in game {game_id} "
        f"(reason: {reason}, frame: {frame_number})"
    )

    # Get players before handling exclusion for termination recording
    game = PYODIDE_COORDINATOR.games.get(game_id)
    players = list(game.players.keys()) if game else []

    # Record termination for admin dashboard (Phase 34) and archive for history
    if ADMIN_AGGREGATOR:
        # Build session snapshot for historical viewing
        session_snapshot = None
        if game:
            session_snapshot = {
                'game_id': game_id,
                'players': players,
                'subject_ids': list(game.player_subjects.values()),
                'current_frame': game.frame_number,
                'is_server_authoritative': game.server_authoritative,
                'created_at': game.created_at,
                'game_type': 'multiplayer',
                'current_episode': getattr(game, 'episode_number', None),
            }
        ADMIN_AGGREGATOR.record_session_termination(
            game_id=game_id,
            reason=reason,  # sustained_ping, tab_hidden, etc.
            players=players,
            details={'excluded_player_id': excluded_player_id, 'frame_number': frame_number},
            session_snapshot=session_snapshot
        )

    PYODIDE_COORDINATOR.handle_player_exclusion(
        game_id=game_id,
        excluded_player_id=excluded_player_id,
        reason=reason,
        frame_number=frame_number
    )


@socketio.on("p2p_validation_status")
def handle_p2p_validation_status(data):
    """Handle P2P validation status update (Phase 19).

    Relays status to all players in game room for UI update.
    """
    game_id = data.get("game_id")
    status = data.get("status")

    # Relay status to all players in game room for UI update
    socketio.emit(
        "p2p_validation_status",
        {"status": status},
        room=game_id,
    )


@socketio.on("p2p_health_report")
def on_p2p_health_report(data):
    """Receive P2P health report from client (Phase 33).

    Updates admin dashboard with connection health metrics for each active game.
    """
    if ADMIN_AGGREGATOR:
        ADMIN_AGGREGATOR.receive_p2p_health(
            game_id=data.get('game_id'),
            player_id=data.get('player_id'),
            health_data={
                'connection_type': data.get('connection_type'),
                'latency_ms': data.get('latency_ms'),
                'status': data.get('status'),
                'episode': data.get('episode'),
                'timestamp': time.time()
            }
        )


@socketio.on("p2p_validation_success")
def handle_p2p_validation_success(data):
    """Handle successful P2P validation from a client (Phase 19)."""
    global PYODIDE_COORDINATOR

    if PYODIDE_COORDINATOR is None:
        logger.error("PYODIDE_COORDINATOR not initialized")
        return

    game_id = data.get("game_id")
    player_id = data.get("player_id")

    result = PYODIDE_COORDINATOR.record_validation_success(game_id, player_id)

    if result == 'complete':
        # All players validated - emit completion to all
        logger.info(f"All players validated in game {game_id}")
        socketio.emit(
            "p2p_validation_complete",
            {"game_id": game_id},
            room=game_id,
        )
    # If 'waiting', do nothing - other player(s) still validating


@socketio.on("p2p_validation_failed")
def handle_p2p_validation_failed(data):
    """Handle P2P validation failure - re-pool both players (Phase 19)."""
    global PYODIDE_COORDINATOR, GAME_MANAGERS, STAGERS

    if PYODIDE_COORDINATOR is None:
        logger.error("PYODIDE_COORDINATOR not initialized")
        return

    game_id = data.get("game_id")
    player_id = data.get("player_id")
    reason = data.get("reason", "unknown")

    logger.warning(f"P2P validation failed for game {game_id}: {reason}")

    # Get socket IDs before cleanup
    socket_ids = PYODIDE_COORDINATOR.handle_validation_failure(game_id, player_id, reason)

    # Emit re-pool event to all players in the game
    for socket_id in socket_ids:
        socketio.emit(
            "p2p_validation_repool",
            {
                "message": "Connection could not be established. Finding new partner...",
                "reason": reason,
            },
            room=socket_id,
        )

    # Clean up game from coordinator
    PYODIDE_COORDINATOR.remove_game(game_id)

    # Clean up game from game manager
    # Find the scene's game manager and remove the game
    for scene_id, game_manager in GAME_MANAGERS.items():
        if game_id in game_manager.games:
            # Remove subjects from game tracking
            game = game_manager.games.get(game_id)
            if game:
                for subject_id in list(game.human_players.values()):
                    if subject_id in game_manager.subject_games:
                        del game_manager.subject_games[subject_id]
                    if subject_id in game_manager.subject_rooms:
                        del game_manager.subject_rooms[subject_id]
            game_manager._remove_game(game_id)
            logger.info(f"Cleaned up game {game_id} from GameManager for scene {scene_id}")
            break


# ========== Mid-Game Reconnection Handlers (Phase 20) ==========


@socketio.on("p2p_connection_lost")
def handle_p2p_connection_lost(data):
    """Handle P2P connection loss - coordinate bilateral pause (Phase 20)."""
    global PYODIDE_COORDINATOR

    if PYODIDE_COORDINATOR is None:
        logger.error("PYODIDE_COORDINATOR not initialized")
        return

    game_id = data.get("game_id")
    player_id = data.get("player_id")
    frame_number = data.get("frame_number")

    logger.warning(
        f"P2P connection lost in game {game_id} "
        f"detected by player {player_id} at frame {frame_number}"
    )

    result = PYODIDE_COORDINATOR.handle_connection_lost(game_id, player_id, frame_number)

    if result == 'pause':
        # Emit pause to ALL players via SocketIO (works even when P2P down)
        socketio.emit(
            "p2p_pause",
            {
                "game_id": game_id,
                "pause_frame": frame_number,
                "detecting_player": player_id
            },
            room=game_id
        )


@socketio.on("p2p_reconnection_success")
def handle_p2p_reconnection_success(data):
    """Handle successful P2P reconnection (Phase 20)."""
    global PYODIDE_COORDINATOR

    if PYODIDE_COORDINATOR is None:
        return

    game_id = data.get("game_id")
    player_id = data.get("player_id")

    result = PYODIDE_COORDINATOR.handle_reconnection_success(game_id, player_id)

    if result == 'resume':
        logger.info(f"All players reconnected in game {game_id}")
        socketio.emit(
            "p2p_resume",
            {"game_id": game_id},
            room=game_id
        )


@socketio.on("p2p_reconnection_timeout")
def handle_p2p_reconnection_timeout(data):
    """Handle reconnection timeout - end game cleanly (Phase 20, Phase 23)."""
    global PYODIDE_COORDINATOR

    if PYODIDE_COORDINATOR is None:
        return

    game_id = data.get("game_id")
    player_id = data.get("player_id")

    logger.warning(f"P2P reconnection timeout in game {game_id}")

    # Get the disconnected player ID from the coordinator (Phase 23 - DATA-04)
    disconnected_player_id = PYODIDE_COORDINATOR.get_disconnected_player_id(game_id)

    # Get players before cleanup for termination recording
    game = PYODIDE_COORDINATOR.games.get(game_id)
    players = list(game.players.keys()) if game else []

    # Get reconnection data for logging
    reconnection_data = PYODIDE_COORDINATOR.handle_reconnection_timeout(game_id)

    # Record termination for admin dashboard (Phase 34) and archive for history
    if ADMIN_AGGREGATOR:
        # Build session snapshot for historical viewing
        session_snapshot = None
        if game:
            session_snapshot = {
                'game_id': game_id,
                'players': players,
                'subject_ids': list(game.player_subjects.values()),
                'current_frame': game.frame_number,
                'is_server_authoritative': game.server_authoritative,
                'created_at': game.created_at,
                'game_type': 'multiplayer',
                'current_episode': getattr(game, 'episode_number', None),
            }
        ADMIN_AGGREGATOR.record_session_termination(
            game_id=game_id,
            reason='partner_disconnected',
            players=players,
            details={'disconnected_player_id': disconnected_player_id},
            session_snapshot=session_snapshot
        )

    # Emit game ended to all players
    socketio.emit(
        "p2p_game_ended",
        {
            "game_id": game_id,
            "reason": "reconnection_timeout",
            "reconnection_data": reconnection_data,
            "disconnected_player_id": disconnected_player_id  # Phase 23 - DATA-04
        },
        room=game_id
    )

    # Clean up game
    PYODIDE_COORDINATOR.remove_game(game_id)


@socketio.on('execute_entry_callback')
def handle_execute_entry_callback(data):
    """Execute researcher-defined entry screening callback.

    Checks experiment-level callback first, then falls back to scene-level.
    Receives participant context from client, executes callback if configured,
    returns exclusion decision.

    Args:
        data: {
            'session_id': str,
            'scene_id': str,
            'context': {
                'ping': number,
                'browser_name': str,
                'browser_version': str,
                'device_type': str,
                'os_name': str,
                'os_version': str
            }
        }
    """
    session_id = data.get('session_id')
    scene_id = data.get('scene_id')
    context = data.get('context', {})

    # Get subject ID from session
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    if subject_id is None:
        flask_socketio.emit('entry_callback_result', {'exclude': False, 'message': None})
        return

    # Add subject_id and scene_id to context
    context['subject_id'] = subject_id
    context['scene_id'] = scene_id

    # Check experiment-level callback
    if CONFIG is None or CONFIG.entry_exclusion_callback is None:
        # No callback configured, pass through
        flask_socketio.emit('entry_callback_result', {'exclude': False, 'message': None})
        return

    try:
        # Execute the callback
        result = CONFIG.entry_exclusion_callback(context)

        # Validate result format
        exclude = result.get('exclude', False)
        message = result.get('message', None)

        logger.info(f"Entry callback for {subject_id}: exclude={exclude}")
        flask_socketio.emit('entry_callback_result', {'exclude': exclude, 'message': message})
    except Exception as e:
        logger.error(f"[Callback Error] Entry callback failed for {subject_id}: {e}")
        # On error, allow entry (fail open) but log
        flask_socketio.emit('entry_callback_result', {'exclude': False, 'message': None, 'error': str(e)})


@socketio.on('execute_continuous_callback')
def handle_execute_continuous_callback(data):
    """Execute researcher-defined continuous monitoring callback.

    Receives participant context from client during gameplay, executes callback,
    returns exclusion/warning decision.

    Args:
        data: {
            'session_id': str,
            'scene_id': str,
            'context': {
                'ping': number,
                'is_tab_hidden': bool,
                'tab_hidden_duration_ms': number,
                'frame_number': number,
                'episode_number': number
            }
        }
    """
    session_id = data.get('session_id')
    scene_id = data.get('scene_id')
    context = data.get('context', {})

    # Get subject ID from session
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    if subject_id is None:
        flask_socketio.emit('continuous_callback_result', {'exclude': False, 'warn': False, 'message': None})
        return

    # Get the current scene from participant's stager
    participant_stager = STAGERS.get(subject_id)
    if participant_stager is None:
        logger.warning(f"Continuous callback: No stager found for {subject_id}")
        flask_socketio.emit('continuous_callback_result', {'exclude': False, 'warn': False, 'message': None})
        return

    scene = participant_stager.current_scene
    if scene is None or not hasattr(scene, 'continuous_exclusion_callback') or scene.continuous_exclusion_callback is None:
        # No callback configured, pass through
        flask_socketio.emit('continuous_callback_result', {'exclude': False, 'warn': False, 'message': None})
        return

    try:
        # Add subject_id and scene_id to context
        context['subject_id'] = subject_id
        context['scene_id'] = scene.scene_id if hasattr(scene, 'scene_id') else scene_id

        # Execute the callback
        result = scene.continuous_exclusion_callback(context)

        # Validate result format
        exclude = result.get('exclude', False)
        warn = result.get('warn', False)
        message = result.get('message', None)

        if exclude or warn:
            logger.info(f"Continuous callback for {subject_id}: exclude={exclude}, warn={warn}")
        flask_socketio.emit('continuous_callback_result', {'exclude': exclude, 'warn': warn, 'message': message})
    except Exception as e:
        logger.error(f"[Callback Error] Continuous callback failed for {subject_id}: {e}")
        # On error, don't exclude (fail open) but log
        flask_socketio.emit('continuous_callback_result', {'exclude': False, 'warn': False, 'message': None, 'error': str(e)})


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


@socketio.on("p2p_state_sync")
def on_p2p_state_sync(data):
    """
    Relay P2P state sync message from host to other players (non-server-authoritative mode).

    Host broadcasts state hash periodically for non-host clients to compare
    and detect desyncs.

    Args:
        data: {
            'game_id': str,
            'sender_id': str | int,
            'frame_number': int,
            'state_hash': str,
            'action_counts': dict (optional, for debugging)
        }
    """
    global PYODIDE_COORDINATOR

    if PYODIDE_COORDINATOR is None:
        logger.error("Pyodide coordinator not initialized")
        return

    game_id = data.get("game_id")
    sender_id = data.get("sender_id")

    # Get the game to relay to all other players
    game = PYODIDE_COORDINATOR.games.get(game_id)
    if game is None:
        logger.warning(f"P2P state sync for non-existent game {game_id}")
        return

    # Don't relay in server-authoritative mode (server handles sync)
    if game.server_authoritative:
        return

    # Relay to all other players in the game
    for player_id, socket_id in game.players.items():
        if player_id != sender_id:
            socketio.emit('p2p_state_sync', data, room=socket_id)

    logger.debug(
        f"Relayed P2P state sync from player {sender_id} in game {game_id} "
        f"at frame {data.get('frame_number')} to {len(game.players) - 1} other player(s)"
    )


@socketio.on("p2p_state_request")
def on_p2p_state_request(data):
    """
    Relay P2P state request from one player to another (for desync recovery).

    When a player detects desync via hash mismatch, the lower player ID
    requests state from the higher player ID (deterministic tie-breaker).

    Args:
        data: {
            'game_id': str,
            'requester_id': str | int,
            'target_id': str | int,
            'frame_number': int
        }
    """
    global PYODIDE_COORDINATOR

    if PYODIDE_COORDINATOR is None:
        logger.error("Pyodide coordinator not initialized")
        return

    game_id = data.get("game_id")
    target_id = data.get("target_id")

    game = PYODIDE_COORDINATOR.games.get(game_id)
    if game is None:
        logger.warning(f"P2P state request for non-existent game {game_id}")
        return

    # Only relay in non-server-authoritative mode
    if game.server_authoritative:
        return

    # Relay to the target player
    target_socket_id = game.players.get(target_id)
    if target_socket_id:
        socketio.emit('p2p_state_request', data, room=target_socket_id)
        logger.debug(f"Relayed P2P state request to {target_id} in game {game_id}")


@socketio.on("p2p_state_response")
def on_p2p_state_response(data):
    """
    Relay P2P state response from one player to another (for desync recovery).

    Args:
        data: {
            'game_id': str,
            'sender_id': str | int,
            'target_id': str | int,
            'frame_number': int,
            'step_num': int,
            'env_state': dict,
            'cumulative_rewards': dict
        }
    """
    global PYODIDE_COORDINATOR

    if PYODIDE_COORDINATOR is None:
        logger.error("Pyodide coordinator not initialized")
        return

    game_id = data.get("game_id")
    target_id = data.get("target_id")

    game = PYODIDE_COORDINATOR.games.get(game_id)
    if game is None:
        logger.warning(f"P2P state response for non-existent game {game_id}")
        return

    # Only relay in non-server-authoritative mode
    if game.server_authoritative:
        return

    # Relay to the target player
    target_socket_id = game.players.get(target_id)
    if target_socket_id:
        socketio.emit('p2p_state_response', data, room=target_socket_id)
        logger.debug(f"Relayed P2P state response to {target_id} in game {game_id}")


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

    # Log activity for admin dashboard (before cleanup)
    session = PARTICIPANT_SESSIONS.get(subject_id)
    if ADMIN_AGGREGATOR:
        ADMIN_AGGREGATOR.log_activity(
            "disconnect",
            subject_id,
            {"scene_id": session.current_scene_id if session else None}
        )

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
    global app, CONFIG, logger, GENERIC_STAGER, PYODIDE_COORDINATOR, GROUP_MANAGER, ADMIN_AGGREGATOR
    CONFIG = config
    GENERIC_STAGER = config.stager

    # Initialize Pyodide coordinator
    PYODIDE_COORDINATOR = pyodide_game_coordinator.PyodideGameCoordinator(socketio)
    logger.info("Initialized Pyodide multiplayer coordinator")

    # Initialize player group manager
    GROUP_MANAGER = player_pairing_manager.PlayerGroupManager()
    logger.info("Initialized player group manager")

    # Initialize admin event aggregator
    ADMIN_AGGREGATOR = AdminEventAggregator(
        sio=socketio,
        participant_sessions=PARTICIPANT_SESSIONS,
        stagers=STAGERS,
        game_managers=GAME_MANAGERS,
        pyodide_coordinator=PYODIDE_COORDINATOR,
        processed_subjects=PROCESSED_SUBJECT_NAMES,
        save_console_logs=CONFIG.save_experiment_data
    )
    ADMIN_AGGREGATOR.start_broadcast_loop(interval_seconds=1.0)
    logger.info("Admin event aggregator initialized and broadcast loop started")

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

    # Register admin namespace with aggregator
    admin_namespace = AdminNamespace('/admin', aggregator=ADMIN_AGGREGATOR)
    socketio.on_namespace(admin_namespace)
    logger.info("Admin namespace registered on /admin")

    socketio.run(
        app,
        log_output=app.config["DEBUG"],
        port=CONFIG.port,
        host=CONFIG.host,
    )
