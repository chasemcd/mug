# Stack Research: Participant Exclusion APIs

**Domain:** Browser-based experiment participant screening
**Researched:** 2026-01-21
**Confidence:** HIGH (APIs verified against MDN and official docs)

## Executive Summary

For participant exclusion in browser-based experiments, the JavaScript ecosystem provides robust native APIs for most needs. The project already implements Socket.IO latency measurement and WebRTC quality monitoring via `getStats()`. For browser/device detection and inactivity monitoring, native APIs cover the core use cases, though browser support varies significantly for newer APIs like Idle Detection (Chromium-only).

**Key insight:** The existing codebase already implements the hardest parts (WebRTC RTT via `RTCPeerConnection.getStats()` and Socket.IO ping/pong). Participant exclusion primarily requires adding threshold enforcement and device detection around these existing measurements.

---

## Ping/Latency Measurement

### Existing Implementation (HIGH Confidence)

The project already implements two latency measurement approaches:

**1. Socket.IO Ping/Pong** (`index.js` lines 45-87)
```javascript
// Already implemented - measures server RTT
socket.on('pong', function(data) {
    var latency = Date.now() - window.lastPingTime;
    // ... median calculation, UI update
});
```

**2. WebRTC RTT via getStats()** (`webrtc_manager.js` lines 66-154)
```javascript
// Already implemented - measures P2P RTT
const stats = await this.pc.getStats();
// Uses RTCIceCandidatePairStats.currentRoundTripTime
```

### Recommended Approach: Use Existing + Add Thresholds

| Method | Already Implemented | Use For | Accuracy |
|--------|---------------------|---------|----------|
| Socket.IO ping/pong | Yes | Server connection quality | ~10-50ms overhead |
| WebRTC getStats() | Yes | P2P connection quality | STUN RTT, ~1ms precision |
| DataChannel ping/pong | No (optional) | True P2P latency | Best for experiments |

**For participant exclusion, the existing implementations are sufficient.** Both provide:
- Continuous monitoring (Socket.IO: 1s intervals, WebRTC: 2s intervals)
- Threshold detection (WebRTC: 150ms warning, 300ms critical)

### If More Precision Needed: DataChannel Ping/Pong

For experiments requiring precise latency measurement:

```javascript
// Send timestamp, measure round-trip
const start = performance.now();
dataChannel.send(JSON.stringify({ type: 'ping', t: start }));

// On receiving pong with echoed timestamp
const rtt = performance.now() - data.t;
const latency = rtt / 2;
```

**Advantages over getStats():**
- Measures actual DataChannel latency, not STUN
- Works even when ICE is routed through SFU
- `performance.now()` provides sub-millisecond precision

**Browser Support:** Universal (DataChannel supported everywhere WebRTC is)

### API Reference: RTCIceCandidatePairStats

```javascript
// Key properties for latency monitoring
{
  currentRoundTripTime: 0.042,      // Seconds (most recent STUN RTT)
  totalRoundTripTime: 1.234,        // Cumulative seconds
  responsesReceived: 29,            // For calculating average
  availableOutgoingBitrate: 2500000 // Bits/sec
}
```

**Source:** [MDN RTCIceCandidatePairStats](https://developer.mozilla.org/en-US/docs/Web/API/RTCIceCandidatePairStats/currentRoundTripTime)

---

## Browser Detection

### Recommended: Feature Detection + ua-parser-js Fallback (HIGH Confidence)

**Primary approach: Feature detection for capabilities**
```javascript
// Detect capabilities, not browsers
const hasTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
const hasWebGL = !!document.createElement('canvas').getContext('webgl');
const hasWebRTC = !!window.RTCPeerConnection;
```

**Secondary approach: ua-parser-js for browser identification**
```javascript
import UAParser from 'ua-parser-js';
const parser = new UAParser();
const result = parser.getResult();
// result.browser.name, result.browser.version
// result.os.name, result.device.type
```

### API Options Comparison

| API | Browser Support | Best For |
|-----|-----------------|----------|
| Feature detection | Universal | Capability checks |
| `navigator.userAgentData` | Chrome/Edge only | Modern, privacy-aware detection |
| `navigator.userAgent` + parsing | Universal | Fallback browser identification |
| ua-parser-js library | Universal | Comprehensive device/browser info |

### navigator.userAgentData (Experimental)

**Status:** Not recommended as primary method due to limited support.

```javascript
// Only works in Chromium-based browsers
if (navigator.userAgentData) {
  const { mobile, platform, brands } = navigator.userAgentData;
  // brands: [{ brand: "Chromium", version: "120" }, ...]
}
```

**Browser Support:**
- Chrome/Edge/Opera: Full support
- Firefox: No support
- Safari: No support

**Source:** [MDN navigator.userAgentData](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/userAgentData)

### Recommendation for This Project

```javascript
// Participant screening browser check
function checkBrowserCompatibility() {
  const parser = new UAParser();
  const browser = parser.getBrowser();
  const device = parser.getDevice();

  return {
    isSupported: ['Chrome', 'Firefox', 'Safari', 'Edge'].includes(browser.name),
    isMobile: device.type === 'mobile' || device.type === 'tablet',
    browserName: browser.name,
    browserVersion: browser.version,
    hasWebRTC: !!window.RTCPeerConnection,
    hasPyodide: typeof loadPyodide !== 'undefined'
  };
}
```

**Library:** [ua-parser-js v2.0.8](https://www.npmjs.com/package/ua-parser-js) - MIT/AGPLv3 dual license

---

## Inactivity Monitoring

### Existing Implementation (HIGH Confidence)

The project already implements Page Visibility API (`index.js` lines 25-43):

```javascript
// Already implemented
document.addEventListener("visibilitychange", function() {
  if (document.hidden) {
    documentInFocus = false;
  } else {
    documentInFocus = true;
  }
});
```

### Recommended: Page Visibility + Custom Activity Tracking

**Tier 1: Page Visibility API (Universal Support)**
```javascript
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') {
    // Tab is hidden - pause, warn, or exclude
  }
});
```

**Browser Support:** Universal (IE 10+, all modern browsers)

**Tier 2: Custom Activity Tracking**
```javascript
class ActivityMonitor {
  constructor(timeoutMs = 30000) {
    this.lastActivity = Date.now();
    this.timeout = timeoutMs;
    this.events = ['mousemove', 'keydown', 'mousedown', 'touchstart'];

    this.events.forEach(event => {
      document.addEventListener(event, () => this.lastActivity = Date.now(),
        { passive: true });
    });
  }

  isIdle() {
    return Date.now() - this.lastActivity > this.timeout;
  }

  getIdleTime() {
    return Date.now() - this.lastActivity;
  }
}
```

### Idle Detection API (NOT Recommended)

**Status:** Avoid for cross-browser experiments.

```javascript
// Chrome/Edge only - NOT recommended for this project
const controller = new AbortController();
const idleDetector = new IdleDetector();
idleDetector.start({ threshold: 60000, signal: controller.signal });
```

**Browser Support:**
- Chrome 94+: Supported (requires permission)
- Edge 94+: Supported
- Firefox: **Explicitly rejected** (privacy concerns)
- Safari: **Explicitly rejected**

**Why rejected:** Mozilla and Apple consider it a privacy risk and surveillance vector. It detects system-wide idle state (screensaver, lock screen), not just page inactivity.

**Source:** [MDN Idle Detection API](https://developer.mozilla.org/en-US/docs/Web/API/Idle_Detection_API)

### Recommendation for This Project

Use the existing Page Visibility implementation plus custom activity tracking:

```javascript
// Participant screening inactivity check
class ParticipantActivityMonitor {
  constructor(warningMs = 15000, excludeMs = 60000) {
    this.warningThreshold = warningMs;
    this.excludeThreshold = excludeMs;
    this.lastActivity = Date.now();
    this.tabHiddenAt = null;

    // Track user input
    ['mousemove', 'keydown', 'mousedown', 'touchstart'].forEach(event => {
      document.addEventListener(event, () => this.recordActivity(),
        { passive: true });
    });

    // Track tab visibility
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        this.tabHiddenAt = Date.now();
      } else {
        this.tabHiddenAt = null;
        this.recordActivity();
      }
    });
  }

  recordActivity() {
    this.lastActivity = Date.now();
  }

  getStatus() {
    const idleTime = Date.now() - this.lastActivity;
    const tabHiddenTime = this.tabHiddenAt ? Date.now() - this.tabHiddenAt : 0;

    return {
      idleTimeMs: idleTime,
      tabHiddenTimeMs: tabHiddenTime,
      isTabHidden: document.hidden,
      shouldWarn: idleTime > this.warningThreshold || tabHiddenTime > this.warningThreshold,
      shouldExclude: idleTime > this.excludeThreshold || tabHiddenTime > this.excludeThreshold
    };
  }
}
```

---

## Device Info Collection

### Screen/Viewport Detection (HIGH Confidence)

**Recommended APIs:**

```javascript
// Screen dimensions (physical display)
const screenWidth = screen.width;
const screenHeight = screen.height;
const pixelRatio = window.devicePixelRatio;

// Viewport dimensions (browser window)
const viewportWidth = window.innerWidth;
const viewportHeight = window.innerHeight;

// Responsive breakpoint detection
const isMobileViewport = window.matchMedia('(max-width: 768px)').matches;
const isLandscape = window.matchMedia('(orientation: landscape)').matches;
```

**Browser Support:** Universal

### Touch Detection (MEDIUM Confidence)

**Recommended approach - combine multiple signals:**

```javascript
function detectTouchCapability() {
  // Primary: maxTouchPoints (most reliable)
  const maxTouchPoints = navigator.maxTouchPoints || 0;

  // Secondary: ontouchstart event
  const hasTouch = 'ontouchstart' in window;

  // Tertiary: Media query for pointer type
  const hasCoarsePointer = window.matchMedia('(pointer: coarse)').matches;
  const hasNoHover = window.matchMedia('(hover: none)').matches;

  return {
    isTouchDevice: maxTouchPoints > 0 || hasTouch,
    maxTouchPoints,
    hasCoarsePointer,
    hasNoHover,
    // High confidence mobile if both touch AND coarse pointer
    isLikelyMobile: (maxTouchPoints > 0 || hasTouch) && hasCoarsePointer
  };
}
```

**Caveats:**
- Chrome on non-touch laptops may report `maxTouchPoints: 1` (false positive)
- 2-in-1 devices always report touch capability
- Touch laptops exist

**Source:** [MDN Touch events](https://developer.mozilla.org/en-US/docs/Web/API/Touch_events)

### Network Information API (LOW Confidence for Safari/Firefox)

**Use sparingly - limited browser support:**

```javascript
if ('connection' in navigator) {
  const conn = navigator.connection;
  // conn.effectiveType: '4g', '3g', '2g', 'slow-2g'
  // conn.downlink: estimated bandwidth in Mbps
  // conn.rtt: estimated RTT in ms (rounded to 25ms)
}
```

**Browser Support:**
- Chrome/Edge/Opera: Full support (~48% global)
- Safari: **No support**
- Firefox: **No support**

**Global support:** ~80% (includes partial support)

**Source:** [Can I Use - Network Information API](https://caniuse.com/netinfo)

**Recommendation:** Do not use as primary exclusion criteria. Use actual measured latency instead (Socket.IO ping, WebRTC getStats).

### Comprehensive Device Check

```javascript
function collectDeviceInfo() {
  const parser = new UAParser();
  const device = parser.getDevice();
  const os = parser.getOS();

  return {
    // Screen
    screenWidth: screen.width,
    screenHeight: screen.height,
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight,
    pixelRatio: window.devicePixelRatio,

    // Device type
    deviceType: device.type || 'desktop', // mobile, tablet, desktop
    os: os.name,
    osVersion: os.version,

    // Capabilities
    isTouchDevice: navigator.maxTouchPoints > 0 || 'ontouchstart' in window,
    hasWebRTC: !!window.RTCPeerConnection,
    hasWebGL: !!document.createElement('canvas').getContext('webgl'),

    // Network (if available)
    connectionType: navigator.connection?.effectiveType || 'unknown',
    connectionRtt: navigator.connection?.rtt || null
  };
}
```

---

## Recommendations

### For Participant Screening Implementation

| Criterion | API/Method | Browser Support | Confidence |
|-----------|------------|-----------------|------------|
| Server latency | Socket.IO ping/pong (existing) | Universal | HIGH |
| P2P latency | WebRTC getStats (existing) | Universal (WebRTC) | HIGH |
| Browser type | ua-parser-js | Universal | HIGH |
| Tab visibility | Page Visibility API (existing) | Universal | HIGH |
| User inactivity | Custom event tracking | Universal | HIGH |
| Screen size | screen.width/height, innerWidth/Height | Universal | HIGH |
| Mobile detection | Touch + viewport + ua-parser-js | Universal | MEDIUM |
| Network quality | Measured latency (not Network Info API) | Universal | HIGH |

### Libraries to Add

| Library | Version | Purpose | Size |
|---------|---------|---------|------|
| ua-parser-js | 2.0.8 | Browser/device detection | ~15KB min |

**Note:** No other libraries required. All other functionality uses native APIs.

### Integration Points with Existing Code

1. **Latency exclusion:** Extend existing `maxLatency` check in `index.js` (line 849)
2. **Tab focus tracking:** Extend existing `documentInFocus` in `index.js` (line 25)
3. **WebRTC quality:** Use existing `ConnectionQualityMonitor` callbacks in `webrtc_manager.js`
4. **Device checks:** Add at experiment join time (before `join_game` emit)

---

## What to Avoid

### Deprecated/Unreliable Approaches

| Approach | Problem | Use Instead |
|----------|---------|-------------|
| `navigator.userAgent` string parsing | Unreliable, spoofable, being reduced | ua-parser-js library |
| Network Information API for exclusion | Safari/Firefox unsupported | Measured latency |
| Idle Detection API | Firefox/Safari rejected | Custom activity tracking |
| `navigator.platform` | Deprecated | ua-parser-js |
| `navigator.appVersion` | Deprecated | ua-parser-js |
| Battery API | Restricted in most browsers | N/A |

### Common Mistakes

1. **Relying on Network Information API** - 20% of users (Safari/Firefox) won't have it
2. **Using Idle Detection API** - Firefox and Safari explicitly rejected it
3. **Touch detection alone for mobile** - Touch laptops exist, 2-in-1s always report touch
4. **Single-check device detection** - Use multiple signals for confidence

---

## Sources

**Official Documentation:**
- [MDN RTCPeerConnection.getStats()](https://developer.mozilla.org/en-US/docs/Web/API/RTCPeerConnection/getStats)
- [MDN RTCIceCandidatePairStats](https://developer.mozilla.org/en-US/docs/Web/API/RTCIceCandidatePairStats/currentRoundTripTime)
- [MDN Page Visibility API](https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API)
- [MDN Idle Detection API](https://developer.mozilla.org/en-US/docs/Web/API/Idle_Detection_API)
- [MDN navigator.userAgentData](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/userAgentData)
- [MDN Touch events](https://developer.mozilla.org/en-US/docs/Web/API/Touch_events)

**Browser Support:**
- [Can I Use - Network Information API](https://caniuse.com/netinfo)
- [Can I Use - Page Visibility API](https://caniuse.com/pagevisibility)

**Libraries:**
- [ua-parser-js npm](https://www.npmjs.com/package/ua-parser-js)
- [Socket.IO Latency Documentation](https://socket.io/how-to/check-the-latency-of-the-connection)

**WebRTC Resources:**
- [W3C WebRTC Statistics Specification](https://www.w3.org/TR/webrtc-stats/)
- [WebRTC Latency Measurement Techniques](https://webrtchacks.com/calculate-true-end-to-end-rtt/)
