# Overcooked Examples

This directory contains Interactive Gym examples using the CoGrid Overcooked environment. These examples demonstrate both single-player (Human-AI) and multiplayer (Human-Human) experiments using client-side Pyodide execution.

## Prerequisites

Install the CoGrid Overcooked environment:

```bash
pip install git+https://github.com/chasemcd/cogrid.git
```

Or install a specific version:

```bash
pip install cogrid==0.0.15
```

## Examples

### 1. Human-AI Comparison (`overcooked_human_ai_client_side.py`)

**Description**: Within-subjects experiment comparing two AI partners (Self-Play vs Behavior Shaping).

**Features**:
- Client-side Pyodide execution (zero server computation)
- Two AI conditions: SP (Self-Play) and BS (Behavior Shaping)
- One random layout selected per participant
- Preference elicitation between partners
- ONNX-based AI policies

**Usage**:
```bash
python -m interactive_gym.examples.cogrid.overcooked_human_ai_client_side
```

Navigate to `http://localhost:5702` in your browser.

**Experiment Flow**:
1. Welcome & instructions
2. Tutorial (single-player practice)
3. Round 1: Play with SP AI partner
4. Round 2: Play with BS AI partner
5. Preference feedback
6. Completion

### 2. Human-Human Multiplayer (`overcooked_human_human_multiplayer.py`)

**Description**: Real-time multiplayer experiment with two human participants.

**Features**:
- **NEW**: Multiplayer Pyodide coordination
- Each client runs environment in their browser
- Server coordinates action synchronization
- Deterministic execution via seeded RNG
- State verification (every 30 frames)
- Automatic desync recovery
- Host-only data logging (no duplicates)
- Host migration on disconnection

**Usage**:
```bash
python -m interactive_gym.examples.cogrid.overcooked_human_human_multiplayer
```

Open **TWO** browser windows to `http://localhost:5702`.

**Experiment Flow**:
1. Welcome & instructions
2. Tutorial (solo practice)
3. Waiting room (until 2 players join)
4. Multiplayer game (one random layout)
5. Multiplayer feedback
6. Completion

**How Multiplayer Works**:

```
┌─────────────────┐         ┌──────────────┐         ┌─────────────────┐
│   Browser 1     │         │    Server    │         │   Browser 2     │
│   (Player 0)    │         │ Coordinator  │         │   (Player 1)    │
│                 │         │              │         │                 │
│ ┌─────────────┐ │         │              │         │ ┌─────────────┐ │
│ │  Pyodide    │ │         │              │         │ │  Pyodide    │ │
│ │ Environment │ │         │              │         │ │ Environment │ │
│ └─────────────┘ │         │              │         │ └─────────────┘ │
└─────────────────┘         └──────────────┘         └─────────────────┘
         │                         │                         │
         │    1. Send action       │                         │
         ├────────────────────────>│                         │
         │                         │    1. Send action       │
         │                         │<────────────────────────┤
         │                         │                         │
         │              2. Collect & broadcast              │
         │                         │                         │
         │    3. Actions ready     │    3. Actions ready     │
         │<────────────────────────┼────────────────────────>│
         │                         │                         │
         │    4. env.step()        │         4. env.step()   │
         │    (synchronized)       │         (synchronized)  │
```

## Scene Definitions

All scenes are defined in `scenes/scenes.py`:

### Single-Player Scenes (Human-AI)
- `cramped_room_sp_0` / `cramped_room_ibc_0`
- `counter_circuit_sp_0` / `counter_circuit_ibc_0`
- `forced_coordination_sp_0` / `forced_coordination_ibc_0`
- `asymmetric_advantages_sp_0` / `asymmetric_advantages_ibc_0`
- `coordination_ring_sp_0` / `coordination_ring_ibc_0`

### Multiplayer Scenes (Human-Human)
- `cramped_room_human_human`
- `counter_circuit_human_human`
- `forced_coordination_human_human`
- `asymmetric_advantages_human_human`
- `coordination_ring_human_human`

## Layouts

All five Overcooked layouts are included:

1. **Cramped Room** (5×3) - Tight coordination, high conflict
2. **Asymmetric Advantages** (9×5) - Asymmetric roles
3. **Counter Circuit** (7×5) - Large space, specialization
4. **Forced Coordination** (5×5) - Required division of labor
5. **Coordination Ring** (5×5) - Circular layout, central cooking

## Configuration

### Policy Mappings

**Human-AI**:
```python
{
    0: configuration_constants.PolicyTypes.Human,
    1: "static/assets/overcooked/models/sp_cramped_room_00.onnx"
}
```

**Human-Human**:
```python
{
    0: configuration_constants.PolicyTypes.Human,
    1: configuration_constants.PolicyTypes.Human
}
```

### Enabling Multiplayer

```python
scene = (
    gym_scene.GymScene()
    .scene(scene_id="my_multiplayer_scene", experiment_config={})
    .runtime(
        run_through_pyodide=True,
        environment_initialization_code_filepath="...",
        packages_to_install=[...]
    )
    .multiplayer(
        multiplayer=True,  # Enable multiplayer coordination
    )
    .policies(policy_mapping={
        0: configuration_constants.PolicyTypes.Human,
        1: configuration_constants.PolicyTypes.Human
    })
    # ... rest of configuration
)
```

## Data Collection

### Human-AI Experiments
- Each participant's data saved independently
- Format: `data/scene_id/participant_id.csv`

### Human-Human Experiments
- **Only host logs data** (first player to join)
- Prevents duplicate data from multiple clients
- Format: `data/scene_id/host_participant_id.csv`
- Contains both players' actions and observations

## Technical Details

### Multiplayer Implementation

The Human-Human multiplayer uses a sophisticated synchronization system:

**Key Components**:
- `SeededRandom` (JS) - Deterministic RNG for AI policies
- `MultiplayerPyodideGame` (JS) - Client-side multiplayer coordinator
- `PyodideGameCoordinator` (Python) - Server-side action synchronizer
- SocketIO events for real-time communication

**Synchronization Guarantees**:
- All clients receive same seed at game start
- Actions collected and broadcast synchronously each frame
- State verification every 30 frames via SHA256 hashing
- Automatic resync on desync detection
- Host migration on disconnection

**Performance**:
- Zero server-side environment computation
- ~2.7% overhead from state verification
- Sub-second desync detection
- ~100ms recovery time from desyncs

For detailed implementation documentation, see:
- `../../docs/multiplayer_pyodide_implementation.md`

## Troubleshooting

### Common Issues

**Issue**: Players see different game states

**Solution**: Check browser console for desync messages. State verification should detect and recover automatically. If persistent, ensure both clients have same Pyodide/package versions.

**Issue**: Waiting room timeout

**Solution**: Increase `waitroom_timeout` in scene configuration (default 120 seconds).

**Issue**: Actions not synchronized

**Solution**: Check network latency. High latency (>500ms) may cause delays. Consider adjusting `action_timeout` in PyodideGameCoordinator.

**Issue**: No data saved

**Solution**: For multiplayer, only the host logs data. Check server logs to identify which participant is host.

### Debug Logging

Enable detailed logging in Python:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Enable debug logging in browser console:
```javascript
localStorage.debug = '*';  // Enable all debug logs
```

## Citation

If you use these examples in research, please cite:

```bibtex
@software{interactive_gym,
  title={Interactive Gym: Browser-Based Multi-Agent RL Experiments},
  author={McDonald, Chase},
  year={2024},
  url={https://github.com/chasemcd/interactive-gym}
}

@article{mcdonald2025controllable,
  title={Controllable Complementarity: Subjective Preferences in Human-AI Collaboration},
  author={McDonald, Chase and Gonzalez, Cleotilde},
  journal={arXiv preprint arXiv:2503.05455},
  year={2025}
}
```

## Related Examples

- `../pettingzoo/` - Other multi-agent environments
- See main Interactive Gym documentation for more examples
