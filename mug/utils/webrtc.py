from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def configure_webrtc(
    config,
    turn_username: str | None = None,
    turn_credential: str | None = None,
    force_relay: bool = False,
) -> None:
    """Configure WebRTC/TURN settings on a config object.

    Sets turn_username, turn_credential, and force_turn_relay attributes.
    Falls back to TURN_USERNAME and TURN_CREDENTIAL environment variables
    if credentials are not provided directly.

    Args:
        config: The configuration object to update (ExperimentConfig).
        turn_username: TURN server username (from metered.ca or similar).
                       Falls back to TURN_USERNAME env var if not provided.
        turn_credential: TURN server credential/password.
                         Falls back to TURN_CREDENTIAL env var if not provided.
        force_relay: Force relay mode (for testing TURN without direct P2P).
    """
    # Use provided values, fall back to environment variables
    resolved_username = turn_username or os.environ.get("TURN_USERNAME")
    resolved_credential = turn_credential or os.environ.get("TURN_CREDENTIAL")

    if resolved_username and resolved_credential:
        config.turn_username = resolved_username
        config.turn_credential = resolved_credential
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

    config.force_turn_relay = force_relay
    if force_relay:
        logger.info("TURN force_relay enabled - all connections will use TURN")
