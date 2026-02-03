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
from interactive_gym.server.remote_game import SessionState
from interactive_gym.server.participant_state import ParticipantState
from interactive_gym.server.matchmaker import Matchmaker, MatchCandidate, FIFOMatchmaker
from interactive_gym.server.match_logger import MatchAssignmentLogger
from interactive_gym.scenes import stager, gym_scene, scene

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from interactive_gym.server.probe_coordinator import ProbeCoordinator
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
        get_subject_rtt: callable | None = None,
        participant_state_tracker=None,  # Optional for backward compatibility
        matchmaker: Matchmaker | None = None,  # Phase 55: pluggable matchmaking
        match_logger: MatchAssignmentLogger | None = None,  # Phase 56: assignment logging
        probe_coordinator: "ProbeCoordinator | None" = None,  # Phase 59: P2P RTT probing
    ):
        assert isinstance(scene, gym_scene.GymScene)
        self.scene = scene
        self.experiment_config = experiment_config
        self.sio = sio
        self.pyodide_coordinator = pyodide_coordinator
        self.pairing_manager = pairing_manager
        self.get_subject_rtt = get_subject_rtt  # Callback to get RTT for a subject
        self.participant_state_tracker = participant_state_tracker  # Phase 54
        self.matchmaker = matchmaker or FIFOMatchmaker()  # Phase 55: defaults to FIFO
        self.match_logger = match_logger  # Phase 56: assignment logging
        self.probe_coordinator = probe_coordinator  # Phase 59: P2P RTT probing

        # Pending matches waiting for P2P RTT probe results (Phase 59)
        # probe_session_id -> match context dict
        self._pending_matches: dict[str, dict] = {}

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

    def subject_in_game(self, subject_id: SubjectID) -> bool:
        return subject_id in self.subject_games

    def validate_subject_state(self, subject_id: SubjectID) -> tuple[bool, str | None]:
        """Validate subject state before adding to a game.

        Checks for invalid states that could cause routing issues:
        - Subject already in subject_games but game doesn't exist
        - Subject in subject_rooms but not in subject_games
        - Subject in a game that's already ended

        Returns:
            (is_valid, error_message) - True if state is valid, False with error message if not
        """
        # Check for orphaned subject_games entry
        if subject_id in self.subject_games:
            game_id = self.subject_games[subject_id]
            if game_id not in self.games:
                logger.warning(
                    f"[StateValidation] Subject {subject_id} has orphaned subject_games entry. "
                    f"game_id={game_id} not in games. Cleaning up."
                )
                # Clean up orphaned entry
                del self.subject_games[subject_id]
                if subject_id in self.subject_rooms:
                    del self.subject_rooms[subject_id]
                return (True, None)  # Cleaned up, can proceed

            game = self.games[game_id]
            # Check if game is in a terminal state
            if game.status == remote_game.GameStatus.Done or game.status == remote_game.GameStatus.Inactive:
                logger.warning(
                    f"[StateValidation] Subject {subject_id} mapped to finished game. "
                    f"game_id={game_id}, status={game.status}. Cleaning up."
                )
                # Clean up stale entry
                game.remove_human_player(subject_id)
                del self.subject_games[subject_id]
                if subject_id in self.subject_rooms:
                    del self.subject_rooms[subject_id]
                return (True, None)  # Cleaned up, can proceed

        # Check for orphaned subject_rooms entry (should not exist without subject_games)
        if subject_id in self.subject_rooms and subject_id not in self.subject_games:
            logger.warning(
                f"[StateValidation] Subject {subject_id} has orphaned subject_rooms entry. Cleaning up."
            )
            del self.subject_rooms[subject_id]
            return (True, None)  # Cleaned up, can proceed

        return (True, None)  # All checks passed

    def _create_game(self) -> remote_game.RemoteGameV2:
        """Create a Game object corresponding to the specified Scene."""
        try:
            game_id = str(uuid.uuid4())

            # Even if we're using Pyodide, we'll still instantiate a RemoteGame, since
            # it'll track the players within a game.
            # TODO(chase): check if we actually do need this for Pyodide-based games...
            # Game starts in SessionState.WAITING (set in RemoteGameV2.__init__)
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

        All games are created through the matchmaker path (FIFO queue by default).
        The matchmaker decides when to form groups based on waiting participants.

        Note: Group reunion (wait_for_known_group) is deferred to a future matchmaker
        variant (see REUN-01/REUN-02 in REQUIREMENTS.md). The wait_for_known_group
        config is accepted but currently behaves as FIFO matching.
        """
        logger.info(f"add_subject_to_game called for {subject_id}. Current waiting_games: {self.waiting_games}")

        # Group reunion is deferred to future matchmaker variant (REUN-01/REUN-02)
        if self.scene.wait_for_known_group:
            logger.warning(
                f"[GroupReunion] wait_for_known_group=True is currently deferred. "
                f"Subject {subject_id} will use standard FIFO matching. "
                f"See REUN-01/REUN-02 for future matchmaker variant."
            )

        # All games go through standard matchmaker path
        return self._add_to_fifo_queue(subject_id)

    def _add_subject_to_specific_game(
        self,
        subject_id: SubjectID,
        game: remote_game.RemoteGameV2
    ) -> bool:
        """Add a subject to a specific game (used for group matching).

        Returns True if the player was successfully added, False otherwise.
        """
        with game.lock:
            # Safety check: verify game has available slots
            available_human_agent_ids = game.get_available_human_agent_ids()
            if not available_human_agent_ids:
                logger.error(
                    f"No available slots in game {game.game_id} for subject {subject_id}. "
                    f"Current players: {game.cur_num_human_players()}, "
                    f"Human players: {list(game.human_players.values())}"
                )
                return False

            self.subject_games[subject_id] = game.game_id
            self.subject_rooms[subject_id] = game.game_id
            self.reset_events[game.game_id][subject_id] = eventlet.event.Event()
            # Note: join_room needs the request context, so we emit to the subject
            # and they'll join the room on their end via start_game

            player_id = random.choice(available_human_agent_ids)
            player_added = game.add_player(player_id, subject_id)
            if not player_added:
                logger.error(
                    f"Failed to add subject {subject_id} to slot {player_id} in game {game.game_id}. "
                    f"Cleaning up partial state."
                )
                # Clean up the partial state we added
                del self.subject_games[subject_id]
                del self.subject_rooms[subject_id]
                del self.reset_events[game.game_id][subject_id]
                return False

            # If multiplayer Pyodide, add player to coordinator
            if self.scene.pyodide_multiplayer and self.pyodide_coordinator:
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

            return True

    def _is_rtt_compatible(self, subject_id: SubjectID, game: remote_game.RemoteGameV2) -> bool:
        """Check if a subject's RTT is compatible with players already in a game.

        Returns True if:
        - No matchmaking_max_rtt is configured
        - No get_subject_rtt callback is available
        - The subject's RTT is within max_rtt of all existing players
        """
        max_rtt_diff = self.scene.matchmaking_max_rtt
        if max_rtt_diff is None or self.get_subject_rtt is None:
            return True

        subject_rtt = self.get_subject_rtt(subject_id)
        if subject_rtt is None:
            # No RTT measurement yet, allow pairing
            logger.debug(f"No RTT measurement for {subject_id}, allowing pairing")
            return True

        # Check against all players already in the game
        for player_id, existing_subject_id in game.human_players.items():
            if existing_subject_id == utils.Available:
                continue

            existing_rtt = self.get_subject_rtt(existing_subject_id)
            if existing_rtt is None:
                # Existing player has no RTT measurement, allow pairing
                continue

            rtt_diff = abs(subject_rtt - existing_rtt)
            if rtt_diff > max_rtt_diff:
                logger.info(
                    f"RTT incompatible: {subject_id} (RTT={subject_rtt}ms) vs "
                    f"{existing_subject_id} (RTT={existing_rtt}ms), diff={rtt_diff}ms > max={max_rtt_diff}ms"
                )
                return False

        logger.debug(f"RTT compatible: {subject_id} (RTT={subject_rtt}ms)")
        return True

    def _get_waiting_subject_ids(self) -> list[SubjectID]:
        """Get list of subject IDs currently waiting in the waitroom.

        Collects subjects from all games in the waiting_games queue.
        """
        waiting_subjects = []
        for game_id in self.waiting_games:
            game = self.games.get(game_id)
            if game:
                for player_id, subject_id in game.human_players.items():
                    if subject_id and subject_id != utils.Available:
                        waiting_subjects.append(subject_id)
        return waiting_subjects

    def _get_group_size(self) -> int:
        """Get the number of human players needed for a full game."""
        return len([
            p for p in self.scene.policy_mapping.values()
            if p == configuration_constants.PolicyTypes.Human
        ])

    def _add_to_fifo_queue(
        self, subject_id: SubjectID
    ) -> remote_game.RemoteGameV2 | None:
        """Add a subject to the standard FIFO matching queue.

        Uses the matchmaker to decide when to form groups. If matchmaking_max_rtt
        is configured, RTT filtering is applied before the matchmaker decision.

        Phase 55: Delegates matching decision to self.matchmaker.find_match()
        Phase 59: If P2P RTT probing enabled, defers game creation until probe completes.

        Returns:
            The game if created immediately, or None if waiting for probe/waitroom.
        """
        # Use lock to prevent race conditions when multiple participants join simultaneously
        with self.waiting_games_lock:
            # Build MatchCandidate for arriving participant
            arriving = MatchCandidate(
                subject_id=subject_id,
                rtt_ms=self.get_subject_rtt(subject_id) if self.get_subject_rtt else None,
            )

            # Build waiting list from RTT-compatible participants
            # Note: RTT filtering is applied here, before calling the matchmaker
            waiting = []
            for game_id in self.waiting_games:
                candidate_game = self.games.get(game_id)
                if candidate_game and self._is_rtt_compatible(subject_id, candidate_game):
                    for player_id, sid in candidate_game.human_players.items():
                        if sid and sid != utils.Available:
                            waiting.append(MatchCandidate(
                                subject_id=sid,
                                rtt_ms=self.get_subject_rtt(sid) if self.get_subject_rtt else None,
                            ))

            group_size = self._get_group_size()

            # Delegate matching decision to matchmaker (Phase 55)
            matched = self.matchmaker.find_match(arriving, waiting, group_size)

            if matched is None:
                # No match yet - add arriving participant to waitroom
                logger.info(f"Matchmaker returned None for {subject_id}. Adding to waitroom. "
                           f"Waiting: {len(waiting)}, Group size: {group_size}")
                return self._add_to_waitroom(subject_id)

            # Match found - check if P2P RTT probing is needed (Phase 59)
            logger.info(f"Matchmaker matched {len(matched)} participants: "
                       f"{[c.subject_id for c in matched]}")

            needs_probe = (
                self.probe_coordinator is not None
                and self.matchmaker.max_p2p_rtt_ms is not None
            )

            if needs_probe:
                # Defer game creation until probe completes
                return self._probe_and_create_game(matched, subject_id)
            else:
                # Create game immediately (no P2P RTT filtering)
                return self._create_game_for_match(matched, subject_id)

    def _add_to_waitroom(self, subject_id: SubjectID) -> remote_game.RemoteGameV2:
        """Add a participant to the waitroom when no match is available yet.

        Creates a new game or finds existing RTT-compatible game to place participant.
        """
        # Find a compatible game based on RTT
        compatible_game = None
        for game_id in self.waiting_games:
            candidate_game = self.games.get(game_id)
            if candidate_game and self._is_rtt_compatible(subject_id, candidate_game):
                compatible_game = candidate_game
                break

        if compatible_game is None:
            # No compatible game found, create a new one
            logger.info(f"No RTT-compatible game found for {subject_id}. Creating a new game.")
            self._create_game()
            logger.info(f"Created game. waiting_games now: {self.waiting_games}")
            compatible_game = self.games[self.waiting_games[-1]]

        game = compatible_game

        with game.lock:
            # Double-check availability inside the lock
            available_human_agent_ids = game.get_available_human_agent_ids()
            if not available_human_agent_ids:
                logger.error(
                    f"No available slots in game {game.game_id} after acquiring lock. "
                    f"This indicates a race condition. Creating new game for {subject_id}."
                )
                game = None

        # Handle the case where we need to create a new game due to race condition
        if game is None:
            self._create_game()
            game = self.games[self.waiting_games[-1]]
            logger.info(f"Created new game {game.game_id} for subject {subject_id} after race condition")

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
                player_added = game.add_player(player_id, subject_id)
                if not player_added:
                    logger.error(
                        f"Failed to add player {subject_id} to slot {player_id} in game {game.game_id}. "
                        f"This should not happen if locks are working correctly."
                    )

            # If multiplayer Pyodide, add player to coordinator
            if self.scene.pyodide_multiplayer and self.pyodide_coordinator and player_id is not None:
                self.pyodide_coordinator.add_player(
                    game_id=game.game_id,
                    player_id=player_id,
                    socket_id=flask.request.sid,
                    subject_id=subject_id
                )
                logger.info(
                    f"Added player {player_id} (subject: {subject_id}) to Pyodide coordinator for game {game.game_id}"
                )

            if self.scene.game_page_html_fn is not None:
                self.sio.emit(
                    "update_game_page_text",
                    {
                        "game_page_text": self.scene.game_page_html_fn(game, subject_id)
                    },
                    room=subject_id,
                )

            # Broadcast to all players in the room so everyone sees updated count
            self.broadcast_waiting_room_status(game.game_id)

        return game

    def _probe_and_create_game(
        self,
        matched: list[MatchCandidate],
        arriving_subject_id: SubjectID,
    ) -> None:
        """Initiate P2P RTT probe before creating game for matched participants.

        Adds all matched participants to the waitroom immediately, then triggers
        a WebRTC probe between the first two. If probe succeeds and RTT is acceptable,
        game is created. Otherwise, candidates stay in waitroom for future matching.

        Phase 59: P2P RTT filtering integration.

        Args:
            matched: List of matched MatchCandidates (from matchmaker.find_match)
            arriving_subject_id: The subject that triggered this match

        Returns:
            None - game creation is deferred until probe completes
        """
        # Add arriving participant to waitroom while probe runs
        # (waiting participants are already in the waitroom)
        self._add_to_waitroom(arriving_subject_id)

        # For 2-player games, probe between the two candidates
        if len(matched) >= 2:
            subject_a = matched[0].subject_id
            subject_b = matched[1].subject_id

            logger.info(
                f"Starting P2P RTT probe for match: {subject_a} <-> {subject_b}. "
                f"Threshold: {self.matchmaker.max_p2p_rtt_ms}ms"
            )

            # Create probe with callback
            probe_session_id = self.probe_coordinator.create_probe(
                subject_a=subject_a,
                subject_b=subject_b,
                on_complete=self._on_probe_complete,
            )

            # Store match context for callback
            self._pending_matches[probe_session_id] = {
                'matched': matched,
                'arriving_subject_id': arriving_subject_id,
                'created_at': time.time(),
            }

        return None

    def _on_probe_complete(
        self,
        subject_a: str,
        subject_b: str,
        rtt_ms: float | None,
    ) -> None:
        """Handle P2P RTT probe completion.

        Called by ProbeCoordinator when RTT measurement finishes (or fails/times out).

        Args:
            subject_a: First subject in the probe
            subject_b: Second subject in the probe
            rtt_ms: Measured RTT in milliseconds, or None if failed/timed out
        """
        # Find the pending match for this probe
        probe_session_id = None
        match_context = None
        for pid, ctx in list(self._pending_matches.items()):
            matched_subjects = [c.subject_id for c in ctx['matched']]
            if subject_a in matched_subjects and subject_b in matched_subjects:
                probe_session_id = pid
                match_context = ctx
                break

        if not match_context:
            logger.warning(
                f"Probe complete for {subject_a} <-> {subject_b} but no pending match found"
            )
            return

        # Clean up pending match entry
        del self._pending_matches[probe_session_id]

        matched = match_context['matched']
        arriving_subject_id = match_context['arriving_subject_id']

        # Check if match should be rejected based on RTT
        should_reject = self.matchmaker.should_reject_for_rtt(rtt_ms)

        if should_reject:
            threshold = self.matchmaker.max_p2p_rtt_ms
            logger.info(
                f"RTT rejection: {rtt_ms}ms {'> ' + str(threshold) + 'ms' if rtt_ms else '(failed)'} "
                f"for {subject_a} <-> {subject_b}. Candidates remain in waitroom."
            )
            # Candidates stay in waitroom, no action needed - they were already added
            # Future matches will try different pairings
            return

        logger.info(
            f"RTT accepted: {rtt_ms}ms <= {self.matchmaker.max_p2p_rtt_ms}ms "
            f"for {subject_a} <-> {subject_b}. Creating game."
        )

        # RTT acceptable - create game for matched participants
        # Need to acquire lock since we're modifying game state
        with self.waiting_games_lock:
            # Verify all candidates are still in waitroom (they might have disconnected)
            all_still_waiting = True
            for candidate in matched:
                game_id = self.subject_games.get(candidate.subject_id)
                if not game_id or game_id not in self.waiting_games:
                    logger.warning(
                        f"Candidate {candidate.subject_id} no longer in waitroom. "
                        f"Aborting match creation."
                    )
                    all_still_waiting = False
                    break

            if not all_still_waiting:
                # Candidates left during probe - nothing to do
                return

            # Remove matched candidates from their waitroom games before creating new game
            self._remove_from_waitroom(matched)

            # Create and start the game
            self._create_game_for_match_internal(matched)

    def _remove_from_waitroom(self, candidates: list[MatchCandidate]) -> None:
        """Remove candidates from their waitroom games before creating new match.

        Called when P2P RTT probe succeeds and we're ready to create the real game.
        """
        for candidate in candidates:
            subject_id = candidate.subject_id
            game_id = self.subject_games.get(subject_id)
            if not game_id:
                continue

            game = self.games.get(game_id)
            if not game:
                continue

            with game.lock:
                # Remove player from waitroom game
                game.remove_human_player(subject_id)

                # Clean up tracking
                if subject_id in self.subject_games:
                    del self.subject_games[subject_id]
                if subject_id in self.subject_rooms:
                    del self.subject_rooms[subject_id]
                if game_id in self.reset_events and subject_id in self.reset_events[game_id]:
                    del self.reset_events[game_id][subject_id]

                # Leave the room
                try:
                    flask_socketio.leave_room(game_id)
                except RuntimeError:
                    # May not be in request context
                    pass

                # If game is now empty, clean it up
                if game.cur_num_human_players() == 0:
                    if game_id in self.waiting_games:
                        self.waiting_games.remove(game_id)
                    if game_id in self.games:
                        del self.games[game_id]
                    if game_id in self.reset_events:
                        del self.reset_events[game_id]
                    if game_id in self.waitroom_timeouts:
                        del self.waitroom_timeouts[game_id]
                    logger.debug(f"Cleaned up empty waitroom game {game_id}")

    def _create_game_for_match_internal(
        self,
        matched: list[MatchCandidate],
    ) -> remote_game.RemoteGameV2 | None:
        """Create game for matched candidates after probe success.

        Similar to _create_game_for_match but without handling arriving participant
        separately (all candidates are in equivalent state after probe).
        """
        # Create a new game
        self._create_game()
        game: remote_game.RemoteGameV2 = self.games[self.waiting_games[-1]]

        # Add each participant to the game
        added_subjects = []
        for candidate in matched:
            if self._add_subject_to_specific_game(candidate.subject_id, game):
                added_subjects.append(candidate.subject_id)
            else:
                logger.error(
                    f"Failed to add subject {candidate.subject_id} to matched game {game.game_id}. "
                    f"Successfully added: {added_subjects}. Cleaning up."
                )
                self._remove_game(game.game_id)
                return None

        # Validate game is ready
        if not game.is_ready_to_start():
            logger.error(
                f"Matched game {game.game_id} is not ready after adding all players! "
                f"Added: {added_subjects}, Available slots: {game.get_available_human_agent_ids()}"
            )
            self._remove_game(game.game_id)
            return None

        self.waiting_games.remove(game.game_id)
        game.transition_to(SessionState.MATCHED)

        # Log match assignment (Phase 56)
        if self.match_logger:
            self.match_logger.log_match(
                scene_id=self.scene.scene_id,
                game_id=game.game_id,
                matched_candidates=matched,
                matchmaker_class=type(self.matchmaker).__name__,
            )

        self.start_game(game)
        return game

    def _create_game_for_match(
        self,
        matched: list[MatchCandidate],
        arriving_subject_id: SubjectID
    ) -> remote_game.RemoteGameV2:
        """Create and start a game for matched participants.

        Handles the case where some participants are already in waitroom games
        and need to be moved to the new match game.
        """
        # Separate arriving from already-waiting participants
        waiting_matched = [c for c in matched if c.subject_id != arriving_subject_id]

        # Find existing game to use (from the first waiting participant)
        # This preserves the RTT-compatible game assignment
        existing_game = None
        for candidate in waiting_matched:
            game_id = self.subject_games.get(candidate.subject_id)
            if game_id and game_id in self.waiting_games:
                existing_game = self.games.get(game_id)
                break

        if existing_game is None:
            # No existing game - create one
            self._create_game()
            existing_game = self.games[self.waiting_games[-1]]

        game = existing_game
        current_players = game.cur_num_human_players()
        expected_players = self._get_group_size()
        logger.info(
            f"Creating match in game {game.game_id}. "
            f"Current players: {current_players}/{expected_players}"
        )

        # Safety check: verify game isn't already at capacity before proceeding
        if game.is_at_player_capacity():
            logger.error(
                f"Race condition detected: Game {game.game_id} is already at capacity "
                f"({current_players}/{expected_players} players). "
                f"Subject {arriving_subject_id} will be added to a new game instead."
            )
            self._create_game()
            game = self.games[self.waiting_games[-1]]
            logger.info(f"Created new game {game.game_id} for subject {arriving_subject_id}")

        with game.lock:
            # Double-check availability inside the lock
            available_human_agent_ids = game.get_available_human_agent_ids()
            if not available_human_agent_ids:
                logger.error(
                    f"No available slots in game {game.game_id} after acquiring lock. "
                    f"This indicates a race condition. Creating new game for {arriving_subject_id}."
                )
                game = None

        # Handle the case where we need to create a new game due to race condition
        if game is None:
            self._create_game()
            game = self.games[self.waiting_games[-1]]
            logger.info(f"Created new game {game.game_id} for subject {arriving_subject_id} after race condition")

        with game.lock:
            # Add the arriving participant
            self.subject_games[arriving_subject_id] = game.game_id
            self.subject_rooms[arriving_subject_id] = game.game_id
            self.reset_events[game.game_id][arriving_subject_id] = eventlet.event.Event()
            flask_socketio.join_room(game.game_id)

            available_human_agent_ids = game.get_available_human_agent_ids()
            player_id = None
            player_added = False
            if not available_human_agent_ids:
                logger.warning(
                    f"No available human agent IDs for game {game.game_id}. Adding as a spectator."
                )
            else:
                player_id = random.choice(available_human_agent_ids)
                player_added = game.add_player(player_id, arriving_subject_id)
                if not player_added:
                    logger.error(
                        f"Failed to add player {arriving_subject_id} to slot {player_id} in game {game.game_id}. "
                        f"This should not happen if locks are working correctly."
                    )

            # If multiplayer Pyodide, add player to coordinator
            if self.scene.pyodide_multiplayer and self.pyodide_coordinator and player_id is not None:
                self.pyodide_coordinator.add_player(
                    game_id=game.game_id,
                    player_id=player_id,
                    socket_id=flask.request.sid,
                    subject_id=arriving_subject_id
                )
                logger.info(
                    f"Added player {player_id} (subject: {arriving_subject_id}) to Pyodide coordinator for game {game.game_id}"
                )

            if self.scene.game_page_html_fn is not None:
                self.sio.emit(
                    "update_game_page_text",
                    {
                        "game_page_text": self.scene.game_page_html_fn(game, arriving_subject_id)
                    },
                    room=arriving_subject_id,
                )

            # Check if the game is ready to start
            is_ready = game.is_ready_to_start()
            logger.info(f"Game {game.game_id} ready to start: {is_ready}. Available slots: {game.get_available_human_agent_ids()}")
            if is_ready:
                logger.info(f"Removing game {game.game_id} from waiting_games")
                self.waiting_games.remove(game.game_id)
                assert game.game_id not in self.waiting_games

            if is_ready:
                game.transition_to(SessionState.MATCHED)

                # Log match assignment (Phase 56)
                if self.match_logger:
                    self.match_logger.log_match(
                        scene_id=self.scene.scene_id,
                        game_id=game.game_id,
                        matched_candidates=matched,
                        matchmaker_class=type(self.matchmaker).__name__,
                    )

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
                "hide_lobby_count": self.scene.hide_lobby_count,
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
                "hide_lobby_count": self.scene.hide_lobby_count,
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

            # Reset participant state (Phase 54)
            if self.participant_state_tracker:
                self.participant_state_tracker.reset(subject_id)

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
        # Safety validation: ensure correct number of players before starting
        expected_human_players = len([
            p for p in self.scene.policy_mapping.values()
            if p == configuration_constants.PolicyTypes.Human
        ])
        actual_human_players = game.cur_num_human_players()
        available_slots = len(game.get_available_human_agent_ids())

        if actual_human_players != expected_human_players:
            logger.error(
                f"CRITICAL: Attempted to start game {game.game_id} with wrong player count! "
                f"Expected {expected_human_players} human players, got {actual_human_players}. "
                f"Available slots: {available_slots}. "
                f"Players: {list(game.human_players.items())}. "
                f"Aborting game start."
            )
            # Don't start the game - return the players to the waiting room or error state
            return

        if available_slots != 0:
            logger.error(
                f"CRITICAL: Attempted to start game {game.game_id} with {available_slots} "
                f"unfilled slots! Players: {list(game.human_players.items())}. "
                f"Aborting game start."
            )
            return

        logger.info(
            f"Starting game {game.game_id} with {actual_human_players} subjects: "
            f"{[sid for sid in game.human_players.values()]}"
        )

        # Transition all players to IN_GAME (Phase 54)
        if self.participant_state_tracker:
            for subject_id in game.human_players.values():
                if subject_id and subject_id != utils.Available:
                    self.participant_state_tracker.transition_to(subject_id, ParticipantState.IN_GAME)

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
            # Non-pyodide games go straight to PLAYING (no validation phase)
            game.transition_to(SessionState.PLAYING)
            self.sio.start_background_task(self.run_server_game, game)
        # Note: For pyodide_multiplayer games, transition to VALIDATING/PLAYING
        # happens in PyodideGameCoordinator (see Task 3)

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
        """End a game and clean up ALL associated state.

        Idempotent: safe to call multiple times for the same game_id.
        """
        # Guard: make idempotent
        if game_id not in self.games:
            logger.debug(f"cleanup_game called for already-cleaned game {game_id}")
            return

        game = self.games[game_id]

        # Transition to ENDED before cleanup (SESS-02: session destroyed after ENDED)
        game.transition_to(SessionState.ENDED)

        # Transition all players to GAME_ENDED (Phase 54)
        if self.participant_state_tracker:
            for subject_id in list(game.human_players.values()):
                if subject_id and subject_id != utils.Available:
                    self.participant_state_tracker.transition_to(subject_id, ParticipantState.GAME_ENDED)

        # Clean up subject tracking for ALL players in this game
        for subject_id in list(game.human_players.values()):
            if subject_id and subject_id != utils.Available:
                if subject_id in self.subject_games:
                    del self.subject_games[subject_id]
                if subject_id in self.subject_rooms:
                    del self.subject_rooms[subject_id]
                logger.debug(f"Cleaned subject mappings for {subject_id}")

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
