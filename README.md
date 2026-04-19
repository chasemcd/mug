# Multi-User Gymnasium (MUG)

![PyPI - Version](https://img.shields.io/pypi/v/multi-user-gymnasium)
![PyPI - Downloads](https://img.shields.io/pypi/dm/multi-user-gymnasium)

<div align="center">
  <img src="docs/assets/images/mug_logo.png" alt="MUG logo" width="300"/>
</div>

Multi-User Gymnasium (MUG) converts [Gymnasium](https://gymnasium.farama.org/) and [PettingZoo](https://pettingzoo.farama.org/) environments into browser-based, multi-user experiments. It enables Python simulation environments to be accessed online, allowing humans to interact with them individually or alongside AI agents and other participants.

Get started by reading the [documentation](https://multi-user-gymnasium.readthedocs.io/).

## Installation

```bash
pip install multi-user-gymnasium[server]
```

<div align="center">
  <img src="docs/assets/images/overcooked_example.apng" alt="Overcooked human-AI demo" width="600"/>
</div>

## What does MUG offer?

- **Same environment, training to deployment.** Run user experiments in the browser against the exact same simulation environments you use to train your AI agents without any rewrites or ports.
- **In-browser execution.** Python environments and AI policies can run client-side for zero-latency experiences for participants. Heavier environments---or those that can't be compiled to run in the browser---can be run on the server.
- **Multi-human Experiments.** Built-in networking, rollback netcode, and waiting rooms for multi-participant experiments.
- **Experiment orchestration.** Scene flow, [participant management, and data collection](https://multi-user-gymnasium.readthedocs.io/en/latest/core-concepts/participants-and-data/) out of the box.
- **Extensive customizability.** Advanced hooks and configuration for custom rendering, matchmaking, scene logic, and more.

For full explanations of each feature, see the [documentation](https://multi-user-gymnasium.readthedocs.io/).


## Citation

If you use MUG in your research, please cite:

```bibtex
@article{mcdonald2026cogrid,
  title={CoGrid \& the Multi-User Gymnasium: A Framework for Multi-Agent Experimentation},
  author={McDonald, Chase and Gonzalez, Cleotilde},
  journal={arXiv preprint arXiv:2604.15044},
  year={2026}
}
```

## MUG in the Wild

Below are a list of projects that have used MUG. If you use it in your research, please let us know or open a PR for it to be added here.

```bibtex
@article{mcdonald2025controllable,
  title={Controllable Complementarity: Subjective Preferences in Human-AI Collaboration},
  author={McDonald, Chase and Gonzalez, Cleotilde},
  journal={arXiv preprint arXiv:2503.05455},
  year={2025}
}
```

## Acknowledgements

The Phaser integration and server implementation are inspired by and derived from the
Overcooked AI demo by Carroll et al. (https://github.com/HumanCompatibleAI/overcooked-demo/tree/master).
