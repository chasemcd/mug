"""
Server Game Runner - Frame-Aligned Authoritative Environment

Runs a Python environment on the server that steps in sync with client frames.
Unlike a timer-based approach, this steps ONLY when all player actions for a
frame have been received, ensuring perfect synchronization.

Key properties:
- Deterministic: Steps exactly when clients step
- No drift: Server frame always matches client consensus
- On-demand: No background loop, steps on action events
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ServerGameRunner:
    """
    Frame-aligned authoritative game environment.

    Steps only when all player actions are received for the current frame.
    Broadcasts authoritative state periodically.
    """

    def __init__(
        self,
        game_id: str,
        environment_code: str,
        num_players: int,
        state_broadcast_interval: int = 30,
        sio=None,
    ):
        self.game_id = game_id
        self.environment_code = environment_code
        self.num_players = num_players
        self.state_broadcast_interval = state_broadcast_interval
        self.sio = sio

        # Environment state
        self.env = None
        self.frame_number = 0
        self.step_num = 0
        self.episode_num = 0
        self.cumulative_rewards: Dict[str, float] = {}
        self.is_initialized = False
        self.rng_seed: int | None = None

        # Action collection for current server step
        # Instead of matching by client frame number (which drift apart),
        # we collect the NEXT action from each player and step when all are received.
        # {player_id: action} - one pending action per player for the next step
        self.pending_actions_for_step: Dict[str, Any] = {}
        self.action_lock = threading.Lock()

        # Legacy frame-based pending actions (kept for cleanup compatibility)
        self.pending_actions: Dict[int, Dict[str, Any]] = {}

        # Track expected players
        self.player_ids: set = set()

        # Default action for fallback
        self.default_action = 0

        # Action tracking for sync verification
        self.action_sequence: list[dict] = []  # List of {frame: N, actions: {player: action}}
        self.action_counts: Dict[str, Dict[int, int]] = {}  # {player_id: {action: count}}

        # Sync epoch counter - incremented on each state broadcast.
        # Clients include this in their actions; server ignores actions from old epochs.
        # This prevents stale actions (sent before client received sync) from causing extra steps.
        self.sync_epoch = 0

    def initialize_environment(self, rng_seed: int) -> bool:
        """
        Initialize environment from code string.
        Uses exec() to run the same code clients run in Pyodide.

        Returns True if successful, False otherwise.
        """
        self.rng_seed = rng_seed

        # Use __main__ as namespace to match Pyodide client behavior
        # Classes defined here will have __module__ = '__main__'
        # The get_state() method should pickle with __main__ module reference
        # so both server and client can find the class when unpickling
        import sys
        env_globals = {"__name__": "__main__"}

        # Store reference to __main__ module for class registration
        if "__main__" not in sys.modules:
            import types
            sys.modules["__main__"] = types.ModuleType("__main__")

        try:
            # Set up numpy seed before execution
            exec(
                f"""
import numpy as np
import random
np.random.seed({rng_seed})
random.seed({rng_seed})
""",
                env_globals,
            )

            # Execute environment initialization code
            exec(self.environment_code, env_globals)

            if "env" not in env_globals:
                logger.error(
                    f"[ServerGameRunner] Environment code must define 'env' variable"
                )
                return False

            self.env = env_globals["env"]

            # Register classes into __main__ module so pickle can find them
            main_module = sys.modules["__main__"]
            for name, obj in env_globals.items():
                if isinstance(obj, type) and not name.startswith('_'):
                    setattr(main_module, name, obj)
                    logger.debug(f"[ServerGameRunner] Registered class {name} in __main__ for pickling")

            # Disable rendering on server to avoid unnecessary computations
            # The server only needs to step the environment, not render it
            if hasattr(self.env, 'render_mode'):
                self.env.render_mode = None
            # Also try to disable on unwrapped env if it's a wrapper
            if hasattr(self.env, 'unwrapped') and hasattr(self.env.unwrapped, 'render_mode'):
                self.env.unwrapped.render_mode = None

            # Reset with seed
            obs, info = self.env.reset(seed=rng_seed)

            # Initialize cumulative rewards
            for player_id in obs.keys():
                self.cumulative_rewards[str(player_id)] = 0.0

            self.is_initialized = True
            self.frame_number = 0
            self.step_num = 0

            logger.info(
                f"[ServerGameRunner] Initialized environment for game {self.game_id} "
                f"with seed {rng_seed}"
            )
            return True

        except Exception as e:
            logger.error(
                f"[ServerGameRunner] Failed to initialize environment: {e}"
            )
            import traceback
            traceback.print_exc()
            return False

    def add_player(self, player_id: str | int):
        """Register a player ID."""
        self.player_ids.add(str(player_id))
        logger.debug(
            f"[ServerGameRunner] Added player {player_id}, "
            f"now have {len(self.player_ids)} players"
        )

    def receive_action(
        self,
        player_id: str | int,
        action: Any,
        frame_number: int,
        sync_epoch: int | None = None
    ) -> bool:
        """
        Receive an action from a player.

        Returns True if this action completed the current step (all players submitted).

        The server steps based on ACTION ARRIVAL ORDER, not client frame numbers.
        When one action is received from each player, the server steps using those
        actions. This ensures the server keeps stepping even when clients have
        slightly different frame numbers due to network latency.

        Args:
            player_id: Player sending the action
            action: The action value
            frame_number: Frame number from client (logged for debugging, not used for matching)
            sync_epoch: Sync epoch from client. If provided and doesn't match
                       current server epoch, action is ignored (stale action
                       from before a sync).
        """
        if not self.is_initialized:
            logger.warning(f"[ServerGameRunner] Not initialized, ignoring action from {player_id}")
            return False

        player_id_str = str(player_id)

        # Validate sync epoch if provided
        if sync_epoch is not None and sync_epoch != self.sync_epoch:
            logger.info(
                f"[ServerGameRunner] Ignoring stale action from player {player_id} "
                f"(client epoch {sync_epoch} != server epoch {self.sync_epoch})"
            )
            return False

        with self.action_lock:
            # Store the action for this player (overwrites any previous pending action)
            # We only keep ONE pending action per player - the most recent one
            self.pending_actions_for_step[player_id_str] = action

            # Log action receipt at INFO level for debugging
            logger.info(
                f"[ServerGameRunner] Received action from player {player_id_str}: "
                f"pending={list(self.pending_actions_for_step.keys())}, "
                f"need={list(self.player_ids)}, epoch={sync_epoch}"
            )

            # Check if we have one action from each player
            have_all = len(self.pending_actions_for_step) >= len(self.player_ids)

            if have_all:
                logger.debug(
                    f"[ServerGameRunner] Game {self.game_id}: "
                    f"All actions received for server step {self.step_num} "
                    f"(client frame {frame_number})"
                )

            return have_all

    def step_frame(self, frame_number: int) -> Dict[str, Any] | None:
        """
        Step the environment using collected actions.

        Call this after receive_action returns True.
        Returns step results and whether to broadcast state.

        Note: frame_number is now just for logging - the server uses its own
        step_num as the authoritative frame counter.
        """
        if not self.is_initialized:
            return None

        with self.action_lock:
            # Use actions collected from all players (arrival-order based)
            if len(self.pending_actions_for_step) < len(self.player_ids):
                logger.warning(
                    f"[ServerGameRunner] Not enough actions for step "
                    f"(have {len(self.pending_actions_for_step)}, need {len(self.player_ids)})"
                )
                return None

            # Build action dict with proper types
            actions = {}
            for player_id in self.player_ids:
                if player_id in self.pending_actions_for_step:
                    actions[player_id] = self.pending_actions_for_step[player_id]
                else:
                    # Fallback to default (shouldn't happen if have_all was true)
                    actions[player_id] = self.default_action
                    logger.debug(
                        f"[ServerGameRunner] Using default action for player {player_id}"
                    )

            # Clear pending actions for next step
            self.pending_actions_for_step.clear()

            logger.info(
                f"[ServerGameRunner] Stepping with actions: {actions}, step_num={self.step_num}"
            )

        # Step environment (outside lock to avoid blocking)
        try:
            # Convert keys to int if needed (environment expects int keys)
            env_actions = {}
            for k, v in actions.items():
                try:
                    key = int(k)
                except (ValueError, TypeError):
                    key = k
                env_actions[key] = v

            obs, rewards, terminateds, truncateds, infos = self.env.step(env_actions)

            # Debug: Log each step to understand action count vs frame number
            logger.debug(
                f"[ServerGameRunner] STEP: frame_number={frame_number}, "
                f"step_num={self.step_num}, action_sequence_len={len(self.action_sequence)}"
            )

            # Track action sequence and counts for sync verification
            self.action_sequence.append({
                "frame": frame_number,
                "actions": {str(k): int(v) for k, v in env_actions.items()}
            })

            # Update action counts per player
            for player_id, action in env_actions.items():
                pid_str = str(player_id)
                if pid_str not in self.action_counts:
                    self.action_counts[pid_str] = {}
                action_int = int(action)
                self.action_counts[pid_str][action_int] = self.action_counts[pid_str].get(action_int, 0) + 1

            # Update cumulative rewards
            for player_id, reward in rewards.items():
                pid_str = str(player_id)
                if pid_str in self.cumulative_rewards:
                    self.cumulative_rewards[pid_str] += reward

            self.frame_number = frame_number
            self.step_num += 1

            # Check if should broadcast
            should_broadcast = (
                self.step_num % self.state_broadcast_interval == 0
            )

            # Check for episode end
            episode_done = (
                terminateds.get("__all__", False) or
                truncateds.get("__all__", False)
            )

            return {
                "terminateds": terminateds,
                "truncateds": truncateds,
                "episode_done": episode_done,
                "should_broadcast": should_broadcast,
                "frame_number": frame_number,
            }

        except Exception as e:
            logger.error(
                f"[ServerGameRunner] Error stepping game {self.game_id}: {e}"
            )
            import traceback
            traceback.print_exc()
            return None

    def get_authoritative_state(self) -> Dict[str, Any]:
        """
        Get full authoritative state for broadcast.

        Requires the environment to implement get_state() returning a
        JSON-serializable dict. This is necessary for deterministic hash
        comparison between server (CPython) and client (Pyodide).

        If state serialization fails, we still broadcast basic state
        (frame_number, cumulative_rewards) which is sufficient for keeping
        clients in sync on score display, but state corrections won't work.
        """
        import time
        start_time = time.time()

        state = {
            "episode_num": self.episode_num,
            "step_num": self.step_num,
            "frame_number": self.frame_number,
            "cumulative_rewards": self.cumulative_rewards.copy(),
            "server_timestamp": time.time() * 1000,  # ms timestamp for staleness tracking
            # Sync epoch - clients must include this in actions to prevent stale action matching
            "sync_epoch": self.sync_epoch,
            # Action tracking for sync verification
            "action_counts": {k: dict(v) for k, v in self.action_counts.items()},
            "action_sequence_hash": self._compute_action_sequence_hash(),
            "total_actions": len(self.action_sequence),
        }

        # Include environment state - requires get_state() method
        if not hasattr(self.env, "get_state"):
            logger.error(
                f"[ServerGameRunner] Environment does not implement get_state(). "
                f"State synchronization will NOT work. "
                f"Please implement get_state() and set_state() methods that return/accept "
                f"JSON-serializable dicts with primitive types only."
            )
            return state

        try:
            import json
            import hashlib

            serialize_start = time.time()
            env_state = self.env.get_state()
            serialize_time_ms = (time.time() - serialize_start) * 1000

            # Verify it's JSON-serializable (for socket.io transmission)
            json_start = time.time()
            json_str = json.dumps(env_state, sort_keys=True)
            json_time_ms = (time.time() - json_start) * 1000
            env_state_size = len(json_str)

            # Compute a hash of the state for quick comparison
            # Clients can compare hashes before full deserialization
            state_hash = hashlib.md5(json_str.encode()).hexdigest()[:16]

            state["env_state"] = env_state
            state["state_hash"] = state_hash

            total_time_ms = (time.time() - start_time) * 1000
            logger.info(
                f"[ServerGameRunner] State serialization: frame={self.frame_number}, "
                f"size={env_state_size/1024:.1f}KB, "
                f"serialize={serialize_time_ms:.1f}ms, json={json_time_ms:.1f}ms, total={total_time_ms:.1f}ms, "
                f"hash={state_hash}"
            )
        except Exception as e:
            # Log warning - this is important because without env_state, clients can't sync positions
            logger.warning(
                f"[ServerGameRunner] Cannot include env_state in broadcast: {e}. "
                f"Clients will NOT be able to sync game state (positions, etc). "
                f"Ensure get_state() returns a JSON-serializable dict."
            )

        return state

    def _compute_action_sequence_hash(self) -> str:
        """Compute hash of action sequence for quick comparison."""
        import hashlib
        import json
        seq_str = json.dumps(self.action_sequence, sort_keys=True)
        return hashlib.md5(seq_str.encode()).hexdigest()[:16]

    def broadcast_state(self, event_type: str = "server_authoritative_state"):
        """
        Broadcast authoritative state to all clients.

        Args:
            event_type: Socket event name to emit. Use "server_authoritative_state"
                       for periodic updates and "server_episode_start" for episode begins.
        """
        if self.sio is None:
            return

        # Increment sync epoch BEFORE getting state so clients receive the new epoch
        self.sync_epoch += 1

        state = self.get_authoritative_state()

        self.sio.emit(
            event_type,
            {
                "game_id": self.game_id,
                "state": state,
            },
            room=self.game_id,
        )

        logger.info(
            f"[ServerGameRunner] Broadcast {event_type} to room {self.game_id} "
            f"at frame {self.frame_number}, epoch {self.sync_epoch}"
        )

        # Clear ALL pending actions after sync.
        # With sync epochs, clients will include the new epoch in their actions,
        # and any actions with the old epoch will be rejected. Clearing pending
        # actions ensures we don't accumulate stale data.
        with self.action_lock:
            if self.pending_actions_for_step:
                cleared_count = len(self.pending_actions_for_step)
                self.pending_actions_for_step.clear()
                logger.debug(
                    f"[ServerGameRunner] Cleared {cleared_count} pending actions after broadcast"
                )
            # Also clear legacy pending_actions if any
            if self.pending_actions:
                self.pending_actions.clear()

    def handle_episode_end(self):
        """
        Handle episode completion - reset environment and broadcast new episode state.

        Clients wait for the server_episode_start event before beginning the new episode,
        ensuring all clients start from the exact same state at the same time.
        """
        self.episode_num += 1
        self.step_num = 0
        self.frame_number = 0

        # Re-seed RNG for deterministic reset
        if self.rng_seed is not None:
            import numpy as np
            import random
            np.random.seed(self.rng_seed)
            random.seed(self.rng_seed)

        obs, info = self.env.reset(seed=self.rng_seed)

        # Clear pending actions for fresh episode
        with self.action_lock:
            self.pending_actions_for_step.clear()
            self.pending_actions.clear()  # Legacy

        # Clear action tracking for new episode
        self.action_sequence = []
        self.action_counts = {}

        # Broadcast state after reset with special event type
        # Clients wait for this before starting the new episode
        self.broadcast_state(event_type="server_episode_start")

        logger.info(
            f"[ServerGameRunner] Episode {self.episode_num} started for {self.game_id}"
        )

    def _cleanup_old_frames(self, current_frame: int):
        """Remove action data for old frames."""
        frames_to_remove = [
            f for f in self.pending_actions.keys()
            if f < current_frame - 10  # Keep small buffer
        ]
        for f in frames_to_remove:
            del self.pending_actions[f]

    def stop(self):
        """Clean up resources."""
        self.is_initialized = False
        self.env = None
        logger.info(f"[ServerGameRunner] Stopped game {self.game_id}")
