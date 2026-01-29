from __future__ import annotations
from typing import Any

import base64
import itertools
import logging
import random
import time
import uuid

import eventlet
import flask
import flask_socketio

from interactive_gym.utils.typing import SubjectID, GameID, RoomID

logger = logging.getLogger(__name__)


try:
    import cv2
except ImportError:
    cv2 = None
    print(
        "cv2 not installed. This is required if you're not "
        "defining a rendering function and want to (inefficiently) "
        "have the canvas display whatever is returned from `env.render('rgb_array')`."
    )

from interactive_gym.configurations import (
    configuration_constants,
    remote_config,
)
from interactive_gym.server import remote_game, utils, pyodide_game_coordinator, player_pairing_manager
from interactive_gym.scenes import stager, gym_scene, scene
import flask_socketio


class GameManager:
    """
    The GameManager class is responsible for managing the state of the server
    and the games being played for a particular Scene.
    """

    def __init__(
        self,
        scene: gym_scene.GymScene,
        experiment_config: remote_config.RemoteConfig,
        sio: flask_socketio.SocketIO,
        pyodide_coordinator: pyodide_game_coordinator.PyodideGameCoordinator | None = None,
        pairing_manager: player_pairing_manager.PlayerPairingManager | None = None,
    ):
        assert isinstance(scene, gym_scene.GymScene)
        self.scene = scene
        self.experiment_config = experiment_config
        self.sio = sio
        self.pyodide_coordinator = pyodide_coordinator
        self.pairing_manager = pairing_manager

        # Data structure to save subjects by their socket id
        self.subject = utils.ThreadSafeDict()

        # Data structure to save subjects games in memory OBJECTS by their socket id
        self.games: dict[GameID, remote_game.RemoteGameV2] = (
            utils.ThreadSafeDict()
        )

        # Map subjects to the game they're in
        self.subject_games: dict[SubjectID, GameID] = utils.ThreadSafeDict()

        # save subject IDs and the room they are in
        self.subject_rooms: dict[SubjectID] = utils.ThreadSafeDict()

        # Games that are currently being played
        self.active_games = utils.ThreadSafeSet()

        # Queue of games IDs that are waiting for additional players to join.
        self.waiting_games = []
        self.waiting_games_lock = eventlet.semaphore.Semaphore()  # Protect waiting_games access
        self.waitroom_timeouts = utils.ThreadSafeDict()

        # holds reset events so we only continue in game loop when triggered
        # this is not used when running with Pyodide
        self.reset_events = utils.ThreadSafeDict()

        # Group waitrooms: group_id -> list of subject_ids waiting together
        # Used when wait_for_known_group=True to reunite players from previous games
        self.group_waitrooms: dict[str, list[SubjectID]] = utils.ThreadSafeDict()
        # Track when each subject started waiting for their group members
        self.group_wait_start_times: dict[SubjectID, float] = utils.ThreadSafeDict()

    def subject_in_game(self, subject_id: SubjectID) -> bool:
        return subject_id in self.subject_games

    def _create_game(self) -> remote_game.RemoteGameV2:
        """Create a Game object corresponding to the specified Scene."""
        try:
            game_id = str(uuid.uuid4())

            # Even if we're using Pyodide, we'll still instantiate a RemoteGame, since
            # it'll track the players within a game.
            # TODO(chase): check if we actually do need this for Pyodide-based games...
            game = remote_game.RemoteGameV2(
                self.scene,
                experiment_config=self.experiment_config,
                game_id=game_id,
            )

            # Instantiate Game and add it to all the necessary data structures
            # game = Game(
            #     game_id=game_id,
            #     scene=self.scene,
            #     remote_game=remote_game,
            #     room=room,
            # )
            self.games[game_id] = game
            self.waiting_games.append(game_id)

            # The timeout is the wall clock time in which the waiting room will time out and
            # redirect anyone in it to a specified location/URL.
            self.waitroom_timeouts[game_id] = time.time() + (
                self.scene.waitroom_timeout / 1000
            )

            # Reset events make sure that we only reset once every player has triggered the event
            self.reset_events[game_id] = utils.ThreadSafeDict()

            # If this is a multiplayer Pyodide game, create coordinator state
            if self.scene.pyodide_multiplayer and self.pyodide_coordinator:
                num_players = len(self.scene.policy_mapping)  # Number of agents in the game

                # Get server-authoritative config from scene
                server_authoritative = getattr(self.scene, 'server_authoritative', False)
                state_broadcast_interval = getattr(self.scene, 'state_broadcast_interval', 30)
                environment_code = getattr(self.scene, 'environment_initialization_code', None)
                fps = getattr(self.scene, 'fps', 30)
                default_action = getattr(self.scene, 'default_action', 0) or 0
                action_population_method = getattr(self.scene, 'action_population_method', 'previous_submitted_action')
                realtime_mode = getattr(self.scene, 'realtime_mode', True)
                input_buffer_size = getattr(self.scene, 'input_buffer_size', 300)
                num_episodes = getattr(self.scene, 'num_episodes', 1)
                max_steps = getattr(self.scene, 'max_steps', 10000)

                # WebRTC TURN configuration from experiment config
                turn_username = getattr(self.experiment_config, 'turn_username', None)
                turn_credential = getattr(self.experiment_config, 'turn_credential', None)
                force_turn_relay = getattr(self.experiment_config, 'force_turn_relay', False)

                if turn_username:
                    logger.info(f"TURN config will be passed to game {game_id}: username={turn_username[:4]}..., force_relay={force_turn_relay}")
                else:
                    logger.warning(f"No TURN credentials for game {game_id}")

                self.pyodide_coordinator.create_game(
                    game_id=game_id,
                    num_players=num_players,
                    server_authoritative=server_authoritative,
                    environment_code=environment_code,
                    state_broadcast_interval=state_broadcast_interval,
                    fps=fps,
                    default_action=default_action,
                    action_population_method=action_population_method,
                    realtime_mode=realtime_mode,
                    input_buffer_size=input_buffer_size,
                    max_episodes=num_episodes,
                    max_steps=max_steps,
                    turn_username=turn_username,
                    turn_credential=turn_credential,
                    force_turn_relay=force_turn_relay,
                    scene_metadata=self.scene.scene_metadata,
                )
                logger.info(
                    f"Created multiplayer Pyodide game state for {game_id} "
                    f"with {num_players} players"
                    f"{' (server-authoritative)' if server_authoritative else ''}"
                )

        except Exception as e:
            logger.error(f"Error in `_create_game`: {e}")
            self.sio.emit(
                "create_game_failed",
                {"error": e.__repr__()},
                room=flask.request.sid,
            )
            raise e

    def _remove_game(self, game_id: GameID) -> None:
        """Remove a game from the server."""
        with self.waiting_games_lock:
            if game_id in self.waiting_games:
                self.waiting_games.remove(game_id)

        if game_id in self.games:
            del self.games[game_id]
        if game_id in self.reset_events:
            del self.reset_events[game_id]
        if game_id in self.waitroom_timeouts:
            del self.waitroom_timeouts[game_id]
        if game_id in self.active_games:
            self.active_games.remove(game_id)

        self.sio.close_room(game_id)

        assert game_id not in self.games
        assert game_id not in self.reset_events
        assert game_id not in self.waitroom_timeouts
        assert game_id not in self.active_games
        with self.waiting_games_lock:
            assert game_id not in self.waiting_games

        logger.info(
            f"Successfully removed game {game_id} and closed the associated room."
        )

    def add_subject_to_game(
        self, subject_id: SubjectID
    ) -> remote_game.RemoteGameV2 | None:
        """Add a subject to a game and return it.

        If wait_for_known_group is enabled and the subject has known group members,
        they will be added to a group-specific waitroom. Returns None if waiting
        for group members.

        Supports groups of any size (2 or more players).
        """
        logger.info(f"add_subject_to_game called for {subject_id}. Current waiting_games: {self.waiting_games}")

        # Check if we should wait for known group members
        if self.scene.wait_for_known_group and self.pairing_manager:
            group_members = self.pairing_manager.get_group_members(subject_id)
            if group_members:
                logger.info(f"Subject {subject_id} has known group members: {group_members}. Using group waitroom.")
                return self._join_or_wait_for_group(subject_id, group_members)

        # Standard FIFO matching
        return self._add_to_fifo_queue(subject_id)

    def _join_or_wait_for_group(
        self,
        subject_id: SubjectID,
        group_members: list[SubjectID]
    ) -> remote_game.RemoteGameV2 | None:
        """Handle matching with known group members.

        Supports groups of any size (2 or more players).
        Returns the game if all group members have arrived, None if still waiting.
        """
        group_id = self.pairing_manager.get_group_id(subject_id)
        if not group_id:
            logger.warning(f"Subject {subject_id} has group members but no group_id. Falling back to FIFO.")
            return self._add_to_fifo_queue(subject_id)

        # Get all members of this group
        all_group_members = self.pairing_manager.get_all_group_members(subject_id)
        num_players_needed = len([
            policy for policy in self.scene.policy_mapping.values()
            if policy == configuration_constants.PolicyTypes.Human
        ])

        # Check if group member(s) are already waiting
        if group_id in self.group_waitrooms:
            waiting_subjects = self.group_waitrooms[group_id]

            # Add this subject to the waitroom
            if subject_id not in waiting_subjects:
                waiting_subjects.append(subject_id)
                self.group_wait_start_times[subject_id] = time.time()
                logger.info(f"Subject {subject_id} joined group waitroom {group_id}. "
                           f"Now {len(waiting_subjects)}/{num_players_needed} players waiting.")

            # Check if all group members have arrived
            if len(waiting_subjects) >= num_players_needed:
                logger.info(f"All group members arrived for group {group_id}. Creating game.")
                # Clear the group waitroom
                del self.group_waitrooms[group_id]
                for sid in waiting_subjects:
                    if sid in self.group_wait_start_times:
                        del self.group_wait_start_times[sid]
                # Create game for these specific group members
                return self._create_game_for_group(waiting_subjects)
            else:
                # Still waiting for more group members
                self._broadcast_group_waiting_status(subject_id, group_id, waiting_subjects, num_players_needed)
                return None
        else:
            # Start a new group waitroom
            self.group_waitrooms[group_id] = [subject_id]
            self.group_wait_start_times[subject_id] = time.time()
            logger.info(f"Subject {subject_id} started group waitroom {group_id}. "
                       f"Waiting for {num_players_needed - 1} more group member(s).")
            self._broadcast_group_waiting_status(subject_id, group_id, [subject_id], num_players_needed)
            return None

    def _broadcast_group_waiting_status(
        self,
        subject_id: SubjectID,
        group_id: str,
        waiting_subjects: list[SubjectID],
        num_players_needed: int
    ):
        """Broadcast waiting status to subjects waiting for their group members."""
        group_wait_timeout = self.scene.group_wait_timeout
        start_time = self.group_wait_start_times.get(subject_id, time.time())
        elapsed_ms = (time.time() - start_time) * 1000
        remaining_ms = max(0, group_wait_timeout - elapsed_ms)

        self.sio.emit(
            "waiting_for_group",
            {
                "message": "Waiting for your group members from the previous game...",
                "cur_num_players": len(waiting_subjects),
                "players_needed": num_players_needed - len(waiting_subjects),
                "ms_remaining": remaining_ms,
            },
            room=flask.request.sid,
        )

    def _create_game_for_group(
        self,
        subject_ids: list[SubjectID]
    ) -> remote_game.RemoteGameV2:
        """Create a game for a specific group of players."""
        with self.waiting_games_lock:
            # Create a new game
            self._create_game()
            game: remote_game.RemoteGameV2 = self.games[self.waiting_games[-1]]

            # Add each partner to the game
            for subject_id in subject_ids:
                self._add_subject_to_specific_game(subject_id, game)

            # The game should now be ready
            if game.is_ready_to_start():
                self.waiting_games.remove(game.game_id)
                self.start_game(game)

        return game

    def _add_subject_to_specific_game(
        self,
        subject_id: SubjectID,
        game: remote_game.RemoteGameV2
    ):
        """Add a subject to a specific game (used for group matching)."""
        with game.lock:
            self.subject_games[subject_id] = game.game_id
            self.subject_rooms[subject_id] = game.game_id
            self.reset_events[game.game_id][subject_id] = eventlet.event.Event()
            # Note: join_room needs the request context, so we emit to the subject
            # and they'll join the room on their end via start_game

            available_human_agent_ids = game.get_available_human_agent_ids()
            player_id = None
            if not available_human_agent_ids:
                logger.warning(
                    f"No available human agent IDs for game {game.game_id}. Adding as a spectator."
                )
            else:
                player_id = random.choice(available_human_agent_ids)
                game.add_player(player_id, subject_id)

            # If multiplayer Pyodide, add player to coordinator
            if self.scene.pyodide_multiplayer and self.pyodide_coordinator and player_id is not None:
                # Get the socket_id for this subject from the pairing manager
                # For now, we'll need to handle this separately
                logger.info(
                    f"Added player {player_id} (subject: {subject_id}) to game {game.game_id}"
                )

            if self.scene.game_page_html_fn is not None:
                self.sio.emit(
                    "update_game_page_text",
                    {
                        "game_page_text": self.scene.game_page_html_fn(
                            game, subject_id
                        )
                    },
                    room=subject_id,
                )

    def _add_to_fifo_queue(
        self, subject_id: SubjectID
    ) -> remote_game.RemoteGameV2:
        """Add a subject to the standard FIFO matching queue."""
        # Use lock to prevent race conditions when multiple participants join simultaneously
        with self.waiting_games_lock:
            if not self.waiting_games:
                logger.info("No games waiting for players. Creating a new game.")
                self._create_game()
                logger.info(f"Created game. waiting_games now: {self.waiting_games}")

            game: remote_game.RemoteGameV2 = self.games[self.waiting_games[0]]
            logger.info(f"Adding subject {subject_id} to game {game.game_id}. Game has {len(game.human_players)} players, needs {len(self.scene.policy_mapping)}")
            with game.lock:
                self.subject_games[subject_id] = game.game_id
                self.subject_rooms[subject_id] = game.game_id
                self.reset_events[game.game_id][subject_id] = eventlet.event.Event()
                flask_socketio.join_room(game.game_id)

                available_human_agent_ids = game.get_available_human_agent_ids()
                player_id = None
                if not available_human_agent_ids:
                    logger.warning(
                        f"No available human agent IDs for game {game.game_id}. Adding as a spectator."
                    )
                else:
                    player_id = random.choice(available_human_agent_ids)
                    game.add_player(player_id, subject_id)

                # If multiplayer Pyodide, add player to coordinator
                if self.scene.pyodide_multiplayer and self.pyodide_coordinator and player_id is not None:
                    self.pyodide_coordinator.add_player(
                        game_id=game.game_id,
                        player_id=player_id,
                        socket_id=flask.request.sid,
                        subject_id=subject_id  # Pass subject_id for data logging
                    )
                    logger.info(
                        f"Added player {player_id} (subject: {subject_id}) to Pyodide coordinator for game {game.game_id}"
                    )

                if self.scene.game_page_html_fn is not None:
                    self.sio.emit(
                        "update_game_page_text",
                        {
                            "game_page_text": self.scene.game_page_html_fn(
                                game, subject_id
                            )
                        },
                        room=subject_id,
                    )

                # If the game is ready to start, we'll remove it from WAITING_GAMES.
                is_ready = game.is_ready_to_start()
                logger.info(f"Game {game.game_id} ready to start: {is_ready}. Available slots: {game.get_available_human_agent_ids()}")
                if is_ready:
                    logger.info(f"Removing game {game.game_id} from waiting_games")
                    self.waiting_games.remove(game.game_id)
                    assert game.game_id not in self.waiting_games

                if is_ready:
                    self.start_game(game)
                else:
                    # Broadcast to all players in the room so everyone sees updated count
                    self.broadcast_waiting_room_status(game.game_id)

        return game

    def send_participant_to_waiting_room(self, subject_id: SubjectID):
        """Send a participant to the waiting room for the game that they're assigned to."""
        logger.info(f"Sending subject {subject_id} to the waiting room.")
        game = self.get_subject_game(subject_id)

        remaining_wait_time = (
            self.waitroom_timeouts[game.game_id] - time.time()
        ) * 1000

        self.sio.emit(
            "waiting_room",
            {
                "cur_num_players": game.cur_num_human_players(),
                "players_needed": len(game.get_available_human_agent_ids()),
                "ms_remaining": remaining_wait_time,
                "waitroom_timeout_message": self.scene.waitroom_timeout_message,
            },
            room=subject_id,
        )

    def broadcast_waiting_room_status(self, game_id: GameID):
        """Broadcast waiting room status to all players in the game room."""
        game = self.games.get(game_id)
        if game is None or game_id not in self.waiting_games:
            return

        remaining_wait_time = (
            self.waitroom_timeouts[game_id] - time.time()
        ) * 1000

        logger.info(
            f"Broadcasting waiting room status for game {game_id}: "
            f"{game.cur_num_human_players()} players, "
            f"{len(game.get_available_human_agent_ids())} needed"
        )

        self.sio.emit(
            "waiting_room",
            {
                "cur_num_players": game.cur_num_human_players(),
                "players_needed": len(game.get_available_human_agent_ids()),
                "ms_remaining": remaining_wait_time,
                "waitroom_timeout_message": self.scene.waitroom_timeout_message,
            },
            room=game_id,
        )

    def get_subject_game(
        self, subject_id: SubjectID
    ) -> remote_game.RemoteGameV2:
        """Get the game that a subject is in."""
        return self.games.get(self.subject_games.get(subject_id))

    def leave_game(self, subject_id: SubjectID) -> bool:
        """Handle the logic for when a subject leaves a game."""
        game_id = self.subject_games.get(subject_id)

        if game_id is None:
            logger.warning(
                f"{subject_id} attempted to leave but there's no matching game ID."
            )
            return False

        game = self.games.get(game_id)
        if game is None:
            logger.warning(
                f"{subject_id} attempted to leave but the game with ID {game_id} doesn't exist."
            )
            return False

        with game.lock:
            self.remove_subject(subject_id)

            game_was_active = (
                game.game_id in self.active_games
                and game.status
                in [
                    remote_game.GameStatus.Active,
                    remote_game.GameStatus.Reset,
                ]
            )
            game_is_empty = game.cur_num_human_players() == 0

            if game_was_active and game_is_empty:
                exit_status = utils.GameExitStatus.ActiveNoPlayers
                logger.info(
                    f"Subject {subject_id} left game {game.game_id} with exit status {exit_status}. Cleaning up."
                )
                self.cleanup_game(game_id)

            # If the game wasn't active and there are no players,
            # cleanup the traces of the game.
            elif game_is_empty:
                exit_status = utils.GameExitStatus.InactiveNoPlayers
                logger.info(
                    f"Subject {subject_id} left game {game.game_id} with exit status {exit_status}. Cleaning up."
                )
                self.cleanup_game(game_id)

            # if the game was not active and not empty, the remaining players are still in the waiting room.
            elif not game_was_active:
                exit_status = utils.GameExitStatus.InactiveWithOtherPlayers
                logger.info(
                    f"Subject {subject_id} left game {game.game_id} with exit status {exit_status}. "
                    f"Notifying remaining players and ending lobby."
                )

                # Notify remaining players that someone left and end the lobby
                self.sio.emit(
                    "waiting_room_player_left",
                    {
                        "message": "Another player left the waiting room. You will be redirected shortly..."
                    },
                    room=game.game_id,
                )

                # Give clients a moment to receive the message before cleanup
                eventlet.sleep(0.1)

                # Cleanup the game since we're ending the lobby
                self.cleanup_game(game_id)

            elif game_was_active and not game_is_empty:
                exit_status = utils.GameExitStatus.ActiveWithOtherPlayers
                logger.info(
                    f"Subject {subject_id} left game {game.game_id} with exit status {exit_status}. Cleaning up."
                )

                # Emit end_game to remaining players BEFORE cleanup
                # so they receive the message before the room is closed
                self.sio.emit(
                    "end_game",
                    {
                        "message": "Your game ended because another player disconnected."
                    },
                    room=game.game_id,
                )

                # Give clients a moment to receive the message before cleanup
                eventlet.sleep(0.1)

                self.cleanup_game(game_id)

            else:
                raise NotImplementedError("Something went wrong on exit!")

            # For ActiveNoPlayers, trigger callback (no players to notify)
            if exit_status == utils.GameExitStatus.ActiveNoPlayers:
                if self.scene.callback is not None:
                    self.scene.callback.on_game_end(game)
            # Note: ActiveWithOtherPlayers already emits end_game with message above
            # and calls cleanup_game, so no additional emit needed here

        return exit_status

    def remove_subject(self, subject_id: SubjectID):
        """Remove a subject from their game."""
        game_id = self.subject_games[subject_id]
        game = self.games[game_id]
        game.remove_human_player(subject_id)

        # Remove the subject from the game
        del self.subject_games[subject_id]
        del self.subject_rooms[subject_id]

        # Use flask_socketio.leave_room instead of self.sio.leave_room
        flask_socketio.leave_room(game_id)

        # If the game is now empty, remove it
        if not game.cur_num_human_players():
            self._remove_game(game_id)

    def start_game(self, game: remote_game.RemoteGameV2):
        """Start a game."""
        logger.info(
            f"Starting game {game.game_id} with subjects {[sid for sid in game.human_players.values()]}"
        )
        self.active_games.add(game.game_id)

        self.sio.emit(
            "start_game",
            {
                "scene_metadata": self.scene.scene_metadata,
                "game_id": game.game_id,
                # "experiment_config": self.experiment_config.to_dict(),
            },
            room=game.game_id,
        )

        if not self.scene.run_through_pyodide:
            self.sio.start_background_task(self.run_server_game, game)

    def run_server_game(self, game: remote_game.RemoteGameV2):
        """Run a remote game on the server."""
        end_status = [
            remote_game.GameStatus.Inactive,
            remote_game.GameStatus.Done,
        ]

        with game.lock:
            game.reset()

            if self.scene.callback is not None:
                self.scene.callback.on_episode_start(game)

        self.render_server_game(game)

        while game.status not in end_status:

            with game.lock:
                if self.scene.callback is not None:
                    self.scene.callback.on_game_tick_start(game)

                game.tick()

                if self.scene.callback is not None:
                    self.scene.callback.on_game_tick_end(game)

            self.render_server_game(game)

            if (
                self.scene.input_mode
                == configuration_constants.InputModes.PressedKeys
            ):
                self.sio.emit("request_pressed_keys", {})

            self.sio.sleep(1 / game.scene.fps)

            if (
                game.status == remote_game.GameStatus.Reset
                or game.status == remote_game.GameStatus.Done
            ):
                if self.scene.callback is not None:
                    self.scene.callback.on_episode_end(game)

            if game.status == remote_game.GameStatus.Reset:
                eventlet.sleep(self.scene.reset_freeze_s)
                self.sio.emit(
                    "game_reset",
                    {
                        "timeout": self.scene.reset_timeout,
                        "config": self.scene.scene_metadata,
                        "room": game.game_id,
                    },
                    room=game.game_id,
                )

                game.reset_event.wait()

                # Replace the events for each player with new eventlet.event.Event instances
                for player_id in self.reset_events[game.game_id].keys():
                    self.reset_events[game.game_id][
                        player_id
                    ] = eventlet.event.Event()

                # Clear the game reset event
                game.set_reset_event()

                with game.lock:
                    game.reset()
                    if self.scene.callback is not None:
                        self.scene.callback.on_episode_start(game)

                self.render_server_game(game)

                self.sio.sleep(1 / game.scene.fps)

        with game.lock:
            logger.info(
                f"Game loop ended for {game.game_id}, ending and cleaning up."
            )
            if game.status != remote_game.GameStatus.Inactive:
                game.tear_down()

            if self.scene.callback is not None:
                self.scene.callback.on_game_end(game)
            self.sio.emit(
                "end_game",
                {},
                room=game.game_id,
            )
            self.cleanup_game(game.game_id)

    def trigger_reset(self, subject_id: SubjectID):
        game = self.get_subject_game(subject_id)
        if game is None:
            logger.warning(
                f"Received a reset event for subject {subject_id} for a non-existent game."
            )
            return

        game_resets = self.reset_events.get(game.game_id)
        if game_resets is None:
            logger.warning(
                f"Received a reset event for subject {subject_id} for a game that doesn't have any reset events."
            )
            return

        subject_reset_event = game_resets.get(subject_id)
        if subject_reset_event is None:
            logger.warning(
                f"Received a reset event for subject {subject_id} that doesn't have a reset event."
            )
            return

        subject_reset_event.send()

        if all(e.ready() for e in game_resets.values()):
            game.reset_event.send()

    def process_pressed_keys(
        self,
        subject_id: SubjectID,
        pressed_keys: list,
    ) -> None:
        game = self.get_subject_game(subject_id)

        if game is None:
            return

        subject_agent_id = None
        for agent_id, sid in game.human_players.items():
            if subject_id == sid:
                subject_agent_id = agent_id
                break

        if subject_agent_id is None:
            logger.error(
                f"Subject {subject_id} is not in game {game.game_id} but we received key presses."
            )

        # No keys pressed, queue the default action
        if len(pressed_keys) == 0:
            game.enqueue_action(subject_agent_id, self.scene.default_action)

        elif len(pressed_keys) > 1:
            if not self.scene.game_has_composite_actions:
                pressed_keys = pressed_keys[:1]
            else:
                pressed_keys = self.generate_composite_action(pressed_keys)

        if game is None:
            return

        if not any([k in self.scene.action_mapping for k in pressed_keys]):
            return

        action = None
        for k in pressed_keys:
            if k in self.scene.action_mapping:
                action = self.scene.action_mapping[k]
                break

        assert action is not None

        game.enqueue_action(subject_agent_id, action)

    def generate_composite_action(self, pressed_keys) -> list[tuple[str]]:
        max_composite_action_size = max(
            [
                len(k)
                for k in self.scene.action_mapping.keys()
                if isinstance(k, tuple)
            ]
            + [0]
        )

        if max_composite_action_size > 1:
            composite_actions = [
                action
                for action in self.scene.action_mapping
                if isinstance(action, tuple)
            ]

            composites = [
                tuple(sorted(action_comp))
                for action_comp in itertools.combinations(
                    pressed_keys, max_composite_action_size
                )
            ]
            for composite in composites:
                if composite in composite_actions:
                    pressed_keys = [composite]
                    break

        return pressed_keys

    def render_server_game(self, game: remote_game.RemoteGameV2):
        state = None
        encoded_image = None
        if self.scene.env_to_state_fn is not None:
            # generate a state object representation
            state = self.scene.env_to_state_fn(game.env, self.scene)
        else:
            # Generate a base64 image of the game and send it to display
            assert (
                cv2 is not None
            ), "Must install cv2 to use default image rendering!"
            assert (
                game.env.render_mode == "rgb_array"
            ), "Env must be using render mode `rgb_array`!"

            game_image = game.env.render()
            _, encoded_image = cv2.imencode(
                ".jpg", game_image, [cv2.IMWRITE_JPEG_QUALITY, 75]
            )
            # encoded_image = base64.b64encode(encoded_image).decode()

        hud_text = (
            self.scene.hud_text_fn(game)
            if self.scene.hud_text_fn is not None
            else None
        )

        # TODO(chase): this emits the same state to every player in a room, but we may want
        #   to have different observations for each player. Figure that out (maybe state is a dict
        #   with player_ids and their respective observations?).
        self.sio.emit(
            "environment_state",
            {
                "game_state_objects": state,
                "game_image_binary": encoded_image.tobytes(),
                "step": game.tick_num,
                "hud_text": hud_text,
            },
            room=game.game_id,
        )

    def cleanup_game(self, game_id: GameID):
        """End a game and persist player groups."""
        game = self.games[game_id]

        # Always record player groups when a game ends
        # This allows future scenes to either require the same group or allow new matches
        if self.pairing_manager:
            subject_ids = list(game.human_players.values())
            # Filter out "Available" placeholders
            real_subjects = [
                sid for sid in subject_ids
                if sid != utils.Available and sid is not None
            ]
            if len(real_subjects) > 1:
                self.pairing_manager.create_group(real_subjects, self.scene.scene_id)
                logger.info(
                    f"Created/updated group for subjects {real_subjects} from scene {self.scene.scene_id}"
                )

        if self.scene.callback is not None:
            self.scene.callback.on_game_end(game)

        game.tear_down()

        self._remove_game(game_id)

        # TODO(chase): do we need this?
        # self.sio.emit("end_game", {}, room=game_id)

    def tear_down(self) -> None:
        """End all games, but make sure we trigger the ending callbacks."""
        for game in self.games.values():
            self.cleanup_game(game.game_id)

    def remove_subject_quietly(self, subject_id: SubjectID) -> bool:
        """Remove a subject from their game without notifying other players.

        Used when a player disconnects from a non-active scene (e.g., during a survey)
        so their group members don't receive a disconnect notification.

        Returns True if subject was removed, False if not found.
        """
        game_id = self.subject_games.get(subject_id)
        if game_id is None:
            return False

        game = self.games.get(game_id)
        if game is None:
            return False

        with game.lock:
            # Just remove the subject without any notifications
            game.remove_human_player(subject_id)

            if subject_id in self.subject_games:
                del self.subject_games[subject_id]
            if subject_id in self.subject_rooms:
                del self.subject_rooms[subject_id]

            flask_socketio.leave_room(game_id)

            # If game is now empty, clean it up quietly
            if game.cur_num_human_players() == 0:
                game.tear_down()
                self._remove_game(game_id)

        logger.info(f"Quietly removed subject {subject_id} from game {game_id}")
        return True

    def remove_from_group_waitroom(self, subject_id: SubjectID) -> bool:
        """Remove a subject from a group waitroom if they're waiting.

        Returns True if subject was in a group waitroom, False otherwise.
        """
        # Find if subject is in any group waitroom
        for group_id, waiting_subjects in list(self.group_waitrooms.items()):
            if subject_id in waiting_subjects:
                waiting_subjects.remove(subject_id)
                if subject_id in self.group_wait_start_times:
                    del self.group_wait_start_times[subject_id]

                # If waitroom is now empty, remove it
                if not waiting_subjects:
                    del self.group_waitrooms[group_id]
                else:
                    # Notify remaining subjects that a group member left
                    for remaining_sid in waiting_subjects:
                        self.sio.emit(
                            "waiting_room_player_left",
                            {
                                "message": "A group member disconnected. You will be redirected shortly..."
                            },
                            room=remaining_sid,
                        )

                logger.info(f"Removed subject {subject_id} from group waitroom {group_id}")
                return True

        return False

    def check_group_wait_timeouts(self) -> list[SubjectID]:
        """Check for subjects who have exceeded their group wait timeout.

        Returns list of subject IDs that timed out.
        """
        timed_out = []
        current_time = time.time()
        timeout_seconds = self.scene.group_wait_timeout / 1000

        for subject_id, start_time in list(self.group_wait_start_times.items()):
            if current_time - start_time > timeout_seconds:
                timed_out.append(subject_id)

        return timed_out

    def handle_group_wait_timeout(self, subject_id: SubjectID):
        """Handle a group wait timeout by removing from waitroom and redirecting."""
        # Remove from group waitroom
        self.remove_from_group_waitroom(subject_id)

        # Redirect to timeout URL
        redirect_url = self.scene.waitroom_timeout_redirect_url
        if redirect_url:
            self.sio.emit(
                "request_redirect",
                {"redirect_url": redirect_url},
                room=subject_id,
            )
            logger.info(f"Redirecting timed-out subject {subject_id} to {redirect_url}")
        else:
            # No redirect URL configured, emit error
            self.sio.emit(
                "end_game",
                {"message": "Group members did not arrive in time. Please try again later."},
                room=subject_id,
            )
            logger.info(f"Subject {subject_id} timed out waiting for group members, no redirect URL configured")

    def is_subject_in_active_game(self, subject_id: SubjectID) -> bool:
        """Check if a subject is currently in an active game.

        Used for disconnect handling to determine whether to notify group members.
        """
        game_id = self.subject_games.get(subject_id)
        if game_id is None:
            return False

        game = self.games.get(game_id)
        if game is None:
            return False

        return (
            game_id in self.active_games
            and game.status in [
                remote_game.GameStatus.Active,
                remote_game.GameStatus.Reset,
            ]
        )
