"""
Server Game Runner - Real-Time Authoritative Environment

Runs a Python environment on the server with real-time stepping:
- Steps on a timer at target FPS, using latest/predicted actions
- Never blocks waiting for slow players
- Uses "sticky" actions (last received) or configured fallback
- Broadcasts authoritative state periodically for client reconciliation

Key properties:
- Low latency: Server runs independently of client action timing
- Smooth: No pauses when one player is idle/slow
- Authoritative: Server state is ground truth for all clients
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Ensure this module's logger has a handler so messages are visible
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class ServerGameRunner:
    """
    Authoritative game environment with real-time and frame-aligned modes.

    Real-time mode (realtime_mode=True):
        - Steps on a timer at target FPS
        - Uses "sticky" last-received action per player
        - Falls back to configured action_population_method when no action received
        - Never blocks waiting for slow players

    """

    def __init__(
        self,
        game_id: str,
        environment_code: str,
        num_players: int,
        state_broadcast_interval: int = 30,
        sio=None,
        fps: int = 30,
        default_action: int = 0,
        action_population_method: str = "previous_submitted_action",
        realtime_mode: bool = True,
        input_buffer_size: int = 300,  # Unused, kept for API compatibility
        max_episodes: int = 1,
        max_steps: int = 10000,
    ):
        self.game_id = game_id
        self.environment_code = environment_code
        self.num_players = num_players
        self.state_broadcast_interval = state_broadcast_interval
        self.sio = sio

        # Config-driven settings
        self.target_fps = fps
        self.frame_interval_s = 1.0 / fps
        self.default_action = default_action
        self.action_population_method = action_population_method
        self.realtime_mode = realtime_mode
        self.max_episodes = max_episodes
        self.max_steps = max_steps

        # Environment state
        self.env = None
        self.frame_number = 0
        self.step_num = 0
        self.episode_num = 0
        self.cumulative_rewards: Dict[str, float] = {}
        self.is_initialized = False
        self.rng_seed: int | None = None

        # Action tracking (used in both modes)
        self.action_lock = threading.Lock()

        # GGPO-style frame-indexed input buffer
        # input_buffer[frame_number][player_id] = action
        self.input_buffer: Dict[int, Dict[str, int]] = {}
        self.input_buffer_max_size = 120  # Keep ~4 seconds at 30 FPS

        # Legacy sticky actions (kept for backwards compatibility during transition)
        self.current_actions: Dict[str, int] = {}

        # For action_population_method="previous_submitted_action"
        # Tracks the last action each player actually submitted
        self.last_submitted_actions: Dict[str, int] = {}

        # Track expected players
        self.player_ids: set = set()

        # Action tracking for sync verification
        self.action_sequence: list[dict] = []
        self.action_counts: Dict[str, Dict[int, int]] = {}

        # Sync epoch counter - incremented on episode start
        self.sync_epoch = 0

        # Real-time mode: timer control
        self.running = False
        self.last_tick_time = 0.0
        self._tick_greenlet = None

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

    # =========================================================================
    # Real-time mode methods
    # =========================================================================

    def start_realtime(self):
        """Start the real-time game loop using eventlet."""
        if not self.is_initialized:
            logger.error("[ServerGameRunner] Cannot start - not initialized")
            return

        if not self.realtime_mode:
            logger.debug("[ServerGameRunner] Real-time mode disabled, not starting timer")
            return

        self.running = True
        self.last_tick_time = time.time()
        self._schedule_next_tick()
        logger.info(
            f"[ServerGameRunner] Started real-time loop for {self.game_id} "
            f"at {self.target_fps} FPS"
        )

    def stop_realtime(self):
        """Stop the real-time game loop."""
        self.running = False
        if self._tick_greenlet:
            try:
                self._tick_greenlet.cancel()
            except Exception:
                pass
            self._tick_greenlet = None
        logger.debug(f"[ServerGameRunner] Stopped real-time loop for {self.game_id}")

    def _schedule_next_tick(self):
        """Schedule the next tick using eventlet."""
        if not self.running:
            return

        import eventlet
        now = time.time()
        elapsed = now - self.last_tick_time
        delay = max(0, self.frame_interval_s - elapsed)
        self._tick_greenlet = eventlet.spawn_after(delay, self._tick)

    def _tick(self):
        """Called every frame_interval_s. Steps the game unconditionally."""
        if not self.running or not self.is_initialized:
            return

        now = time.time()
        self.last_tick_time = now

        # GGPO: Build action dict using frame-indexed inputs
        # Use input for current frame if available, otherwise use fallback
        actions = {}
        frame_inputs = self.input_buffer.get(self.frame_number, {})

        for player_id in self.player_ids:
            player_id_str = str(player_id)
            if player_id_str in frame_inputs:
                # Have confirmed input for this frame
                actions[player_id] = frame_inputs[player_id_str]
                # Track as last submitted for fallback
                self.last_submitted_actions[player_id_str] = actions[player_id]
            elif player_id_str in self.current_actions:
                # Fallback: use latest received action (legacy sticky)
                actions[player_id] = self.current_actions[player_id_str]
                self.last_submitted_actions[player_id_str] = actions[player_id]
            else:
                # No action at all - use configured fallback
                actions[player_id] = self._get_action_for_player(player_id)

        # Clean up used frame inputs
        if self.frame_number in self.input_buffer:
            del self.input_buffer[self.frame_number]

        # Step environment
        try:
            env_actions = {int(k) if str(k).isdigit() else k: v for k, v in actions.items()}
            obs, rewards, terminateds, truncateds, infos = self.env.step(env_actions)

            # Update cumulative rewards
            for player_id, reward in rewards.items():
                pid_str = str(player_id)
                if pid_str in self.cumulative_rewards:
                    self.cumulative_rewards[pid_str] += reward

            # Track action sequence
            action_record = {
                "frame": self.frame_number,
                "actions": {str(k): int(v) for k, v in env_actions.items()}
            }
            self.action_sequence.append(action_record)

            # Log every 30 frames for debugging divergence
            if self.frame_number % 30 == 0:
                logger.info(
                    f"[SERVER] Frame {self.frame_number}: actions={action_record['actions']}"
                )

            # Update action counts per player
            for player_id, action in env_actions.items():
                pid_str = str(player_id)
                if pid_str not in self.action_counts:
                    self.action_counts[pid_str] = {}
                action_int = int(action)
                self.action_counts[pid_str][action_int] = \
                    self.action_counts[pid_str].get(action_int, 0) + 1

            self.frame_number += 1
            self.step_num += 1

            # Check for episode end (environment termination OR max_steps reached)
            episode_done = (
                terminateds.get("__all__", False) or
                truncateds.get("__all__", False) or
                self.step_num >= self.max_steps
            )
            if episode_done:
                self._handle_episode_end_realtime()
            elif self.frame_number % self.state_broadcast_interval == 0:
                self.broadcast_state()

        except Exception as e:
            logger.error(f"[ServerGameRunner] Error in tick: {e}")
            import traceback
            traceback.print_exc()

        # Schedule next tick
        self._schedule_next_tick()

    def _get_action_for_player(self, player_id: str) -> int:
        """Get action for player using configured fallback strategy."""
        player_id_str = str(player_id)

        # Check if we have a sticky action from this player
        if player_id_str in self.current_actions:
            return self.current_actions[player_id_str]

        # No action received - use configured fallback
        if self.action_population_method == "previous_submitted_action":
            return self.last_submitted_actions.get(player_id_str, self.default_action)
        else:
            return self.default_action

    def _prune_input_buffer(self):
        """Remove old entries from input buffer to prevent memory growth."""
        if len(self.input_buffer) > self.input_buffer_max_size:
            # Remove entries for frames we've already processed
            frames_to_delete = [
                f for f in self.input_buffer.keys()
                if f < self.frame_number - 10  # Keep some recent history
            ]
            for frame in frames_to_delete:
                del self.input_buffer[frame]

    def _handle_episode_end_realtime(self):
        """Handle episode completion in real-time mode."""
        self.episode_num += 1
        logger.info(
            f"[ServerGameRunner] Episode {self.episode_num}/{self.max_episodes} "
            f"completed for {self.game_id}"
        )

        # Check if we've reached max episodes
        if self.episode_num >= self.max_episodes:
            logger.info(
                f"[ServerGameRunner] All {self.max_episodes} episodes complete "
                f"for {self.game_id}, stopping"
            )
            self.stop_realtime()

            # Broadcast game completion to clients
            if self.sio:
                self.sio.emit(
                    "server_game_complete",
                    {
                        "game_id": self.game_id,
                        "episode_num": self.episode_num,
                        "max_episodes": self.max_episodes,
                        "cumulative_rewards": self.cumulative_rewards,
                    },
                    room=self.game_id
                )
            return

        # Pause the real-time loop during episode transition
        # This prevents ticking while clients show their countdown
        self.running = False
        logger.info(f"[ServerGameRunner] Pausing for episode transition")

        # Reset for next episode
        self.frame_number = 0
        self.step_num = 0

        # Re-seed RNG
        if self.rng_seed is not None:
            import numpy as np
            import random
            np.random.seed(self.rng_seed)
            random.seed(self.rng_seed)

        self.env.reset(seed=self.rng_seed)

        # Clear action tracking
        self.current_actions.clear()
        self.last_submitted_actions.clear()  # Clear fallback actions from previous episode
        self.input_buffer.clear()  # Clear GGPO input buffer
        self.action_sequence = []
        self.action_counts = {}
        self.sync_epoch += 1

        # Broadcast episode start state to clients
        # Clients will show countdown then signal ready
        self.broadcast_state(event_type="server_episode_start")
        logger.info(f"[ServerGameRunner] Episode {self.episode_num + 1} state broadcast, waiting for clients")

        # Resume after a delay to allow client countdown (3 seconds + buffer)
        import eventlet
        eventlet.spawn_after(4.0, self._resume_after_episode_transition)

    def _resume_after_episode_transition(self):
        """Resume the real-time loop after episode transition delay."""
        if not self.is_initialized:
            return

        # Don't resume if we've been stopped (e.g., game ended)
        if self.episode_num >= self.max_episodes:
            return

        logger.info(
            f"[ServerGameRunner] Resuming real-time loop for episode "
            f"{self.episode_num + 1} of {self.game_id}"
        )
        self.running = True
        self.last_tick_time = time.time()
        self._schedule_next_tick()

    def receive_action_realtime(
        self,
        player_id: str | int,
        action: Any,
        client_frame: int,
        sync_epoch: int | None = None
    ):
        """
        Receive action in real-time mode with GGPO frame tagging.

        Actions are stored by their target frame number, not as sticky actions.
        This allows the server to match inputs to specific frames, enabling
        proper synchronization with clients using input delay.

        The timer-based _tick() method handles stepping independently.
        """
        if not self.is_initialized:
            return

        player_id_str = str(player_id)

        # Validate sync epoch if provided (reject stale actions after episode reset)
        if sync_epoch is not None and sync_epoch != self.sync_epoch:
            logger.debug(
                f"[ServerGameRunner] Ignoring stale action from {player_id_str} "
                f"(epoch {sync_epoch} != {self.sync_epoch})"
            )
            return

        with self.action_lock:
            # GGPO: Store action by target frame number
            # client_frame is the frame this action should execute at
            if client_frame not in self.input_buffer:
                self.input_buffer[client_frame] = {}
            self.input_buffer[client_frame][player_id_str] = action

            # Also keep legacy sticky action for fallback
            self.current_actions[player_id_str] = action
            # Track for previous_submitted_action fallback
            self.last_submitted_actions[player_id_str] = action

            # Prune old input buffer entries
            self._prune_input_buffer()

        logger.debug(
            f"[ServerGameRunner] Received action from {player_id_str}: "
            f"action={action}, target_frame={client_frame}"
        )

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
            # Include recent action sequence for detailed comparison (last 30 frames)
            "recent_actions": self._get_recent_action_sequence(30),
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
            logger.debug(
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

    def _get_recent_action_sequence(self, num_frames: int) -> list:
        """Get the most recent N frames of action sequence for comparison."""
        if len(self.action_sequence) <= num_frames:
            return self.action_sequence
        return self.action_sequence[-num_frames:]

    def broadcast_state(self, event_type: str = "server_authoritative_state"):
        """
        Broadcast authoritative state to all clients.

        Args:
            event_type: Socket event name to emit. Use "server_authoritative_state"
                       for periodic updates and "server_episode_start" for episode begins.
        """
        if self.sio is None:
            return

        # Only increment sync epoch on episode start broadcasts.
        # The epoch mechanism prevents stale actions after state resets, but we don't
        # want to reject actions between periodic syncs (that would block the server
        # from ever stepping since clients can't update their epoch fast enough).
        if event_type == "server_episode_start":
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

        logger.debug(
            f"[ServerGameRunner] Broadcast {event_type} to room {self.game_id} "
            f"at frame {self.frame_number}, epoch {self.sync_epoch}"
        )

    def stop(self):
        """Clean up resources."""
        self.stop_realtime()  # Stop real-time loop if running
        self.is_initialized = False
        self.env = None
        logger.info(f"[ServerGameRunner] Stopped game {self.game_id}")
