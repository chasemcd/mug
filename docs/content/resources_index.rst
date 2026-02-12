Examples
========

Complete example experiments demonstrating various MUG features. Each example includes full source code, detailed documentation, and instructions for customization.

All examples are located in the `mug/examples/ <https://github.com/chasemcd/interactive-gym/tree/main/mug/examples>`_ directory.

Example Comparison
------------------

.. list-table::
   :header-rows: 1
   :widths: 20 15 15 15 35

   * - Example
     - Players
     - Mode
     - Complexity
     - Key Features
   * - :doc:`examples/mountain_car`
     - Human
     - Client
     - Beginner
     - Client-side execution, custom rendering, RGB array conversion
   * - :doc:`examples/slime_volleyball`
     - Human-Human, Human-AI
     - Server/Client
     - Intermediate
     - Human vs AI, ONNX policy inference, sprite rendering
   * - :doc:`examples/overcooked_human_ai`
     - Human-AI
     - Client
     - Advanced
     - Human-AI coordination, SP and BS policies, randomized layouts
   * - :doc:`examples/overcooked_multiplayer`
     - Human-Human
     - Server
     - Advanced
     - Multi-player coordination, matchmaking, synchronized gameplay
   * - :doc:`examples/footsies`
     - Human-AI
     - Client (WebGL)
     - Advanced
     - Fighting game mechanics, frame-perfect timing, competitive play

Prerequisites
^^^^^^^^^^^^^

**Important**: Examples must be run from a cloned repository, not from a pip installation, because they rely on relative paths for assets (sprites, models, etc.).

1. **Clone the repository**:

   .. code-block:: bash

       git clone https://github.com/chasemcd/interactive-gym.git
       cd interactive-gym

2. **Install MUG with server dependencies**:

   .. code-block:: bash

       pip install -e .[server]

3. **Install example-specific dependencies** (if needed):

   Some examples require additional packages. See individual example documentation for details.

Running Examples
^^^^^^^^^^^^^^^^

Examples must be run as modules from the repository root to ensure correct asset paths:

1. **From the repository root**, run the example as a module:

   .. code-block:: bash

       python -m mug.examples.example_name.experiment_file

   For example:

   .. code-block:: bash

       # Mountain Car
       python -m mug.examples.mountain_car.mountain_car_experiment

       # Slime Volleyball (Human vs AI, Pyodide mode)
       python -m mug.examples.slime_volleyball.human_ai_pyodide

       # Overcooked (Human vs AI, client-side)
       python -m mug.examples.cogrid.overcooked_human_ai_client_side

       # Overcooked (Human vs Human, server-side)
       python -m mug.examples.cogrid.overcooked_human_human_server_side

       # Footsies
       python -m mug.examples.footsies.footsies_experiment

2. **Open browser** to the specified port (usually http://localhost:5702 or http://localhost:5000)

Example Structure
^^^^^^^^^^^^^^^^^

Each example directory typically contains:

.. code-block:: text

    example_name/
    ├── experiment_file.py            # Main experiment file
    ├── environment_file.py           # Environment implementation (if needed)
    ├── README.md                     # Setup instructions
    ├── policies/                     # AI policies (if applicable)
    └── assets/                       # Images, sprites, etc.

.. toctree::
   :maxdepth: 1
   :hidden:

   examples/mountain_car
   examples/slime_volleyball
   examples/overcooked_human_ai
   examples/overcooked_multiplayer
   examples/footsies
