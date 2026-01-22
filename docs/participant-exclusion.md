# Participant Exclusion API

## Overview

Interactive Gym provides a configurable, extensible system to exclude participants who don't meet experiment requirements. Exclusion checks happen both at entry (before the game starts) and continuously during gameplay.

This system enables researchers to:
- Filter participants by device type, browser, or connection quality
- Monitor participants during gameplay for connection issues or tab switching
- Define custom exclusion logic via Python callbacks
- Handle multiplayer scenarios gracefully when one player is excluded

---

## Quick Start

All exclusion configuration uses fluent method chaining on `GymScene`:

```python
from interactive_gym.scenes import GymScene

scene = GymScene(
    scene_id="my_experiment",
    experiment_id="exp_001",
    ...
).entry_screening(
    device_exclusion="mobile",
    max_ping=150
).continuous_monitoring(
    max_ping=200,
    tab_exclude_ms=10000
)
```

---

## Entry Screening

Pre-game checks that run before the participant can start. Use `entry_screening()` to configure.

### Method Signature

```python
def entry_screening(
    self,
    device_exclusion: str = None,           # "mobile", "desktop", or None
    browser_requirements: list[str] = None,  # Allowlist of browsers
    browser_blocklist: list[str] = None,     # Blocklist (takes precedence)
    max_ping: int = None,                    # Maximum latency in milliseconds
    min_ping_measurements: int = 3,          # Samples before checking ping
    exclusion_messages: dict[str, str] = None,  # Custom messages per rule
) -> GymScene
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `device_exclusion` | `str` | `None` | `"mobile"` excludes phones/tablets, `"desktop"` excludes desktops |
| `browser_requirements` | `list[str]` | `None` | Allowlist of browsers (e.g., `["Chrome", "Firefox"]`) |
| `browser_blocklist` | `list[str]` | `None` | Blocklist of browsers (takes precedence over allowlist) |
| `max_ping` | `int` | `None` | Maximum allowed latency in milliseconds |
| `min_ping_measurements` | `int` | `3` | Number of ping samples before enforcing threshold |
| `exclusion_messages` | `dict` | See below | Custom messages for each exclusion rule |

### Default Exclusion Messages

```python
{
    "mobile": "This experiment requires a desktop or laptop computer. Please return on a non-mobile device.",
    "desktop": "This experiment requires a mobile device. Please return on a phone or tablet.",
    "browser": "Your browser is not supported. Please use one of the following browsers: {browsers}",
    "ping": "Your connection latency is too high for this experiment. Please try again with a faster connection."
}
```

### Example

```python
scene.entry_screening(
    device_exclusion="mobile",
    browser_blocklist=["Safari"],  # Safari has WebRTC issues
    max_ping=150,
    min_ping_measurements=5,
    exclusion_messages={
        "mobile": "Please use a desktop computer for this study.",
        "browser": "Safari is not supported. Please use Chrome or Firefox.",
        "ping": "Your internet connection is too slow for real-time gameplay."
    }
)
```

---

## Continuous Monitoring

Real-time checks during gameplay. Use `continuous_monitoring()` to configure.

### Method Signature

```python
def continuous_monitoring(
    self,
    max_ping: int = None,                    # Exclude if ping exceeds this
    ping_violation_window: int = 5,          # Rolling window size
    ping_required_violations: int = 3,       # Violations needed in window
    tab_warning_ms: int = 3000,              # Warn after this duration hidden
    tab_exclude_ms: int = 10000,             # Exclude after this duration hidden
    exclusion_messages: dict[str, str] = None,  # Custom messages
) -> GymScene
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_ping` | `int` | `None` | Exclude if latency exceeds this threshold |
| `ping_violation_window` | `int` | `5` | Size of rolling window for ping checks |
| `ping_required_violations` | `int` | `3` | Number of violations in window to trigger exclusion |
| `tab_warning_ms` | `int` | `3000` | Show warning after tab hidden for this duration (ms) |
| `tab_exclude_ms` | `int` | `10000` | Exclude after tab hidden for this duration (ms) |
| `exclusion_messages` | `dict` | See below | Custom messages for monitoring events |

### Rolling Window Logic

The ping check uses a rolling window to prevent false positives from temporary spikes:
- Window tracks the last N ping measurements (default: 5)
- Exclusion triggers only if M of N measurements exceed threshold (default: 3 of 5)
- This prevents exclusion from a single network hiccup

### Default Exclusion Messages

```python
{
    "ping": "Your connection became unstable during the experiment.",
    "tab_warning": "Please return to the experiment window.",
    "tab_exclude": "You were away from the experiment for too long."
}
```

### Example

```python
scene.continuous_monitoring(
    max_ping=200,
    ping_violation_window=5,
    ping_required_violations=3,  # 3 of 5 must violate
    tab_warning_ms=3000,         # Warn after 3 seconds
    tab_exclude_ms=10000,        # Exclude after 10 seconds
    exclusion_messages={
        "ping": "Your connection dropped below acceptable quality.",
        "tab_warning": "Please keep this window focused!",
        "tab_exclude": "The experiment ended because you left the window."
    }
)
```

---

## Custom Exclusion Callbacks

For arbitrary exclusion logic, use Python callbacks. Use `exclusion_callbacks()` to configure.

### Method Signature

```python
def exclusion_callbacks(
    self,
    entry_callback: Callable[[dict], dict] = None,
    continuous_callback: Callable[[dict], dict] = None,
    continuous_callback_interval_frames: int = 30,
) -> GymScene
```

### Entry Callback

Called once before the game starts, after built-in entry screening passes.

**Input Context:**
```python
{
    "ping": float,              # Current latency in ms
    "browser_name": str,        # e.g., "Chrome"
    "browser_version": str,     # e.g., "120.0.0"
    "device_type": str,         # "desktop", "mobile", or "tablet"
    "os_name": str,             # e.g., "Windows", "macOS"
    "subject_id": str,          # Participant identifier
    "scene_id": str             # Current scene identifier
}
```

**Return Value:**
```python
{
    "exclude": bool,            # True to exclude participant
    "message": str | None       # Optional custom message
}
```

**Example:**
```python
def my_entry_check(context: dict) -> dict:
    # Stricter ping requirement for Safari users
    if context["browser_name"] == "Safari" and context["ping"] > 100:
        return {
            "exclude": True,
            "message": "Safari users need a connection under 100ms latency."
        }
    return {"exclude": False, "message": None}

scene.exclusion_callbacks(entry_callback=my_entry_check)
```

### Continuous Callback

Called periodically during gameplay (default: every 30 frames, ~1 second at 30 FPS).

**Input Context:**
```python
{
    "ping": float,                  # Current latency in ms
    "is_tab_hidden": bool,          # Whether tab is currently hidden
    "tab_hidden_duration_ms": int,  # How long tab has been hidden
    "frame_number": int,            # Current game frame
    "episode_number": int,          # Current episode (0-indexed)
    "subject_id": str,              # Participant identifier
    "scene_id": str                 # Current scene identifier
}
```

**Return Value:**
```python
{
    "exclude": bool,            # True to exclude participant
    "warn": bool,               # True to show warning (no exclusion)
    "message": str | None       # Optional custom message
}
```

**Example:**
```python
def my_continuous_check(context: dict) -> dict:
    # More lenient in early episodes, stricter later
    threshold = 150 if context["episode_number"] < 5 else 100

    if context["ping"] > threshold:
        if context["episode_number"] < 5:
            return {
                "exclude": False,
                "warn": True,
                "message": f"Connection quality is degrading (ping: {context['ping']:.0f}ms)"
            }
        else:
            return {
                "exclude": True,
                "warn": False,
                "message": "Connection too unstable for later episodes."
            }

    return {"exclude": False, "warn": False, "message": None}

scene.exclusion_callbacks(
    continuous_callback=my_continuous_check,
    continuous_callback_interval_frames=30  # Check every ~1 second
)
```

### Error Handling

Callbacks are executed server-side and **fail open** (allow entry/continue) if:
- The callback raises an exception
- The callback times out (5 seconds for entry callbacks)
- The callback returns an invalid response

This prevents researcher code bugs from blocking all participants.

---

## Multiplayer Behavior

When one player is excluded mid-game in a multiplayer session:

1. **Partner Notification**: The non-excluded player sees a neutral message:
   > "Your partner experienced a technical issue. The game has ended."

2. **Clean Termination**: Both players' game loops stop gracefully

3. **Data Preservation**: All valid game data up to the exclusion point is preserved

4. **Session Marking**: The session is marked as partial with metadata:
   ```python
   {
       "isPartial": True,
       "terminationReason": "partner_exclusion",  # or "self_exclusion"
       "terminationFrame": 1234,
       "completedEpisodes": 5
   }
   ```

This ensures researchers can identify and handle partial sessions in their analysis.

---

## Complete Example

```python
from interactive_gym.scenes import GymScene

def custom_entry_check(context: dict) -> dict:
    """Require fast connections for Safari users."""
    if context["browser_name"] == "Safari" and context["ping"] > 80:
        return {
            "exclude": True,
            "message": "Safari requires a faster connection. Please use Chrome."
        }
    return {"exclude": False, "message": None}

def custom_continuous_check(context: dict) -> dict:
    """Progressive strictness based on episode."""
    if context["episode_number"] >= 10 and context["ping"] > 120:
        return {
            "exclude": True,
            "warn": False,
            "message": "Connection unstable in critical phase."
        }
    return {"exclude": False, "warn": False, "message": None}

scene = GymScene(
    scene_id="my_multiplayer_experiment",
    experiment_id="exp_001",
    # ... other config ...
).entry_screening(
    device_exclusion="mobile",
    browser_blocklist=["Safari"],
    max_ping=150,
    min_ping_measurements=3,
    exclusion_messages={
        "mobile": "Desktop required for this study.",
        "ping": "Connection too slow for real-time play."
    }
).continuous_monitoring(
    max_ping=200,
    ping_violation_window=5,
    ping_required_violations=3,
    tab_warning_ms=3000,
    tab_exclude_ms=10000
).exclusion_callbacks(
    entry_callback=custom_entry_check,
    continuous_callback=custom_continuous_check,
    continuous_callback_interval_frames=30
)
```

---

## Best Practices

1. **Be lenient at entry, strict during play**: Use generous entry thresholds to avoid false rejections, then monitor more strictly during gameplay.

2. **Use rolling windows for ping**: Single ping spikes are common; require sustained violations before excluding.

3. **Provide clear messages**: Participants should understand why they were excluded and what they can do (use different browser, faster connection, etc.).

4. **Test on real networks**: Entry and continuous thresholds that work on localhost may be too strict for real-world conditions.

5. **Handle partial sessions**: Design your analysis pipeline to identify and appropriately handle sessions marked as partial.

6. **Fail open in callbacks**: Custom callbacks should return `{"exclude": False, ...}` for unexpected conditions rather than crashing.

---

*Documentation for Interactive Gym v1.2*
