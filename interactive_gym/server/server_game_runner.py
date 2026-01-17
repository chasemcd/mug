"""
Server Game Runner - Real-Time Authoritative Environment

Runs a Python environment on the server with two modes:
1. Frame-aligned (legacy): Steps only when all player actions received
2. Real-time (new): Steps on a timer at target FPS, using latest/predicted actions

Real-time mode enables smooth multiplayer with client prediction + rollback:
- Server never blocks waiting for slow players
- Uses "sticky" actions (last received) or configured fallback
- Broadcasts authoritative state periodically for client reconciliation
- Includes input history so clients can replay with correct actions

Key properties:
- Low latency: Server runs independently of client action timing
- Smooth: No pauses when one player is idle/slow
- Authoritative: Server state is ground truth for all clients
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from collections import deque
from typing import Any, Deque, Dict

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class InputFrame:
    """Record of actions used for a single server frame."""
    frame: int
    actions: Dict[str, int]  # player_id -> action
    timestamp: float

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

    Frame-aligned mode (realtime_mode=False, legacy):
        - Steps only when all player actions received
        - Ensures perfect sync but can block on slow players
    """

    def __init__(
        self,
        game_id: str,
        environment_code: str,
        num_players: int,
        state_broadcast_interval: int = 30,
        sio=None,
        # New config-driven settings
        fps: int = 30,
        default_action: int = 0,
        action_population_method: str = "previous_submitted_action",
        realtime_mode: bool = True,
        input_buffer_size: int = 300,
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
        self.input_buffer_size = input_buffer_size
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

        # Real-time mode: "sticky" actions - last received action per player
        # Persists until replaced by new action from that player
        self.current_actions: Dict[str, int] = {}

        # For action_population_method="previous_submitted_action"
        # Tracks the last action each player actually submitted
        self.last_submitted_actions: Dict[str, int] = {}

        # Input history for client replay verification (real-time mode)
        self.input_history: Deque[InputFrame] = deque(maxlen=input_buffer_size)

        # Frame-aligned mode: pending actions for current step
        self.pending_actions_for_step: Dict[str, Any] = {}
        self.pending_actions: Dict[int, Dict[str, Any]] = {}  # Legacy

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

        # Build action dict: use received action if available, otherwise fallback
        # Clear each action after use to match client's "pop from queue" behavior
        actions = {}
        for player_id in self.player_ids:
            player_id_str = str(player_id)
            if player_id_str in self.current_actions:
                # Use the received action and consume it (non-sticky)
                actions[player_id] = self.current_actions.pop(player_id_str)
                # Track as last submitted for fallback
                self.last_submitted_actions[player_id_str] = actions[player_id]
            else:
                # No action received this tick - use fallback
                actions[player_id] = self._get_action_for_player(player_id)

        # Record input for this frame (for client replay verification)
        self.input_history.append(InputFrame(
            frame=self.frame_number,
            actions={str(k): int(v) for k, v in actions.items()},
            timestamp=now
        ))

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
            self.action_sequence.append({
                "frame": self.frame_number,
                "actions": {str(k): int(v) for k, v in env_actions.items()}
            })

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
        self.input_history.clear()
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
        Receive action in real-time mode. Updates sticky action, doesn't trigger step.

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
            # Update sticky action
            self.current_actions[player_id_str] = action
            # Track for previous_submitted_action fallback
            self.last_submitted_actions[player_id_str] = action

        logger.debug(
            f"[ServerGameRunner] Received action from {player_id_str}: "
            f"action={action}, client_frame={client_frame}"
        )

    # =========================================================================
    # Frame-aligned mode methods (legacy)
    # =========================================================================

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
            logger.debug(
                f"[ServerGameRunner] Ignoring stale action from player {player_id} "
                f"(client epoch {sync_epoch} != server epoch {self.sync_epoch})"
            )
            return False

        with self.action_lock:
            # Store the action for this player (overwrites any previous pending action)
            # We only keep ONE pending action per player - the most recent one
            self.pending_actions_for_step[player_id_str] = action

            # Log action receipt at DEBUG level (too frequent for INFO)
            logger.debug(
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

            logger.debug(
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

        # Include recent input history for client replay (real-time mode)
        # Clients use this to correct their predictions when reconciling
        if self.realtime_mode and self.input_history:
            recent_inputs = [
                {"frame": inp.frame, "actions": inp.actions, "timestamp": inp.timestamp}
                for inp in list(self.input_history)[-60:]  # Last ~2 sec at 30fps
            ]
            state["input_history"] = recent_inputs

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

        # Only clear pending actions on episode start (when epoch increments).
        # For periodic syncs, we DON'T clear because:
        # 1. Epoch doesn't change, so clients don't need to resend with new epoch
        # 2. Clearing would lose actions that clients already sent for next frame
        # 3. This would cause server to wait indefinitely while clients think they already sent
        #
        # On episode start, clients wait for server_episode_start before stepping,
        # so clearing is safe (they'll send fresh actions after receiving the event).
        if event_type == "server_episode_start":
            with self.action_lock:
                if self.pending_actions_for_step:
                    cleared_count = len(self.pending_actions_for_step)
                    self.pending_actions_for_step.clear()
                    logger.debug(
                        f"[ServerGameRunner] Cleared {cleared_count} pending actions after episode start"
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
        self.stop_realtime()  # Stop real-time loop if running
        self.is_initialized = False
        self.env = None
        logger.info(f"[ServerGameRunner] Stopped game {self.game_id}")
