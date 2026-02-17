from __future__ import annotations

import atexit
import dataclasses
import json
import logging
import os
import secrets
import socket
import threading
import time
import urllib.request
import uuid

import flask
import flask_socketio
import flatten_dict
import msgpack
import pandas as pd
from flask_login import LoginManager

from mug.configurations import remote_config
from mug.scenes import gym_scene, stager, unity_scene
from mug.server import (game_manager, player_pairing_manager,
                        pyodide_game_coordinator, thread_safe_collections)
from mug.server.admin import AdminUser, admin_bp
from mug.server.admin.aggregator import AdminEventAggregator
from mug.server.admin.namespace import AdminNamespace
from mug.server.match_logger import MatchAssignmentLogger
from mug.server.participant_state import (ParticipantState,
                                          ParticipantStateTracker)
from mug.server.probe_coordinator import ProbeCoordinator
from mug.server.remote_game import AvailableSlot
from mug.utils.typing import SceneID, SubjectID


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
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        formatter
    )  # Setting the formatter for the console handler as well

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.addHandler(console_handler)
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
STAGERS: dict[SubjectID, stager.Stager] = thread_safe_collections.ThreadSafeDict()

# Data structure to save subjects by their socket id
SUBJECTS = thread_safe_collections.ThreadSafeDict()

# Game managers handle all the game logic, connection, and waiting room for a given scene
GAME_MANAGERS: dict[SceneID, game_manager.GameManager] = thread_safe_collections.ThreadSafeDict()

# Pyodide multiplayer game coordinator
PYODIDE_COORDINATOR: pyodide_game_coordinator.PyodideGameCoordinator | None = None

# Player group manager for tracking player relationships across scenes
# Supports groups of any size (2 or more players)
GROUP_MANAGER: player_pairing_manager.PlayerGroupManager | None = None

# Admin event aggregator for dashboard state collection
ADMIN_AGGREGATOR: AdminEventAggregator | None = None

# Match assignment logger for research data collection (Phase 56)
MATCH_LOGGER: MatchAssignmentLogger | None = None

# Probe coordinator for P2P RTT measurement (Phase 57)
PROBE_COORDINATOR: ProbeCoordinator | None = None

# Mapping of users to locks associated with the ID. Enforces user-level serialization
USER_LOCKS = thread_safe_collections.ThreadSafeDict()


# Session ID to participant ID map
SESSION_ID_TO_SUBJECT_ID = thread_safe_collections.ThreadSafeDict()

# Participant session storage for session restoration after disconnect
# Maps subject_id -> ParticipantSession
PARTICIPANT_SESSIONS: dict[SubjectID, ParticipantSession] = thread_safe_collections.ThreadSafeDict()

# Participant state tracker - single source of truth for participant lifecycle states
# Prevents routing to wrong games by tracking IDLE/IN_WAITROOM/IN_GAME/GAME_ENDED
PARTICIPANT_TRACKER: ParticipantStateTracker = ParticipantStateTracker()

# Pending multiplayer metrics for aggregation
# Maps (scene_id, game_id) -> {player_id: metrics, ...}
# When both players submit, metrics are aggregated into a comparison file
PENDING_MULTIPLAYER_METRICS: dict[tuple[str, str], dict] = thread_safe_collections.ThreadSafeDict()

# Pyodide loading grace period tracking (Phase 69)
# Maps subject_id -> loading start timestamp. Clients in this dict are currently
# loading Pyodide WASM and should not be treated as truly disconnected.
LOADING_CLIENTS: dict[str, float] = {}
LOADING_TIMEOUT_S = 60  # Max loading time before considering client dead


def get_subject_id_from_session_id(session_id: str) -> SubjectID:
    subject_id = SESSION_ID_TO_SUBJECT_ID.get(session_id, None)
    return subject_id


def is_client_in_loading_grace(subject_id: str) -> bool:
    """Check if client is in Pyodide loading grace period (not timed out)."""
    start_time = LOADING_CLIENTS.get(subject_id)
    if start_time is None:
        return False
    timeout = getattr(CONFIG, 'pyodide_load_timeout_s', LOADING_TIMEOUT_S)
    if time.time() - start_time > timeout:
        LOADING_CLIENTS.pop(subject_id, None)
        logger.warning(f"[Grace] {subject_id} loading grace expired after {timeout}s")
        return False
    return True


def get_socket_for_subject(subject_id: str) -> str | None:
    """Get current socket_id for a subject_id from PARTICIPANT_SESSIONS.

    Used by ProbeCoordinator to look up socket IDs fresh (not cached).
    """
    session = PARTICIPANT_SESSIONS.get(subject_id)
    if session and session.is_connected:
        return session.socket_id
    return None


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
    # Ping settings: ping_timeout increased to accommodate Pyodide WASM compilation
    # (5-15s) in the fallback path where preload didn't happen.
    # Total grace before disconnect: 8 + 30 = 38 seconds, well beyond worst case.
    # This weakens real disconnect detection from 16s to 38s, but multiplayer games
    # already have P2P WebRTC disconnect detection at 500ms, so this is acceptable.
    ping_interval=8,   # Ping every 8 seconds (default: 25)
    ping_timeout=30,   # Wait 30 seconds for pong before disconnect (default: 5)
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

    # Clean up stale participant state on fresh connection
    # If participant is IN_GAME/IN_WAITROOM but no game exists, reset to IDLE
    # If participant is GAME_ENDED, also reset (allows new game in same session)
    current_participant_state = PARTICIPANT_TRACKER.get_state(subject_id)
    if current_participant_state == ParticipantState.GAME_ENDED:
        # Game ended - reset for potential new game (e.g., multi-episode experiments, tests)
        logger.info(
            f"[RegisterSession] Participant {subject_id} reconnecting after GAME_ENDED. "
            f"Resetting to IDLE for fresh start."
        )
        PARTICIPANT_TRACKER.reset(subject_id)
    elif current_participant_state in (ParticipantState.IN_GAME, ParticipantState.IN_WAITROOM):
        # Check if they're actually in a game
        in_any_game = False
        for game_manager in GAME_MANAGERS.values():
            if game_manager.subject_in_game(subject_id):
                in_any_game = True
                break
        if not in_any_game:
            logger.warning(
                f"[RegisterSession] Participant {subject_id} has stale state {current_participant_state.name} "
                f"but is not in any game. Resetting to IDLE."
            )
            PARTICIPANT_TRACKER.reset(subject_id)

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

    # Send experiment-level config to client (entry screening + pyodide config)
    if CONFIG is not None:
        experiment_config_data = {
            "entry_screening": CONFIG.get_entry_screening_config(),
        }
        if hasattr(CONFIG, "get_pyodide_config"):
            experiment_config_data["pyodide_config"] = CONFIG.get_pyodide_config()

        flask_socketio.emit("experiment_config", experiment_config_data, room=sid)

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

    participant_stager.current_scene.experiment_id = CONFIG.experiment_id
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

    # Reset participant state when advancing to a new scene
    # This ensures participants can join new games after completing previous scenes
    current_state = PARTICIPANT_TRACKER.get_state(subject_id)
    if current_state != ParticipantState.IDLE:
        logger.info(
            f"[AdvanceScene] Resetting participant {subject_id} from {current_state.name} to IDLE "
            f"for new scene"
        )
        PARTICIPANT_TRACKER.reset(subject_id)

    # Clean up Pyodide game state BEFORE scene transition
    # This prevents false 'partner_disconnected' when WebRTC closes during transition
    if PYODIDE_COORDINATOR is not None:
        for game_id, game_state in list(PYODIDE_COORDINATOR.games.items()):
            for player_id, socket_id in list(game_state.players.items()):
                if socket_id == flask.request.sid:
                    logger.info(
                        f"[AdvanceScene] Removing {subject_id} (player {player_id}) "
                        f"from Pyodide game {game_id} before scene transition"
                    )
                    PYODIDE_COORDINATOR.remove_player(
                        game_id=game_id,
                        player_id=player_id,
                        notify_others=True,
                        reason='scene_completed',
                    )
                    break

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

            # Initialize match logger if not already done (Phase 56)
            global MATCH_LOGGER
            if MATCH_LOGGER is None:
                MATCH_LOGGER = MatchAssignmentLogger(admin_aggregator=ADMIN_AGGREGATOR, experiment_id=CONFIG.experiment_id)

            gm_instance = game_manager.GameManager(
                scene=current_scene,
                experiment_config=CONFIG,
                socketio=socketio,
                pyodide_coordinator=PYODIDE_COORDINATOR,
                pairing_manager=GROUP_MANAGER,
                get_subject_rtt=_get_subject_rtt,
                participant_state_tracker=PARTICIPANT_TRACKER,
                matchmaker=current_scene.matchmaker,
                match_logger=MATCH_LOGGER,  # Phase 56
                probe_coordinator=PROBE_COORDINATOR,  # Phase 59: P2P RTT probing
                get_socket_for_subject=get_socket_for_subject,  # Phase 60+: waitroom->match
            )
            GAME_MANAGERS[current_scene.scene_id] = gm_instance
        else:
            logger.info(
                f"Game manager already exists for scene {current_scene.scene_id}, reusing it"
            )

    current_scene.experiment_id = CONFIG.experiment_id
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

        # Check participant state before routing (Phase 54)
        current_state = PARTICIPANT_TRACKER.get_state(subject_id)
        logger.info(
            f"[JoinGame:StateCheck] Subject {subject_id} current state: {current_state.name}, "
            f"tracked_subjects={list(PARTICIPANT_TRACKER._states.keys())}"
        )
        if not PARTICIPANT_TRACKER.can_join_waitroom(subject_id):
            logger.warning(
                f"[JoinGame] Subject {subject_id} cannot join waitroom, current state: {current_state.name}"
            )
            socketio.emit(
                "waiting_room_error",
                {
                    "message": f"Cannot join game while in state: {current_state.name}",
                    "error_code": "INVALID_PARTICIPANT_STATE",
                    "details": f"Current state: {current_state.name}"
                },
                room=flask.request.sid,
            )
            return

        # Transition to IN_WAITROOM (Phase 54)
        PARTICIPANT_TRACKER.transition_to(subject_id, ParticipantState.IN_WAITROOM)

        # Diagnostic logging for stale game routing bug (BUG-04)
        logger.info(
            f"[JoinGame:Diag] subject_id={subject_id}, "
            f"in_subject_games={subject_id in game_manager.subject_games}, "
            f"subject_games_keys={list(game_manager.subject_games.keys())}, "
            f"active_games={list(game_manager.active_games)}, "
            f"waiting_games={game_manager.waiting_games}"
        )

        # State validation before routing (BUG-04)
        is_valid, error_message = game_manager.validate_subject_state(subject_id)
        if not is_valid:
            logger.error(
                f"[JoinGame] State validation failed for {subject_id}: {error_message}"
            )
            socketio.emit(
                "waiting_room_error",
                {
                    "message": "Unable to join game due to invalid state. Please refresh the page.",
                    "error_code": "INVALID_STATE",
                    "details": error_message
                },
                room=flask.request.sid,
            )
            return

        # Check if the participant is already in a game in this scene.
        # This can happen if a previous session didn't clean up properly (browser crash, network issue, etc.)
        if game_manager.subject_in_game(subject_id):
            # Diagnostic logging for stale game entry (BUG-04)
            stale_game_id = game_manager.subject_games.get(subject_id)
            stale_game = game_manager.games.get(stale_game_id)
            logger.warning(
                f"[JoinGame:Diag] Subject {subject_id} has stale game entry. "
                f"game_id={stale_game_id}, "
                f"game_exists={stale_game is not None}, "
                f"game_status={stale_game.status if stale_game else 'N/A'}, "
                f"game_active={stale_game_id in game_manager.active_games if stale_game_id else False}"
            )
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
                    f"Game starting. Post-add state: subject_games has {len(game_manager.subject_games)} entries."
                )
            else:
                # game is None when waiting for group members or in waiting room
                logger.info(
                    f"[JoinGame] Subject {subject_id} added to waiting room for scene {current_scene.scene_id}. "
                    f"Waiting for more players. Post-add state: subject_games has {len(game_manager.subject_games)} entries."
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


@socketio.on("leave_game")
def leave_game(data):
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    logger.info(f"[LeaveGame] Subject {subject_id} leaving game (likely waitroom timeout or disconnect).")

    client_reported_session_id = data.get("session_id")

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

        # Also clean up from pyodide coordinator if applicable
        if PYODIDE_COORDINATOR:
            # Find and remove this player from any pyodide games
            for game_id, game in list(PYODIDE_COORDINATOR.games.items()):
                if subject_id in game.player_subjects.values():
                    # Find the player_id for this subject
                    player_id = None
                    for pid, sid in game.player_subjects.items():
                        if sid == subject_id:
                            player_id = pid
                            break
                    if player_id is not None:
                        logger.info(f"[LeaveGame] Removing subject {subject_id} (player {player_id}) from pyodide game {game_id}")
                        # Archive the session before removing if it was a waiting game
                        if ADMIN_AGGREGATOR and not game.is_active:
                            session = PARTICIPANT_SESSIONS.get(subject_id)
                            scene_id = session.current_scene_id if session else None
                            session_snapshot = {
                                'game_id': game_id,
                                'players': list(game.players.keys()),
                                'subject_ids': list(game.player_subjects.values()),
                                'current_frame': game.frame_number,
                                'created_at': game.created_at,
                                'game_type': 'multiplayer',
                                'current_episode': None,
                                'scene_id': scene_id,
                            }
                            ADMIN_AGGREGATOR.record_session_termination(
                                game_id=game_id,
                                reason='waitroom_timeout',
                                players=list(game.player_subjects.values()),
                                details={'leaving_player': subject_id},
                                session_snapshot=session_snapshot
                            )
                        PYODIDE_COORDINATOR.remove_player(game_id, player_id, notify_others=True)
                    break

        # Reset participant state (Phase 54)
        PARTICIPANT_TRACKER.reset(subject_id)

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

@socketio.on("send_pressed_keys")
def send_pressed_keys(data):
    """
    Translate pressed keys into game action and add them to the pending_actions queue.
    """
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    # Fallback to flask.session if needed
    if subject_id is None:
        subject_id = flask.session.get("subject_id")

    # Skip if no subject_id (can happen in Pyodide games that don't use pressed keys)
    if subject_id is None:
        return

    participant_stager = STAGERS.get(subject_id, None)
    if participant_stager is None:
        logger.warning(
            f"Pressed keys requested for {subject_id} but they don't have a Stager."
        )
        return

    current_scene = participant_stager.current_scene
    game_manager = GAME_MANAGERS.get(current_scene.scene_id, None)

    client_reported_server_session_id = data.get("server_session_id")

    pressed_keys = data["pressed_keys"]

    game_manager.process_pressed_keys(
        subject_id=subject_id, pressed_keys=pressed_keys
    )


@socketio.on("reset_complete")
def handle_reset_complete(data):
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    client_session_id = data.get("session_id")

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


@socketio.on("pyodide_loading_start")
def on_pyodide_loading_start(data):
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    if subject_id:
        LOADING_CLIENTS[subject_id] = time.time()
        logger.info(f"[Grace] {subject_id} starting Pyodide loading")


@socketio.on("pyodide_loading_complete")
def on_pyodide_loading_complete(data):
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    if subject_id:
        start_time = LOADING_CLIENTS.pop(subject_id, None)
        if start_time:
            duration = time.time() - start_time
            logger.info(f"[Grace] {subject_id} completed Pyodide loading in {duration:.1f}s")
        else:
            logger.info(f"[Grace] {subject_id} completed Pyodide loading (no start tracked)")


@socketio.on("unityEpisodeEnd")
def on_unity_episode_end(data):
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    participant_stager = STAGERS.get(subject_id, None)
    current_scene = participant_stager.current_scene

    if not isinstance(current_scene, unity_scene.UnityScene):
        return

    current_scene.on_unity_episode_end(
        data,
        socketio=socketio,
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
        socketio=socketio,
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
    current_scene.on_client_callback(data, socketio=socketio, room=flask.request.sid)


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

    # Track waitroom timeout in admin aggregator
    if ADMIN_AGGREGATOR:
        # Get current scene_id from participant session
        session = PARTICIPANT_SESSIONS.get(subject_id)
        scene_id = session.current_scene_id if session else None
        ADMIN_AGGREGATOR.track_waitroom_timeout(subject_id, scene_id)

    # Save completion code to file if data saving is enabled
    if CONFIG.save_experiment_data:
        completion_data = {
            "subject_id": subject_id,
            "completion_code": completion_code,
            "reason": reason,
            "timestamp": time.time(),
        }

        # Save to data/completion_codes/{subject_id}.json
        completion_dir = os.path.join("data", CONFIG.experiment_id, "completion_codes")
        os.makedirs(completion_dir, exist_ok=True)
        filepath = os.path.join(completion_dir, f"{subject_id}.json")

        with open(filepath, "w") as f:
            json.dump(completion_data, f, indent=2)

        logger.info(f"Saved completion code to {filepath}")


def on_exit():
    # Force-terminate all games on server termination
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
    os.makedirs(f"data/{CONFIG.experiment_id}/{scene_id}/", exist_ok=True)

    # Generate a unique filename
    filename = f"data/{CONFIG.experiment_id}/{scene_id}/{subject_id}.csv"
    globals_filename = f"data/{CONFIG.experiment_id}/{scene_id}/{subject_id}_globals.json"

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
    os.makedirs(f"data/{CONFIG.experiment_id}/{data['scene_id']}/", exist_ok=True)

    # Generate a unique filename
    filename = f"data/{CONFIG.experiment_id}/{data['scene_id']}/{subject_id}.csv"
    globals_filename = f"data/{CONFIG.experiment_id}/{data['scene_id']}/{subject_id}_globals.json"

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
    # with open(f"data/{CONFIG.experiment_id}/{data['scene_id']}/{subject_id}_metadata.json", "w") as f:
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

    Returns acknowledgment dict for client-side delivery confirmation.
    """
    global PARTICIPANT_SESSIONS

    subject_id = get_subject_id_from_session_id(flask.request.sid)
    # Fall back to client-provided subject_id if session mapping is missing
    # (can happen under heavy load when session state is cleared between emit and ack)
    if subject_id is None and data.get("subject_id"):
        subject_id = data["subject_id"]
        logger.warning(f"[EpisodeData] Session mapping missing for sid={flask.request.sid}, "
                       f"using client-provided subject_id={subject_id}")
    episode_num = data.get("episode_num", 0)

    # Sync interactiveGymGlobals to session for persistence
    client_globals = data.get("interactiveGymGlobals", {})
    session = PARTICIPANT_SESSIONS.get(subject_id)
    if session is not None and client_globals:
        session.interactive_gym_globals.update(client_globals)
        session.last_updated_at = time.time()

    if not CONFIG.save_experiment_data:
        return {"status": "ok", "saved": False}

    # Decode the msgpack data
    decoded_data = msgpack.unpackb(data["data"])

    # Check if there's any data to save
    if not decoded_data or not decoded_data.get("t"):
        logger.info(f"No data to save for episode {episode_num}")
        return {"status": "ok", "saved": False}

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
    os.makedirs(f"data/{CONFIG.experiment_id}/{data['scene_id']}/", exist_ok=True)

    # Generate filename with episode number
    filename = f"data/{CONFIG.experiment_id}/{data['scene_id']}/{subject_id}_ep{episode_num}.csv"

    # Save as CSV
    logger.info(f"Saving episode {episode_num} data: {filename} ({len(df)} rows)")

    df.to_csv(filename, index=False)

    # Also save globals (overwrite each episode to keep latest)
    globals_filename = f"data/{CONFIG.experiment_id}/{data['scene_id']}/{subject_id}_globals.json"
    with open(globals_filename, "w") as f:
        json.dump(data.get("interactiveGymGlobals", {}), f)

    return {"status": "ok", "saved": True}


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
    os.makedirs(f"data/{CONFIG.experiment_id}/{scene_id}/", exist_ok=True)

    # Save individual player's metrics
    filename = f"data/{CONFIG.experiment_id}/{scene_id}/{subject_id}_multiplayer_metrics.json"
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
    filename = f"data/{CONFIG.experiment_id}/{scene_id}/{game_id}_aggregated_metrics.json"
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


#####################################
# P2P Probe Event Handlers (Phase 57)
#####################################


@socketio.on('probe_ready')
def handle_probe_ready(data):
    """Handle client reporting ready for probe connection.

    After receiving probe_prepare, clients initialize their ProbeConnection
    and emit probe_ready. Once both clients report ready, the coordinator
    emits probe_start to trigger WebRTC connection establishment.
    """
    if PROBE_COORDINATOR is None:
        logger.warning("Probe ready received but no coordinator")
        return

    probe_session_id = data.get('probe_session_id')
    subject_id = get_subject_id_from_session_id(flask.request.sid)

    logger.debug(f"[Probe] Ready: session={probe_session_id}, subject={subject_id}")
    PROBE_COORDINATOR.handle_ready(probe_session_id, subject_id)


@socketio.on('probe_signal')
def handle_probe_signal(data):
    """Relay WebRTC signaling for probe connections.

    Routes SDP offers/answers and ICE candidates between probe peers.
    Uses separate event name from game signaling to avoid collision.
    """
    if PROBE_COORDINATOR is None:
        logger.warning("Probe signal received but no coordinator")
        return

    PROBE_COORDINATOR.handle_signal(
        probe_session_id=data.get('probe_session_id'),
        target_subject_id=data.get('target_subject_id'),
        signal_type=data.get('type'),
        payload=data.get('payload'),
        sender_socket_id=flask.request.sid
    )


@socketio.on('probe_result')
def handle_probe_result(data):
    """Handle probe measurement result from client.

    Called when a client reports the RTT measurement result.
    The coordinator invokes the on_complete callback and cleans up.
    """
    if PROBE_COORDINATOR is None:
        logger.warning("Probe result received but no coordinator")
        return

    probe_session_id = data.get('probe_session_id')
    rtt_ms = data.get('rtt_ms')
    success = data.get('success', False)

    logger.info(f"[Probe] Result: session={probe_session_id}, rtt={rtt_ms}ms, success={success}")
    PROBE_COORDINATOR.handle_result(probe_session_id, rtt_ms, success)


@socketio.on("player_action")
def on_player_action(data):
    """Receive a player action from a server-authoritative game client.

    The client sends the raw key press, and we map it to the action via
    the scene's action_mapping, then enqueue it on the game.
    """
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    if subject_id is None:
        return

    key = data.get("key")
    game_id = data.get("game_id")

    if key is None or game_id is None:
        return

    # Find the game manager for this subject
    for gm in GAME_MANAGERS.values():
        if gm.subject_in_game(subject_id):
            game = gm.get_subject_game(subject_id)
            if game is None:
                return

            # Find which agent_id this subject controls
            agent_id = None
            for aid, sid in game.human_players.items():
                if sid == subject_id:
                    agent_id = aid
                    break

            if agent_id is None:
                logger.warning(f"[PlayerAction] Subject {subject_id} not found in game players")
                return

            # Map key to action using the scene's action_mapping
            scene = gm.scene
            action = scene.action_mapping.get(key)
            if action is None:
                # Key not in action mapping -- ignore
                return

            game.enqueue_action(agent_id, action)
            return


@socketio.on("rejoin_server_auth")
def on_rejoin_server_auth(data):
    """Handle reconnection to a running server-authoritative game.

    When a client reconnects and was previously in a server-auth game,
    it emits this event. We look up their game across all GameManagers
    and rejoin them to the socket room so state broadcasts resume.
    """
    subject_id = get_subject_id_from_session_id(flask.request.sid)
    if subject_id is None:
        return

    for gm in GAME_MANAGERS.values():
        game = gm.rejoin_server_auth_game(subject_id, flask.request.sid)
        if game is not None:
            socketio.emit(
                "rejoin_success",
                {
                    "game_id": game.game_id,
                    "scene_metadata": gm.scene.scene_metadata,
                },
                room=flask.request.sid,
            )
            return

    socketio.emit("rejoin_failed", {}, room=flask.request.sid)


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
    client_timestamp = data.get("sync_epoch") or data.get("client_timestamp")  # backwards compatible

    # logger.debug(
    #     f"Received action from player {player_id} in game {game_id} "
    #     f"for frame {frame_number}: {action}"
    # )

    PYODIDE_COORDINATOR.receive_action(
        game_id=game_id,
        player_id=player_id,
        action=action,
        frame_number=frame_number,
        client_timestamp=client_timestamp
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
            # Get scene_id from first player's session
            scene_id = None
            subject_ids = list(game.player_subjects.values())
            if subject_ids:
                first_session = PARTICIPANT_SESSIONS.get(subject_ids[0])
                scene_id = first_session.current_scene_id if first_session else None

            session_snapshot = {
                'game_id': game_id,
                'players': players,
                'subject_ids': subject_ids,
                'current_frame': game.frame_number,
                'created_at': game.created_at,
                'game_type': 'multiplayer',
                'current_episode': getattr(game, 'episode_number', None),
                'scene_id': scene_id,
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

    # Clean up GameManager state (Phase 52)
    for scene_id, game_manager in GAME_MANAGERS.items():
        if game_id in game_manager.games:
            game_manager.cleanup_game(game_id)
            logger.info(f"Cleaned up GameManager state for mid-game exclusion in game {game_id}")
            break


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


@socketio.on("multiplayer_game_complete")
def handle_multiplayer_game_complete(data):
    """Handle notification that a multiplayer game completed all episodes.

    Called by clients when all episodes finish successfully.
    Archives the session for admin console viewing.
    """
    game_id = data.get("game_id")
    episode_num = data.get("episode_num")
    max_episodes = data.get("max_episodes")

    if not game_id:
        return

    logger.info(f"[GameComplete] Multiplayer game {game_id} completed: {episode_num}/{max_episodes} episodes")

    if ADMIN_AGGREGATOR and PYODIDE_COORDINATOR:
        game = PYODIDE_COORDINATOR.games.get(game_id)
        if game:
            # Get subject IDs from pyodide coordinator
            subject_ids = list(game.player_subjects.values())
            players = list(game.players.keys())

            # Get scene_id from first participant
            scene_id = None
            for sid in subject_ids:
                session = PARTICIPANT_SESSIONS.get(sid)
                if session:
                    scene_id = session.current_scene_id
                    break

            # Get P2P health data before archiving
            p2p_health = ADMIN_AGGREGATOR._get_p2p_health_for_game(game_id)

            # Build session snapshot with connection stats
            session_snapshot = {
                'game_id': game_id,
                'players': players,
                'subject_ids': subject_ids,
                'current_frame': game.frame_number,
                'created_at': game.created_at,
                'game_type': 'multiplayer',
                'current_episode': episode_num,
                'max_episodes': max_episodes,
                'scene_id': scene_id,
                'p2p_health': p2p_health,
                'session_health': ADMIN_AGGREGATOR._compute_session_health(p2p_health),
            }

            ADMIN_AGGREGATOR.record_session_termination(
                game_id=game_id,
                reason='normal',
                players=subject_ids,
                details={
                    'episode_num': episode_num,
                    'max_episodes': max_episodes,
                },
                session_snapshot=session_snapshot
            )
            logger.info(f"[GameComplete] Archived session {game_id} with {len(subject_ids)} players")

            # Transition all players to GAME_ENDED (Phase 54)
            for sid in subject_ids:
                PARTICIPANT_TRACKER.transition_to(sid, ParticipantState.GAME_ENDED)


@socketio.on("participant_terminal_state")
def handle_participant_terminal_state(data):
    """Handle participant entering a terminal state (partner disconnected, etc.).

    Updates admin console to show correct participant status by adding to
    PROCESSED_SUBJECT_NAMES, which the aggregator checks for 'completed' status.

    Args:
        data: {
            'game_id': str,
            'scene_id': str,
            'reason': str ('partner_disconnected', 'focus_loss_timeout'),
            'frame_number': int,
            'episode_number': int
        }
    """
    global PROCESSED_SUBJECT_NAMES

    subject_id = get_subject_id_from_session_id(flask.request.sid)
    if subject_id is None:
        return

    game_id = data.get("game_id")
    scene_id = data.get("scene_id")
    reason = data.get("reason")

    logger.info(
        f"[TerminalState] Subject {subject_id} entered terminal state: {reason} "
        f"(game: {game_id}, scene: {scene_id})"
    )

    # Transition to GAME_ENDED (Phase 54)
    PARTICIPANT_TRACKER.transition_to(subject_id, ParticipantState.GAME_ENDED)

    # Add to processed subjects so aggregator shows them as 'completed'
    if subject_id not in PROCESSED_SUBJECT_NAMES:
        PROCESSED_SUBJECT_NAMES.append(subject_id)

    # Record session completion for duration tracking
    if ADMIN_AGGREGATOR:
        session = PARTICIPANT_SESSIONS.get(subject_id)
        if session:
            ADMIN_AGGREGATOR.record_session_completion(
                subject_id=subject_id,
                started_at=session.created_at,
                completed_at=time.time()
            )
        # Close console log file for this subject
        ADMIN_AGGREGATOR.close_subject_console_log(subject_id)


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

    # Collect subject IDs before cleanup for state reset
    subject_ids_to_reset = []
    for scene_id, game_manager in GAME_MANAGERS.items():
        game = game_manager.games.get(game_id)
        if game:
            subject_ids_to_reset = [
                sid for sid in game.human_players.values()
                if sid and sid != AvailableSlot
            ]
            break

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

    # Clean up GameManager state - use _remove_game to avoid GAME_ENDED transition
    # which would block re-pooling (need IDLE state to rejoin waitroom)
    for scene_id, game_manager in GAME_MANAGERS.items():
        if game_id in game_manager.games:
            # Manual cleanup without transitioning to GAME_ENDED
            game = game_manager.games[game_id]
            for subject_id in list(game.human_players.values()):
                if subject_id and subject_id != AvailableSlot:
                    if subject_id in game_manager.subject_games:
                        del game_manager.subject_games[subject_id]
                    if subject_id in game_manager.subject_rooms:
                        del game_manager.subject_rooms[subject_id]
            game_manager._remove_game(game_id)
            logger.info(f"Cleaned up GameManager state for failed P2P validation game {game_id}")
            break

    # Reset participant state to IDLE so they can re-pool (not GAME_ENDED)
    for subject_id in subject_ids_to_reset:
        PARTICIPANT_TRACKER.reset(subject_id)
        logger.info(f"Reset participant {subject_id} to IDLE after P2P validation failure")


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
            # Get scene_id from first player's session
            scene_id = None
            subject_ids = list(game.player_subjects.values())
            if subject_ids:
                first_session = PARTICIPANT_SESSIONS.get(subject_ids[0])
                scene_id = first_session.current_scene_id if first_session else None

            session_snapshot = {
                'game_id': game_id,
                'players': players,
                'subject_ids': subject_ids,
                'current_frame': game.frame_number,
                'created_at': game.created_at,
                'game_type': 'multiplayer',
                'current_episode': getattr(game, 'episode_number', None),
                'scene_id': scene_id,
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

    # Clean up game from Pyodide coordinator
    PYODIDE_COORDINATOR.remove_game(game_id)

    # Clean up GameManager state for both players (Phase 52)
    for scene_id, game_manager in GAME_MANAGERS.items():
        if game_id in game_manager.games:
            game_manager.cleanup_game(game_id)
            logger.info(f"Cleaned up GameManager state for reconnection timeout game {game_id}")
            break


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
    Relay P2P state sync message from host to other players.

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

    # Grace check: if client is loading Pyodide, preserve session and skip cleanup (Phase 69)
    if is_client_in_loading_grace(subject_id):
        logger.warning(
            f"[Grace] {subject_id} disconnected during Pyodide loading. "
            f"Preserving session for reconnection."
        )
        session = PARTICIPANT_SESSIONS.get(subject_id)
        if session is not None:
            participant_stager = STAGERS.get(subject_id, None)
            if participant_stager:
                session.stager_state = participant_stager.get_state()
                session.current_scene_id = (
                    participant_stager.current_scene.scene_id
                    if participant_stager.current_scene else None
                )
            session.socket_id = None
            session.is_connected = False
            session.last_updated_at = time.time()
        return  # Skip game cleanup, partner notifications, etc.

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
        # Note: Group reunion deferred to future matchmaker variant (REUN-01/REUN-02)

    # Handle Pyodide multiplayer games
    if PYODIDE_COORDINATOR is not None:
        # Iterate through all games to find this player
        for game_id, game_state in list(PYODIDE_COORDINATOR.games.items()):
            for player_id, socket_id in game_state.players.items():
                if socket_id == flask.request.sid:
                    # For Pyodide games, check if the game is active
                    is_in_active_pyodide_game = game_state.is_active

                    logger.info(
                        f"Player {player_id} (subject {subject_id}) disconnected "
                        f"from Pyodide game {game_id} (active={is_in_active_pyodide_game})"
                    )

                    # Record session termination for admin dashboard
                    if ADMIN_AGGREGATOR and is_in_active_pyodide_game:
                        # Build session snapshot with P2P health data
                        all_subject_ids = list(game_state.player_subjects.values())
                        p2p_health = ADMIN_AGGREGATOR._get_p2p_health_for_game(game_id)

                        session_snapshot = {
                            'game_id': game_id,
                            'subject_ids': all_subject_ids,
                            'p2p_health': p2p_health,
                            'frame_number': game_state.frame_number,
                            'created_at': game_state.created_at,
                        }

                        ADMIN_AGGREGATOR.record_session_termination(
                            game_id=game_id,
                            reason='partner_disconnected',
                            players=all_subject_ids,
                            details={
                                'disconnected_player': subject_id,
                                'disconnected_player_id': player_id,
                                'frame_at_disconnect': game_state.frame_number,
                            },
                            session_snapshot=session_snapshot
                        )

                    # Only notify others if player was in an active game
                    PYODIDE_COORDINATOR.remove_player(
                        game_id=game_id,
                        player_id=player_id,
                        notify_others=is_in_active_pyodide_game
                    )

                    # CRITICAL: Also clean up GameManager state
                    # The player may be in GameManager's waitroom (subject_games, waiting_games)
                    # even though they're also registered in PYODIDE_COORDINATOR
                    logger.info(
                        f"[Disconnect:Pyodide] Checking GameManager cleanup for {subject_id}. "
                        f"current_scene={current_scene.scene_id if current_scene else None}"
                    )
                    game_manager = GAME_MANAGERS.get(current_scene.scene_id, None) if current_scene else None
                    if game_manager:
                        in_game = game_manager.subject_in_game(subject_id)
                        logger.info(
                            f"[Disconnect:Pyodide] game_manager found, subject_in_game={in_game}, "
                            f"subject_games={list(game_manager.subject_games.keys())}, "
                            f"waiting_games={game_manager.waiting_games}"
                        )
                        if in_game:
                            logger.info(
                                f"[Disconnect:Pyodide] Calling remove_subject_quietly for {subject_id}"
                            )
                            game_manager.remove_subject_quietly(subject_id)
                            logger.info(
                                f"[Disconnect:Pyodide] After cleanup: "
                                f"subject_games={list(game_manager.subject_games.keys())}, "
                                f"waiting_games={game_manager.waiting_games}"
                            )
                    else:
                        logger.warning(
                            f"[Disconnect:Pyodide] No game_manager found for scene {current_scene.scene_id if current_scene else 'None'}"
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

    # Clean up waitroom state across all game managers
    # (waitroom participants aren't in subject_games, so subject_in_game() misses them)
    for _scene_id, _gm in GAME_MANAGERS.items():
        if subject_id in _gm.waitroom_participants:
            _gm.waitroom_participants.remove(subject_id)
            logger.info(
                f"[Disconnect] Removed {subject_id} from waitroom_participants "
                f"for scene {_scene_id}. Remaining: {_gm.waitroom_participants}"
            )

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
    logger.info(
        f"[Disconnect:Route] subject={subject_id}, "
        f"is_in_active_gym_scene={is_in_active_gym_scene}, "
        f"subject_in_game={game_manager.subject_in_game(subject_id)}, "
        f"waiting_games={game_manager.waiting_games}"
    )
    if is_in_active_gym_scene:
        logger.info(
            f"Subject {subject_id} disconnected from active game, triggering leave_game."
        )
        game_manager.leave_game(subject_id=subject_id)
    else:
        # Subject is not in an active game scene (e.g., in waitroom or survey)
        # Remove quietly without notifying group members
        logger.info(
            f"Subject {subject_id} disconnected from waitroom/non-active scene, "
            f"calling remove_subject_quietly."
        )
        result = game_manager.remove_subject_quietly(subject_id)
        logger.info(
            f"[Disconnect:Route] remove_subject_quietly returned {result}, "
            f"waiting_games after={game_manager.waiting_games}"
        )

    # Clean up group manager
    if GROUP_MANAGER:
        GROUP_MANAGER.cleanup_subject(subject_id)


def run(config):
    global app, CONFIG, logger, GENERIC_STAGER, PYODIDE_COORDINATOR, GROUP_MANAGER, ADMIN_AGGREGATOR, PROBE_COORDINATOR
    CONFIG = config
    GENERIC_STAGER = config.stager

    # Helper to look up GameManager by game_id for session state transitions
    def get_game_manager_for_game(game_id):
        """Look up which GameManager owns a specific game_id."""
        for scene_id, gm_instance in GAME_MANAGERS.items():
            if game_id in gm_instance.games:
                return gm_instance
        return None

    # Initialize Pyodide coordinator with game_manager_getter for session state transitions
    PYODIDE_COORDINATOR = pyodide_game_coordinator.PyodideGameCoordinator(
        socketio,
        game_manager_getter=get_game_manager_for_game
    )
    logger.info("Initialized Pyodide multiplayer coordinator")

    # Initialize player group manager
    GROUP_MANAGER = player_pairing_manager.PlayerGroupManager()
    logger.info("Initialized player group manager")

    # Initialize probe coordinator for P2P RTT measurement (Phase 57)
    PROBE_COORDINATOR = ProbeCoordinator(
        socketio=socketio,
        get_socket_for_subject=get_socket_for_subject,
        turn_username=CONFIG.turn_username,
        turn_credential=CONFIG.turn_credential,
    )
    logger.info("Initialized probe coordinator for P2P RTT measurement")

    # Initialize admin event aggregator
    ADMIN_AGGREGATOR = AdminEventAggregator(
        socketio=socketio,
        participant_sessions=PARTICIPANT_SESSIONS,
        stagers=STAGERS,
        game_managers=GAME_MANAGERS,
        pyodide_coordinator=PYODIDE_COORDINATOR,
        processed_subjects=PROCESSED_SUBJECT_NAMES,
        save_console_logs=CONFIG.save_experiment_data,
        experiment_id=CONFIG.experiment_id
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
