# Multi-User Gymnasium (MUG)

![PyPI - Version](https://img.shields.io/pypi/v/multi-user-gymnasium)
![PyPI - Downloads](https://img.shields.io/pypi/dm/multi-user-gymnasium)

<div align="center">
  <img src="docs/content/mug_logo.png" alt="MUG logo" width="300"/>
</div>

Multi-User Gymnasium (MUG) converts Gymnasium and PettingZoo environments into browser-based, multi-user experiments. It enables Python simulation environments to be accessed online, allowing humans to interact with them individually or alongside AI agents and other participants.

## Multiplayer Configuration

For P2P multiplayer experiments, MUG uses WebRTC for low-latency peer-to-peer connections. When direct P2P connections fail (due to firewalls, NAT, or restrictive networks), a TURN server provides relay fallback.

**Setting up TURN credentials:**

1. Sign up for a free TURN server at [Open Relay (metered.ca)](https://www.metered.ca/tools/openrelay/) (free tier: 20GB/month)

2. Set environment variables with your credentials:

   ```bash
   export TURN_USERNAME="your-openrelay-username"
   export TURN_CREDENTIAL="your-openrelay-api-key"
   ```

3. Enable WebRTC in your experiment configuration:

   ```python
   from mug.configurations import RemoteConfig

   config = RemoteConfig()
   config.webrtc()  # Auto-loads from TURN_USERNAME and TURN_CREDENTIAL env vars
   ```

**Alternative: Using a .env file**

Create a `.env` file (add to `.gitignore`):

```text
TURN_USERNAME=your-openrelay-username
TURN_CREDENTIAL=your-openrelay-api-key
```

Then load it in your experiment:

```python
from dotenv import load_dotenv
load_dotenv()

config = RemoteConfig()
config.webrtc()
```

**Testing TURN relay:**

To force all connections through TURN (useful for testing):

```python
config.webrtc(force_relay=True)
```

## Acknowledgements

The Phaser integration and server implementation are inspired by and derived from the
Overcooked AI demo by Carroll et al. (https://github.com/HumanCompatibleAI/overcooked-demo/tree/master).
