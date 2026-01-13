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

import base64
import logging
import pickle
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

        # Action collection for current frame
        # frame_number -> {player_id: action}
        self.pending_actions: Dict[int, Dict[str, Any]] = {}
        self.action_lock = threading.Lock()

        # Track expected players
        self.player_ids: set = set()

        # Default action for fallback
        self.default_action = 0

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
        frame_number: int
    ) -> bool:
        """
        Receive an action from a player.

        Returns True if this action completed the frame (all players submitted).
        """
        if not self.is_initialized:
            return False

        player_id_str = str(player_id)

        with self.action_lock:
            # Initialize frame action dict if needed
            if frame_number not in self.pending_actions:
                self.pending_actions[frame_number] = {}

            # Store action
            self.pending_actions[frame_number][player_id_str] = action

            # Check if we have all actions for this frame
            frame_actions = self.pending_actions[frame_number]
            have_all = len(frame_actions) >= len(self.player_ids)

            if have_all:
                logger.debug(
                    f"[ServerGameRunner] Game {self.game_id}: "
                    f"All actions received for frame {frame_number}"
                )

            return have_all

    def step_frame(self, frame_number: int) -> Dict[str, Any] | None:
        """
        Step the environment for a specific frame.

        Call this after receive_action returns True.
        Returns step results and whether to broadcast state.
        """
        if not self.is_initialized:
            return None

        with self.action_lock:
            if frame_number not in self.pending_actions:
                logger.warning(
                    f"[ServerGameRunner] No actions for frame {frame_number}"
                )
                return None

            frame_actions = self.pending_actions[frame_number]

            # Build action dict with proper types
            actions = {}
            for player_id in self.player_ids:
                if player_id in frame_actions:
                    actions[player_id] = frame_actions[player_id]
                else:
                    # Fallback to default
                    actions[player_id] = self.default_action
                    logger.debug(
                        f"[ServerGameRunner] Using default action for player {player_id}"
                    )

            # Clean up old frames
            self._cleanup_old_frames(frame_number)

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

        Uses the environment's get_state() if available, otherwise falls back
        to default pickle-based serialization. The state is base64-encoded
        pickle data that can be unpickled on the Pyodide client.

        If state serialization fails, we still broadcast basic state
        (frame_number, cumulative_rewards) which is sufficient for keeping
        clients in sync on score display.
        """
        state = {
            "episode_num": self.episode_num,
            "step_num": self.step_num,
            "frame_number": self.frame_number,
            "cumulative_rewards": self.cumulative_rewards.copy(),
        }

        # Include environment state
        # Use env.get_state() if available, otherwise use default pickle method
        try:
            if hasattr(self.env, "get_state"):
                env_state = self.env.get_state()
            else:
                env_state = self._default_get_env_state()

            # Verify it's JSON-serializable (for socket.io transmission)
            import json
            json.dumps(env_state)
            state["env_state"] = env_state
        except Exception as e:
            # Log once per game to avoid spam
            if not getattr(self, "_env_state_warning_logged", False):
                logger.warning(
                    f"[ServerGameRunner] Cannot include env_state in broadcast: {e}. "
                    f"Basic state sync (frame, rewards) will still work."
                )
                self._env_state_warning_logged = True

        return state

    def broadcast_state(self, event_type: str = "server_authoritative_state"):
        """
        Broadcast authoritative state to all clients.

        Args:
            event_type: Socket event name to emit. Use "server_authoritative_state"
                       for periodic updates and "server_episode_start" for episode begins.
        """
        if self.sio is None:
            return

        state = self.get_authoritative_state()

        self.sio.emit(
            event_type,
            {
                "game_id": self.game_id,
                "state": state,
            },
            room=self.game_id,
        )

        logger.debug(
            f"[ServerGameRunner] Broadcast {event_type} at frame {self.frame_number}"
        )

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
        self.pending_actions.clear()

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

    def _default_get_env_state(self) -> dict:
        """
        Default pickle-based state serialization.

        Used when the environment doesn't implement its own get_state() method.
        Temporarily sets the class module to '__main__' before pickling so that
        the Pyodide client (which also uses '__main__') can unpickle it.

        Returns a dict with 'pickled_state' containing base64-encoded pickle data.
        """
        if self.env is None:
            return {}

        # Temporarily set module to __main__ for pickling compatibility
        # Both server and Pyodide client use __main__ namespace
        original_module = self.env.__class__.__module__
        self.env.__class__.__module__ = '__main__'
        try:
            pickled = pickle.dumps(self.env)
        finally:
            # Restore original module
            self.env.__class__.__module__ = original_module

        encoded = base64.b64encode(pickled).decode('utf-8')
        return {'pickled_state': encoded}

    def _default_set_env_state(self, state: dict) -> None:
        """
        Default pickle-based state deserialization.

        Used when the environment doesn't implement its own set_state() method.
        Unpickles the state and updates the environment's __dict__.
        """
        if 'pickled_state' not in state:
            logger.warning("[ServerGameRunner] No pickled_state in state dict")
            return

        encoded = state['pickled_state']
        pickled = base64.b64decode(encoded.encode('utf-8'))
        restored = pickle.loads(pickled)
        self.env.__dict__.update(restored.__dict__)

    def stop(self):
        """Clean up resources."""
        self.is_initialized = False
        self.env = None
        logger.info(f"[ServerGameRunner] Stopped game {self.game_id}")
