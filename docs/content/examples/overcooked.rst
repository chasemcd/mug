Overcooked Examples
===================

Overcooked is a cooperative cooking game where two players collaborate to prepare and deliver dishes in various kitchen layouts. MUG includes three Overcooked examples that demonstrate different execution modes and player configurations.

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - Example
     - Mode
     - Description
   * - :doc:`overcooked_human_ai`
     - Client-side
     - Human plays with a trained AI partner (ONNX policy). Demonstrates client-side inference, multiple layouts, and between-subjects design.
   * - :doc:`overcooked_client_side`
     - Client-side (P2P)
     - Two humans play together with GGPO rollback netcode. Each browser runs its own environment via Pyodide; inputs are exchanged over WebRTC.
   * - :doc:`overcooked_multiplayer`
     - Server-authoritative
     - Two humans play together with the environment running on the server. Browsers are thin clients that display state and capture input.

**Which mode should I use?**

- If your environment is pure Python and can run in Pyodide, use **client-side (P2P)**. It scales better (no server computation), has lower perceived latency (GGPO rollback), and works well for most research experiments.
- If your environment has compiled dependencies (C/C++ extensions), requires GPU inference, or you need a single authoritative source of truth, use **server-authoritative** mode.

See :doc:`../core_concepts/server_mode` and :doc:`../core_concepts/pyodide_mode` for a detailed comparison.

.. toctree::
   :maxdepth: 1
   :hidden:

   overcooked_human_ai
   overcooked_client_side
   overcooked_multiplayer
