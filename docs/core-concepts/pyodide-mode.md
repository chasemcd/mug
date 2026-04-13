# Browser-Side Execution

By default, MUG runs your environment directly in the participant's browser using [Pyodide](https://pyodide.org/), a WebAssembly-based Python runtime. This is the preferred execution mode because it eliminates network latency from the game loop and enables GGPO-based rollback netcode for multiplayer experiments.

## What is Pyodide?

Pyodide is Python compiled to WebAssembly that runs in web browsers:

- Full Python interpreter
- Includes NumPy, SciPy, scikit-learn, and more
- Can install pure Python packages via micropip
- Sandboxed and secure

When your experiment uses browser-side execution, the Python environment runs in each participant's browser, not on your server.

## Environment Compatibility

Browser-side execution is preferred whenever the environment is compatible. The only reason to fall back to server-side execution is if your environment has dependencies that cannot run in Pyodide (e.g., compiled C/C++ extensions, GPU-based inference, or system-level libraries). If your environment is pure Python, use browser-side execution.

## Enabling Browser-Side Execution

Browser-side execution is automatically enabled when you provide any Pyodide-specific runtime parameter (e.g., `environment_initialization_code`, `environment_initialization_code_filepath`, or `packages_to_install`).

### Basic Configuration

```python
from mug.scenes import gym_scene

game_scene = (
    gym_scene.GymScene()
    .scene(scene_id="my_game")
    .runtime(
        environment_initialization_code=(
            "import gymnasium as gym\n"
            "env = gym.make('CartPole-v1', render_mode='multi-user-gymnasium')"
        ),
        packages_to_install=["gymnasium==1.0.0"],
    )
)
```

### With External File

For complex environments, use a separate file:

```python
.runtime(
    environment_initialization_code_filepath="my_environment.py",
    packages_to_install=["gymnasium==1.0.0", "numpy"],
)
```

The file should end with:

```python
# my_environment.py

class MyEnv(gym.Env):
    # ... environment implementation

# IMPORTANT: Must create instance named 'env'
env = MyEnv(render_mode="mug")
```

## How Browser-Side Execution Works

### Initialization Flow

1. **Participant loads page** → HTML/JavaScript downloaded
2. **Pyodide initializes** → WebAssembly Python runtime starts (~10-30s)
3. **Packages install** → pip installs specified packages (~10-60s)
4. **Environment code executes** → Your Python code runs in browser
5. **Game starts** → Participant can interact

**Total initial load:** 30-90 seconds depending on packages and connection.

### Game Loop

```text
Browser (Pyodide Python)              Server
────────────────────────              ──────

1. env.step(action)
2. observation, reward, done, info
3. env.render()
4. objects = [...]
5. Display objects
6. Capture keyboard input
7. Repeat
```

All computation happens in the browser. The server only coordinates and saves data.

### Data Collection

Data is sent to the server periodically:

```text
Browser                               Server
───────                              ──────

[Collect observations,
 actions, rewards]
                                ←    Save to CSV
[Continue game loop]
```

The server aggregates and saves this data to CSV files.

**Tracking Custom Data:**

By default, MUG tracks observations, actions, and rewards. To track additional information, add it to the `infos` dictionary returned from `step()`:

```python
def step(self, actions: dict[str, int]):
    # Standard step logic
    observations = self._get_observations()
    rewards = self._compute_rewards()
    dones = self._check_done()
    truncated = False

    # Add custom data to infos for tracking
    infos = {agent_id: {} for agent_id in self.agents}
    for agent_id in self.agents:
        infos[agent_id]["reward"] = rewards[agent_id]
        infos[agent_id]["custom_metric"] = self._compute_custom_metric(agent_id)
        infos[agent_id]["state_hash"] = hash(observations[agent_id])

    return observations, rewards, dones, truncated, infos
```

All data in `infos` is automatically logged to the CSV output files.

## Environment Requirements

### Pure Python Only

Pyodide only supports pure Python packages. Environments with compiled C/C++ dependencies cannot run in the browser.

**Compatible packages** include gymnasium, numpy, scipy, scikit-learn, pandas, and pillow.

**Incompatible packages** include pygame (C dependencies), OpenCV (C++ dependencies), TensorFlow/PyTorch (too large, compiled), and custom C extensions.

### Custom Rendering

Standard Gymnasium environments use pygame for rendering. Override with the Surface API:

```python
from gymnasium.envs.classic_control.cartpole import CartPoleEnv
from mug.rendering import Surface
import numpy as np

class PyodideCartPole(CartPoleEnv):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.surface = Surface(width=600, height=400)

    def reset(self, *args, **kwargs):
        obs, info = super().reset(*args, **kwargs)
        self.surface.reset()
        return obs, info

    def render(self):
        assert self.render_mode == "mug"

        x, x_dot, theta, theta_dot = self.state

        self.surface.polygon(
            id="cart",
            color="#333333",
            points=[(x-0.25, 0.5), (x+0.25, 0.5), (x+0.25, 0.6), (x-0.25, 0.6)],
            relative=True,
        )

        self.surface.line(
            id="pole",
            color="#964B00",
            points=[(x, 0.55), (x + np.sin(theta)*0.3, 0.55 - np.cos(theta)*0.3)],
            width=5,
            relative=True,
        )

        return self.surface.commit().to_dict()

env = PyodideCartPole(render_mode="mug")
```

### Multi-Agent Format

Pyodide environments must accept dict actions:

```python
class MyPyodideEnv(gym.Env):

    def step(self, actions: dict):
        """Actions is a dict: {"human": action_value}"""
        assert "human" in actions
        action = actions["human"]

        # Step environment with single action
        obs, reward, done, truncated, info = super().step(action)

        return obs, reward, done, truncated, info
```

This matches MUG's multi-agent format.

## Package Management

### Specifying Packages

List all required packages with versions:

```python
.runtime(
    packages_to_install=[
        "gymnasium==1.0.0",
        "numpy",
        "scipy",
    ],
)
```

**Best practices:**

- Pin versions for reproducibility
- Only include necessary packages (faster loading)
- Test package compatibility with Pyodide

### Available Packages

Check [Pyodide package list](https://pyodide.org/en/stable/usage/packages-in-pyodide.html) for built-in packages.

For pure Python packages not in Pyodide:

```python
.runtime(
    packages_to_install=[
        "my-pure-python-package",  # Installed via micropip
    ],
)
```

### Custom Code Initialization

If you need setup code before creating the environment:

```python
.runtime(
    environment_initialization_code="""
import gymnasium as gym
import numpy as np

# Custom initialization
np.random.seed(42)

# Helper functions
def my_helper():
    pass

# Create environment
class MyEnv(gym.Env):
    # ...

env = MyEnv(render_mode='multi-user-gymnasium')
    """,
)
```

## Performance Considerations

### Initial Load Time

First page load is slow:

- Pyodide download: ~8 MB
- Package downloads: varies (NumPy ~10 MB)
- Initialization: 10-30 seconds

**Optimization tips:**

1. **Minimize packages**: Only install what you need
2. **Show loading screen**: Use `scene_body` to explain delay
3. **Test with slow connection**: Ensure acceptable experience
4. **Consider caching**: Service workers can cache Pyodide

### Runtime Performance

Once loaded, performance is good:

- Python code runs at ~50-70% native speed
- NumPy operations are fast (WebAssembly optimized)
- No network latency for game loop

**Optimization tips:**

1. **Vectorize with NumPy**: Much faster than Python loops
2. **Minimize object count**: <500 render objects per frame
3. **Use permanent objects**: For static visual elements
4. **Profile your code**: Use `console.time()` in browser

### Memory Usage

Browsers limit WebAssembly memory:

- Typical limit: 2-4 GB
- Check for memory leaks
- Clear large arrays when done

```python
def reset(self):
    # Clear old data
    self.trajectory_history = []
    # ...
```

## User Experience

### Loading Screen

Provide clear feedback during initialization:

```python
.content(
    scene_header="Game Loading...",
    scene_body="""
        <center>
        <p>Python is initializing in your browser.</p>
        <p>This may take 30-60 seconds on first load.</p>
        <p>Progress will show below...</p>
        </center>
    """,
    in_game_scene_body="<center><p>Use arrow keys to play!</p></center>",
)
```

The "Continue" button is disabled until Pyodide finishes loading.

### Error Handling

Users should check browser console (F12) for Python errors:

- Import errors (missing packages)
- Runtime errors in environment code
- Rendering issues

Encourage participants to report errors or provide fallback instructions.

## Debugging Browser-Side Execution

### Test Locally First

Before running with participants:

1. Start your experiment server
2. Open browser to experiment URL
3. Open browser console (F12 → Console)
4. Watch for errors during loading
5. Complete a full playthrough

### Common Issues

**"Package not found"**

- Check package name spelling
- Verify package is pure Python
- Check [Pyodide package compatibility](https://pyodide.org/en/stable/usage/packages-in-pyodide.html)

**"Module has no attribute 'env'"**

- Ensure your code creates `env = MyEnv(...)`
- Check for syntax errors in environment code

**Blank canvas or no rendering**

- Verify `render_mode="mug"`
- Check `render()` returns list of dicts
- Look for JavaScript errors in console

**Slow performance**

- Reduce object count in `render()`
- Simplify environment logic
- Check for infinite loops or memory leaks

## Advanced Usage

### Precomputing Data

Precompute expensive operations:

```python
class MyEnv(gym.Env):
    def __init__(self):
        # Precompute lookup tables
        self.distance_matrix = self.compute_distances()
        self.reward_table = self.compute_rewards()

    def step(self, action):
        # Use precomputed data (fast)
        reward = self.reward_table[self.state, action]
```

### AI Policies in Browser

Run AI inference in the browser:

```python
.runtime(
    environment_initialization_code="""
import gymnasium as gym
import numpy as np

# Load ONNX model (if using onnxruntime-web)
# Or implement simple policy

def ai_policy(observation):
    # Simple rule-based or loaded model
    return action

# Multi-agent environment
class MultiAgentEnv(gym.Env):
    def step(self, actions):
        if "ai_player" not in actions:
            # Run AI policy
            obs = self.get_observation("ai_player")
            actions["ai_player"] = ai_policy(obs)

        # Step with all actions
        return super().step(actions)

env = MultiAgentEnv(render_mode='multi-user-gymnasium')
    """,
)
```

### Restarting Pyodide

By default, Pyodide persists across scenes. To restart:

```python
.runtime(
    restart_pyodide=True,  # Restart between scenes
)
```

This is useful if you want a clean state for each scene.

## Comparison: Browser-Side vs Server-Side

| Feature | Browser-Side (Preferred) | Server-Side |
|---------|------------------------|-------------|
| **Players** | Single or multiplayer (via GGPO) | Multiplayer |
| **Latency** | None (local) + GGPO rollback for multiplayer | Network-dependent |
| **Initial Load** | 30-90 seconds | Instant |
| **Server Load** | Minimal | Proportional to players |
| **Environment** | Pure Python only | Any Python code |
| **AI Inference** | In browser (ONNX) | On server (can use GPU) |
| **Data Collection** | Sent periodically | Real-time |
| **Debugging** | Browser console | Server logs |

## Best Practices

1. **Test the full loading experience**: Ensure 30-60s wait is acceptable
2. **Pin package versions**: For reproducibility
3. **Provide clear loading feedback**: Participants need to know what's happening
4. **Minimize package count**: Faster initial load
5. **Use object-based rendering**: No pygame or compiled renderers
6. **Test on slow connections**: Some participants may have poor internet
7. **Provide fallback instructions**: For when loading fails
8. **Monitor browser console**: Catch errors early during testing

## Example: Complete Browser-Side Scene

```python
from mug.scenes import gym_scene
from mug.configurations import configuration_constants

game_scene = (
    gym_scene.GymScene()
    .scene(scene_id="pyodide_game")
    .rendering(
        fps=30,
        game_width=600,
        game_height=400,
    )
    .gameplay(
        num_episodes=5,
        action_mapping={
            "ArrowLeft": 0,
            "ArrowRight": 1,
        },
        default_action=0,
        input_mode=configuration_constants.InputModes.PressedKeys,
    )
    .policies(
        policy_mapping={"human": configuration_constants.PolicyTypes.Human}
    )
    .content(
        scene_header="Mountain Car",
        scene_body="""
            <center>
            <h3>Loading Python Environment...</h3>
            <p>This may take up to 60 seconds.</p>
            <p>The button below will activate when ready.</p>
            </center>
        """,
        in_game_scene_body="<center><p>Use arrow keys to reach the flag!</p></center>",
    )
    .runtime(
        environment_initialization_code_filepath="environments/mountain_car.py",
        packages_to_install=["gymnasium==1.0.0", "numpy"],
    )
)
```

## Next Steps

- **Server-side execution**: [Server Mode](server-mode.md)
- **Learn about rendering**: [Surface API](surface-api.md)
- **See complete example**: [Quick Start](../getting-started/quick-start.md)
