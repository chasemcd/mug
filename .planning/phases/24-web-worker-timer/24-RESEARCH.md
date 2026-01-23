# Phase 24: Web Worker Timer Infrastructure - Research

**Researched:** 2026-01-22
**Domain:** Web Worker timing, browser throttling, game loop architecture
**Confidence:** HIGH

## Summary

This research investigates how to move game timing logic to a Web Worker to prevent browser throttling when tabs are backgrounded. The core problem is that browsers (Chrome 88+, Firefox, Safari) aggressively throttle `setInterval` and `setTimeout` in background tabs - reducing execution to once per minute after 5 minutes of inactivity.

The standard solution is to run timing-critical code in a **dedicated Web Worker**, which is exempt from main thread throttling. The Worker sends tick messages to the main thread via `postMessage()`, which triggers game state updates. This pattern is well-established for multiplayer games where accurate timing must persist even when players tab away.

**Primary recommendation:** Create a dedicated `GameTimerWorker` that runs `setInterval` at the target frame rate (100ms for 10fps) and posts tick messages to the main thread. The main thread processes game state updates only when ticks arrive. Use inline Worker creation via Blob URL for simpler deployment without separate worker files.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Native Web Worker API | N/A (browser built-in) | Run timer in separate thread | Built-in, no dependencies, full browser support |
| Blob URL Worker | N/A (browser built-in) | Create inline workers without separate files | Simplifies deployment, bundling |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| worker-timers | 8.0.x | Drop-in timer replacement | When you need minimal code changes |
| performance.now() | N/A | High-precision timing | Measure actual elapsed time, compensate for drift |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| worker-timers library | Custom inline Worker | Library adds dependency but is simpler; custom gives full control |
| SharedArrayBuffer | postMessage | SharedArrayBuffer faster but requires COOP/COEP headers, complex setup |
| Transferable objects | JSON postMessage | Transferable is faster for large data but adds complexity |

**Installation:**
```bash
# If using worker-timers library:
npm install worker-timers

# Otherwise, no installation needed for native Web Worker API
```

## Architecture Patterns

### Recommended Project Structure
```
interactive_gym/server/static/js/
├── pyodide_multiplayer_game.js   # Main game, receives ticks from worker
├── game_timer_worker.js          # OR inline via Blob
└── webrtc_manager.js             # Existing WebRTC code (unchanged)
```

### Pattern 1: Inline Worker via Blob URL (Recommended)
**What:** Create the Worker from a string/Blob instead of a separate file
**When to use:** Always, unless you need the worker code in a separate file for debugging
**Example:**
```javascript
// Source: https://gist.github.com/simonghales/3bf189c97f0a0fea2f028566c45ce414
// Create inline worker from code string
const workerCode = `
  let intervalId = null;
  const targetInterval = 100; // 100ms for 10fps

  self.onmessage = function(e) {
    if (e.data.command === 'start') {
      if (intervalId) clearInterval(intervalId);
      intervalId = setInterval(() => {
        self.postMessage({ type: 'tick', timestamp: performance.now() });
      }, e.data.interval || targetInterval);
    } else if (e.data.command === 'stop') {
      if (intervalId) {
        clearInterval(intervalId);
        intervalId = null;
      }
    }
  };
`;

const blob = new Blob([workerCode], { type: 'application/javascript' });
const workerUrl = URL.createObjectURL(blob);
const timerWorker = new Worker(workerUrl);

// Listen for ticks
timerWorker.onmessage = (e) => {
  if (e.data.type === 'tick') {
    this._processGameTick(e.data.timestamp);
  }
};

// Start the timer
timerWorker.postMessage({ command: 'start', interval: 100 });
```

### Pattern 2: Dual-Loop Architecture (Update Worker + RAF Render)
**What:** Worker handles game logic updates, main thread handles rendering
**When to use:** When you want rendering to pause in background but logic to continue
**Example:**
```javascript
// Source: https://stephendoddtech.com/blog/game-design/javascript-web-worker-set-interval-game-loop
// Worker sends tick messages
// Main thread:
timerWorker.onmessage = (e) => {
  if (e.data.type === 'tick') {
    this._updateGameState();  // Always runs (even backgrounded)
  }
};

// Separate render loop with requestAnimationFrame (pauses when backgrounded)
function renderLoop() {
  this._renderCurrentState();
  requestAnimationFrame(renderLoop);
}
```

### Pattern 3: Time-Compensated Ticks
**What:** Use actual elapsed time to handle drift and inconsistent tick timing
**When to use:** Always, for frame-rate independence
**Example:**
```javascript
// Worker tracks last tick time
let lastTickTime = performance.now();

setInterval(() => {
  const now = performance.now();
  const elapsed = now - lastTickTime;
  lastTickTime = now;

  self.postMessage({
    type: 'tick',
    timestamp: now,
    elapsed: elapsed  // Actual ms since last tick
  });
}, targetInterval);
```

### Anti-Patterns to Avoid
- **Running game logic IN the Worker:** Workers cannot access DOM, Pyodide, or the game state directly. Only run the timer in the Worker; keep all game logic on the main thread.
- **Using SharedArrayBuffer without COOP/COEP:** SharedArrayBuffer requires special HTTP headers and cross-origin isolation. Unless already configured, avoid it.
- **Assuming Worker timers are perfectly accurate:** Workers still have some variance. Always use `performance.now()` to measure actual elapsed time.
- **Creating a new Worker per game:** Reuse the Worker instance. Worker creation has overhead.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Timer drift compensation | Custom drift algorithm | `performance.now()` delta measurement | Browser APIs handle high-precision timing |
| Worker lifecycle management | Custom worker pool | Single long-lived worker | Game only needs one timer; pools add complexity |
| Cross-thread data transfer | Custom serialization | Structured clone (default) or JSON | postMessage handles serialization automatically |

**Key insight:** The Worker's job is ONLY to send tick messages. All actual game logic stays on the main thread where it can access Pyodide, DOM, and game state.

## Common Pitfalls

### Pitfall 1: Worker Cannot Access Game State
**What goes wrong:** Attempting to run game logic in the Worker fails because Workers have no access to DOM, window, Pyodide, or main thread state.
**Why it happens:** Workers run in isolated contexts by design.
**How to avoid:** Worker ONLY runs the timer and posts tick messages. Main thread receives ticks and runs all game logic.
**Warning signs:** ReferenceError for `window`, `document`, `pyodide`, or game objects in Worker code.

### Pitfall 2: Timer Still Throttled Despite Worker
**What goes wrong:** Timer appears throttled even with Worker implementation.
**Why it happens:** Timer was created on the main thread and only messages go through the Worker, or Worker wasn't properly started.
**How to avoid:** Ensure `setInterval` is called INSIDE the Worker code, not in main thread code passed to Worker.
**Warning signs:** Tick frequency drops to 1/second or 1/minute when tab backgrounded.

### Pitfall 3: Memory Leak from Worker URL
**What goes wrong:** Blob URLs accumulate, consuming memory.
**Why it happens:** `URL.createObjectURL()` creates a reference that must be explicitly released.
**How to avoid:** Call `URL.revokeObjectURL(workerUrl)` after Worker is no longer needed.
**Warning signs:** Memory usage grows over time; Worker reinstantiation without cleanup.

### Pitfall 4: postMessage Overhead for Large Payloads
**What goes wrong:** Frame rate drops or stutters when sending large data through postMessage.
**Why it happens:** postMessage uses structured cloning which copies data.
**How to avoid:** Send only minimal data (tick type, timestamp). Game state stays on main thread.
**Warning signs:** Lag when postMessage payload exceeds ~50KB.

### Pitfall 5: Ignoring iOS Compatibility Issues
**What goes wrong:** Timers fire erratically on iOS 15 and below.
**Why it happens:** Known bug in worker-timers library on older iOS versions.
**How to avoid:** Test on iOS devices; consider fallback to main-thread timers on older iOS if needed.
**Warning signs:** Excessive callback firing on iOS Safari.

## Code Examples

Verified patterns from official sources:

### Complete GameTimerWorker Implementation
```javascript
// Source: Synthesized from multiple patterns
// https://hackwild.com/article/web-worker-timers/
// https://gist.github.com/simonghales/3bf189c97f0a0fea2f028566c45ce414

class GameTimerWorker {
  constructor(targetFps = 10) {
    this.worker = null;
    this.workerUrl = null;
    this.targetInterval = 1000 / targetFps;  // 100ms for 10fps
    this.onTick = null;
    this._createWorker();
  }

  _createWorker() {
    const workerCode = `
      let intervalId = null;

      self.onmessage = function(e) {
        const { command, interval } = e.data;

        if (command === 'start') {
          if (intervalId) clearInterval(intervalId);
          intervalId = setInterval(() => {
            self.postMessage({ type: 'tick', timestamp: performance.now() });
          }, interval);
        } else if (command === 'stop') {
          if (intervalId) {
            clearInterval(intervalId);
            intervalId = null;
          }
        } else if (command === 'setInterval') {
          if (intervalId) {
            clearInterval(intervalId);
            intervalId = setInterval(() => {
              self.postMessage({ type: 'tick', timestamp: performance.now() });
            }, interval);
          }
        }
      };
    `;

    const blob = new Blob([workerCode], { type: 'application/javascript' });
    this.workerUrl = URL.createObjectURL(blob);
    this.worker = new Worker(this.workerUrl);

    this.worker.onmessage = (e) => {
      if (e.data.type === 'tick' && this.onTick) {
        this.onTick(e.data.timestamp);
      }
    };

    this.worker.onerror = (err) => {
      console.error('[GameTimerWorker] Error:', err.message);
    };
  }

  start() {
    this.worker.postMessage({ command: 'start', interval: this.targetInterval });
  }

  stop() {
    this.worker.postMessage({ command: 'stop' });
  }

  setFps(fps) {
    this.targetInterval = 1000 / fps;
    this.worker.postMessage({ command: 'setInterval', interval: this.targetInterval });
  }

  destroy() {
    this.stop();
    this.worker.terminate();
    URL.revokeObjectURL(this.workerUrl);
    this.worker = null;
    this.workerUrl = null;
  }
}
```

### Integration with Existing Game Loop
```javascript
// In MultiplayerPyodideGame constructor or initialization:
this.timerWorker = new GameTimerWorker(this.config.fps || 10);
this.timerWorker.onTick = (timestamp) => this._handleWorkerTick(timestamp);

// Replace existing Phaser update-driven loop
_handleWorkerTick(timestamp) {
  // Skip if game is paused or done
  if (this.state === 'done' || this.reconnectionState.isPaused) return;

  // Process the frame - this is what was previously driven by Phaser update()
  // Note: Rendering still happens via Phaser's requestAnimationFrame
  this._processGameFrame();
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Main thread setInterval | Web Worker setInterval | Chrome 88 (Jan 2021) introduced intensive throttling | Workers exempt from throttling; required for background execution |
| Separate .js Worker files | Inline Blob URL Workers | ~2015, now standard | Simpler bundling, no extra files to serve |
| requestAnimationFrame for game loop | RAF for render only, Worker for updates | Multiplayer game best practice | Game logic continues in background |

**Deprecated/outdated:**
- **requestAnimationFrame for game logic:** Does not run when tab is backgrounded; only use for rendering
- **Single-threaded game loops:** Cannot maintain timing accuracy in background tabs
- **Polling-based timers on main thread:** Throttled to 1/minute after 5 minutes in background (Chrome 88+)

## Browser Throttling Rules (Chrome 88+)

Understanding when throttling applies helps validate the Worker solution:

| Throttling Level | When Applied | Timer Frequency |
|------------------|--------------|-----------------|
| Minimal | Tab visible OR audio playing | Normal (4ms min for chains) |
| Moderate | Tab hidden < 5 minutes | Once per second |
| Intensive | Tab hidden > 5 minutes, silent, no WebRTC | Once per minute |

**Exceptions that prevent intensive throttling:**
- Active WebRTC with open data channels or live media streams
- Audio playback within last 30 seconds
- Timer chain count < 5

Note: This game already uses WebRTC, which may provide some protection. However, there can be gaps in WebRTC activity, and the Worker solution provides reliable protection regardless.

## Open Questions

Things that couldn't be fully resolved:

1. **iOS Safari Compatibility**
   - What we know: worker-timers library has known issues on iOS 15 and below
   - What's unclear: Whether native Worker timers have the same issue
   - Recommendation: Test on iOS Safari; consider feature detection and fallback

2. **Interaction with Pyodide async operations**
   - What we know: Pyodide runs async Python which yields to the event loop
   - What's unclear: Whether Worker ticks during Pyodide execution could cause issues
   - Recommendation: Add guard to skip tick processing if previous tick still processing (isProcessingTick flag)

3. **Optimal tick rate vs game FPS**
   - What we know: Worker ticks can be independent of render FPS
   - What's unclear: Whether tick rate should match game FPS or be higher
   - Recommendation: Start with matching game FPS (10fps = 100ms ticks), adjust if needed

## Sources

### Primary (HIGH confidence)
- [MDN Web Workers API](https://developer.mozilla.org/en-US/docs/Web/API/Worker) - Official documentation
- [Chrome Timer Throttling Blog](https://developer.chrome.com/blog/timer-throttling-in-chrome-88) - Official Chrome throttling rules
- [MDN postMessage API](https://developer.mozilla.org/en-US/docs/Web/API/Worker/postMessage) - Official postMessage documentation

### Secondary (MEDIUM confidence)
- [HackWild Web Worker Timers](https://hackwild.com/article/web-worker-timers/) - Verified implementation patterns
- [Stephen Dodd Tech Game Loop](https://stephendoddtech.com/blog/game-design/javascript-web-worker-set-interval-game-loop) - Game loop architecture
- [GitHub simonghales gist](https://gist.github.com/simonghales/3bf189c97f0a0fea2f028566c45ce414) - Running game loop on web worker
- [worker-timers npm](https://www.npmjs.com/package/worker-timers) - Popular library implementation

### Tertiary (LOW confidence)
- [worker-timers GitHub Issues](https://github.com/chrisguttandin/worker-timers/issues) - Known issues, especially iOS (#442)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Web Worker API is well-documented and browser support is universal
- Architecture: HIGH - Dual-loop pattern (Worker timer + RAF render) is established best practice
- Pitfalls: MEDIUM - Most from community experience rather than official docs

**Research date:** 2026-01-22
**Valid until:** 2026-07-22 (6 months - Web Worker API is stable)
