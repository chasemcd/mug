Pyodide Mode
============

Pyodide mode runs your environment entirely in the participant's browser using `Pyodide <https://pyodide.org/>`_, a WebAssembly-based Python runtime. This eliminates server-side computation and network latency for single-player experiments.

What is Pyodide?
----------------

Pyodide is Python compiled to WebAssembly that runs in web browsers:

- Full Python 3.11 interpreter
- Includes NumPy, SciPy, scikit-learn, and more
- Can install pure Python packages via micropip
- Sandboxed and secure

When your experiment uses Pyodide mode, the Python environment runs in each participant's browser, not on your server.

When to Use Pyodide Mode
-------------------------

✅ **Use Pyodide when:**

- Single-player experiments (one human, any number of AI policies)
- Environment is pure Python (no compiled dependencies)
- Want zero network latency
- Want to reduce server load
- Participants have decent internet (for initial package download)

❌ **Don't use Pyodide when:**

- Multi-player experiments (multiple humans)
- Environment requires compiled libraries (e.g., pygame, OpenGL)
- Complex AI policies need GPU inference
- Need centralized data validation
- Environment has non-Python dependencies

Enabling Pyodide Mode
----------------------

Basic Configuration
^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    from mug.scenes import gym_scene

    game_scene = (
        gym_scene.GymScene()
        .scene(scene_id="my_game")
        .runtime(
            run_through_pyodide=True,
            environment_initialization_code=(
                "import gymnasium as gym\n"
                "env = gym.make('CartPole-v1', render_mode='interactive-gym')"
            ),
            packages_to_install=["gymnasium==1.0.0"],
        )
    )

With External File
^^^^^^^^^^^^^^^^^^

For complex environments, use a separate file:

.. code-block:: python

    .runtime(
        run_through_pyodide=True,
        environment_initialization_code_filepath="my_environment.py",
        packages_to_install=["gymnasium==1.0.0", "numpy"],
    )

The file should end with:

.. code-block:: python

    # my_environment.py

    class MyEnv(gym.Env):
        # ... environment implementation

    # IMPORTANT: Must create instance named 'env'
    env = MyEnv(render_mode="mug")

How Pyodide Mode Works
-----------------------

Initialization Flow
^^^^^^^^^^^^^^^^^^^

1. **Participant loads page** → HTML/JavaScript downloaded
2. **Pyodide initializes** → WebAssembly Python runtime starts (~10-30s)
3. **Packages install** → pip installs specified packages (~10-60s)
4. **Environment code executes** → Your Python code runs in browser
5. **Game starts** → Participant can interact

**Total initial load:** 30-90 seconds depending on packages and connection.

Game Loop
^^^^^^^^^

.. code-block:: text

    Browser (Pyodide Python)              Server
    ────────────────────────              ──────

    1. env.step(action)
    2. observation, reward, done, info
    3. env.render()
    4. objects = [...]
    5. Display objects
    6. Capture keyboard input
    7. Repeat

All computation happens in the browser. The server only coordinates and saves data.

Data Collection
^^^^^^^^^^^^^^^

Data is sent to the server periodically:

.. code-block:: text

    Browser                               Server
    ───────                              ──────

    [Collect observations,
     actions, rewards]
                                    ←    Save to CSV
    [Continue game loop]

The server aggregates and saves this data to CSV files.

**Tracking Custom Data:**

By default, MUG tracks observations, actions, and rewards. To track additional information, add it to the ``infos`` dictionary returned from ``step()``:

.. code-block:: python

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

All data in ``infos`` is automatically logged to the CSV output files.

Environment Requirements
------------------------

Pure Python Only
^^^^^^^^^^^^^^^^

Pyodide only supports pure Python packages:

✅ **Works:**

- gymnasium
- numpy
- scipy
- scikit-learn
- pandas
- pillow (pure Python mode)

❌ **Doesn't work:**

- pygame (C dependencies)
- OpenCV (C++ dependencies)
- TensorFlow/PyTorch (too large, compiled)
- Custom C extensions

Custom Rendering
^^^^^^^^^^^^^^^^

Standard Gymnasium environments use pygame for rendering. Override with object contexts:

.. code-block:: python

    from gymnasium.envs.classic_control.cartpole import CartPoleEnv
    from mug.configurations.object_contexts import Circle, Line, Polygon

    class PyodideCartPole(CartPoleEnv):

        def render(self):
            assert self.render_mode == "mug"

            # Extract state
            x, x_dot, theta, theta_dot = self.state

            # Create visual objects
            cart = Polygon(
                uuid="cart",
                color="#333333",
                points=[(x-0.25, 0.5), (x+0.25, 0.5), (x+0.25, 0.6), (x-0.25, 0.6)],
            )

            pole = Line(
                uuid="pole",
                color="#964B00",
                points=[(x, 0.55), (x + np.sin(theta)*0.3, 0.55 - np.cos(theta)*0.3)],
                width=5,
            )

            return [cart.as_dict(), pole.as_dict()]

    env = PyodideCartPole(render_mode="mug")

Multi-Agent Format
^^^^^^^^^^^^^^^^^^

Pyodide environments must accept dict actions:

.. code-block:: python

    class MyPyodideEnv(gym.Env):

        def step(self, actions: dict):
            """Actions is a dict: {"human": action_value}"""
            assert "human" in actions
            action = actions["human"]

            # Step environment with single action
            obs, reward, done, truncated, info = super().step(action)

            return obs, reward, done, truncated, info

This matches MUG's multi-agent format.

Package Management
------------------

Specifying Packages
^^^^^^^^^^^^^^^^^^^

List all required packages with versions:

.. code-block:: python

    .runtime(
        packages_to_install=[
            "gymnasium==1.0.0",
            "numpy",
            "scipy",
        ],
    )

**Best practices:**

- Pin versions for reproducibility
- Only include necessary packages (faster loading)
- Test package compatibility with Pyodide

Available Packages
^^^^^^^^^^^^^^^^^^

Check `Pyodide package list <https://pyodide.org/en/stable/usage/packages-in-pyodide.html>`_ for built-in packages.

For pure Python packages not in Pyodide:

.. code-block:: python

    .runtime(
        packages_to_install=[
            "my-pure-python-package",  # Installed via micropip
        ],
    )

Custom Code Initialization
^^^^^^^^^^^^^^^^^^^^^^^^^^

If you need setup code before creating the environment:

.. code-block:: python

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

env = MyEnv(render_mode='interactive-gym')
        """,
    )

Performance Considerations
--------------------------

Initial Load Time
^^^^^^^^^^^^^^^^^

First page load is slow:

- Pyodide download: ~8 MB
- Package downloads: varies (NumPy ~10 MB)
- Initialization: 10-30 seconds

**Optimization tips:**

1. **Minimize packages**: Only install what you need
2. **Show loading screen**: Use ``scene_body`` to explain delay
3. **Test with slow connection**: Ensure acceptable experience
4. **Consider caching**: Service workers can cache Pyodide

Runtime Performance
^^^^^^^^^^^^^^^^^^^

Once loaded, performance is good:

- Python code runs at ~50-70% native speed
- NumPy operations are fast (WebAssembly optimized)
- No network latency for game loop

**Optimization tips:**

1. **Vectorize with NumPy**: Much faster than Python loops
2. **Minimize object count**: <500 render objects per frame
3. **Use permanent objects**: For static visual elements
4. **Profile your code**: Use ``console.time()`` in browser

Memory Usage
^^^^^^^^^^^^

Browsers limit WebAssembly memory:

- Typical limit: 2-4 GB
- Check for memory leaks
- Clear large arrays when done

.. code-block:: python

    def reset(self):
        # Clear old data
        self.trajectory_history = []
        # ...

User Experience
---------------

Loading Screen
^^^^^^^^^^^^^^

Provide clear feedback during initialization:

.. code-block:: python

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

The "Continue" button is disabled until Pyodide finishes loading.

Error Handling
^^^^^^^^^^^^^^

Users should check browser console (F12) for Python errors:

- Import errors (missing packages)
- Runtime errors in environment code
- Rendering issues

Encourage participants to report errors or provide fallback instructions.

Debugging Pyodide Mode
----------------------

Test Locally First
^^^^^^^^^^^^^^^^^^

Before running with participants:

1. Start your experiment server
2. Open browser to experiment URL
3. Open browser console (F12 → Console)
4. Watch for errors during loading
5. Complete a full playthrough

Common Issues
^^^^^^^^^^^^^

**"Package not found"**

- Check package name spelling
- Verify package is pure Python
- Check `Pyodide package compatibility <https://pyodide.org/en/stable/usage/packages-in-pyodide.html>`_

**"Module has no attribute 'env'"**

- Ensure your code creates ``env = MyEnv(...)``
- Check for syntax errors in environment code

**Blank canvas or no rendering**

- Verify ``render_mode="mug"``
- Check ``render()`` returns list of dicts
- Look for JavaScript errors in console

**Slow performance**

- Reduce object count in ``render()``
- Simplify environment logic
- Check for infinite loops or memory leaks

Advanced Usage
--------------

Precomputing Data
^^^^^^^^^^^^^^^^^

Precompute expensive operations:

.. code-block:: python

    class MyEnv(gym.Env):
        def __init__(self):
            # Precompute lookup tables
            self.distance_matrix = self.compute_distances()
            self.reward_table = self.compute_rewards()

        def step(self, action):
            # Use precomputed data (fast)
            reward = self.reward_table[self.state, action]

AI Policies in Browser
^^^^^^^^^^^^^^^^^^^^^^^

Run AI inference in the browser:

.. code-block:: python

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

env = MultiAgentEnv(render_mode='interactive-gym')
        """,
    )

Restarting Pyodide
^^^^^^^^^^^^^^^^^^

By default, Pyodide persists across scenes. To restart:

.. code-block:: python

    .runtime(
        run_through_pyodide=True,
        restart_pyodide=True,  # Restart between scenes
    )

This is useful if you want a clean state for each scene.

Comparison: Pyodide vs Server
------------------------------

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Feature
     - Pyodide Mode
     - Server Mode
   * - **Players**
     - 1 human + AI
     - Multiple humans + AI
   * - **Latency**
     - None (local)
     - Network-dependent
   * - **Initial Load**
     - 30-90 seconds
     - Instant
   * - **Server Load**
     - Minimal
     - Proportional to players
   * - **Environment**
     - Pure Python only
     - Any Python code
   * - **AI Inference**
     - In browser
     - On server (can use GPU)
   * - **Data Security**
     - Sent periodically
     - Real-time validation
   * - **Debugging**
     - Browser console
     - Server logs

Best Practices
--------------

1. **Test the full loading experience**: Ensure 30-60s wait is acceptable
2. **Pin package versions**: For reproducibility
3. **Provide clear loading feedback**: Participants need to know what's happening
4. **Minimize package count**: Faster initial load
5. **Use object-based rendering**: No pygame or compiled renderers
6. **Test on slow connections**: Some participants may have poor internet
7. **Provide fallback instructions**: For when loading fails
8. **Monitor browser console**: Catch errors early during testing

Example: Complete Pyodide Scene
--------------------------------

.. code-block:: python

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
            run_through_pyodide=True,
            environment_initialization_code_filepath="environments/mountain_car.py",
            packages_to_install=["gymnasium==1.0.0", "numpy"],
        )
    )

Next Steps
----------

- **Compare with server mode**: :doc:`server_mode`
- **Learn about rendering**: :doc:`object_contexts`
- **See complete example**: :doc:`../quick_start`
