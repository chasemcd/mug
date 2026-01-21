from __future__ import annotations
import copy
import json

from interactive_gym.scenes.stager import Stager
from interactive_gym.scenes.utils import NotProvided


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

        print("self.turn_username:", self.turn_username)
        print("self.turn_credential:", self.turn_credential)
        print("self.force_turn_relay:", self.force_turn_relay)

        return self

    def to_dict(self, serializable=False):
        config = copy.deepcopy(vars(self))
        if serializable:
            config = serialize_dict(config)
        return config


def serialize_dict(data):
    """
    Serialize a dictionary to JSON, removing unserializable keys recursively.

    :param data: Dictionary to serialize.
    :return: Serialized object with unserializable elements removed.
    """
    if isinstance(data, dict):
        # Use dictionary comprehension to process each key-value pair
        return {
            key: serialize_dict(value)
            for key, value in data.items()
            if is_json_serializable(value)
        }
    elif isinstance(data, list):
        # Use list comprehension to process each item
        return [
            serialize_dict(item) for item in data if is_json_serializable(item)
        ]
    elif is_json_serializable(data):
        return data
    else:
        return None  # or some other default value


def is_json_serializable(value):
    """
    Check if a value is JSON serializable.

    :param value: The value to check.
    :return: True if the value is JSON serializable, False otherwise.
    """
    try:
        json.dumps(value)
        return True
    except (TypeError, OverflowError):
        return False
