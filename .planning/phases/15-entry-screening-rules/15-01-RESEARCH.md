# Phase 15: Entry Screening Rules - Research

**Researched:** 2026-01-21
**Domain:** Pre-game screening with device, browser, and ping checks
**Confidence:** HIGH

## Summary

Phase 15 implements pre-game entry screening that blocks participants based on device type, browser type, and ping threshold before they can join a game. The codebase already has significant infrastructure in place:

1. **Ping measurement exists** - `index.js` lines 45-78 already measure Socket.IO latency via ping/pong events with median calculation
2. **Max ping config exists** - `remote_config.py` has `max_ping` and `min_ping_measurements` config options
3. **Ping blocking partially exists** - `index.js` lines 849-856 already disable the start button if latency exceeds `maxLatency`
4. **GymScene has ping config** - `gym_scene.py` has `max_ping` and `min_ping_measurements` attributes

What's missing: device/browser detection, configurable per-rule messaging, and server-side enforcement. The existing code only blocks the button client-side without proper exclusion messaging.

**Primary recommendation:** Extend the existing ping measurement infrastructure with browser/device detection using ua-parser-js, add configurable exclusion rules to `GymScene`, and create a proper pre-game screening flow with per-rule messaging.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| ua-parser-js | 2.0+ | Browser/device/OS detection from User-Agent | Only ~15KB, actively maintained, industry standard for UA parsing |
| Native APIs | N/A | Screen size, touch detection | No library needed, well-supported across browsers |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| navigator.userAgentData | Native | Modern UA Client Hints API | Chrome 90+, fallback to UA string for others |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ua-parser-js | bowser | bowser is smaller but less maintained; ua-parser-js has better update cycle |
| ua-parser-js | platform.js | platform.js is heavier and less focused on browser detection |
| Custom UA parsing | regex | Fragile, requires constant updates as browsers change UA strings |

**Installation:**
```bash
# ua-parser-js can be loaded via CDN in index.html
# https://cdnjs.cloudflare.com/ajax/libs/UAParser.js/2.0.0/ua-parser.min.js
```

## Architecture Patterns

### Recommended Project Structure
```
interactive_gym/
├── configurations/
│   └── remote_config.py        # Add entry_rules config (device, browser, ping)
├── scenes/
│   └── gym_scene.py            # Add entry_screening() method
├── server/
│   ├── app.py                  # Add pre_game_screening SocketIO event
│   └── static/
│       └── js/
│           ├── index.js        # Extend with browser/device detection
│           └── entry_screening.js  # NEW: Screening UI and logic
```

### Pattern 1: Configuration Flow
**What:** Researcher configures exclusion rules in Python, sent to client for pre-game checks
**When to use:** All GymScene configurations that need entry screening
**Flow:**
```
Python Config (GymScene)
    -> Scene Metadata (activate_scene event)
    -> Client receives rules
    -> Client runs checks
    -> Client shows result OR proceeds to start button
```

### Pattern 2: Hybrid Client-Server Enforcement
**What:** Client collects metrics and shows UI, server validates before game start
**When to use:** Any security-critical exclusion (prevent bypass)
**Flow:**
```
Client: Collect metrics (ping, browser, device)
Client: Show exclusion message if check fails (instant UX)
Server: Validate metrics on join_game event (security)
Server: Reject if rules violated (authoritative)
```

### Anti-Patterns to Avoid
- **Client-only exclusion:** Never trust client-side checks alone - participants can modify JavaScript
- **Silent rejection:** Always show a message explaining why the participant was excluded
- **Over-complex rules:** Keep rules simple (check A, check B); complex AND/OR logic is over-engineering

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Browser detection | Custom UA regex | ua-parser-js | UA strings change constantly; library handles edge cases |
| Mobile detection | window.innerWidth < 768 | Touch + device type detection | Screen size unreliable (tablets, desktop zoom) |
| Ping measurement | Custom WebSocket timing | Existing Socket.IO ping/pong | Already implemented and working in codebase |

**Key insight:** The hardest parts (ping measurement, focus detection) already exist in the codebase. Browser/device detection is the main gap, and ua-parser-js handles that well.

## Common Pitfalls

### Pitfall 1: Mobile Detection False Positives
**What goes wrong:** Tablets report as mobile but have full keyboards; iPad Pro with keyboard is desktop-class
**Why it happens:** Simple UA-based mobile detection treats all iOS/Android as mobile
**How to avoid:** Combine device type with screen size minimum; consider touch-only as separate criterion
**Warning signs:** Researchers complaining about tablet users being excluded when they shouldn't be

### Pitfall 2: Browser UA Spoofing
**What goes wrong:** Power users spoof UA strings; some browsers lie about identity
**Why it happens:** Privacy tools, compatibility modes, browser extensions
**How to avoid:** Use feature detection as fallback (WebRTC support, WebGL, etc.); don't rely solely on UA
**Warning signs:** Participants with "Chrome" UA failing Chrome-specific features

### Pitfall 3: Ping Measurement Overhead
**What goes wrong:** Socket.IO ping adds 30-50ms TCP overhead vs actual game latency
**Why it happens:** TCP handshake, server processing time included in measurement
**How to avoid:** For multiplayer games, use WebRTC DataChannel RTT which is closer to game traffic latency
**Warning signs:** Players excluded at 200ms Socket.IO ping but have 120ms actual game latency

### Pitfall 4: Race Condition on Page Load
**What goes wrong:** Entry checks run before ping measurements are ready
**Why it happens:** Ping requires several round-trips; checks run immediately
**How to avoid:** Require `min_ping_measurements` before enabling start button (already in code)
**Warning signs:** Start button briefly enabled then disabled as ping comes in

## Code Examples

Verified patterns from existing codebase and standard approaches:

### Existing Ping Measurement (index.js lines 45-78)
```javascript
// Source: interactive_gym/server/static/js/index.js
socket.on('pong', function(data) {
    var latency = Date.now() - window.lastPingTime;
    latencyMeasurements.push(latency);

    var maxMeasurements = 20;
    if (latencyMeasurements.length > maxMeasurements) {
        latencyMeasurements.shift();
    }

    var medianLatency = calculateMedian(latencyMeasurements);
    curLatency = medianLatency;
    maxLatency = data.max_latency;
});
```

### Existing Ping Blocking (index.js lines 849-856)
```javascript
// Source: interactive_gym/server/static/js/index.js
if (maxLatency != null && latencyMeasurements.length > 5 && curLatency > maxLatency) {
    $("#instructions").hide();
    $("#startButton").hide();
    $("#startButton").attr("disabled", true);
    $('#errorText').show()
    $('#errorText').text("Sorry, your connection is too slow...");
}
```

### Browser/Device Detection with ua-parser-js
```javascript
// Source: ua-parser-js official documentation
// Load via CDN: https://cdnjs.cloudflare.com/ajax/libs/UAParser.js/2.0.0/ua-parser.min.js
const parser = new UAParser();
const result = parser.getResult();

const deviceInfo = {
    browser: result.browser.name,      // "Chrome", "Safari", "Firefox"
    browserVersion: result.browser.version,  // "120.0.0"
    os: result.os.name,                // "Windows", "macOS", "iOS"
    deviceType: result.device.type,    // "mobile", "tablet", undefined (desktop)
    isMobile: result.device.type === 'mobile' || result.device.type === 'tablet'
};
```

### Screen Size Detection
```javascript
// Native API - no library needed
const screenInfo = {
    screenWidth: screen.width,
    screenHeight: screen.height,
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight,
    devicePixelRatio: window.devicePixelRatio
};
```

### Recommended Entry Screening Configuration (Python)
```python
# Proposed API for GymScene
scene = GymScene()
scene.entry_screening(
    device_exclusion="mobile",  # "mobile", "desktop", or None
    browser_requirements=["Chrome", "Firefox"],  # Allowed browsers, None for all
    browser_blocklist=["Safari"],  # Blocked browsers, None for none
    max_ping_ms=200,  # Maximum latency in ms
    min_ping_measurements=5,  # Minimum samples before checking
    exclusion_messages={
        "mobile": "Please use a desktop or laptop computer for this study.",
        "browser": "Please use Chrome or Firefox for this study.",
        "ping": "Your connection latency is too high for this study. Please try again with a stronger internet connection."
    }
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| UA string parsing | Client Hints API (navigator.userAgentData) | Chrome 90 (2021) | More reliable, but needs fallback for Safari/Firefox |
| window.innerWidth for mobile | Touch + device type detection | Ongoing | Screen size alone is unreliable |
| Block all mobile | Distinguish phone vs tablet | Ongoing | Tablets with keyboards are often acceptable |

**Deprecated/outdated:**
- Platform.js library: Less maintained than ua-parser-js
- Simple regex for UA parsing: Fragile, breaks with each browser update

## Integration Points

### GymScene Configuration (Python)
```python
# gym_scene.py already has:
self.max_ping: int | None = None
self.min_ping_measurements: int = 5

# Add:
self.device_exclusion: str | None = None  # "mobile", "desktop", None
self.browser_requirements: list[str] | None = None
self.browser_blocklist: list[str] | None = None
self.exclusion_messages: dict[str, str] = {}
```

### Scene Metadata (SocketIO)
```javascript
// activate_scene event already sends scene_metadata
// Add entry screening rules to metadata:
{
    // existing fields...
    max_ping: 200,
    min_ping_measurements: 5,
    device_exclusion: "mobile",
    browser_requirements: ["Chrome", "Firefox"],
    browser_blocklist: ["Safari"],
    exclusion_messages: {
        mobile: "Please use a desktop or laptop...",
        browser: "Please use Chrome or Firefox...",
        ping: "Your connection is too slow..."
    }
}
```

### Client-Side Check Flow
```javascript
// In index.js or new entry_screening.js
function runEntryScreening(sceneMetadata) {
    const parser = new UAParser();
    const result = parser.getResult();

    // Check device
    if (sceneMetadata.device_exclusion === "mobile") {
        if (result.device.type === "mobile" || result.device.type === "tablet") {
            showExclusionMessage(sceneMetadata.exclusion_messages.mobile);
            return false;
        }
    }

    // Check browser
    if (sceneMetadata.browser_requirements) {
        if (!sceneMetadata.browser_requirements.includes(result.browser.name)) {
            showExclusionMessage(sceneMetadata.exclusion_messages.browser);
            return false;
        }
    }

    // Ping check happens asynchronously via existing infrastructure
    // Enable start button only when all checks pass
    return true;
}
```

## SocketIO Event Flow

Current flow (what exists):
```
1. Client connects -> register_subject
2. Server -> activate_scene (sends scene_metadata)
3. Client shows scene with Start button (disabled initially)
4. Client measures ping via ping/pong events
5. Client enables Start button when min_ping_measurements reached AND ping < max
6. User clicks Start -> join_game
7. Server -> waiting_room OR start_game
```

Proposed flow with entry screening:
```
1. Client connects -> register_subject
2. Server -> activate_scene (sends scene_metadata WITH entry rules)
3. Client runs browser/device checks immediately
   - If fail: Show exclusion message, hide Start button
   - If pass: Continue
4. Client measures ping via existing ping/pong events
5. Client enables Start button when:
   - Device check passed
   - Browser check passed
   - min_ping_measurements reached
   - curLatency <= maxLatency
6. User clicks Start -> join_game
7. [NEW] Server validates metrics before game creation
   - If fail: emit 'entry_screening_failed' with message
   - If pass: proceed to waiting_room/start_game
```

## Open Questions

Things that couldn't be fully resolved:

1. **Should tablet be treated as mobile?**
   - What we know: iPad Pro with keyboard is desktop-class; phone screen is not
   - What's unclear: How to distinguish iPad-with-keyboard from iPad-touch-only
   - Recommendation: Add separate "tablet" option, default to treating as mobile

2. **WebRTC ping vs Socket.IO ping?**
   - What we know: WebRTC DataChannel RTT is more accurate for multiplayer games
   - What's unclear: Is the 30-50ms difference significant for entry screening?
   - Recommendation: Use Socket.IO ping for entry screening (simpler), document the overhead

3. **Server-side vs client-side enforcement priority?**
   - What we know: Client-side gives instant UX; server-side is secure
   - What's unclear: How much validation to add on join_game
   - Recommendation: Phase 15 = client-side with message; Phase 16+ adds server validation

## Sources

### Primary (HIGH confidence)
- interactive_gym/server/static/js/index.js - Existing ping measurement and blocking
- interactive_gym/scenes/gym_scene.py - Existing max_ping configuration
- interactive_gym/configurations/remote_config.py - Existing config patterns

### Secondary (MEDIUM confidence)
- .planning/research/SUMMARY.md - Prior research on exclusion system
- .planning/research/ARCHITECTURE.md - Rule engine patterns
- jsPsych browser-check plugin - Reference implementation

### Tertiary (LOW confidence)
- ua-parser-js npm page - Library documentation (verify before use)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - ua-parser-js is well-established; native APIs well-documented
- Architecture: HIGH - Extends existing patterns in codebase
- Pitfalls: HIGH - Based on existing research and codebase analysis

**Research date:** 2026-01-21
**Valid until:** 2026-02-21 (30 days - stable domain)
