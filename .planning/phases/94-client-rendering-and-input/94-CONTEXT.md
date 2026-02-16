# Phase 94: Client Rendering and Input - Context

**Gathered:** 2026-02-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Client receives server-broadcast render states, buffers them, renders at controlled FPS with configurable input delay, and sends actions back. Server pipeline (Phase 93) is complete — this phase builds the client-side consumer. Creating the example/verification is Phase 95.

</domain>

<decisions>
## Implementation Decisions

### Architecture constraint
- All client functionality must derive from `MultiplayerPyodideGame` (the existing P2P client JS)
- Factor out shared logic so both P2P and server-auth execute the same code paths
- Do not build a separate client — extend/refactor the existing one

### Rendering cadence
- Target FPS is scene-configured: each `GymScene` specifies its target client FPS via the existing config
- Play through buffer: queue all incoming states and render them in order at client FPS (do not skip to latest)
- No buffer cap: play every frame, no dropping. If client falls behind, it falls behind — every state matters for experiments
- On network jitter (no new state ready at render time): freeze on last rendered frame, no indicator

### Input behavior
- Send actions immediately on keypress — no batching or sampling at render tick intervals
- Input mode (key repeat vs single keypress) uses existing `GymScene.gameplay(input_mode=PressedKeys/SingleKeypress)` infrastructure — behavior identical to P2P mode
- Configurable N-frame input delay to absorb RTT variance, default is 0 frames (no artificial delay)

### Episode transitions
- Episode reset behavior matches P2P mode exactly — use the same transition flow
- Game complete behavior matches P2P mode exactly — same post-game scene, redirect, etc.
- On episode reset: flush the state buffer immediately, start fresh with new episode states
- Episode counter / round indicator: match whatever P2P mode shows

### Connection resilience
- Disconnect handling matches P2P mode's existing disconnect UX
- Reconnection: participant can rejoin a running game (server-auth advantage over P2P)
- On rejoin: client receives just the current state and starts rendering from there (no burst of history)
- Configurable disconnect timeout: researcher sets max disconnect duration; after expiry, participant is dropped permanently (slot stays on default actions)

### Claude's Discretion
- Buffer data structure implementation
- Socket event naming for client-specific events
- How to structure the P2P/server-auth code sharing (inheritance, composition, flags)
- Reconnection handshake protocol details

</decisions>

<specifics>
## Specific Ideas

- "All functionality should be derived from MultiplayerPyodideGame — if necessary, isolate the necessary logic from that .js and execute the same code for both P2P and server"
- Input infrastructure is already built (PressedKeys/SingleKeypress modes) — reuse it, don't rebuild
- The "play through buffer, no cap" decision prioritizes experiment fidelity over real-time feel — every state the env produces should be seen by participants

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 94-client-rendering-and-input*
*Context gathered: 2026-02-15*
