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
from interactive_gym.server import remote_game, utils, pyodide_game_coordinator
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
    ):
        assert isinstance(scene, gym_scene.GymScene)
        self.scene = scene
        self.experiment_config = experiment_config
        self.sio = sio
        self.pyodide_coordinator = pyodide_coordinator

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
        self.waitroom_timeouts = utils.ThreadSafeDict()

        # holds reset events so we only continue in game loop when triggered
        # this is not used when running with Pyodide
        self.reset_events = utils.ThreadSafeDict()

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
                self.pyodide_coordinator.create_game(game_id, num_players)
                logger.info(
                    f"Created multiplayer Pyodide game state for {game_id} "
                    f"with {num_players} players"
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
        if game_id in self.waiting_games:
            self.waiting_games.remove(game_id)

        self.sio.close_room(game_id)

        assert game_id not in self.games
        assert game_id not in self.reset_events
        assert game_id not in self.waitroom_timeouts
        assert game_id not in self.active_games
        assert game_id not in self.waiting_games

        logger.info(
            f"Successfully removed game {game_id} and closed the associated room."
        )

    def add_subject_to_game(
        self, subject_id: SubjectID
    ) -> remote_game.RemoteGameV2:
        """Add a subject to a game and return it."""
        logger.info(f"add_subject_to_game called for {subject_id}. Current waiting_games: {self.waiting_games}")
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
                    socket_id=flask.request.sid
                )
                logger.info(
                    f"Added player {player_id} to Pyodide coordinator for game {game.game_id}"
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
                        "message": "You were matched with a partner but your game ended because the other player disconnected."
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
        """End a game."""
        game = self.games[game_id]

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
