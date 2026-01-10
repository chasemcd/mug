from __future__ import annotations


from typing import Any, Callable
import copy
import json

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
        self.waitroom_timeout_redirect_url: str = None
        self.waitroom_timeout: int = 120000
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

        # Player group settings (for multiplayer games)
        # Groups are always tracked automatically after each game completes.
        # wait_for_known_group controls whether to require the same group members in this scene.
        self.wait_for_known_group: bool = False  # If True, wait for existing group; if False, use FIFO matching
        self.group_wait_timeout: int = 60000  # ms to wait for known group members before timeout

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
        preload_specs: list[dict[str, str | float | int]] = NotProvided,
        hud_text_fn: Callable = NotProvided,
        hud_score_carry_over: bool = NotProvided,
        location_representation: str = NotProvided,
        game_width: int = NotProvided,
        game_height: int = NotProvided,
        background: str = NotProvided,
        state_init: list = NotProvided,
        assets_dir: str = NotProvided,
        assets_to_preload: list[str] = NotProvided,
        animation_configs: list = NotProvided,
    ):
        """_summary_

        :param fps: Frames per second for rendering the game, defaults to NotProvided
        :type fps: int, optional
        :param env_to_state_fn: Function to convert environment state to renderable state, defaults to NotProvided
        :type env_to_state_fn: Callable, optional
        :param preload_specs: Specifications for preloading assets, defaults to NotProvided
        :type preload_specs: list[dict[str, str  |  float  |  int]], optional
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
        :param state_init: Initial state of the game, defaults to NotProvided
        :type state_init: list, optional
        :param assets_dir: Directory containing game assets, defaults to NotProvided
        :type assets_dir: str, optional
        :param assets_to_preload: List of asset filenames to preload, defaults to NotProvided
        :type assets_to_preload: list[str], optional
        :param animation_configs: Configurations for game animations, defaults to NotProvided
        :type animation_configs: list, optional
        :return: This scene object
        :rtype: GymScene
        """
        if env_to_state_fn is not NotProvided:
            self.env_to_state_fn = env_to_state_fn

        if hud_text_fn is not NotProvided:
            self.hud_text_fn = hud_text_fn

        if hud_score_carry_over is not NotProvided:
            self.hud_score_carry_over = hud_score_carry_over

        if preload_specs is not NotProvided:
            self.preload_specs = preload_specs

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

        if state_init is not NotProvided:
            self.state_init = state_init

        if assets_dir is not NotProvided:
            self.assets_dir = assets_dir

        if assets_to_preload is not NotProvided:
            self.assets_to_preload = assets_to_preload

        if animation_configs is not NotProvided:
            self.animation_configs = animation_configs

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

    def user_experience(
        self,
        scene_header: str = NotProvided,
        scene_body: str = NotProvided,
        scene_body_filepath: str = NotProvided,
        in_game_scene_body: str = NotProvided,
        in_game_scene_body_filepath: str = NotProvided,
        waitroom_timeout: int = NotProvided,
        waitroom_timeout_redirect_url: str = NotProvided,
        game_page_html_fn: Callable = NotProvided,
    ):
        """Configure the user experience for the GymScene.

        :param scene_header: Header text for the scene, defaults to NotProvided
        :type scene_header: str, optional
        :param scene_body: HTML body content for the scene, defaults to NotProvided
        :type scene_body: str, optional
        :param scene_body_filepath: Path to a file containing HTML body content, defaults to NotProvided
        :type scene_body_filepath: str, optional
        :param in_game_scene_body: HTML body content displayed during gameplay, defaults to NotProvided
        :type in_game_scene_body: str, optional
        :param in_game_scene_body_filepath: Path to a file containing in-game HTML body content, defaults to NotProvided
        :type in_game_scene_body_filepath: str, optional
        :param waitroom_timeout: Timeout for waitroom in milliseconds, defaults to NotProvided
        :type waitroom_timeout: int, optional
        :param waitroom_timeout_redirect_url: URL to redirect to if waitroom times out, defaults to NotProvided
        :type waitroom_timeout_redirect_url: str, optional
        :param game_page_html_fn: Function to generate custom game page HTML, defaults to NotProvided
        :type game_page_html_fn: Callable, optional
        :return: The GymScene instance
        :rtype: GymScene
        """
        if scene_header is not NotProvided:
            self.scene_header = scene_header

        if waitroom_timeout_redirect_url is not NotProvided:
            self.waitroom_timeout_redirect_url = waitroom_timeout_redirect_url

        if waitroom_timeout is not NotProvided:
            self.waitroom_timeout = waitroom_timeout

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

    def pyodide(
        self,
        run_through_pyodide: bool = NotProvided,
        multiplayer: bool = NotProvided,
        environment_initialization_code: str = NotProvided,
        environment_initialization_code_filepath: str = NotProvided,
        on_game_step_code: str = NotProvided,
        packages_to_install: list[str] = NotProvided,
        restart_pyodide: bool = NotProvided,
        server_authoritative: bool = NotProvided,
        state_broadcast_interval: int = NotProvided,
    ):
        """Configure Pyodide-related settings for the GymScene.

        This method sets up parameters related to running the environment through Pyodide,
        which allows Python code to run in the browser.

        :param run_through_pyodide: Whether to run the environment through Pyodide, defaults to NotProvided
        :type run_through_pyodide: bool, optional
        :param multiplayer: Enable multiplayer Pyodide coordination (requires run_through_pyodide=True), defaults to NotProvided
        :type multiplayer: bool, optional
        :param environment_initialization_code: Python code to initialize the environment in Pyodide, defaults to NotProvided
        :type environment_initialization_code: str, optional
        :param environment_initialization_code_filepath: Path to a file containing Python code to initialize the environment, defaults to NotProvided
        :type environment_initialization_code_filepath: str, optional
        :param packages_to_install: List of Python packages to install in the Pyodide environment, defaults to NotProvided
        :type packages_to_install: list[str], optional
        :param restart_pyodide: Whether to restart the Pyodide environment, defaults to NotProvided
        :type restart_pyodide: bool, optional
        :param server_authoritative: If True, server runs a parallel Python environment that steps
            in sync with clients and broadcasts authoritative state periodically. This eliminates
            host dependency and provides faster resyncs. Requires multiplayer=True. defaults to NotProvided
        :type server_authoritative: bool, optional
        :param state_broadcast_interval: Frames between state broadcasts/syncs. In server-authoritative
            mode, server broadcasts authoritative state at this interval. In host-based mode, clients
            verify state hashes at this interval. Default is 30 (~1 sec at 30fps). defaults to NotProvided
        :type state_broadcast_interval: int, optional
        :return: The GymScene instance (self)
        :rtype: GymScene
        """
        if run_through_pyodide is not NotProvided:
            assert isinstance(run_through_pyodide, bool)
            self.run_through_pyodide = run_through_pyodide

        if multiplayer is not NotProvided:
            assert isinstance(multiplayer, bool)
            self.pyodide_multiplayer = multiplayer

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

        if server_authoritative is not NotProvided:
            assert isinstance(server_authoritative, bool)
            self.server_authoritative = server_authoritative

        if state_broadcast_interval is not NotProvided:
            assert isinstance(state_broadcast_interval, int) and state_broadcast_interval > 0
            self.state_broadcast_interval = state_broadcast_interval

        return self

    def player_grouping(
        self,
        wait_for_known_group: bool = NotProvided,
        group_wait_timeout: int = NotProvided,
    ):
        """Configure player grouping behavior for multiplayer games.

        Player groups are always tracked automatically after each game completes.
        This method controls whether this scene requires the same group members or
        allows new matches. Supports groups of any size (2 or more players).

        :param wait_for_known_group: If True, players with existing groups will wait
            for all their known group members. If False, players enter the FIFO queue
            and may be matched with new players (which updates their stored group).
            Defaults to NotProvided
        :type wait_for_known_group: bool, optional
        :param group_wait_timeout: Maximum time (ms) to wait for known group members.
            After timeout, player is redirected to waitroom_timeout_redirect_url.
            Defaults to NotProvided
        :type group_wait_timeout: int, optional
        :return: The GymScene instance (self)
        :rtype: GymScene
        """
        if wait_for_known_group is not NotProvided:
            assert isinstance(wait_for_known_group, bool)
            self.wait_for_known_group = wait_for_known_group

        if group_wait_timeout is not NotProvided:
            assert isinstance(group_wait_timeout, int) and group_wait_timeout > 0
            self.group_wait_timeout = group_wait_timeout

        return self

    # Backwards compatibility alias
    def player_pairing(
        self,
        wait_for_known_partner: bool = NotProvided,
        partner_wait_timeout: int = NotProvided,
    ):
        """Deprecated: Use player_grouping() instead.

        This method is kept for backwards compatibility.
        """
        return self.player_grouping(
            wait_for_known_group=wait_for_known_partner,
            group_wait_timeout=partner_wait_timeout,
        )

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

        return metadata
