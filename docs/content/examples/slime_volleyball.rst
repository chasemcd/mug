Slime Volleyball
================

The Slime Volleyball example demonstrates human vs AI gameplay with custom rendering and physics-based mechanics. Players compete against a trained AI opponent in a classic volleyball game.

Overview
--------

Participants control a "slime" creature trying to score points by getting the ball past their AI opponent. This example showcases both Pyodide and server execution modes with ONNX policy integration.

**What you'll learn:**

- Running human vs AI experiments
- Integrating ONNX models for AI policies
- Complex multi-action controls (combinations like "up+left")
- Custom physics-based rendering
- Using permanent objects for static elements

Features Demonstrated
---------------------

.. list-table::
   :widths: 30 70

   * - **Execution Mode**
     - Pyodide or Server (flexible)
   * - **Players**
     - Human vs AI opponent
   * - **Environment**
     - Custom SlimeVolley environment
   * - **AI Policy**
     - ONNX neural network
   * - **Rendering**
     - Circles, Polygons, Lines with depth ordering
   * - **Input**
     - Arrow keys with diagonal combinations
   * - **Complexity**
     - Intermediate

Prerequisites
-------------

1. Clone the MUG repository and install with server dependencies:

   .. code-block:: bash

       git clone https://github.com/chasemcd/interactive-gym.git
       cd interactive-gym
       pip install -e .[server]

2. Install the Slime Volleyball environment:

   .. code-block:: bash

       pip install git+https://github.com/chasemcd/slimevolleygym.git

Running the Example
-------------------

From the repository root, run as a module:

**Pyodide Mode (Recommended)**

Run the game entirely in the browser:

.. code-block:: bash

    python -m mug.examples.slime_volleyball.human_ai_pyodide

**Server Mode**

Run with server-side environment execution:

.. code-block:: bash

    python -m mug.examples.slime_volleyball.human_ai_server

Both modes:

1. **Open browser** to http://localhost:5702
2. **Play the game**:

   - Use arrow keys to move and jump
   - Press combinations for diagonal movement (e.g., up+right)
   - Score points by landing the ball on opponent's side
   - Play 5 episodes

File Structure
--------------

.. code-block:: text

    slime_volleyball/
    ├── human_ai_pyodide.py          # Pyodide experiment (recommended)
    ├── human_ai_server.py           # Server-side experiment
    ├── slimevb_env.py               # Environment with custom rendering
    ├── slime_volleyball_utils.py    # Rendering helper functions
    └── policies/
        └── model.onnx               # Trained AI policy

Code Walkthrough
----------------

Pyodide Experiment File
^^^^^^^^^^^^^^^^^^^^^^^

**human_ai_pyodide.py** configures the browser-based version.

**1. Policy Mapping**

Define human and AI players:

.. code-block:: python

    from mug.configurations import configuration_constants

    POLICY_MAPPING = {
        "agent_right": configuration_constants.PolicyTypes.Human,
        "agent_left": "static/assets/slime_volleyball/models/model.onnx",
    }

The human controls ``agent_right`` (blue slime on the right), while an ONNX model controls ``agent_left`` (red slime on the left).

**2. Multi-Action Controls**

Slime Volleyball supports diagonal movement:

.. code-block:: python

    NOOP = 0
    LEFT = 1
    UPLEFT = 2
    UP = 3
    UPRIGHT = 4
    RIGHT = 5

    ACTION_MAPPING = {
        "ArrowLeft": LEFT,
        ("ArrowLeft", "ArrowUp"): UPLEFT,
        "ArrowUp": UP,
        ("ArrowRight", "ArrowUp"): UPRIGHT,
        "ArrowRight": RIGHT,
    }

Tuple keys ``("ArrowLeft", "ArrowUp")`` represent simultaneous key presses.

**3. Game Scene Configuration**

.. code-block:: python

    from mug.scenes import gym_scene

    slime_scene = (
        gym_scene.GymScene()
        .scene(scene_id="slime_gym_scene", experiment_config={})
        .policies(policy_mapping=POLICY_MAPPING, frame_skip=1)
        .rendering(
            fps=30,
            game_width=600,
            game_height=250,
        )
        .gameplay(
            default_action=NOOP,
            action_mapping=ACTION_MAPPING,
            num_episodes=5,
            max_steps=3000,
            input_mode=configuration_constants.InputModes.PressedKeys,
        )
        .content(
            scene_header="Slime Volleyball",
            scene_body="<center><p>Press start to continue.</p></center>",
            in_game_scene_body="""
                <center>
                <p>Use the arrow keys to control the slime on the right!</p>
                </center>
            """,
        )
        .runtime(
            run_through_pyodide=True,
            environment_initialization_code_filepath=(
                "mug/examples/slime_volleyball/slimevb_env.py"
            ),
            packages_to_install=[
                "slimevb==0.0.2",
                "opencv-python",
            ],
        )
    )

Key points:

- **frame_skip=1**: Every frame is sent to the browser (no frame skipping)
- **Pyodide packages**: Installs ``slimevb`` environment in the browser
- **Long episodes**: 3000 max steps allows full volleyball rallies

Environment Implementation
^^^^^^^^^^^^^^^^^^^^^^^^^^

**slimevb_env.py** creates custom rendering for the volleyball environment.

**1. Object Context Definitions**

The file defines lightweight versions of object contexts for Pyodide:

.. code-block:: python

    import dataclasses

    @dataclasses.dataclass
    class Circle:
        uuid: str
        color: str
        x: float
        y: float
        radius: int
        alpha: float = 1
        object_type: str = "circle"
        depth: int = -1
        permanent: bool = False

        def as_dict(self):
            return dataclasses.asdict(self)

These are duplicated from MUG's object contexts to run in Pyodide without importing the full library.

**2. Coordinate Conversion**

Slime Volleyball uses its own coordinate system:

.. code-block:: python

    from slime_volleyball.core import constants

    def to_x(x):
        """Convert game x-coordinate to 0-1 rendering coordinate."""
        return x / constants.REF_W + 0.5

    def to_y(y):
        """Convert game y-coordinate to 0-1 rendering coordinate."""
        return 1 - y / constants.REF_W

**3. Rendering Function**

The main rendering logic creates visual objects:

.. code-block:: python

    def slime_volleyball_env_to_rendering(env) -> list:
        render_objects = []

        # Static objects only on first frame
        if env.t == 0:
            fence = Line(
                uuid="fence",
                color="#000000",
                points=[
                    (to_x(env.game.fence.x), to_y(env.game.fence.y + env.game.fence.h / 2)),
                    (to_x(env.game.fence.x), to_y(env.game.fence.y - env.game.fence.h / 2)),
                ],
                width=env.game.fence.w * 600 / constants.REF_W,
                permanent=True,
            )
            render_objects.append(fence)

            # ... more static objects (fence_stub, ground)

        # Dynamic slime objects
        render_objects += generate_slime_agent_objects(
            "agent_left",
            x=env.game.agent_left.x,
            y=env.game.agent_left.y,
            dir=env.game.agent_left.dir,
            radius=env.game.agent_left.r,
            color="#FF0000",
            env=env,
        )

        # Ball object
        ball = Circle(
            uuid="ball",
            color="#000000",
            x=env.game.ball.x / constants.REF_W + 0.5,
            y=1 - env.game.ball.y / constants.REF_W,
            radius=env.game.ball.r * 600 / constants.REF_W,
        )
        render_objects.append(ball)

        return [obj.as_dict() for obj in render_objects]

**4. Permanent Objects**

Static elements use ``permanent=True`` to avoid re-rendering:

.. code-block:: python

    ground = Line(
        uuid="ground",
        color="#747275",
        points=[(0, ground_y), (1, ground_y)],
        fill_below=True,
        width=ground_width,
        depth=-1,
        permanent=True,  # Rendered once, persists across frames
    )

This optimization prevents re-creating the fence, ground, and net every frame.

**5. Complex Slime Rendering**

Slimes are rendered as semi-circles with animated eyes:

.. code-block:: python

    def generate_slime_agent_objects(
        identifier: str,
        x: int,
        y: int,
        dir: int,
        radius: int,
        color: str,
        env,
        resolution: int = 30,
    ):
        objects = []

        # Create semi-circle body
        points = []
        for i in range(resolution + 1):
            ang = math.pi - math.pi * i / resolution
            points.append(
                (to_x(math.cos(ang) * radius + x),
                 to_y(math.sin(ang) * radius + y))
            )

        objects.append(
            Polygon(
                uuid=f"{identifier}_body",
                color=color,
                points=points,
                depth=-1
            )
        )

        # Eyes that track the ball
        angle = math.pi * 60 / 180 if dir == -1 else math.pi * 120 / 180
        c = math.cos(angle)
        s = math.sin(angle)

        # Calculate direction to ball
        ballX = env.game.ball.x - (x + 0.6 * radius * c)
        ballY = env.game.ball.y - (y + 0.6 * radius * s)
        dist = math.sqrt(ballX * ballX + ballY * ballY)
        eyeX = ballX / dist
        eyeY = ballY / dist

        # Eye white
        eye_white = Circle(
            uuid=f"{identifier}_eye_white",
            x=to_x(x + 0.6 * radius * c),
            y=to_y(y + 0.6 * radius * s),
            color="#FFFFFF",
            radius=radius * 4,
            depth=1,
        )

        # Pupil that follows ball
        pupil = Circle(
            uuid=f"{identifier}_eye_pupil",
            x=to_x(x + 0.6 * radius * c + eyeX * 0.15 * radius),
            y=to_y(y + 0.6 * radius * s + eyeY * 0.15 * radius),
            color="#000000",
            radius=radius * 2,
            depth=2,
        )

        objects.extend([eye_white, pupil])
        return objects

The eyes dynamically track the ball's position, creating engaging animation.

**6. Environment Class**

Wrap the SlimeVolley environment with custom rendering:

.. code-block:: python

    from slime_volleyball import slimevolley_env

    class SlimeVBEnvIG(slimevolley_env.SlimeVolleyEnv):
        def render(self):
            assert self.render_mode == "mug"
            return slime_volleyball_env_to_rendering(self)

    # Create instance for Pyodide
    env = SlimeVBEnvIG(
        config={"human_inputs": True},
        render_mode="mug"
    )

Server Mode Differences
^^^^^^^^^^^^^^^^^^^^^^^

**human_ai_server.py** runs the environment on the server instead of the browser.

Key differences:

.. code-block:: python

    # No .runtime() configuration
    # Environment runs server-side

    from mug.utils import onnx_inference_utils

    config = (
        remote_config.RemoteConfig()
        .policies(
            policy_mapping=POLICY_MAPPING,
            policy_inference_fn=onnx_inference_utils.onnx_model_inference_fn,
            load_policy_fn=onnx_inference_utils.load_onnx_policy_fn,
        )
        .environment(
            env_creator=env_creator,
            env_name="slime_volleyball"
        )
        .rendering(
            fps=35,
            env_to_state_fn=slime_volleyball_utils.slime_volleyball_env_to_rendering,
        )
        # ... rest of configuration
    )

Server mode requires:

- ``env_creator`` function to instantiate environment
- ``env_to_state_fn`` for converting environment state to rendering objects
- Policy loading and inference functions for ONNX

How It Works
------------

Pyodide Mode Flow
^^^^^^^^^^^^^^^^^

.. code-block:: text

    Browser (Pyodide)                Server
    ─────────────────                ──────

    1. Load Pyodide + slimevb package (~30-60s)
    2. Create environment
    3. Load ONNX AI policy
    4. Game loop:
       a. Capture human input
       b. Run AI policy inference
       c. env.step({"agent_right": human_action, "agent_left": ai_action})
       d. env.render()
       e. Display objects
       f. Send data batch        →   Save to CSV
    (Repeat 4)

All gameplay runs in the browser with zero network latency.

Server Mode Flow
^^^^^^^^^^^^^^^^

.. code-block:: text

    Browser                          Server
    ───────                         ──────

    1. Connect to server
    2. Game loop:
       a. Display current state  ←  Send rendering objects
       b. Capture human input    →  Receive action
                                    c. Run AI policy
                                    d. env.step(actions)
                                    e. env.render()
                                    f. Save data
    (Repeat 2)

Server handles environment and AI, browser handles display and input.

ONNX Policy Integration
------------------------

The AI opponent is a neural network exported to ONNX format.

**In Pyodide Mode:**

The ONNX model is loaded in the browser:

.. code-block:: python

    POLICY_MAPPING = {
        "agent_left": "static/assets/slime_volleyball/models/model.onnx",
    }

MUG automatically:

1. Downloads the ONNX file to the browser
2. Loads it with ONNX Runtime Web
3. Runs inference each step
4. Passes output as ``agent_left`` action

**In Server Mode:**

ONNX models run server-side:

.. code-block:: python

    from mug.utils import onnx_inference_utils

    config.policies(
        policy_mapping=POLICY_MAPPING,
        policy_inference_fn=onnx_inference_utils.onnx_model_inference_fn,
        load_policy_fn=onnx_inference_utils.load_onnx_policy_fn,
    )

MUG loads the model on the server and runs inference using ``onnxruntime``.
