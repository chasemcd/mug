from __future__ import annotations


from typing import Any, Callable, TYPE_CHECKING
import copy
import json

if TYPE_CHECKING:
    from interactive_gym.server.matchmaker import Matchmaker

from interactive_gym.scenes import scene
from interactive_gym.configurations import remote_config
from interactive_gym.scenes import utils as scene_utils
from interactive_gym.configurations import configuration_constants
from interactive_gym.scenes.utils import NotProvided


class GymScene(scene.Scene):
    """GymScene is a Scene that represents an interaction with a Gym-style environment.

    All gym scenes begin with a static HTML page that loads the necessary assets and initializes the environment.
    Participants then click the "Start" button to begin interaction with the scene.

    Attributes:
        env_creator (Callable | None): Function to create the environment.
        env_config (dict[str, Any] | None): Configuration for the environment.
        env_seed (int): Seed for the environment's random number generator.
        load_policy_fn (Callable | None): Function to load policies.
        policy_inference_fn (Callable | None): Function for policy inference.
        policy_mapping (dict[str, Any]): Mapping of agents to policies.
        available_policies (dict[str, Any]): Available policies for the scene.
        policy_configs (dict[str, Any]): Configurations for the policies.
        frame_skip (int): Number of frames to skip between actions.
        num_episodes (int): Number of episodes to run.
        max_steps (int): Maximum number of steps per episode.
        action_mapping (dict[str, int]): Mapping of action names to action indices.
        human_id (str | int | None): Identifier for the human player.
        default_action (int | str | None): Default action to take if none is provided.
        action_population_method (str): Method for populating actions.
        input_mode (str): Mode of input for the scene.
        game_has_composite_actions (bool): Whether the game has composite actions.
        max_ping (int | None): Maximum allowed ping.
        min_ping_measurements (int): Minimum number of ping measurements required.
        callback (None): Callback function for the scene.
        env_to_state_fn (Callable | None): Function to convert environment state to renderable state.
        preload_specs (list[dict[str, str | int | float]] | None): Specifications for preloading assets.
        hud_text_fn (Callable | None): Function to generate HUD text.
        location_representation (str): Representation of locations ('relative' or 'pixels').
        game_width (int | None): Width of the game window.
        game_height (int | None): Height of the game window.
        fps (int): Frames per second for rendering.
        background (str): Background color of the scene.
        state_init (list): Initial state of the scene.
        assets_dir (str): Directory containing assets.
        assets_to_preload (list[str]): List of assets to preload.
        animation_configs (list): Configurations for animations.
        state_sync_frequency_frames (int | None): Frames between periodic state syncs (e.g., 300 = ~10s at 30fps). None disables periodic sync.
        queue_resync_threshold (int): Trigger state resync if action queue exceeds this size (default 50).
    """

    DEFAULT_IG_PACKAGE = "interactive-gym==0.1.1"

    def __init__(
        self,
    ):
        super().__init__()

        # Environment
        self.env_creator: Callable | None = None
        self.env_config: dict[str, Any] | None = None
        self.env_seed: int = 42

        # Policies
        self.load_policy_fn: Callable | None = None
        self.policy_inference_fn: Callable | None = None
        self.policy_mapping: dict[str, Any] = dict()
        self.available_policies: dict[str, Any] = dict()
        self.policy_configs: dict[str, Any] = dict()
        self.frame_skip: int = 4

        # gameplay
        self.num_episodes: int = 1
        self.max_steps: int = 1e4
        self.action_mapping: dict[str, int] = dict()
        self.human_id: str | int | None = None
        self.default_action: int | str | None = None
        self.action_population_method: str = (
            configuration_constants.ActionSettings.DefaultAction
        )
        self.input_mode: str = configuration_constants.InputModes.PressedKeys
        self.game_has_composite_actions: bool = False
        self.max_ping: int | None = None
        self.min_ping_measurements: int = 5
        self.callback: None = (
            None  # TODO(chase): add callback typehint but need to avoid circular import
        )

        # Rendering
        self.env_to_state_fn: Callable | None = None
        self.preload_specs: list[dict[str, str | int | float]] | None = None
        self.hud_text_fn: Callable | None = None
        self.hud_score_carry_over: bool = False  # If True, cumulative rewards carry over between episodes
        self.location_representation: str = "relative"  # "relative" or "pixels"
        self.game_width: int | None = 600
        self.game_height: int | None = 400
        self.fps: int = 10
        self.background: str = "#FFFFFF"  # white background default
        self.state_init: list = []
        self.assets_dir: str = "./static/assets/"
        self.assets_to_preload: list[str] = []
        self.animation_configs: list = []

        # user_experience
        self.scene_header: str = None
        self.scene_body: str = None
        self.in_game_scene_body: str = None
        self.waitroom_timeout_redirect_url: str = None
        self.waitroom_timeout_scene_id: str = None  # Scene to jump to on waitroom timeout
        self.waitroom_timeout: int = 120000
        self.waitroom_timeout_message: str | None = None  # Custom message when waitroom times out
        self.game_page_html_fn: Callable = None
        self.reset_timeout: int = 3000
        self.reset_freeze_s: int = 0

        # pyodide
        self.run_through_pyodide: bool = False
        self.pyodide_multiplayer: bool = False  # Enable multiplayer Pyodide coordination
        self.environment_initialization_code: str = ""
        self.on_game_step_code: str = ""
        self.packages_to_install: list[str] = [GymScene.DEFAULT_IG_PACKAGE]
        self.restart_pyodide: bool = False

        # Multiplayer sync settings (for pyodide_multiplayer=True)
        # state_broadcast_interval: Frames between state broadcasts/syncs
        # - In server-authoritative mode: server broadcasts authoritative state at this interval
        # - In host-based mode: clients verify state hashes at this interval
        # Set to None to disable periodic sync (not recommended)
        self.state_broadcast_interval: int = 30  # Frames between broadcasts (~1s at 30fps)

        # Server-authoritative multiplayer settings
        # When enabled, server runs a parallel Python environment that steps in sync with clients
        # and broadcasts authoritative state periodically, eliminating host dependency
        self.server_authoritative: bool = False

        # Real-time mode (for server-authoritative)
        # When True, server steps on a timer (not blocked by slow players)
        # Clients use prediction + rollback for smooth gameplay
        self.realtime_mode: bool = True

        # Input buffer size for rollback/replay (real-time mode)
        # Number of frames of input history to keep for potential replay
        self.input_buffer_size: int = 300  # ~10 sec at 30fps

        # GGPO input delay (frames)
        # Both local and remote actions are delayed by this many frames
        # This gives time for actions to propagate before they're needed
        # Set to 0 for no input delay (not recommended for multiplayer)
        self.input_delay: int = 0  # frames of input delay

        # Input confirmation timeout for episode boundaries (Phase 61: PARITY-01, PARITY-02)
        # Waits for partner input confirmation before episode export
        # Default 500ms handles 200ms+ RTT with margin for packet retransmission
        self.input_confirmation_timeout_ms: int = 500

        # Lobby/waitroom display settings
        self.hide_lobby_count: bool = False  # If True, hide participant count in waitroom

        # Matchmaking settings
        self.matchmaking_max_rtt: int | None = None  # Max RTT difference (ms) between paired participants
        self._matchmaker: "Matchmaker | None" = None  # Custom matchmaker, None uses default FIFO

        # Player group settings (for multiplayer games)
        # Groups are always tracked automatically after each game completes.
        # wait_for_known_group controls whether to require the same group members in this scene.
        self.wait_for_known_group: bool = False  # If True, wait for existing group; if False, use FIFO matching
        self.group_wait_timeout: int = 60000  # ms to wait for known group members before timeout

        # Rollback smoothing settings (for multiplayer games with GGPO)
        # When enabled, objects smoothly tween to their new positions after rollback corrections
        # instead of snapping/teleporting. This hides visual "jank" from state corrections.
        # Set to None to disable, or a positive integer (ms) to enable with that duration.
        self.rollback_smoothing_duration: int | None = 100  # Tween duration in ms, None to disable

        # Continuous monitoring (Phase 16)
        self.continuous_max_ping: int | None = None  # Max ping during gameplay (ms)
        self.continuous_ping_violation_window: int = 5  # Measurements to track
        self.continuous_ping_required_violations: int = 3  # Consecutive violations for exclusion
        self.continuous_tab_warning_ms: int = 3000  # Warn after 3s hidden
        self.continuous_tab_exclude_ms: int = 10000  # Exclude after 10s hidden
        self.continuous_monitoring_enabled: bool = False  # Master enable flag
        self.continuous_exclusion_messages: dict[str, str] = {
            "ping_warning": "Your connection is unstable. Please close other applications.",
            "ping_exclude": "Your connection became too slow. The game has ended.",
            "tab_warning": "Please return to the experiment window to continue.",
            "tab_exclude": "You left the experiment window for too long. The game has ended."
        }

        # Custom exclusion callbacks (Phase 18)
        self.continuous_exclusion_callback: Callable | None = None  # Called during gameplay
        self.continuous_callback_interval_frames: int = 30  # Frames between callback checks (~1s at 30fps)

        # Mid-game reconnection config
        self.reconnection_timeout_ms: int = 5000  # Default 5 seconds (RECON-04)

        # Partner disconnection message (Phase 23)
        self.partner_disconnect_message: str | None = None  # Custom message, None uses default
        self.partner_disconnect_show_completion_code: bool = True  # Show completion code on partner disconnect

        # Focus loss handling (Phase 27)
        self.focus_loss_timeout_ms: int = 30000  # Default 30 seconds
        self.focus_loss_message: str | None = None  # Custom message, None uses default
        self.pause_on_partner_background: bool = False  # If True, pause game when partner backgrounds

    def environment(
        self,
        env_creator: Callable = NotProvided,
        env_config: dict[str, Any] = NotProvided,
        seed: int = NotProvided,
    ):
        """Specify the environment settings for the scene.

        :param env_creator: A function that creates the environment with optional keyword arguments, defaults to NotProvided.
        :type env_creator: Callable, optional
        :param env_config: A dictionary of configurations for the environment.
        :type env_config: dict[str, Any], optional
        :param seed: Random seed for the environment, defaults to NotProvided
        :type seed: int, optional
        :return: This scene object
        :rtype: GymScene
        """
        if env_creator is not NotProvided:
            self.env_creator = env_creator

        if env_config is not NotProvided:
            self.env_config = env_config

        if seed is not NotProvided:
            self.seed = seed

        return self

    def rendering(
        self,
        fps: int = NotProvided,
        env_to_state_fn: Callable = NotProvided,
        hud_text_fn: Callable = NotProvided,
        hud_score_carry_over: bool = NotProvided,
        location_representation: str = NotProvided,
        game_width: int = NotProvided,
        game_height: int = NotProvided,
        background: str = NotProvided,
        rollback_smoothing_duration: int | None = NotProvided,
    ):
        """Configure display and rendering settings for the GymScene.

        :param fps: Frames per second for rendering the game, defaults to NotProvided
        :type fps: int, optional
        :param env_to_state_fn: Function to convert environment state to renderable state, defaults to NotProvided
        :type env_to_state_fn: Callable, optional
        :param hud_text_fn: Function to generate HUD text, defaults to NotProvided
        :type hud_text_fn: Callable, optional
        :param hud_score_carry_over: If True, cumulative rewards carry over between episodes, defaults to NotProvided
        :type hud_score_carry_over: bool, optional
        :param location_representation: How locations are represented ('relative' or 'pixels'), defaults to NotProvided
        :type location_representation: str, optional
        :param game_width: Width of the game screen in pixels, defaults to NotProvided
        :type game_width: int, optional
        :param game_height: Height of the game screen in pixels, defaults to NotProvided
        :type game_height: int, optional
        :param background: Background color or image for the game, defaults to NotProvided
        :type background: str, optional
        :param rollback_smoothing_duration: Duration of position smoothing tween in milliseconds after
            rollback corrections. Set to None to disable smoothing, or a positive integer to enable.
            Defaults to NotProvided (uses class default of 100ms).
        :type rollback_smoothing_duration: int | None, optional
        :raises ValueError: If rollback_smoothing_duration is less than 0
        :return: This scene object
        :rtype: GymScene
        """
        if env_to_state_fn is not NotProvided:
            self.env_to_state_fn = env_to_state_fn

        if hud_text_fn is not NotProvided:
            self.hud_text_fn = hud_text_fn

        if hud_score_carry_over is not NotProvided:
            self.hud_score_carry_over = hud_score_carry_over

        if location_representation is not NotProvided:
            assert location_representation in [
                "relative",
                "pixels",
            ], "Must pass either relative or pixel location!"
            self.location_representation = location_representation

        if fps is not NotProvided:
            self.fps = fps

        if game_width is not NotProvided:
            self.game_width = game_width

        if game_height is not NotProvided:
            self.game_height = game_height

        if background is not NotProvided:
            self.background = background

        if rollback_smoothing_duration is not NotProvided:
            if rollback_smoothing_duration is not None and rollback_smoothing_duration < 0:
                raise ValueError("rollback_smoothing_duration must be None or >= 0")
            self.rollback_smoothing_duration = rollback_smoothing_duration

        return self

    def assets(
        self,
        preload_specs: list[dict[str, str | float | int]] = NotProvided,
        assets_dir: str = NotProvided,
        assets_to_preload: list[str] = NotProvided,
        animation_configs: list = NotProvided,
        state_init: list = NotProvided,
    ):
        """Configure asset loading and initialization.

        :param preload_specs: Specifications for preloading assets, defaults to NotProvided
        :type preload_specs: list[dict[str, str | float | int]], optional
        :param assets_dir: Directory containing game assets, defaults to NotProvided
        :type assets_dir: str, optional
        :param assets_to_preload: List of asset filenames to preload, defaults to NotProvided
        :type assets_to_preload: list[str], optional
        :param animation_configs: Configurations for game animations, defaults to NotProvided
        :type animation_configs: list, optional
        :param state_init: Initial state of the game, defaults to NotProvided
        :type state_init: list, optional
        :return: This scene object
        :rtype: GymScene
        """
        if preload_specs is not NotProvided:
            self.preload_specs = preload_specs

        if assets_dir is not NotProvided:
            self.assets_dir = assets_dir

        if assets_to_preload is not NotProvided:
            self.assets_to_preload = assets_to_preload

        if animation_configs is not NotProvided:
            self.animation_configs = animation_configs

        if state_init is not NotProvided:
            self.state_init = state_init

        return self

    def policies(
        self,
        policy_mapping: dict = NotProvided,
        load_policy_fn: Callable = NotProvided,
        policy_inference_fn: Callable = NotProvided,
        frame_skip: int = NotProvided,
    ):
        """_summary_

        :param policy_mapping: A dictionary mapping agent IDs to policy names, defaults to NotProvided
        :type policy_mapping: dict, optional
        :param load_policy_fn: A function to load policies, defaults to NotProvided
        :type load_policy_fn: Callable, optional
        :param policy_inference_fn: A function for policy inference, defaults to NotProvided
        :type policy_inference_fn: Callable, optional
        :param frame_skip: Number of frames to skip between actions, defaults to NotProvided
        :type frame_skip: int, optional
        :return: The GymScene instance
        :rtype: GymScene
        """
        if policy_mapping is not NotProvided:
            self.policy_mapping = policy_mapping

        if load_policy_fn is not NotProvided:
            self.load_policy_fn = load_policy_fn

        if policy_inference_fn is not NotProvided:
            self.policy_inference_fn = policy_inference_fn

        if frame_skip is not NotProvided:
            self.frame_skip = frame_skip

        return self

    def gameplay(
        self,
        action_mapping: dict = NotProvided,
        human_id: str | int = NotProvided,
        num_episodes: int = NotProvided,
        max_steps: int = NotProvided,
        default_action: int | str = NotProvided,
        action_population_method: str = NotProvided,
        input_mode: str = NotProvided,
        callback: None = NotProvided,  # TODO(chase): add callback typehint without circular import
        reset_freeze_s: int = NotProvided,
    ):
        """Configure gameplay settings for the GymScene.

        :param action_mapping: Mapping of action names to action indices, defaults to NotProvided
        :type action_mapping: dict, optional
        :param human_id: Identifier for the human player, defaults to NotProvided
        :type human_id: str | int, optional
        :param num_episodes: Number of episodes to run, defaults to NotProvided
        :type num_episodes: int, optional
        :param max_steps: Maximum number of steps per episode, defaults to NotProvided
        :type max_steps: int, optional
        :param default_action: Default action to take if none is provided, defaults to NotProvided
        :type default_action: int | str, optional
        :param action_population_method: Method for populating actions, defaults to NotProvided
        :type action_population_method: str, optional
        :param input_mode: Mode of input for the scene, defaults to NotProvided
        :type input_mode: str, optional
        :param callback: Callback function for the scene, defaults to NotProvided
        :type callback: None, optional
        :param reset_freeze_s: Number of seconds to freeze the scene after reset, defaults to NotProvided
        :type reset_freeze_s: int, optional
        :return: The GymScene instance
        :rtype: GymScene
        """
        if action_mapping is not NotProvided:
            # ensure the composite action tuples are sorted and
            # formatted as strings to work with serialization
            converted_action_mapping = {}
            for k, v in action_mapping.items():
                if isinstance(k, tuple):
                    self.game_has_composite_actions = True
                    converted_action_mapping[",".join(list(sorted(k)))] = v
                else:
                    converted_action_mapping[k] = v
            self.action_mapping = converted_action_mapping

        if action_population_method is not NotProvided:
            self.action_population_method = action_population_method

        if human_id is not NotProvided:
            self.human_id = human_id

        if num_episodes is not NotProvided:
            assert (
                type(num_episodes) == int and num_episodes >= 1
            ), "Must pass an int >=1 to num episodes."
            self.num_episodes = num_episodes

        if max_steps is not NotProvided:
            self.max_steps = max_steps

        if default_action is not NotProvided:
            self.default_action = default_action

        if input_mode is not NotProvided:
            self.input_mode = input_mode

        if callback is not NotProvided:
            self.callback = callback

        if reset_freeze_s is not NotProvided:
            self.reset_freeze_s = reset_freeze_s

        return self

    def content(
        self,
        scene_header: str = NotProvided,
        scene_body: str = NotProvided,
        scene_body_filepath: str = NotProvided,
        in_game_scene_body: str = NotProvided,
        in_game_scene_body_filepath: str = NotProvided,
        game_page_html_fn: Callable = NotProvided,
    ):
        """Configure scene content display.

        :param scene_header: Header text for the scene, defaults to NotProvided
        :type scene_header: str, optional
        :param scene_body: HTML body content for the scene, defaults to NotProvided
        :type scene_body: str, optional
        :param scene_body_filepath: Path to a file containing HTML body content, defaults to NotProvided
        :type scene_body_filepath: str, optional
        :param in_game_scene_body: HTML body content displayed during gameplay, defaults to NotProvided
        :type in_game_scene_body: str, optional
        :param in_game_scene_body_filepath: Path to a file containing in-game HTML body, defaults to NotProvided
        :type in_game_scene_body_filepath: str, optional
        :param game_page_html_fn: Function to generate custom game page HTML, defaults to NotProvided
        :type game_page_html_fn: Callable, optional
        :return: This scene object
        :rtype: GymScene
        """
        if scene_header is not NotProvided:
            self.scene_header = scene_header

        if game_page_html_fn is not NotProvided:
            self.game_page_html_fn = game_page_html_fn

        if scene_body_filepath is not NotProvided:
            assert (
                scene_body is NotProvided
            ), "Cannot set both filepath and html_body."

            with open(scene_body_filepath, "r", encoding="utf-8") as f:
                self.scene_body = f.read()

        if scene_body is not NotProvided:
            assert (
                scene_body_filepath is NotProvided
            ), "Cannot set both filepath and html_body."
            self.scene_body = scene_body

        if in_game_scene_body_filepath is not NotProvided:
            assert (
                in_game_scene_body is NotProvided
            ), "Cannot set both filepath and html_body."

            with open(in_game_scene_body_filepath, "r", encoding="utf-8") as f:
                self.in_game_scene_body = f.read()

        if in_game_scene_body is not NotProvided:
            assert (
                in_game_scene_body_filepath is NotProvided
            ), "Cannot set both filepath and html_body."
            self.in_game_scene_body = in_game_scene_body

        return self

    def waitroom(
        self,
        timeout: int = NotProvided,
        timeout_redirect_url: str = NotProvided,
        timeout_scene_id: str = NotProvided,
        timeout_message: str = NotProvided,
    ):
        """Configure waitroom behavior.

        :param timeout: Timeout for waitroom in milliseconds, defaults to NotProvided
        :type timeout: int, optional
        :param timeout_redirect_url: URL to redirect to if waitroom times out, defaults to NotProvided
        :type timeout_redirect_url: str, optional
        :param timeout_scene_id: Scene ID to jump to if waitroom times out, defaults to NotProvided
        :type timeout_scene_id: str, optional
        :param timeout_message: Custom message when waitroom times out, defaults to NotProvided
        :type timeout_message: str, optional
        :return: This scene object
        :rtype: GymScene
        """
        if timeout is not NotProvided:
            self.waitroom_timeout = timeout

        if timeout_redirect_url is not NotProvided:
            self.waitroom_timeout_redirect_url = timeout_redirect_url

        if timeout_scene_id is not NotProvided:
            self.waitroom_timeout_scene_id = timeout_scene_id

        if timeout_message is not NotProvided:
            self.waitroom_timeout_message = timeout_message

        return self

    def matchmaking(
        self,
        hide_lobby_count: bool = NotProvided,
        max_rtt: int = NotProvided,
        matchmaker: "Matchmaker" = NotProvided,
    ):
        """Configure matchmaking and lobby settings for the GymScene.

        :param hide_lobby_count: If True, hides the participant count display in the waitroom.
            Participants will only see the countdown timer, not how many are waiting.
            Defaults to NotProvided (False).
        :type hide_lobby_count: bool, optional
        :param max_rtt: Maximum RTT difference (in milliseconds) allowed between participants
            when pairing. If a participant's RTT differs from another by more than this value,
            they will not be paired together. Set to None to disable RTT-based pairing.
            Defaults to NotProvided (None).
        :type max_rtt: int, optional
        :param matchmaker: Custom Matchmaker instance for participant grouping logic.
            Must be a subclass of Matchmaker with find_match() implemented.
            Defaults to NotProvided (uses FIFOMatchmaker).
        :type matchmaker: Matchmaker, optional
        :return: The GymScene instance
        :rtype: GymScene

        Example:
            from interactive_gym.server.matchmaker import FIFOMatchmaker

            scene.matchmaking(
                hide_lobby_count=True,  # Don't show "2/4 players in lobby"
                max_rtt=50,  # Only pair participants within 50ms RTT of each other
                matchmaker=FIFOMatchmaker(),  # or custom subclass
            )
        """
        if hide_lobby_count is not NotProvided:
            self.hide_lobby_count = hide_lobby_count

        if max_rtt is not NotProvided:
            if max_rtt is not None and max_rtt <= 0:
                raise ValueError("max_rtt must be a positive integer or None")
            self.matchmaking_max_rtt = max_rtt

        if matchmaker is not NotProvided:
            # Runtime import to avoid circular dependency
            from interactive_gym.server.matchmaker import Matchmaker as MatchmakerABC
            if not isinstance(matchmaker, MatchmakerABC):
                raise TypeError("matchmaker must be a Matchmaker subclass instance")
            self._matchmaker = matchmaker

        return self

    @property
    def matchmaker(self) -> "Matchmaker | None":
        """Return configured matchmaker, or None for default FIFO."""
        return self._matchmaker

    def runtime(
        self,
        run_through_pyodide: bool = NotProvided,
        environment_initialization_code: str = NotProvided,
        environment_initialization_code_filepath: str = NotProvided,
        on_game_step_code: str = NotProvided,
        packages_to_install: list[str] = NotProvided,
        restart_pyodide: bool = NotProvided,
    ):
        """Configure browser runtime (Pyodide) settings.

        This method configures the Pyodide runtime that allows Python environments
        to run directly in the participant's browser.

        :param run_through_pyodide: Whether to run the environment through Pyodide, defaults to NotProvided
        :type run_through_pyodide: bool, optional
        :param environment_initialization_code: Python code to initialize the environment in Pyodide, defaults to NotProvided
        :type environment_initialization_code: str, optional
        :param environment_initialization_code_filepath: Path to a file containing initialization code, defaults to NotProvided
        :type environment_initialization_code_filepath: str, optional
        :param on_game_step_code: Python code to run on each game step, defaults to NotProvided
        :type on_game_step_code: str, optional
        :param packages_to_install: List of packages to install in Pyodide, defaults to NotProvided
        :type packages_to_install: list[str], optional
        :param restart_pyodide: Whether to restart Pyodide between scenes, defaults to NotProvided
        :type restart_pyodide: bool, optional
        :return: This scene object
        :rtype: GymScene
        """
        if run_through_pyodide is not NotProvided:
            assert isinstance(run_through_pyodide, bool)
            self.run_through_pyodide = run_through_pyodide

        if environment_initialization_code is not NotProvided:
            self.environment_initialization_code = (
                environment_initialization_code
            )

        if environment_initialization_code_filepath is not NotProvided:
            assert (
                environment_initialization_code is NotProvided
            ), "Cannot set both filepath and code!"
            with open(
                environment_initialization_code_filepath, "r", encoding="utf-8"
            ) as f:
                self.environment_initialization_code = f.read()

        if packages_to_install is not NotProvided:
            self.packages_to_install = packages_to_install
            if not any("interactive-gym" in pkg for pkg in packages_to_install):
                self.packages_to_install.append(self.DEFAULT_IG_PACKAGE)

        if restart_pyodide is not NotProvided:
            self.restart_pyodide = restart_pyodide

        if on_game_step_code is not NotProvided:
            self.on_game_step_code = on_game_step_code

        return self

    def multiplayer(
        self,
        # Sync/rollback params (from pyodide)
        multiplayer: bool = NotProvided,
        server_authoritative: bool = NotProvided,
        state_broadcast_interval: int = NotProvided,
        realtime_mode: bool = NotProvided,
        input_buffer_size: int = NotProvided,
        input_delay: int = NotProvided,
        input_confirmation_timeout_ms: int = NotProvided,
        # Matchmaking params (from matchmaking)
        hide_lobby_count: bool = NotProvided,
        max_rtt: int = NotProvided,
        matchmaker: "Matchmaker" = NotProvided,
        # Player grouping params (from player_grouping)
        wait_for_known_group: bool = NotProvided,
        group_wait_timeout: int = NotProvided,
        # Continuous monitoring params (from continuous_monitoring)
        continuous_monitoring_enabled: bool = NotProvided,
        continuous_max_ping: int = NotProvided,
        continuous_ping_violation_window: int = NotProvided,
        continuous_ping_required_violations: int = NotProvided,
        continuous_tab_warning_ms: int = NotProvided,
        continuous_tab_exclude_ms: int = NotProvided,
        continuous_exclusion_messages: dict[str, str] = NotProvided,
        # Exclusion callback params (from exclusion_callbacks)
        continuous_callback: Callable = NotProvided,
        continuous_callback_interval_frames: int = NotProvided,
        # Reconnection params (from reconnection_config)
        reconnection_timeout_ms: int = NotProvided,
        # Partner disconnect params (from partner_disconnect_message_config)
        partner_disconnect_message: str = NotProvided,
        partner_disconnect_show_completion_code: bool = NotProvided,
        # Focus loss params (from focus_loss_config)
        focus_loss_timeout_ms: int = NotProvided,
        focus_loss_message: str = NotProvided,
        pause_on_partner_background: bool = NotProvided,
    ):
        """Configure multiplayer settings for the GymScene.

        This method consolidates all multiplayer-related configuration into a single
        builder method. It accepts parameters from sync/rollback, matchmaking, player
        grouping, continuous monitoring, exclusion callbacks, reconnection, partner
        disconnect, and focus loss configuration.

        **Sync/Rollback Configuration:**

        :param multiplayer: Enable multiplayer Pyodide coordination, defaults to NotProvided
        :type multiplayer: bool, optional
        :param server_authoritative: If True, server runs a parallel environment that
            broadcasts authoritative state periodically, defaults to NotProvided
        :type server_authoritative: bool, optional
        :param state_broadcast_interval: Frames between state broadcasts/syncs, defaults to NotProvided
        :type state_broadcast_interval: int, optional
        :param realtime_mode: If True, server steps on a timer rather than waiting for
            all player actions, defaults to NotProvided
        :type realtime_mode: bool, optional
        :param input_buffer_size: Number of frames of input history to keep for
            rollback/replay, defaults to NotProvided
        :type input_buffer_size: int, optional
        :param input_delay: GGPO input delay in frames, defaults to NotProvided
        :type input_delay: int, optional
        :param input_confirmation_timeout_ms: Time in ms to wait for partner input
            confirmation at episode boundaries, defaults to NotProvided
        :type input_confirmation_timeout_ms: int, optional

        **Matchmaking:**

        :param hide_lobby_count: If True, hide participant count in waitroom, defaults to NotProvided
        :type hide_lobby_count: bool, optional
        :param max_rtt: Maximum RTT difference (ms) between paired participants, defaults to NotProvided
        :type max_rtt: int, optional
        :param matchmaker: Custom Matchmaker instance for participant grouping logic, defaults to NotProvided
        :type matchmaker: Matchmaker, optional

        **Player Grouping:**

        :param wait_for_known_group: If True, wait for existing group members, defaults to NotProvided
        :type wait_for_known_group: bool, optional
        :param group_wait_timeout: Max time (ms) to wait for known group members, defaults to NotProvided
        :type group_wait_timeout: int, optional

        **Continuous Monitoring:**

        :param continuous_monitoring_enabled: Master enable flag for continuous monitoring.
            Auto-enabled if any monitoring param is set, defaults to NotProvided
        :type continuous_monitoring_enabled: bool, optional
        :param continuous_max_ping: Maximum allowed latency (ms) during gameplay, defaults to NotProvided
        :type continuous_max_ping: int, optional
        :param continuous_ping_violation_window: Number of measurements to track for
            violation detection, defaults to NotProvided
        :type continuous_ping_violation_window: int, optional
        :param continuous_ping_required_violations: Consecutive violations required
            before exclusion, defaults to NotProvided
        :type continuous_ping_required_violations: int, optional
        :param continuous_tab_warning_ms: Milliseconds hidden before showing warning, defaults to NotProvided
        :type continuous_tab_warning_ms: int, optional
        :param continuous_tab_exclude_ms: Milliseconds hidden before exclusion, defaults to NotProvided
        :type continuous_tab_exclude_ms: int, optional
        :param continuous_exclusion_messages: Custom messages for warnings and exclusions, defaults to NotProvided
        :type continuous_exclusion_messages: dict[str, str], optional

        **Exclusion Callbacks:**

        :param continuous_callback: Function called periodically during gameplay, defaults to NotProvided
        :type continuous_callback: Callable, optional
        :param continuous_callback_interval_frames: Frames between continuous callback
            checks, defaults to NotProvided
        :type continuous_callback_interval_frames: int, optional

        **Reconnection:**

        :param reconnection_timeout_ms: Time in ms to wait for reconnection before
            ending the game, defaults to NotProvided
        :type reconnection_timeout_ms: int, optional

        **Partner Disconnect:**

        :param partner_disconnect_message: Custom message when partner disconnects, defaults to NotProvided
        :type partner_disconnect_message: str, optional
        :param partner_disconnect_show_completion_code: Whether to show completion code
            on partner disconnect, defaults to NotProvided
        :type partner_disconnect_show_completion_code: bool, optional

        **Focus Loss:**

        :param focus_loss_timeout_ms: Time in ms before focus loss ends the game, defaults to NotProvided
        :type focus_loss_timeout_ms: int, optional
        :param focus_loss_message: Custom message when game ends due to focus loss, defaults to NotProvided
        :type focus_loss_message: str, optional
        :param pause_on_partner_background: If True, pause game when partner tabs away, defaults to NotProvided
        :type pause_on_partner_background: bool, optional

        :return: This scene object
        :rtype: GymScene
        """
        # --- Sync/rollback params ---
        if multiplayer is not NotProvided:
            assert isinstance(multiplayer, bool)
            self.pyodide_multiplayer = multiplayer

        if server_authoritative is not NotProvided:
            assert isinstance(server_authoritative, bool)
            self.server_authoritative = server_authoritative

        if state_broadcast_interval is not NotProvided:
            assert isinstance(state_broadcast_interval, int) and state_broadcast_interval > 0
            self.state_broadcast_interval = state_broadcast_interval

        if realtime_mode is not NotProvided:
            assert isinstance(realtime_mode, bool)
            self.realtime_mode = realtime_mode

        if input_buffer_size is not NotProvided:
            assert isinstance(input_buffer_size, int) and input_buffer_size > 0
            self.input_buffer_size = input_buffer_size

        if input_delay is not NotProvided:
            assert isinstance(input_delay, int) and input_delay >= 0
            self.input_delay = input_delay

        if input_confirmation_timeout_ms is not NotProvided:
            if not isinstance(input_confirmation_timeout_ms, int) or input_confirmation_timeout_ms < 0:
                raise ValueError("input_confirmation_timeout_ms must be a non-negative integer")
            self.input_confirmation_timeout_ms = input_confirmation_timeout_ms

        # --- Matchmaking params ---
        if hide_lobby_count is not NotProvided:
            self.hide_lobby_count = hide_lobby_count

        if max_rtt is not NotProvided:
            if max_rtt is not None and max_rtt <= 0:
                raise ValueError("max_rtt must be a positive integer or None")
            self.matchmaking_max_rtt = max_rtt

        if matchmaker is not NotProvided:
            # Runtime import to avoid circular dependency
            from interactive_gym.server.matchmaker import Matchmaker as MatchmakerABC
            if not isinstance(matchmaker, MatchmakerABC):
                raise TypeError("matchmaker must be a Matchmaker subclass instance")
            self._matchmaker = matchmaker

        # --- Player grouping params ---
        if wait_for_known_group is not NotProvided:
            assert isinstance(wait_for_known_group, bool)
            self.wait_for_known_group = wait_for_known_group

        if group_wait_timeout is not NotProvided:
            assert isinstance(group_wait_timeout, int) and group_wait_timeout > 0
            self.group_wait_timeout = group_wait_timeout

        # --- Continuous monitoring params ---
        # Track whether any monitoring param was explicitly provided
        _monitoring_param_provided = False

        if continuous_max_ping is not NotProvided:
            assert continuous_max_ping is None or (isinstance(continuous_max_ping, int) and continuous_max_ping > 0), \
                "continuous_max_ping must be None or a positive integer"
            self.continuous_max_ping = continuous_max_ping
            _monitoring_param_provided = True

        if continuous_ping_violation_window is not NotProvided:
            assert isinstance(continuous_ping_violation_window, int) and continuous_ping_violation_window >= 1, \
                "continuous_ping_violation_window must be a positive integer"
            self.continuous_ping_violation_window = continuous_ping_violation_window
            _monitoring_param_provided = True

        if continuous_ping_required_violations is not NotProvided:
            assert isinstance(continuous_ping_required_violations, int) and continuous_ping_required_violations >= 1, \
                "continuous_ping_required_violations must be a positive integer"
            self.continuous_ping_required_violations = continuous_ping_required_violations
            _monitoring_param_provided = True

        if continuous_tab_warning_ms is not NotProvided:
            assert continuous_tab_warning_ms is None or (isinstance(continuous_tab_warning_ms, int) and continuous_tab_warning_ms >= 0), \
                "continuous_tab_warning_ms must be None or a non-negative integer"
            self.continuous_tab_warning_ms = continuous_tab_warning_ms
            _monitoring_param_provided = True

        if continuous_tab_exclude_ms is not NotProvided:
            assert continuous_tab_exclude_ms is None or (isinstance(continuous_tab_exclude_ms, int) and continuous_tab_exclude_ms >= 0), \
                "continuous_tab_exclude_ms must be None or a non-negative integer"
            self.continuous_tab_exclude_ms = continuous_tab_exclude_ms
            _monitoring_param_provided = True

        if continuous_exclusion_messages is not NotProvided:
            assert isinstance(continuous_exclusion_messages, dict), \
                "continuous_exclusion_messages must be a dictionary"
            self.continuous_exclusion_messages = {**self.continuous_exclusion_messages, **continuous_exclusion_messages}
            _monitoring_param_provided = True

        # Handle continuous_monitoring_enabled: explicit setting or auto-enable
        if continuous_monitoring_enabled is not NotProvided:
            self.continuous_monitoring_enabled = continuous_monitoring_enabled
        elif _monitoring_param_provided:
            self.continuous_monitoring_enabled = True

        # Cross-validation: required_violations must not exceed window
        if self.continuous_ping_required_violations > self.continuous_ping_violation_window:
            raise ValueError(
                f"ping_required_violations ({self.continuous_ping_required_violations}) "
                f"cannot exceed ping_violation_window ({self.continuous_ping_violation_window})"
            )

        # --- Exclusion callback params ---
        if continuous_callback is not NotProvided:
            if continuous_callback is not None and not callable(continuous_callback):
                raise ValueError("continuous_callback must be callable or None")
            self.continuous_exclusion_callback = continuous_callback

        if continuous_callback_interval_frames is not NotProvided:
            if not isinstance(continuous_callback_interval_frames, int) or continuous_callback_interval_frames < 1:
                raise ValueError("continuous_callback_interval_frames must be a positive integer")
            self.continuous_callback_interval_frames = continuous_callback_interval_frames

        # --- Reconnection params ---
        if reconnection_timeout_ms is not NotProvided:
            if not isinstance(reconnection_timeout_ms, int) or reconnection_timeout_ms <= 0:
                raise ValueError("timeout_ms must be a positive integer")
            self.reconnection_timeout_ms = reconnection_timeout_ms

        # --- Partner disconnect params ---
        if partner_disconnect_message is not NotProvided:
            self.partner_disconnect_message = partner_disconnect_message

        if partner_disconnect_show_completion_code is not NotProvided:
            self.partner_disconnect_show_completion_code = partner_disconnect_show_completion_code

        # --- Focus loss params ---
        if focus_loss_timeout_ms is not NotProvided:
            if not isinstance(focus_loss_timeout_ms, int) or focus_loss_timeout_ms < 0:
                raise ValueError("timeout_ms must be a non-negative integer")
            self.focus_loss_timeout_ms = focus_loss_timeout_ms

        if focus_loss_message is not NotProvided:
            self.focus_loss_message = focus_loss_message

        if pause_on_partner_background is not NotProvided:
            self.pause_on_partner_background = pause_on_partner_background

        return self

    @property
    def simulate_waiting_room(self) -> bool:
        """Determines if the scene should simulate a waiting room.

        This property checks if there's any randomization in the waiting room time,
        which would necessitate simulating a waiting room experience.

        Returns a boolean indicating whether or not we're
        forcing all participants to be in a waiting room, regardless
        of if they're waiting for other players or not.

        :return: True if the maximum waiting room time randomization interval is greater than 0, False otherwise.
        :rtype: bool
        """
        return max(self.waitroom_time_randomization_interval_s) > 0

    def get_complete_scene_metadata(self) -> dict:
        """Get the complete metadata for the scene.

        This method returns a dictionary containing all the metadata for the scene,
        including all class properties that are not already in the base scene metadata.
        It handles various data types, converting complex objects to dictionaries or strings
        to ensure all data is serializable.

        :return: A dictionary containing all the scene's metadata
        :rtype: dict
        """
        metadata = super().scene_metadata

        # Add all of the class properties to the metadata
        for k, v in self.__dict__.items():
            if k not in metadata and k != "sio":
                if (
                    isinstance(v, (str, int, float, bool, list, dict))
                    or v is None
                ):
                    metadata[k] = v
                elif hasattr(v, "__dict__"):
                    metadata[k] = v.__dict__
                else:
                    metadata[k] = str(v)

        # Add custom callback flags (Phase 18)
        # Only include boolean flags, not the actual callback functions (they run server-side only)
        metadata["has_continuous_callback"] = self.continuous_exclusion_callback is not None
        metadata["continuous_callback_interval_frames"] = self.continuous_callback_interval_frames

        return metadata
