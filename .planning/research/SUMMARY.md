# Research Summary: Participant Exclusion System

**Project:** Interactive Gym v1.2
**Researched:** 2026-01-21
**Overall Confidence:** HIGH

## Executive Summary

The participant exclusion system for Interactive Gym can leverage significant existing infrastructure while adding a pluggable rule engine for configurable screening. Key findings:

1. **Existing code covers the hard parts** — Ping measurement (Socket.IO + WebRTC getStats), focus detection (visibilitychange), and max latency checking already exist. This milestone extends rather than builds from scratch.

2. **No platform handles real-time multiplayer exclusion well** — oTree has dropout handling for turn-based games, jsPsych has browser-check, but nobody does "exclude one player mid-game, end for both." This is a differentiator.

3. **Hybrid client-server architecture required** — Client-side checks for UX (instant feedback), server-side enforcement for security. Never trust client-only exclusion.

4. **22 specific pitfalls identified** — Most critical: ping measurement inaccuracy (30-50ms overhead), power-saving mode breaking timers, and multiplayer cascade unfairness.

5. **Single dependency needed** — ua-parser-js (~15KB) for browser/device detection. All other functionality uses native APIs.

## Key Findings by Dimension

### Stack (APIs & Libraries)

| Need | Solution | Confidence |
|------|----------|------------|
| Ping measurement | Existing Socket.IO + WebRTC getStats() | HIGH |
| Browser detection | ua-parser-js (add) + feature detection | HIGH |
| Inactivity monitoring | Existing visibilitychange + custom activity tracking | HIGH |
| Screen/device info | Native APIs (screen.width, innerWidth, devicePixelRatio) | HIGH |

**What to avoid:** Network Information API (no Safari/Firefox), Idle Detection API (explicitly rejected by Firefox/Safari for privacy).

### Features (What to Build)

**Table stakes (must have):**
- Device type detection (mobile/desktop)
- Browser type/version check
- Screen size minimum
- Configurable rejection messages per rule

**Differentiators (competitive advantage):**
- Connection quality monitoring (ping, jitter, packet loss)
- Continuous real-time exclusion during gameplay
- Multiplayer dropout coordination ("end for both")
- Custom callback support for arbitrary logic

**Anti-features (explicitly avoid):**
- Duplicating Prolific/MTurk prescreeners
- Auto-rejection on first attention check failure
- Complex rule engine with AND/OR/NOT operators
- Browser fingerprinting for repeat detection

### Architecture (How to Build)

**Pattern:** Strategy + Chain of Responsibility
- Each rule is a self-contained strategy with `ExclusionRule` interface
- Rules evaluated sequentially, short-circuiting on first exclusion
- `ExclusionManager` orchestrates pre-game and continuous evaluation

**Client-server split:**
- Client: Collect metrics, show feedback (instant UX)
- Server: Define rules, evaluate, enforce (security)

**Integration points:**
- `GymScene.exclusion()` — new configuration method
- `GameCallback.on_exclusion()` — new hook for researchers
- New SocketIO events: `pre_game_screening`, `exclusion_metrics`, `excluded`

### Pitfalls (What Can Go Wrong)

**Critical (address early):**
1. **P10: Power-saving mode** — Backgrounded tabs throttle timers to 1/minute. Use Web Workers or visibilitychange handling.
2. **P1: Ping measurement overhead** — TCP/HTTP adds 30-50ms. Use WebRTC DataChannel for true latency.
3. **P13: Partner stranded** — Clear messaging for non-excluded player is essential.
4. **P16: Reconnect vs exclude conflict** — Need clear state machine distinguishing temporary disconnects from exclusions.

**Medium priority:**
- P4: Browser UA unreliable — Use feature detection over browser detection
- P6: Opaque messages — Per-rule messaging explaining what failed and why
- P8: No warning before exclusion — Grace period system

## Implications for Roadmap

Based on research, recommended phase structure:

### Phase 15: Core Exclusion Infrastructure
- `ExclusionRule` base class and `ExclusionResult` dataclass
- `ExclusionManager` with pre_game and continuous evaluation
- `GymScene.exclusion()` configuration method
- **Addresses:** Foundation for all rules
- **Pitfalls:** P10 (power-saving) — use Web Workers for critical timers

### Phase 16: Pre-Game Screening
- `pre_game_screening` SocketIO event flow
- Client-side metrics collection (browser, ping, screen)
- Exclusion UI with per-rule messaging
- Check ordering (fast checks first, parallel where possible)
- **Addresses:** Table stakes entry screening
- **Pitfalls:** P7 (slow screening), P12 (check order)

### Phase 17: Built-in Rules
- `PingThreshold` with consecutive violation requirement
- `BrowserExclusion` with ua-parser-js
- `ScreenSizeMinimum` with viewport detection
- `MobileExclusion` with touch + device type detection
- **Addresses:** Common exclusion scenarios
- **Pitfalls:** P1 (ping overhead), P4 (UA unreliable), P5 (screen size confusion)

### Phase 18: Continuous Monitoring
- `exclusion_metrics` periodic reporting from client
- Grace period warning system before exclusion
- `InactivityDetection` rule with context-aware timeouts
- Mid-game exclusion handling
- **Addresses:** Real-time monitoring differentiator
- **Pitfalls:** P2 (latency spikes), P8 (no warning), P9 (false positive inactivity)

### Phase 19: Multiplayer Exclusion Handling
- Partner notification on exclusion ("Your partner experienced a technical issue")
- Coordinated game termination via SocketIO room events
- WebRTC disconnect coordination
- Partial data preservation before exclusion
- **Addresses:** Critical multiplayer differentiator
- **Pitfalls:** P13 (partner stranded), P15 (state sync), P16 (reconnect conflict)

### Phase 20: Custom Callbacks & Logging
- `CustomCallback` wrapper for user-provided functions
- `GameCallback.on_exclusion()` hook
- Exclusion event logging with full context
- Analytics export (exclusion rate by rule, by time, by browser)
- **Addresses:** Researcher extensibility
- **Pitfalls:** P19 (untestable callbacks), P20 (no visibility)

**Phase ordering rationale:**
1. Core infrastructure first (no dependencies, foundation for everything)
2. Pre-game screening second (high value, blocks bad participants immediately)
3. Built-in rules third (adds utility quickly, most common scenarios)
4. Continuous monitoring fourth (builds on pre-game foundation)
5. Multiplayer handling fifth (requires deeper understanding of game state)
6. Callbacks/logging sixth (polish and extensibility)

## Research Flags for Phases

| Phase | Research Status |
|-------|-----------------|
| 15 (Core) | Standard patterns, minimal research needed |
| 16 (Pre-game) | Standard patterns, jsPsych browser-check as reference |
| 17 (Rules) | ua-parser-js well-documented; ping measurement details researched |
| 18 (Continuous) | Power-saving pitfall well-documented; needs careful implementation |
| 19 (Multiplayer) | **Likely needs deeper research** — no existing patterns for real-time games |
| 20 (Callbacks) | Standard patterns |

## Confidence Assessment

| Area | Confidence | Reason |
|------|------------|--------|
| Stack/APIs | HIGH | Verified against MDN, existing codebase |
| Architecture | HIGH | Based on existing codebase patterns + standard design patterns |
| Features | HIGH | Cross-referenced jsPsych, oTree, Prolific, Gorilla |
| Pitfalls | MEDIUM | WebSearch-based, verified against multiple sources |
| Multiplayer handling | MEDIUM | oTree patterns verified; real-time game scenarios less documented |

## Open Questions

1. **What ping threshold makes research data invalid?** Gaming suggests >100ms problematic, but research experiments may differ. May need experiment-specific tuning.

2. **Should inactivity warning precede exclusion?** Prolific policy implications. Recommend yes with configurable grace period.

3. **Reconnection vs exclusion policy?** Need clear state machine. Recommend: disconnect = temporary (allow reconnect), exclusion = permanent (invalidate session).

4. **Partial data retention on mid-game exclusion?** Recommend: save all data up to exclusion frame, mark session as partial.

## Files Created

| File | Purpose |
|------|---------|
| [STACK.md](STACK.md) | API recommendations with browser support and code examples |
| [FEATURES.md](FEATURES.md) | Feature landscape with platform comparison |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design with rule engine patterns and data flows |
| [PITFALLS.md](PITFALLS.md) | 22 specific pitfalls with prevention strategies |

---

*Research complete: 2026-01-21*
*Ready for: `/gsd:define-requirements` or `/gsd:create-roadmap`*
