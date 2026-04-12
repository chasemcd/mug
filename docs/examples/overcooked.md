# Overcooked Examples

Overcooked is a cooperative cooking game where two players collaborate to prepare and deliver dishes in various kitchen layouts. MUG includes three Overcooked examples that demonstrate different execution modes and player configurations.

| Example | Mode | Description |
|---------|------|-------------|
| [Overcooked: Human-AI](overcooked-human-ai.md) | Client-side | Human plays with a trained AI partner (ONNX policy). Demonstrates client-side inference, multiple layouts, and between-subjects design. |
| [Overcooked: Client-Side](overcooked-client-side.md) | Client-side (P2P) | Two humans play together with GGPO rollback netcode. Each browser runs its own environment via Pyodide; inputs are exchanged over WebRTC. |
| [Overcooked: Server-Side](overcooked-multiplayer.md) | Server-authoritative | Two humans play together with the environment running on the server. Browsers are thin clients that display state and capture input. |

**Which mode should I use?**

- If your environment is pure Python and can run in Pyodide, use **client-side (P2P)**. It scales better (no server computation), has lower perceived latency (GGPO rollback), and works well for most research experiments.
- If your environment has compiled dependencies (C/C++ extensions), requires GPU inference, or you need a single authoritative source of truth, use **server-authoritative** mode.

See [Server Mode](../core-concepts/server-mode.md) and [Browser-Side Execution](../core-concepts/pyodide-mode.md) for a detailed comparison.
