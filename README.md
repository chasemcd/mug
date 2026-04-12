# Multi-User Gymnasium (MUG)

![PyPI - Version](https://img.shields.io/pypi/v/multi-user-gymnasium)
![PyPI - Downloads](https://img.shields.io/pypi/dm/multi-user-gymnasium)

<div align="center">
  <img src="docs/assets/images/mug_logo.png" alt="MUG logo" width="300"/>
</div>

Multi-User Gymnasium (MUG) converts [Gymnasium](https://gymnasium.farama.org/) and [PettingZoo](https://pettingzoo.farama.org/) environments into browser-based, multi-user experiments. It enables Python simulation environments to be accessed online, allowing humans to interact with them individually or alongside AI agents and other participants.

## Installation

```bash
pip install multi-user-gymnasium
```

<div align="center">
  <img src="docs/assets/images/overcooked_example.apng" alt="Overcooked human-AI demo" width="600"/>
</div>

## What does MUG offer?

- **Same environment, training to deployment.** Run user experiments in the browser against the exact same simulation environments you use to train your AI agents without any rewrites or ports.
- **In-browser execution.** Python environments and AI policies can run client-side for zero-latency experiences for participants. Heavier environments---or those that can't be compiled to run in the browser---can be run on the server.
- **Multi-human Experiments.** Built-in networking, rollback netcode, and waiting rooms for multi-participant experiments.
- **Experiment orchestration.** Scene flow, participant management, and data collection out of the box.
- **Extensive customizability.** Advanced hooks and configuration for custom rendering, matchmaking, scene logic, and more.

For full explanations of each feature, see the [documentation](https://multi-user-gymnasium.readthedocs.io/).



## Acknowledgements

The Phaser integration and server implementation are inspired by and derived from the
Overcooked AI demo by Carroll et al. (https://github.com/HumanCompatibleAI/overcooked-demo/tree/master).
