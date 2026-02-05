# Feature Landscape: Pyodide Web Worker Message Protocol

**Domain:** Web Worker message protocol for Pyodide game execution
**Researched:** 2026-02-04
**Confidence:** HIGH (based on MDN documentation and existing codebase patterns)

## Executive Summary

This document defines a message protocol for moving Pyodide game execution from the main thread to a dedicated Web Worker. The protocol must handle:
- Initialization (loading Pyodide, installing packages, running setup code)
- Game operations (step, reset)
- Render state proxy (passing game state back to main thread for Phaser rendering)
- Error handling and lifecycle management

The design leverages existing patterns from `pyodide_multiplayer_game.js` (binary protocol, typed messages) and MDN Web Worker best practices (transferable objects, structured cloning).

---

## Message Type Definitions

### Type Constants

```typescript
// Worker Message Types (Main Thread -> Worker)
const WORKER_MSG = {
  // Lifecycle
  INIT: 0x01,              // Initialize Pyodide runtime
  DESTROY: 0x02,           // Terminate worker cleanly

  // Environment Setup
  INSTALL_PACKAGES: 0x10,  // Install micropip packages
  SET_GLOBALS: 0x11,       // Set interactive_gym_globals
  RUN_INIT_CODE: 0x12,     // Run environment_initialization_code
  REINITIALIZE: 0x13,      // Reinitialize environment (new scene)

  // Game Operations
  RESET: 0x20,             // Reset environment
  STEP: 0x21,              // Execute env.step(actions)

  // Utility
  PING: 0xF0,              // Latency measurement
} as const;

// Main Thread Message Types (Worker -> Main Thread)
const MAIN_MSG = {
  // Status
  READY: 0x01,             // Worker initialized, ready for commands
  ERROR: 0x02,             // Error occurred

  // Lifecycle Responses
  INIT_COMPLETE: 0x10,     // Pyodide loaded successfully
  PACKAGES_INSTALLED: 0x11,// Packages installed
  GLOBALS_SET: 0x12,       // Globals configured
  ENV_READY: 0x13,         // Environment initialized
  REINIT_COMPLETE: 0x14,   // Reinitialization complete

  // Game Operation Responses
  RESET_RESULT: 0x20,      // Reset completed
  STEP_RESULT: 0x21,       // Step completed

  // Utility
  PONG: 0xF0,              // Latency response
  LOG: 0xF1,               // Console log relay
  PROGRESS: 0xF2,          // Progress update (for loading)
} as const;
```

### TypeScript Message Interfaces

```typescript
// ========== Base Message Structure ==========

interface BaseMessage {
  type: number;        // Message type constant
  id: number;          // Unique request ID for response correlation
  timestamp: number;   // performance.now() for latency tracking
}

// ========== Main Thread -> Worker Messages ==========

interface InitMessage extends BaseMessage {
  type: typeof WORKER_MSG.INIT;
  pyodideUrl?: string;  // Optional CDN URL override
}

interface InstallPackagesMessage extends BaseMessage {
  type: typeof WORKER_MSG.INSTALL_PACKAGES;
  packages: string[];   // Package names for micropip
}

interface SetGlobalsMessage extends BaseMessage {
  type: typeof WORKER_MSG.SET_GLOBALS;
  globals: Record<string, unknown>;  // interactive_gym_globals
}

interface RunInitCodeMessage extends BaseMessage {
  type: typeof WORKER_MSG.RUN_INIT_CODE;
  code: string;         // environment_initialization_code
}

interface ReinitializeMessage extends BaseMessage {
  type: typeof WORKER_MSG.REINITIALIZE;
  config: {
    packages_to_install?: string[];
    environment_initialization_code: string;
    interactive_gym_globals: Record<string, unknown>;
  };
}

interface ResetMessage extends BaseMessage {
  type: typeof WORKER_MSG.RESET;
}

interface StepMessage extends BaseMessage {
  type: typeof WORKER_MSG.STEP;
  actions: Record<string | number, number>;  // {playerId: action}
}

interface PingMessage extends BaseMessage {
  type: typeof WORKER_MSG.PING;
}

interface DestroyMessage extends BaseMessage {
  type: typeof WORKER_MSG.DESTROY;
}

// ========== Worker -> Main Thread Messages ==========

interface ReadyMessage extends BaseMessage {
  type: typeof MAIN_MSG.READY;
}

interface ErrorMessage extends BaseMessage {
  type: typeof MAIN_MSG.ERROR;
  requestId: number;    // ID of failed request
  error: string;        // Error message
  stack?: string;       // Stack trace if available
}

interface InitCompleteMessage extends BaseMessage {
  type: typeof MAIN_MSG.INIT_COMPLETE;
  pyodideVersion: string;
}

interface PackagesInstalledMessage extends BaseMessage {
  type: typeof MAIN_MSG.PACKAGES_INSTALLED;
  installed: string[];  // Successfully installed packages
}

interface EnvReadyMessage extends BaseMessage {
  type: typeof MAIN_MSG.ENV_READY;
}

interface ReinitCompleteMessage extends BaseMessage {
  type: typeof MAIN_MSG.REINIT_COMPLETE;
}

interface ResetResultMessage extends BaseMessage {
  type: typeof MAIN_MSG.RESET_RESULT;
  observation: ObservationType;
  infos: Record<string, unknown>;
  renderState: RenderState;
}

interface StepResultMessage extends BaseMessage {
  type: typeof MAIN_MSG.STEP_RESULT;
  observation: ObservationType;
  rewards: Record<string | number, number>;
  terminateds: Record<string | number, boolean>;
  truncateds: Record<string | number, boolean>;
  infos: Record<string, unknown>;
  renderState: RenderState;
}

interface PongMessage extends BaseMessage {
  type: typeof MAIN_MSG.PONG;
  originalTimestamp: number;  // Echo back for RTT calculation
}

interface ProgressMessage extends BaseMessage {
  type: typeof MAIN_MSG.PROGRESS;
  stage: 'pyodide' | 'micropip' | 'packages' | 'globals' | 'env';
  progress: number;     // 0-100
  detail?: string;      // Human-readable status
}

interface LogMessage extends BaseMessage {
  type: typeof MAIN_MSG.LOG;
  level: 'debug' | 'info' | 'warn' | 'error';
  args: unknown[];
}

// ========== Data Types ==========

type ObservationType =
  | Float32Array                                    // Single observation
  | Record<string, Float32Array>                   // Dict observations
  | Record<string, Record<string, Float32Array>>; // Nested dict observations

interface RenderState {
  game_state_objects: RenderObject[] | null;  // For Phaser rendering
  game_image_base64: string | null;           // For RGB array rendering
  step: number;
}

interface RenderObject {
  type: string;
  x: number;
  y: number;
  [key: string]: unknown;  // Additional properties
}
```

---

## Sequence Diagrams

### Initialization Sequence

```
Main Thread                           Pyodide Worker
    |                                      |
    |-- new Worker('pyodide_worker.js') -->|
    |                                      |
    |<-------- READY (worker loaded) ------|
    |                                      |
    |-- INIT {pyodideUrl?} --------------->|
    |                                      | loadPyodide()
    |<------ PROGRESS {stage: pyodide} ----|
    |                                      |
    |<-------- INIT_COMPLETE --------------|
    |                                      |
    |-- INSTALL_PACKAGES {packages} ------>|
    |                                      | micropip.install()
    |<------ PROGRESS {stage: packages} ---|
    |                                      |
    |<------- PACKAGES_INSTALLED ----------|
    |                                      |
    |-- SET_GLOBALS {globals} ------------>|
    |                                      |
    |<---------- GLOBALS_SET --------------|
    |                                      |
    |-- RUN_INIT_CODE {code} ------------->|
    |                                      | runPythonAsync(code)
    |                                      |
    |<----------- ENV_READY ---------------|
    |                                      |
```

### Game Loop Sequence (Step)

```
Main Thread                           Pyodide Worker
    |                                      |
    |-- STEP {id: 42, actions} ----------->|
    |                                      | env.step(actions)
    |                                      | env.render()
    |                                      |
    |<-- STEP_RESULT {id: 42, obs, ...} ---|
    |                                      |
    | [Phaser renders renderState]         |
    |                                      |
```

### Reset Sequence

```
Main Thread                           Pyodide Worker
    |                                      |
    |-- RESET {id: 43} ------------------->|
    |                                      | env.reset()
    |                                      | env.render()
    |                                      |
    |<-- RESET_RESULT {id: 43, obs, ...} --|
    |                                      |
```

### Error Handling Sequence

```
Main Thread                           Pyodide Worker
    |                                      |
    |-- STEP {id: 44, actions} ----------->|
    |                                      | env.step() throws
    |                                      |
    |<-- ERROR {requestId: 44, error} -----|
    |                                      |
    | [Handle error, possibly reinit]      |
    |                                      |
```

### Reinitialization Sequence (Scene Transition)

```
Main Thread                           Pyodide Worker
    |                                      |
    |-- REINITIALIZE {config} ------------>|
    |                                      | install new packages
    |                                      | set globals
    |                                      | run init code
    |                                      |
    |<-------- REINIT_COMPLETE ------------|
    |                                      |
```

---

## Request/Response Correlation

### ID-Based Correlation Pattern

Every request includes a unique `id` field. Responses include the same `id` for correlation. This enables:

1. **Promise resolution:** Main thread stores pending promises by ID
2. **Out-of-order handling:** Responses can arrive in any order
3. **Timeout detection:** Requests without responses after timeout can be rejected

```typescript
// Main thread request manager
class WorkerRequestManager {
  private nextId = 1;
  private pending = new Map<number, {
    resolve: (result: any) => void;
    reject: (error: Error) => void;
    timeout: NodeJS.Timeout;
  }>();

  async request<T>(worker: Worker, message: Omit<BaseMessage, 'id' | 'timestamp'>): Promise<T> {
    const id = this.nextId++;
    const timestamp = performance.now();

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Request ${id} timed out`));
      }, 30000);  // 30s timeout

      this.pending.set(id, { resolve, reject, timeout });
      worker.postMessage({ ...message, id, timestamp });
    });
  }

  handleResponse(message: BaseMessage & { requestId?: number }) {
    const id = message.id ?? message.requestId;
    const pending = this.pending.get(id);
    if (pending) {
      clearTimeout(pending.timeout);
      this.pending.delete(id);

      if (message.type === MAIN_MSG.ERROR) {
        pending.reject(new Error((message as ErrorMessage).error));
      } else {
        pending.resolve(message);
      }
    }
  }
}
```

---

## Latency Considerations

### Structured Cloning Overhead

All data passed via `postMessage` is cloned using the structured clone algorithm. For game loops at 10-60 FPS:

| Data Type | Typical Size | Clone Time | Recommendation |
|-----------|--------------|------------|----------------|
| Actions (object) | ~100 bytes | <0.1ms | Use as-is |
| Observations (Float32Array) | 1-10KB | 0.1-0.5ms | Transfer if large |
| RenderState (objects) | 5-50KB | 0.5-2ms | Optimize structure |
| RGB Image (base64) | 100KB-1MB | 5-50ms | **Avoid in loop** |

### Transferable Objects

For large typed arrays, use Transferable transfer to avoid copying:

```typescript
// Main thread
const observations = new Float32Array(1024);
worker.postMessage(
  { type: WORKER_MSG.STEP, actions, id, timestamp },
  // Transfer list - these buffers are moved, not copied
  [observations.buffer]
);

// Worker response (transfer back)
const obsBuffer = new Float32Array(result.observation);
self.postMessage(
  { type: MAIN_MSG.STEP_RESULT, observation: obsBuffer, ... },
  [obsBuffer.buffer]
);
```

**Caveat:** After transfer, the original buffer is neutered (length becomes 0). Only use for one-shot data.

### Batching Considerations

For a 10 FPS game loop (100ms per frame):

```
Frame timeline:
|-- Input capture (1ms) --|-- postMessage (0.1ms) --|-- Worker step (50ms) --|-- postMessage (1ms) --|-- Render (20ms) --|

Total: ~72ms, leaving 28ms headroom
```

**DO NOT batch multiple steps.** Each step depends on the previous state. Pipeline optimization should focus on:

1. **Overlapping render with next input:** Start capturing next frame's input while rendering
2. **Minimizing render state size:** Only send what changed
3. **Pre-serializing static data:** Cache serialized render objects

### Latency Tracking

Include timestamps in messages for pipeline monitoring:

```typescript
interface LatencyMetrics {
  requestTimestamp: number;     // When main thread sent request
  workerReceiveTimestamp: number; // When worker received request
  workerSendTimestamp: number;  // When worker sent response
  responseTimestamp: number;    // When main thread received response
}

// Calculated metrics:
// - Request transit: workerReceiveTimestamp - requestTimestamp
// - Worker execution: workerSendTimestamp - workerReceiveTimestamp
// - Response transit: responseTimestamp - workerSendTimestamp
// - Total RTT: responseTimestamp - requestTimestamp
```

---

## Example Message Flows

### Complete Initialization Flow

```typescript
// 1. Create worker
const worker = new Worker('/static/js/pyodide_worker.js');

// 2. Wait for worker ready
await waitForMessage(worker, MAIN_MSG.READY);

// 3. Initialize Pyodide
const initResult = await requestManager.request(worker, {
  type: WORKER_MSG.INIT,
  pyodideUrl: 'https://cdn.jsdelivr.net/pyodide/v0.24.1/full/'
});
console.log(`Pyodide ${initResult.pyodideVersion} loaded`);

// 4. Install packages
if (config.packages_to_install?.length > 0) {
  await requestManager.request(worker, {
    type: WORKER_MSG.INSTALL_PACKAGES,
    packages: config.packages_to_install
  });
}

// 5. Set globals
await requestManager.request(worker, {
  type: WORKER_MSG.SET_GLOBALS,
  globals: config.interactive_gym_globals
});

// 6. Initialize environment
await requestManager.request(worker, {
  type: WORKER_MSG.RUN_INIT_CODE,
  code: config.environment_initialization_code
});

console.log('Environment ready');
```

### Game Loop Flow

```typescript
class PyodideWorkerGame {
  private worker: Worker;
  private requestManager: WorkerRequestManager;

  async step(actions: Record<string, number>): Promise<StepResult> {
    const result = await this.requestManager.request<StepResultMessage>(
      this.worker,
      { type: WORKER_MSG.STEP, actions }
    );

    return {
      observation: result.observation,
      rewards: result.rewards,
      terminateds: result.terminateds,
      truncateds: result.truncateds,
      infos: result.infos,
      renderState: result.renderState
    };
  }

  async reset(): Promise<ResetResult> {
    const result = await this.requestManager.request<ResetResultMessage>(
      this.worker,
      { type: WORKER_MSG.RESET }
    );

    return {
      observation: result.observation,
      infos: result.infos,
      renderState: result.renderState
    };
  }
}
```

### Worker Implementation Skeleton

```javascript
// pyodide_worker.js
let pyodide = null;
let micropip = null;

self.onmessage = async (event) => {
  const msg = event.data;
  const startTime = performance.now();

  try {
    switch (msg.type) {
      case WORKER_MSG.INIT:
        pyodide = await loadPyodide({ indexURL: msg.pyodideUrl });
        await pyodide.loadPackage('micropip');
        micropip = pyodide.pyimport('micropip');

        self.postMessage({
          type: MAIN_MSG.INIT_COMPLETE,
          id: msg.id,
          timestamp: performance.now(),
          pyodideVersion: pyodide.version
        });
        break;

      case WORKER_MSG.STEP:
        const stepResult = await executeStep(msg.actions);

        self.postMessage({
          type: MAIN_MSG.STEP_RESULT,
          id: msg.id,
          timestamp: performance.now(),
          ...stepResult
        });
        break;

      // ... other cases
    }
  } catch (error) {
    self.postMessage({
      type: MAIN_MSG.ERROR,
      id: msg.id,
      requestId: msg.id,
      timestamp: performance.now(),
      error: error.message,
      stack: error.stack
    });
  }
};

// Signal ready
self.postMessage({
  type: MAIN_MSG.READY,
  id: 0,
  timestamp: performance.now()
});
```

---

## Anti-Features (What NOT to Build)

### Synchronous Communication

**DO NOT** use `Atomics.wait()` or `SharedArrayBuffer` for synchronous worker calls:
- Blocks the main thread, defeating the purpose
- Adds complexity without benefit for game loop use case
- Most browsers restrict `SharedArrayBuffer` anyway

### Message Compression

**DO NOT** implement custom compression for messages:
- Adds CPU overhead on both ends
- Modern browsers optimize structured cloning
- Game state is already reasonably sized

### Multi-Step Batching

**DO NOT** batch multiple `step()` calls into one message:
- Each step depends on previous state
- Breaks the Gymnasium API contract
- Impossible to correctly implement

### Shared Pyodide Instance

**DO NOT** try to share Pyodide across multiple workers:
- Pyodide is single-threaded by design
- WASM memory is not shareable
- Each worker needs its own instance

---

## Sources

- MDN Web Workers API: https://developer.mozilla.org/en-US/docs/Web/API/Web_Workers_API/Using_web_workers (HIGH confidence)
- Existing codebase: `pyodide_multiplayer_game.js` binary protocol (HIGH confidence)
- Existing codebase: `GameTimerWorker` pattern for inline workers (HIGH confidence)
- Existing codebase: `RemoteGame` API for step/reset/initialize (HIGH confidence)
