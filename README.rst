
Multi-User Gymnasium (MUG)
==========================

.. image:: https://img.shields.io/pypi/dm/multi-user-gymnasium
:alt: PyPI - Downloads

.. image:: https://img.shields.io/pypi/v/multi-user-gymnasium
:alt: PyPI - Version




.. image:: docs/content/mug_logo.png
    :alt: MUG Logo
    :align: center

Multi-User Gymnasium (MUG) is a library that provides a generalized interface for creating interactive, browser-based experiments from simulation environments. More specifically,
it is meant to take Python-based Gymnasium or PettingZoo formatted environments and run them in the browser such that humans can interact with the
environments either alone or alongside AI or other humans.


Multiplayer Configuration
-------------------------

For P2P multiplayer experiments, MUG uses WebRTC for low-latency peer-to-peer connections. When direct P2P connections fail (due to firewalls, NAT, or restrictive networks), a TURN server provides relay fallback.

**Setting up TURN credentials:**

1. Sign up for a free TURN server at `Open Relay (metered.ca) <https://www.metered.ca/tools/openrelay/>`_ (free tier: 20GB/month)

2. Set environment variables with your credentials:

   .. code-block:: bash

       export TURN_USERNAME="your-openrelay-username"
       export TURN_CREDENTIAL="your-openrelay-api-key"

3. Enable WebRTC in your experiment configuration:

   .. code-block:: python

       from mug.configurations import RemoteConfig

       config = RemoteConfig()
       config.webrtc()  # Auto-loads from TURN_USERNAME and TURN_CREDENTIAL env vars

**Alternative: Using a .env file**

Create a ``.env`` file (add to ``.gitignore``):

.. code-block:: text

    TURN_USERNAME=your-openrelay-username
    TURN_CREDENTIAL=your-openrelay-api-key

Then load it in your experiment:

.. code-block:: python

    from dotenv import load_dotenv
    load_dotenv()

    config = RemoteConfig()
    config.webrtc()

**Testing TURN relay:**

To force all connections through TURN (useful for testing):

.. code-block:: python

    config.webrtc(force_relay=True)


Acknowledgements
---------------------

The Phaser integration and server implementation are inspired by and derived from the
Overcooked AI demo by Carroll et al. (https://github.com/HumanCompatibleAI/overcooked-demo/tree/master).
