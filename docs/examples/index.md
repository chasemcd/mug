# Examples

Complete example experiments demonstrating various MUG features. Each example includes full source code, detailed documentation, and instructions for customization.

All examples are located in the [examples/](https://github.com/chasemcd/mug/tree/main/examples) directory.

## Example Comparison

| Example | Players | Mode | Complexity | Key Features |
|---------|---------|------|------------|--------------|
| [Mountain Car](mountain-car.md) | Human | Client | Beginner | Client-side execution, custom rendering, RGB array conversion |
| [Slime Volleyball](slime-volleyball.md) | Human-Human, Human-AI | Server/Client | Intermediate | Human vs AI, ONNX policy inference, sprite rendering |
| [Overcooked: Human-AI](overcooked-human-ai.md) | Human-AI | Client | Advanced | Human-AI coordination, SP and BS policies, randomized layouts |
| [Overcooked: Client-Side](overcooked-client-side.md) | Human-Human | Client (P2P/GGPO) | Advanced | P2P multiplayer, GGPO rollback, latency-aware matchmaking |
| [Overcooked: Server-Side](overcooked-multiplayer.md) | Human-Human | Server | Advanced | Server-authoritative multiplayer, synchronized gameplay |
| [Footsies](footsies.md) | Human-AI | Client (WebGL) | Advanced | Fighting game mechanics, frame-perfect timing, competitive play |

### Prerequisites

**Important**: Examples must be run from a cloned repository, not from a pip installation, because they rely on relative paths for assets (sprites, models, etc.).

1. **Clone the repository**:

    ```bash
    git clone https://github.com/chasemcd/mug.git
    cd mug
    ```

2. **Install MUG with server dependencies**:

    ```bash
    pip install -e .[server]
    ```

3. **Install example-specific dependencies** (if needed):

    Some examples require additional packages. See individual example documentation for details.

### Running Examples

Examples must be run as modules from the repository root to ensure correct asset paths:

1. **From the repository root**, run the example as a module:

    ```bash
    python -m examples.example_name.experiment_file
    ```

    For example:

    ```bash
    # Mountain Car
    python -m examples.mountain_car.mountain_car_experiment

    # Slime Volleyball (Human vs AI, browser-side)
    python -m examples.slime_volleyball.human_ai_pyodide

    # Overcooked (Human vs AI, client-side)
    python -m examples.cogrid.overcooked_human_ai_client_side

    # Overcooked (Human vs Human, client-side P2P)
    python -m examples.cogrid.overcooked_human_human_multiplayer --experiment-id test

    # Overcooked (Human vs Human, server-authoritative)
    python -m examples.cogrid.overcooked_server_auth --experiment-id test

    # Footsies
    python -m examples.footsies.footsies_experiment
    ```

2. **Open browser** to the specified port (usually http://localhost:5702 or http://localhost:5000)

### Example Structure

Each example directory typically contains:

```text
example_name/
├── experiment_file.py            # Main experiment file
├── environment_file.py           # Environment implementation (if needed)
├── README.md                     # Setup instructions
├── policies/                     # AI policies (if applicable)
└── assets/                       # Images, sprites, etc.
```
