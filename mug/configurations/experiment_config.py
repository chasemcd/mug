from __future__ import annotations
import copy
import json
from typing import Callable

from mug.scenes.stager import Stager
from mug.utils.sentinels import NotProvided


class ExperimentConfig:
    def __init__(self):

        # Experiment
        self.experiment_id: str = None
        self.stager: Stager = None

        # Hosting
        self.host = None
        self.port = 8000
        self.max_ping = 100000
        self.min_ping_measurements = 5

        # Experiment data
        self.save_experiment_data = True

        # WebRTC / TURN server configuration
        self.turn_username: str | None = None
        self.turn_credential: str | None = None
        self.force_turn_relay: bool = False

        # Entry screening configuration (experiment-level)
        self.device_exclusion: str | None = None
        self.browser_requirements: list[str] | None = None
        self.browser_blocklist: list[str] | None = None
        self.entry_max_ping: int | None = None
        self.entry_min_ping_measurements: int = 5
        self.exclusion_messages: dict[str, str] = {
            "mobile": "This study requires a desktop or laptop computer.",
            "desktop": "This study requires a mobile device.",
            "browser": "Your browser is not supported for this study.",
            "ping": "Your connection is too slow for this study.",
        }
        self.entry_exclusion_callback: Callable | None = None

        # Pyodide loading timeout (configurable, used by server-side grace period)
        self.pyodide_load_timeout_s: int = 60

    def experiment(
        self,
        experiment_id: str = NotProvided,
        stager: Stager = NotProvided,
        save_experiment_data: bool = True,
    ) -> ExperimentConfig:
        if experiment_id is not NotProvided:
            self.experiment_id = experiment_id

        if stager is not NotProvided:
            self.stager = stager

        if save_experiment_data is not NotProvided:
            self.save_experiment_data = save_experiment_data

        return self

    def hosting(
        self,
        host: str | None = NotProvided,
        port: int | None = NotProvided,
        max_ping: int = NotProvided,
    ):
        if host is not NotProvided:
            self.host = host

        if port is not NotProvided:
            self.port = port

        if max_ping is not NotProvided:
            self.max_ping = max_ping

        return self

    def webrtc(
        self,
        turn_username: str | None = None,
        turn_credential: str | None = None,
        force_relay: bool = False,
    ):
        """
        Configure WebRTC settings for P2P multiplayer.

        Credentials can be provided directly or via environment variables:
            - TURN_USERNAME: TURN server username
            - TURN_CREDENTIAL: TURN server credential/password

        Args:
            turn_username: TURN server username (from metered.ca or similar).
                          Falls back to TURN_USERNAME env var if not provided.
            turn_credential: TURN server credential/password.
                            Falls back to TURN_CREDENTIAL env var if not provided.
            force_relay: Force relay mode (for testing TURN without direct P2P)
        """
        import os
        import logging

        logger = logging.getLogger(__name__)

        # Use provided values, fall back to environment variables
        resolved_username = turn_username or os.environ.get("TURN_USERNAME")
        resolved_credential = turn_credential or os.environ.get("TURN_CREDENTIAL")

        if resolved_username and resolved_credential:
            self.turn_username = resolved_username
            self.turn_credential = resolved_credential
            logger.info(
                f"TURN credentials loaded (username: {resolved_username[:4]}...)"
            )
        elif resolved_username or resolved_credential:
            logger.warning(
                "Partial TURN config: both TURN_USERNAME and TURN_CREDENTIAL required"
            )
        else:
            logger.warning(
                "No TURN credentials found. Set TURN_USERNAME and TURN_CREDENTIAL "
                "env vars for NAT traversal fallback."
            )

        self.force_turn_relay = force_relay
        if force_relay:
            logger.info("TURN force_relay enabled - all connections will use TURN")

        return self

    def entry_screening(
        self,
        device_exclusion: str = NotProvided,
        browser_requirements: list[str] = NotProvided,
        browser_blocklist: list[str] = NotProvided,
        max_ping: int = NotProvided,
        min_ping_measurements: int = NotProvided,
        exclusion_messages: dict[str, str] = NotProvided,
        entry_callback: Callable = NotProvided,
    ):
        """Configure entry screening rules at the experiment level.

        Entry screening runs once when a participant first connects to the experiment.
        If any check fails, the participant sees the appropriate exclusion message
        and cannot proceed to any scene.

        :param device_exclusion: Device type to exclude. "mobile" excludes phones/tablets,
            "desktop" excludes desktop/laptop computers, None allows all.
        :type device_exclusion: str, optional
        :param browser_requirements: List of allowed browser names (case-insensitive).
            If provided, only these browsers are allowed. e.g., ["Chrome", "Firefox"].
        :type browser_requirements: list[str], optional
        :param browser_blocklist: List of blocked browser names (case-insensitive).
            These browsers are excluded even if in requirements. e.g., ["Safari"].
        :type browser_blocklist: list[str], optional
        :param max_ping: Maximum allowed latency in milliseconds. Participants with
            ping exceeding this are excluded.
        :type max_ping: int, optional
        :param min_ping_measurements: Minimum number of ping measurements required
            before checking latency. Defaults to 5.
        :type min_ping_measurements: int, optional
        :param exclusion_messages: Custom messages for each exclusion type.
            Keys: "mobile", "desktop", "browser", "ping".
        :type exclusion_messages: dict[str, str], optional
        :param entry_callback: Custom callback function for additional exclusion logic.
            Receives participant context dict, returns dict with 'exclude' and optional 'message'.
        :type entry_callback: Callable, optional
        :return: The ExperimentConfig instance (self)
        :rtype: ExperimentConfig
        """
        if device_exclusion is not NotProvided:
            assert device_exclusion in [None, "mobile", "desktop"], \
                "device_exclusion must be None, 'mobile', or 'desktop'"
            self.device_exclusion = device_exclusion

        if browser_requirements is not NotProvided:
            assert browser_requirements is None or isinstance(browser_requirements, list), \
                "browser_requirements must be None or a list of browser names"
            self.browser_requirements = browser_requirements

        if browser_blocklist is not NotProvided:
            assert browser_blocklist is None or isinstance(browser_blocklist, list), \
                "browser_blocklist must be None or a list of browser names"
            self.browser_blocklist = browser_blocklist

        if max_ping is not NotProvided:
            assert max_ping is None or (isinstance(max_ping, int) and max_ping > 0), \
                "max_ping must be None or a positive integer"
            self.entry_max_ping = max_ping

        if min_ping_measurements is not NotProvided:
            assert isinstance(min_ping_measurements, int) and min_ping_measurements >= 1, \
                "min_ping_measurements must be a positive integer"
            self.entry_min_ping_measurements = min_ping_measurements

        if exclusion_messages is not NotProvided:
            assert isinstance(exclusion_messages, dict), \
                "exclusion_messages must be a dictionary"
            self.exclusion_messages = {**self.exclusion_messages, **exclusion_messages}

        if entry_callback is not NotProvided:
            assert callable(entry_callback), \
                "entry_callback must be a callable function"
            self.entry_exclusion_callback = entry_callback

        return self

    def get_entry_screening_config(self) -> dict:
        """Get the entry screening configuration for sending to the client.

        :return: Dictionary with entry screening settings
        :rtype: dict
        """
        return {
            "device_exclusion": self.device_exclusion,
            "browser_requirements": self.browser_requirements,
            "browser_blocklist": self.browser_blocklist,
            "max_ping": self.entry_max_ping,
            "min_ping_measurements": self.entry_min_ping_measurements,
            "exclusion_messages": self.exclusion_messages,
            "has_entry_callback": self.entry_exclusion_callback is not None,
        }

    def get_pyodide_config(self) -> dict:
        """Scan stager scenes for Pyodide requirements.

        Iterates through all scenes (including wrapped scenes via unpack())
        to find any GymScene with run_through_pyodide=True, and collects the
        union of all packages_to_install across those scenes.

        :return: Dictionary with needs_pyodide flag and packages list
        :rtype: dict
        """
        if self.stager is None:
            return {"needs_pyodide": False, "packages_to_install": [], "pyodide_load_timeout_s": self.pyodide_load_timeout_s}

        needs_pyodide = False
        all_packages = set()

        for scene_or_wrapper in self.stager.scenes:
            unpacked = scene_or_wrapper.unpack()
            for s in unpacked:
                if hasattr(s, "run_through_pyodide") and s.run_through_pyodide:
                    needs_pyodide = True
                    if hasattr(s, "packages_to_install") and s.packages_to_install:
                        all_packages.update(s.packages_to_install)

        return {
            "needs_pyodide": needs_pyodide,
            "packages_to_install": list(all_packages),
            "pyodide_load_timeout_s": self.pyodide_load_timeout_s,
        }
