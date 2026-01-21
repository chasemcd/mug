# Architecture Research: Participant Exclusion System

**Domain:** Participant screening and exclusion for web-based experiments
**Researched:** 2026-01-21
**Confidence:** HIGH (based on existing codebase analysis + established patterns)

## Executive Summary

The exclusion system should be a **hybrid client-server architecture** with:

1. **Server-side rule registry** - Python classes defining exclusion rules, configured in experiment setup
2. **Client-side checks** - JavaScript implementations for real-time monitoring (latency, browser, focus)
3. **Server-side enforcement** - All exclusion decisions validated and enforced server-side
4. **Pluggable rule engine** - Strategy pattern with chain-of-responsibility for rule evaluation

**Key architectural decision:** Client-side checks for UX (instant feedback) but server-side enforcement for security. Never trust client-only exclusion - malicious participants can bypass JavaScript.

The system integrates naturally with the existing `GymScene` configuration pattern and extends the current `GameCallback` hook system.

## Client vs Server Responsibilities

### Client-Side Responsibilities (JavaScript)

| Responsibility | Rationale | Implementation |
|---------------|-----------|----------------|
| **Latency measurement** | Already exists via ping/pong | Extend `index.js` latency tracking |
| **Browser detection** | Only client knows UA string | Feature detection preferred over UA sniffing |
| **Focus monitoring** | Only client knows visibility | Already exists: `visibilitychange` listener |
| **UI feedback** | Instant user feedback | Show exclusion messages immediately |
| **Data collection** | Gather metrics for server | Report via SocketIO events |

**Current client-side code already handles:**
- Ping measurement (lines 45-78 in `index.js`)
- Focus detection (`visibilitychange`, `focus`, `blur` events)
- Max latency checking (lines 848-855 in `index.js`)

### Server-Side Responsibilities (Python)

| Responsibility | Rationale | Implementation |
|---------------|-----------|----------------|
| **Rule definition** | Single source of truth | Python classes in configuration |
| **Rule evaluation** | Security - can't be bypassed | Evaluate in `app.py` or `GameManager` |
| **Exclusion enforcement** | Prevent game start/continue | Emit exclusion events to client |
| **Multiplayer handling** | Coordinate exclusion across players | Notify all players in game room |
| **Logging/audit** | Research data integrity | Log all exclusion events |

### Why This Split?

1. **Security**: Client-side JavaScript can be bypassed. Server must be authoritative.
2. **User Experience**: Waiting for server round-trip for every check is poor UX.
3. **Performance**: Real-time checks (ping, focus) need client-side loop.
4. **Research Integrity**: Server logs ensure exclusion data is trustworthy.

**Pattern**: Client detects, reports, and shows feedback. Server validates, decides, and enforces.

## Rule Engine Patterns

### Recommended: Strategy Pattern + Chain of Responsibility

The exclusion system should use a **Strategy Pattern** where each rule is a self-contained strategy, combined with **Chain of Responsibility** for sequential evaluation.

```
                          +------------------+
                          | ExclusionManager |
                          +------------------+
                                   |
                    +--------------+--------------+
                    |              |              |
               +--------+    +--------+    +----------+
               | Rule 1 |    | Rule 2 |    | Rule N   |
               | (Ping) |    |(Browser)|   |(Custom)  |
               +--------+    +--------+    +----------+
```

### Rule Interface (Python)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Any

@dataclass
class ExclusionResult:
    """Result of evaluating an exclusion rule."""
    should_exclude: bool
    rule_name: str
    message: str  # User-facing message
    data: dict | None = None  # Additional context for logging

class ExclusionRule(ABC):
    """Base class for all exclusion rules."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this rule."""
        pass

    @property
    @abstractmethod
    def check_timing(self) -> str:
        """When to check: 'pre_game', 'continuous', or 'both'."""
        pass

    @abstractmethod
    def evaluate(self, context: dict) -> ExclusionResult:
        """
        Evaluate the rule against the provided context.

        Args:
            context: Dict containing participant state, metrics, etc.

        Returns:
            ExclusionResult indicating whether to exclude.
        """
        pass
```

### Built-in Rule Examples

```python
class PingThreshold(ExclusionRule):
    """Exclude participants with latency above threshold."""

    def __init__(self, max_ms: int = 200, message: str | None = None):
        self.max_ms = max_ms
        self._message = message or f"Your connection latency ({'{ping}'} ms) exceeds the maximum allowed ({max_ms} ms)."

    @property
    def name(self) -> str:
        return "ping_threshold"

    @property
    def check_timing(self) -> str:
        return "both"  # Check before game and continuously

    def evaluate(self, context: dict) -> ExclusionResult:
        ping = context.get("ping_ms", 0)
        should_exclude = ping > self.max_ms
        return ExclusionResult(
            should_exclude=should_exclude,
            rule_name=self.name,
            message=self._message.format(ping=ping) if should_exclude else "",
            data={"ping_ms": ping, "threshold": self.max_ms}
        )


class BrowserExclusion(ExclusionRule):
    """Exclude specific browsers."""

    def __init__(
        self,
        blocked: list[str] | None = None,
        allowed: list[str] | None = None,
        message: str | None = None
    ):
        self.blocked = [b.lower() for b in (blocked or [])]
        self.allowed = [a.lower() for a in (allowed or [])]
        self._message = message or "Your browser is not supported for this experiment."

    @property
    def name(self) -> str:
        return "browser_exclusion"

    @property
    def check_timing(self) -> str:
        return "pre_game"  # Only check once at start

    def evaluate(self, context: dict) -> ExclusionResult:
        browser = context.get("browser", "unknown").lower()

        if self.blocked and browser in self.blocked:
            return ExclusionResult(True, self.name, self._message, {"browser": browser})

        if self.allowed and browser not in self.allowed:
            return ExclusionResult(True, self.name, self._message, {"browser": browser})

        return ExclusionResult(False, self.name, "")


class FocusRequirement(ExclusionRule):
    """Exclude participants who tab away too often or too long."""

    def __init__(
        self,
        max_blur_duration_ms: int = 5000,
        max_blur_count: int = 3,
        message: str | None = None
    ):
        self.max_blur_duration_ms = max_blur_duration_ms
        self.max_blur_count = max_blur_count
        self._message = message or "Please keep the experiment window focused."

    @property
    def name(self) -> str:
        return "focus_requirement"

    @property
    def check_timing(self) -> str:
        return "continuous"

    def evaluate(self, context: dict) -> ExclusionResult:
        blur_count = context.get("blur_count", 0)
        blur_duration = context.get("blur_duration_ms", 0)

        should_exclude = (
            blur_count > self.max_blur_count or
            blur_duration > self.max_blur_duration_ms
        )

        return ExclusionResult(
            should_exclude=should_exclude,
            rule_name=self.name,
            message=self._message if should_exclude else "",
            data={"blur_count": blur_count, "blur_duration_ms": blur_duration}
        )


class CustomCallback(ExclusionRule):
    """Wrap a user-provided callback function as a rule."""

    def __init__(
        self,
        callback: Callable[[dict], bool],
        name: str = "custom",
        timing: str = "both",
        message: str = "You have been excluded from this experiment."
    ):
        self._callback = callback
        self._name = name
        self._timing = timing
        self._message = message

    @property
    def name(self) -> str:
        return self._name

    @property
    def check_timing(self) -> str:
        return self._timing

    def evaluate(self, context: dict) -> ExclusionResult:
        should_exclude = self._callback(context)
        return ExclusionResult(
            should_exclude=should_exclude,
            rule_name=self.name,
            message=self._message if should_exclude else ""
        )
```

### Exclusion Manager (Chain of Responsibility)

```python
class ExclusionManager:
    """Manages and evaluates exclusion rules."""

    def __init__(self, rules: list[ExclusionRule]):
        self.rules = rules

    def evaluate_pre_game(self, context: dict) -> ExclusionResult | None:
        """Evaluate rules before game starts. Returns first exclusion or None."""
        for rule in self.rules:
            if rule.check_timing in ("pre_game", "both"):
                result = rule.evaluate(context)
                if result.should_exclude:
                    return result
        return None

    def evaluate_continuous(self, context: dict) -> ExclusionResult | None:
        """Evaluate rules during gameplay. Returns first exclusion or None."""
        for rule in self.rules:
            if rule.check_timing in ("continuous", "both"):
                result = rule.evaluate(context)
                if result.should_exclude:
                    return result
        return None

    def evaluate_all(self, context: dict, timing: str = "both") -> list[ExclusionResult]:
        """Evaluate all applicable rules, returning all violations."""
        results = []
        for rule in self.rules:
            if timing == "both" or rule.check_timing in (timing, "both"):
                result = rule.evaluate(context)
                if result.should_exclude:
                    results.append(result)
        return results
```

### Configuration API (Integration with GymScene)

```python
# In experiment configuration
game_scene = (
    GymScene()
    .scene(scene_id="main_game")
    .exclusion(
        rules=[
            PingThreshold(max_ms=200, message="Your connection is too slow."),
            BrowserExclusion(blocked=["Firefox"], message="Please use Chrome or Edge."),
            FocusRequirement(max_blur_count=5),
            CustomCallback(
                callback=lambda ctx: ctx.get("age", 99) < 18,
                name="age_check",
                timing="pre_game",
                message="You must be 18+ to participate."
            ),
        ],
        # Behavior options
        pre_game_check=True,  # Block game start on exclusion
        continuous_check=True,  # Monitor during gameplay
        on_exclude_multiplayer="end_for_all",  # or "end_for_excluded"
        grace_period_ms=2000,  # Warn before excluding
    )
    # ... other configuration
)
```

## Data Flow

### Pre-Game Exclusion Check

```
Participant clicks "Start"
         |
         v
+-------------------+
| Client: Collect   |     1. Gather browser info, current ping,
| screening data    |        focus state, etc.
+-------------------+
         |
         v (SocketIO: "pre_game_screening")
+-------------------+
| Server: Receive   |     2. Receive screening data
| screening data    |
+-------------------+
         |
         v
+-------------------+
| Server: Evaluate  |     3. Run ExclusionManager.evaluate_pre_game()
| pre_game rules    |
+-------------------+
         |
    +----+----+
    |         |
  PASS      FAIL
    |         |
    v         v
+--------+ +------------------+
| Proceed| | Emit "excluded"  |    4a. If pass: normal game flow
| to     | | with message     |    4b. If fail: send exclusion event
| game   | +------------------+
+--------+        |
                  v
           +------------------+
           | Client: Show     |    5. Display exclusion message
           | exclusion UI     |        and redirect
           +------------------+
```

### Continuous Monitoring During Gameplay

```
+-------------------+
| Client: Monitor   |     1. Track ping, focus, custom metrics
| metrics loop      |        at configured interval (e.g., 1s)
+-------------------+
         |
         v (SocketIO: "exclusion_metrics")
+-------------------+
| Server: Receive   |     2. Update participant context
| metrics update    |
+-------------------+
         |
         v
+-------------------+
| Server: Evaluate  |     3. Run ExclusionManager.evaluate_continuous()
| continuous rules  |
+-------------------+
         |
    +----+----+
    |         |
  PASS      FAIL
    |         |
    v         v
+--------+ +------------------+
| Continue| | Grace period?   |    4a. If pass: continue
| game   | | (warn first)    |    4b. If fail: check grace period
+--------+ +------------------+
                  |
        +---------+---------+
        |                   |
    WARNED              EXCLUDED
        |                   |
        v                   v
+------------------+ +------------------+
| Emit "exclusion_ | | Emit "excluded"  |
| warning"         | | end game for     |
+------------------+ | player(s)        |
                     +------------------+
```

### Multiplayer Exclusion Handling

```
Player A excluded
         |
         v
+-------------------+
| Server: Check     |     1. Determine multiplayer behavior
| on_exclude config |        from scene configuration
+-------------------+
         |
    +----+----+
    |         |
"end_for_   "end_for_
 excluded"   all"
    |         |
    v         v
+--------+ +------------------+
| Emit   | | Emit "end_game"  |    2a. Only excluded player ends
| to A   | | to game room     |    2b. All players in game end
+--------+ +------------------+
    |              |
    v              v
+------------------+
| Clean up game    |     3. Remove from active games,
| state            |        persist data, clean up
+------------------+
```

## Integration Points

### Where Exclusion Hooks Into Existing Architecture

| Hook Point | File | Description |
|------------|------|-------------|
| **Scene Configuration** | `gym_scene.py` | New `.exclusion()` method on GymScene |
| **Pre-game Check** | `game_manager.py` | Check in `add_subject_to_game()` before adding |
| **Continuous Check** | `game_manager.py` | New background task or integrate with game loop |
| **Client Metrics** | `index.js` | Extend existing ping/focus code to report metrics |
| **Exclusion Events** | `app.py` | New SocketIO events: `pre_game_screening`, `exclusion_metrics`, `excluded`, `exclusion_warning` |
| **Callback Integration** | `callback.py` | New hooks: `on_pre_exclusion_check`, `on_exclusion` |

### New SocketIO Events

| Event | Direction | Payload | Purpose |
|-------|-----------|---------|---------|
| `pre_game_screening` | Client -> Server | `{browser, ping_ms, ...}` | Send screening data before game |
| `exclusion_metrics` | Client -> Server | `{ping_ms, focus_state, blur_count, ...}` | Continuous monitoring data |
| `excluded` | Server -> Client | `{rule, message, redirect_url}` | Notify of exclusion |
| `exclusion_warning` | Server -> Client | `{rule, message, grace_remaining_ms}` | Grace period warning |
| `screening_passed` | Server -> Client | `{}` | Confirm screening passed, proceed |

### Extending GameCallback

```python
class GameCallback:
    # ... existing methods ...

    def on_pre_exclusion_check(self, subject_id: str, context: dict) -> dict:
        """
        Hook called before exclusion rules are evaluated.
        Can modify context to add custom data for rules.

        Returns:
            Modified context dict
        """
        return context

    def on_exclusion(
        self,
        subject_id: str,
        result: ExclusionResult,
        remote_game: RemoteGame | None
    ):
        """
        Hook called when a participant is excluded.
        Can perform custom logging, data export, etc.
        """
        pass

    def on_exclusion_warning(
        self,
        subject_id: str,
        result: ExclusionResult,
        grace_remaining_ms: int
    ):
        """
        Hook called when a grace period warning is issued.
        """
        pass
```

## Suggested Build Order

Based on dependencies and incremental value delivery:

### Phase 1: Core Rule Infrastructure (Server-Side)

**Files to create/modify:**
- `interactive_gym/configurations/exclusion_rules.py` (new)
- `interactive_gym/scenes/gym_scene.py` (add `.exclusion()` method)

**What to build:**
1. `ExclusionRule` base class
2. `ExclusionResult` dataclass
3. `ExclusionManager` class
4. Built-in rules: `PingThreshold`
5. `GymScene.exclusion()` configuration method

**Why first:** Foundation for everything else. No external dependencies.

### Phase 2: Pre-Game Exclusion (Client + Server)

**Files to modify:**
- `interactive_gym/server/app.py` (new SocketIO events)
- `interactive_gym/server/game_manager.py` (pre-game check)
- `interactive_gym/server/static/js/index.js` (screening data collection)

**What to build:**
1. `pre_game_screening` event handler
2. Pre-game check in `add_subject_to_game()`
3. Client-side screening data collection
4. `excluded` event emission and handling
5. Basic exclusion UI on client

**Why second:** High value, blocks bad participants before they start.

### Phase 3: Built-in Rule Set

**Files to modify:**
- `interactive_gym/configurations/exclusion_rules.py`

**What to build:**
1. `BrowserExclusion` rule
2. `FocusRequirement` rule
3. `MobileExclusion` rule (detect mobile devices)
4. `CustomCallback` wrapper

**Why third:** Adds immediate utility with common exclusion scenarios.

### Phase 4: Continuous Monitoring

**Files to modify:**
- `interactive_gym/server/app.py`
- `interactive_gym/server/game_manager.py`
- `interactive_gym/server/static/js/index.js`

**What to build:**
1. `exclusion_metrics` periodic reporting from client
2. Continuous rule evaluation on server
3. Grace period warning system
4. Mid-game exclusion handling

**Why fourth:** More complex, builds on pre-game foundation.

### Phase 5: Multiplayer Handling

**Files to modify:**
- `interactive_gym/server/game_manager.py`
- `interactive_gym/server/pyodide_game_coordinator.py`

**What to build:**
1. `on_exclude_multiplayer` behavior options
2. Room-level exclusion notifications
3. Clean game termination for all players
4. WebRTC disconnect handling on exclusion

**Why fifth:** Requires understanding of multiplayer state management.

### Phase 6: Callback Integration & Logging

**Files to modify:**
- `interactive_gym/server/callback.py`
- Data logging infrastructure

**What to build:**
1. `on_pre_exclusion_check` hook
2. `on_exclusion` hook
3. `on_exclusion_warning` hook
4. Exclusion event logging to data files

**Why sixth:** Polish phase, adds extensibility for researchers.

## Patterns to Consider

### Strategy Pattern
Each exclusion rule is a strategy with a common interface. Allows:
- Easy addition of new rules
- Rules can be tested in isolation
- Configuration via composition

### Chain of Responsibility
Rules are evaluated in sequence, stopping at first exclusion (or collecting all). Allows:
- Short-circuit on first failure (performance)
- Configurable rule ordering
- Collect all violations for comprehensive feedback

### Observer Pattern (for callbacks)
Existing `GameCallback` already uses this. Extend for exclusion events:
- Researchers can add custom logging
- UI components can react to exclusion events
- Decouples core logic from extensions

### Middleware Pattern (alternative consideration)
Similar to Django/Express middleware. Each rule can:
- Pass to next rule
- Reject with response
- Modify context for subsequent rules

This is more powerful but more complex. **Recommendation: Start with simpler Chain of Responsibility, consider middleware if more flexibility needed later.**

### Factory Pattern (for rule instantiation)
If rules are loaded from configuration files (JSON/YAML):

```python
class ExclusionRuleFactory:
    _rules = {
        "ping_threshold": PingThreshold,
        "browser_exclusion": BrowserExclusion,
        # ...
    }

    @classmethod
    def create(cls, rule_type: str, **kwargs) -> ExclusionRule:
        return cls._rules[rule_type](**kwargs)
```

**Recommendation: Not needed initially if rules are defined in Python config. Add if JSON config is desired later.**

## Security Considerations

1. **Never trust client-only exclusion**: All decisions must be validated server-side.

2. **Rate limit metrics reporting**: Prevent DoS via excessive `exclusion_metrics` events.

3. **Validate metric values**: Client could send fake ping values. Consider server-measured RTT as ground truth.

4. **Log exclusion attempts**: For audit trail and detecting manipulation attempts.

5. **Secure redirect URLs**: Validate redirect URLs to prevent open redirect vulnerabilities.

## Sources

- [Rules Engine Design Pattern - Nected](https://www.nected.ai/us/blog-us/rules-engine-design-pattern)
- [Chain of Responsibility Pattern - Refactoring Guru](https://refactoring.guru/design-patterns/chain-of-responsibility)
- [Input Validation Cheat Sheet - OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html)
- [Client-Side vs Server-Side Validation - PacketLabs](https://www.packetlabs.net/posts/input-validation/)
- [Browser Detection Using User Agent - MDN](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Browser_detection_using_the_user_agent)
- [Feature Detection - MDN](https://developer.mozilla.org/en-US/docs/Learn_web_development/Extensions/Testing/Feature_detection)
- [WebRTC Latency Monitoring - VideoSDK](https://www.videosdk.live/developer-hub/webrtc/webrtc-latency)
- [Chain of Responsibility in Python - Medium](https://medium.com/@amirm.lavasani/design-patterns-in-python-chain-of-responsibility-cc22bb241b41)
