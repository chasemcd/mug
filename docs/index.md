# Multi-User Gymnasium (MUG)

![PyPI - Version](https://img.shields.io/pypi/v/multi-user-gymnasium)
![PyPI - Downloads](https://img.shields.io/pypi/dm/multi-user-gymnasium)
![GitHub Repo stars](https://img.shields.io/github/stars/chasemcd/interactive-gym)

<div align="center">
  <img src="assets/images/mug_logo.png" alt="MUG logo" width="300"/>
</div>

Multi-User Gymnasium (MUG) converts [Gymnasium](https://gymnasium.farama.org/) and [PettingZoo](https://pettingzoo.farama.org/) environments into browser-based, multi-user experiments. It enables Python simulation environments to be accessed online, allowing humans to interact with them individually or alongside AI agents and other participants.

## Installation

```bash
pip install multi-user-gymnasium[server]
```

## Getting Started

- [Installation](getting-started/installation.md) — Complete installation guide including prerequisites and verification steps.
- [Quick Start: Single Player](getting-started/quick-start.md) — Step-by-step walkthrough creating a Mountain Car experiment with custom rendering and Pyodide.
- [Quick Start: Multiplayer](getting-started/quick-start-multiplayer.md) — Step-by-step walkthrough creating a two-player Slime Volleyball experiment with P2P synchronization and GGPO rollback netcode.

## Next Steps

After completing the installation and quick start guides:

- **Learn the architecture**: [Core Concepts](core-concepts/scenes.md) explains how MUG works
- **Explore examples**: [Examples](examples/index.md) shows complete experiments
- **Read detailed guides**: Browse the Core Concepts section for in-depth documentation
