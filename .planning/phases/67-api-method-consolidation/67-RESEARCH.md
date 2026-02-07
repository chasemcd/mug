# Phase 67: API Method Consolidation - Research

**Researched:** 2026-02-07
**Domain:** Python builder-pattern API refactoring (GymScene class)
**Confidence:** HIGH

## Summary

This phase is a pure API surface refactoring of the `GymScene` class in `interactive_gym/scenes/gym_scene.py`. The class currently has 12 builder methods (including a deprecated alias) that need to be reorganized into a cleaner grouping. The refactoring involves renaming (`pyodide` -> `runtime`), splitting (`user_experience` -> `content` + `waitroom`, `rendering` -> `rendering` + `assets`), and merging (7 multiplayer-related methods + sync params -> single `multiplayer`).

The codebase uses a consistent builder pattern where every method accepts `NotProvided` sentinels as defaults, conditionally sets attributes only when values are provided, and returns `self` for chaining. The underlying instance attributes on `GymScene.__init__` do NOT change -- only the builder method signatures and groupings change. The server code reads attributes directly from `scene.*` (e.g., `scene.run_through_pyodide`, `scene.waitroom_timeout`), so attribute names must remain identical.

**Primary recommendation:** Add the new methods alongside old ones first (Phase 67), then remove old methods in Phase 68. This phase should NOT delete old methods -- it only adds new ones. All attribute names on the instance must remain unchanged since server code references them by name.

## Standard Stack

### Core

This is purely internal Python refactoring. No external libraries needed.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib | 3.10+ | Class definition, typing | Already in use |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `interactive_gym.scenes.utils.NotProvided` | internal | Sentinel for "not provided" args | Every builder method uses this pattern |

**No new dependencies required.** This is a method reorganization within a single file.

## Architecture Patterns

### Current Class Structure

```
interactive_gym/scenes/gym_scene.py  (1023 lines)
  class GymScene(Scene):
    __init__()          - 210 lines, initializes ~60 instance attributes
    environment()       - builder: env_creator, env_config, seed
    rendering()         - builder: 14 params (fps, env_to_state_fn, preload_specs, etc.)
    policies()          - builder: 4 params (policy_mapping, load_policy_fn, etc.)
    gameplay()          - builder: 9 params (action_mapping, human_id, etc.)
    user_experience()   - builder: 10 params (scene_header, waitroom_timeout, etc.)
    matchmaking()       - builder: 3 params (hide_lobby_count, max_rtt, matchmaker)
    pyodide()           - builder: 12 params (run_through_pyodide, multiplayer, server_authoritative, etc.)
    player_grouping()   - builder: 2 params (wait_for_known_group, group_wait_timeout)
    continuous_monitoring() - builder: 6 params (max_ping, ping settings, tab settings)
    exclusion_callbacks()   - builder: 2 params (continuous_callback, interval)
    reconnection_config()   - builder: 1 param (timeout_ms)
    partner_disconnect_message_config() - builder: 2 params (message, show_completion_code)
    focus_loss_config()     - builder: 3 params (timeout_ms, message, pause_on_partner_background)
    player_pairing()    - DEPRECATED alias -> player_grouping()
    simulate_waiting_room (property)
    get_complete_scene_metadata()
```

### New Method Structure (Target)

```
class GymScene(Scene):
    # UNCHANGED methods:
    environment()       - no changes (APIC-06 doesn't mention it, but it's not in scope)
    policies()          - no changes (APIC-06)
    gameplay()          - no changes (APIC-06)

    # RENAMED:
    runtime()           - replaces pyodide() with ONLY browser execution params:
                          run_through_pyodide, environment_initialization_code,
                          environment_initialization_code_filepath, on_game_step_code,
                          packages_to_install, restart_pyodide

    # NEW (merged from pyodide sync params + 7 methods):
    multiplayer()       - ALL multiplayer params from:
                          - pyodide() sync params: multiplayer, server_authoritative,
                            state_broadcast_interval, realtime_mode, input_buffer_size,
                            input_delay, input_confirmation_timeout_ms
                          - matchmaking(): hide_lobby_count, max_rtt, matchmaker
                          - player_grouping(): wait_for_known_group, group_wait_timeout
                          - continuous_monitoring(): 6 params
                          - exclusion_callbacks(): 2 params
                          - reconnection_config(): timeout_ms
                          - partner_disconnect_message_config(): 2 params
                          - focus_loss_config(): 3 params
                          Total: ~24 params

    # SPLIT from user_experience():
    content()           - scene_header, scene_body, scene_body_filepath,
                          in_game_scene_body, in_game_scene_body_filepath,
                          game_page_html_fn
    waitroom()          - waitroom_timeout, waitroom_timeout_redirect_url,
                          waitroom_timeout_scene_id, waitroom_timeout_message

    # SPLIT from rendering():
    rendering()         - fps, env_to_state_fn, hud_text_fn, hud_score_carry_over,
                          location_representation, game_width, game_height,
                          background, rollback_smoothing_duration
    assets()            - preload_specs, assets_dir, assets_to_preload,
                          animation_configs, state_init
```

### Pattern: NotProvided Sentinel Builder Method

Every builder method follows this exact pattern:

```python
def method_name(
    self,
    param1: type = NotProvided,
    param2: type = NotProvided,
):
    """Docstring."""
    if param1 is not NotProvided:
        self.param1 = param1

    if param2 is not NotProvided:
        self.param2 = param2

    return self
```

Key points:
- Default is always `NotProvided` (from `interactive_gym.scenes.utils`)
- Check is always `is not NotProvided` (identity check)
- Method always returns `self`
- Some methods have validation (assert, raise ValueError)
- Some methods handle filepath alternatives (read file and store content)

### Anti-Patterns to Avoid

- **Renaming instance attributes:** Server code references `scene.run_through_pyodide`, `scene.pyodide_multiplayer`, `scene.waitroom_timeout`, etc. by attribute name. Changing attribute names would break server code. Only builder method signatures change.
- **Breaking the chaining pattern:** Every builder method MUST return `self`.
- **Changing default values:** The defaults in `__init__` must remain identical. Only the method grouping changes.
- **Forgetting `in_game_scene_body`:** This attribute is NOT initialized in `__init__` but is set dynamically in `user_experience()`. The new `content()` method must handle this correctly. It should be initialized in `__init__` for consistency (add `self.in_game_scene_body: str = None`).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Parameter sentinel values | Custom None-check logic | Existing `NotProvided` singleton | Already established in codebase, identity-based check |
| Method chaining | Custom return pattern | Existing `return self` pattern | Consistency with all existing methods |

## Common Pitfalls

### Pitfall 1: Missing the `in_game_scene_body` attribute

**What goes wrong:** `in_game_scene_body` is NOT declared in `GymScene.__init__()` but IS set in `user_experience()`. The new `content()` method must handle this.
**Why it happens:** It was added to `user_experience()` without updating `__init__`.
**How to avoid:** Add `self.in_game_scene_body: str = None` to `__init__` and ensure `content()` handles both `in_game_scene_body` and `in_game_scene_body_filepath` params.
**Warning signs:** AttributeError when accessing `scene.in_game_scene_body` on scenes that never called `content()`.

### Pitfall 2: Server attribute reference breakage

**What goes wrong:** Server code accesses attributes by name (e.g., `scene.pyodide_multiplayer`, `scene.wait_for_known_group`, `scene.matchmaking_max_rtt`). Renaming these breaks runtime.
**Why it happens:** Conflating "method name change" with "attribute name change."
**How to avoid:** ONLY change builder method signatures and parameter names. ALL instance attribute names must remain identical in `__init__`.
**Warning signs:** The `multiplayer()` builder method's parameter `multiplayer=` sets `self.pyodide_multiplayer` (not `self.multiplayer`). This mapping must be preserved.

Key server references to verify are preserved:
- `scene.run_through_pyodide` (game_manager.py, remote_game.py, admin/aggregator.py)
- `scene.pyodide_multiplayer` (game_manager.py)
- `scene.server_authoritative` (game_manager.py)
- `scene.state_broadcast_interval` (game_manager.py)
- `scene.realtime_mode` (game_manager.py)
- `scene.input_buffer_size` (game_manager.py)
- `scene.environment_initialization_code` (game_manager.py)
- `scene.wait_for_known_group` (game_manager.py)
- `scene.matchmaking_max_rtt` (game_manager.py)
- `scene.hide_lobby_count` (game_manager.py)
- `scene.waitroom_timeout` (game_manager.py)
- `scene.waitroom_timeout_message` (game_manager.py)
- `scene.game_page_html_fn` (game_manager.py)
- `scene.continuous_exclusion_callback` (app.py)
- `scene._matchmaker` / `scene.matchmaker` property (game_manager.py)

### Pitfall 3: Multiplayer method parameter explosion

**What goes wrong:** The `multiplayer()` method will have ~24 parameters, which is unwieldy.
**Why it happens:** Merging 7 methods + sync params into one.
**How to avoid:** This is by design per requirements (APIC-02, APIC-03). SIMP-01 in v2 requirements explicitly defers splitting this method. Group parameters logically in the docstring with sections. Accept the large signature for now.
**Warning signs:** N/A - this is expected.

### Pitfall 4: matchmaker property

**What goes wrong:** GymScene has a `@property matchmaker` that returns `self._matchmaker`. This must be preserved.
**Why it happens:** The matchmaker param is stored as `_matchmaker` (private) but accessed via the `matchmaker` property.
**How to avoid:** Ensure `multiplayer()` method's `matchmaker=` parameter still sets `self._matchmaker` and the `@property matchmaker` is preserved.

### Pitfall 5: continuous_monitoring side effect

**What goes wrong:** The `continuous_monitoring()` method sets `self.continuous_monitoring_enabled = True` as a side effect before processing params.
**Why it happens:** Calling the method at all implies enabling monitoring.
**How to avoid:** In `multiplayer()`, only set `continuous_monitoring_enabled = True` when monitoring-related params are actually provided. Or replicate the current behavior by checking if any monitoring params were passed.

### Pitfall 6: Validation logic in existing methods

**What goes wrong:** Several methods have validation that must be preserved:
- `matchmaking()`: `max_rtt > 0` check, `isinstance(matchmaker, Matchmaker)` check with runtime import
- `continuous_monitoring()`: `required_violations <= window` cross-validation
- `reconnection_config()`: `timeout_ms > 0`
- `exclusion_callbacks()`: `callable()` check
- `focus_loss_config()`: `timeout_ms >= 0`
- `rendering()`: `location_representation in ["relative", "pixels"]`
- `rendering()`: `rollback_smoothing_duration >= 0`
**How to avoid:** Copy all validation logic exactly into the new methods.

### Pitfall 7: Deep copy behavior

**What goes wrong:** Examples use `copy.deepcopy(scene)` to create variants (e.g., `counter_circuit_human_human = copy.deepcopy(cramped_room_human_human)`). Then call builder methods on the copy to override specific settings.
**Why it happens:** This is the established pattern for creating scene variants.
**How to avoid:** Ensure new methods work correctly on deep-copied scenes. No special handling needed since the pattern is the same, but be aware this exists.

## Code Examples

### New `runtime()` method (replaces `pyodide()` for browser execution params only)

```python
def runtime(
    self,
    run_through_pyodide: bool = NotProvided,
    environment_initialization_code: str = NotProvided,
    environment_initialization_code_filepath: str = NotProvided,
    on_game_step_code: str = NotProvided,
    packages_to_install: list[str] = NotProvided,
    restart_pyodide: bool = NotProvided,
):
    """Configure browser runtime (Pyodide) settings."""
    if run_through_pyodide is not NotProvided:
        assert isinstance(run_through_pyodide, bool)
        self.run_through_pyodide = run_through_pyodide

    if environment_initialization_code is not NotProvided:
        self.environment_initialization_code = environment_initialization_code

    if environment_initialization_code_filepath is not NotProvided:
        assert environment_initialization_code is NotProvided, \
            "Cannot set both filepath and code!"
        with open(environment_initialization_code_filepath, "r", encoding="utf-8") as f:
            self.environment_initialization_code = f.read()

    if packages_to_install is not NotProvided:
        self.packages_to_install = packages_to_install
        if not any("interactive-gym" in pkg for pkg in packages_to_install):
            self.packages_to_install.append(self.DEFAULT_IG_PACKAGE)

    if restart_pyodide is not NotProvided:
        self.restart_pyodide = restart_pyodide

    if on_game_step_code is not NotProvided:
        self.on_game_step_code = on_game_step_code

    return self
```

### New `multiplayer()` method (merged from sync params + 7 methods)

```python
def multiplayer(
    self,
    # Sync/rollback params (from pyodide)
    multiplayer: bool = NotProvided,
    server_authoritative: bool = NotProvided,
    state_broadcast_interval: int = NotProvided,
    realtime_mode: bool = NotProvided,
    input_buffer_size: int = NotProvided,
    input_delay: int = NotProvided,
    input_confirmation_timeout_ms: int = NotProvided,
    # Matchmaking params (from matchmaking)
    hide_lobby_count: bool = NotProvided,
    max_rtt: int = NotProvided,
    matchmaker: "Matchmaker" = NotProvided,
    # Player grouping params (from player_grouping)
    wait_for_known_group: bool = NotProvided,
    group_wait_timeout: int = NotProvided,
    # Continuous monitoring params (from continuous_monitoring)
    continuous_max_ping: int = NotProvided,
    continuous_ping_violation_window: int = NotProvided,
    continuous_ping_required_violations: int = NotProvided,
    continuous_tab_warning_ms: int = NotProvided,
    continuous_tab_exclude_ms: int = NotProvided,
    continuous_exclusion_messages: dict[str, str] = NotProvided,
    # Exclusion callback params (from exclusion_callbacks)
    continuous_callback: Callable = NotProvided,
    continuous_callback_interval_frames: int = NotProvided,
    # Reconnection params (from reconnection_config)
    reconnection_timeout_ms: int = NotProvided,
    # Partner disconnect params (from partner_disconnect_message_config)
    partner_disconnect_message: str = NotProvided,
    partner_disconnect_show_completion_code: bool = NotProvided,
    # Focus loss params (from focus_loss_config)
    focus_loss_timeout_ms: int = NotProvided,
    focus_loss_message: str = NotProvided,
    pause_on_partner_background: bool = NotProvided,
):
    """Configure all multiplayer settings."""
    # ... validation and assignment for each param ...
    return self
```

Note: The parameter names in the method signature should match what callers pass, but the instance attributes they set may differ. For example:
- `multiplayer=True` sets `self.pyodide_multiplayer = True`
- `max_rtt=50` sets `self.matchmaking_max_rtt = 50`
- `reconnection_timeout_ms=5000` sets `self.reconnection_timeout_ms = 5000`

### New `content()` method (split from `user_experience()`)

```python
def content(
    self,
    scene_header: str = NotProvided,
    scene_body: str = NotProvided,
    scene_body_filepath: str = NotProvided,
    in_game_scene_body: str = NotProvided,
    in_game_scene_body_filepath: str = NotProvided,
    game_page_html_fn: Callable = NotProvided,
):
    """Configure scene content display."""
    # ... existing logic from user_experience for these params ...
    return self
```

### New `waitroom()` method (split from `user_experience()`)

```python
def waitroom(
    self,
    timeout: int = NotProvided,
    timeout_redirect_url: str = NotProvided,
    timeout_scene_id: str = NotProvided,
    timeout_message: str = NotProvided,
):
    """Configure waitroom behavior."""
    if timeout is not NotProvided:
        self.waitroom_timeout = timeout
    if timeout_redirect_url is not NotProvided:
        self.waitroom_timeout_redirect_url = timeout_redirect_url
    if timeout_scene_id is not NotProvided:
        self.waitroom_timeout_scene_id = timeout_scene_id
    if timeout_message is not NotProvided:
        self.waitroom_timeout_message = timeout_message
    return self
```

Note: The `waitroom()` method parameter names are shortened (e.g., `timeout` instead of `waitroom_timeout`) since the method name provides context. But the instance attributes remain `self.waitroom_timeout`, `self.waitroom_timeout_redirect_url`, etc.

### New `assets()` method (split from `rendering()`)

```python
def assets(
    self,
    preload_specs: list[dict[str, str | float | int]] = NotProvided,
    assets_dir: str = NotProvided,
    assets_to_preload: list[str] = NotProvided,
    animation_configs: list = NotProvided,
    state_init: list = NotProvided,
):
    """Configure asset loading."""
    if preload_specs is not NotProvided:
        self.preload_specs = preload_specs
    if assets_dir is not NotProvided:
        self.assets_dir = assets_dir
    if assets_to_preload is not NotProvided:
        self.assets_to_preload = assets_to_preload
    if animation_configs is not NotProvided:
        self.animation_configs = animation_configs
    if state_init is not NotProvided:
        self.state_init = state_init
    return self
```

### Updated `rendering()` method (reduced params)

```python
def rendering(
    self,
    fps: int = NotProvided,
    env_to_state_fn: Callable = NotProvided,
    hud_text_fn: Callable = NotProvided,
    hud_score_carry_over: bool = NotProvided,
    location_representation: str = NotProvided,
    game_width: int = NotProvided,
    game_height: int = NotProvided,
    background: str = NotProvided,
    rollback_smoothing_duration: int | None = NotProvided,
):
    """Configure rendering display settings."""
    # ... same validation logic as before for these params ...
    return self
```

## Detailed Parameter Mapping

### pyodide() -> runtime() + multiplayer()

| Old `pyodide()` param | New method | New param name | Instance attribute |
|---|---|---|---|
| `run_through_pyodide` | `runtime()` | `run_through_pyodide` | `self.run_through_pyodide` |
| `environment_initialization_code` | `runtime()` | `environment_initialization_code` | `self.environment_initialization_code` |
| `environment_initialization_code_filepath` | `runtime()` | `environment_initialization_code_filepath` | `self.environment_initialization_code` (via file read) |
| `on_game_step_code` | `runtime()` | `on_game_step_code` | `self.on_game_step_code` |
| `packages_to_install` | `runtime()` | `packages_to_install` | `self.packages_to_install` |
| `restart_pyodide` | `runtime()` | `restart_pyodide` | `self.restart_pyodide` |
| `multiplayer` | `multiplayer()` | `multiplayer` | `self.pyodide_multiplayer` |
| `server_authoritative` | `multiplayer()` | `server_authoritative` | `self.server_authoritative` |
| `state_broadcast_interval` | `multiplayer()` | `state_broadcast_interval` | `self.state_broadcast_interval` |
| `realtime_mode` | `multiplayer()` | `realtime_mode` | `self.realtime_mode` |
| `input_buffer_size` | `multiplayer()` | `input_buffer_size` | `self.input_buffer_size` |
| `input_delay` | `multiplayer()` | `input_delay` | `self.input_delay` |
| `input_confirmation_timeout_ms` | `multiplayer()` | `input_confirmation_timeout_ms` | `self.input_confirmation_timeout_ms` |

### user_experience() -> content() + waitroom()

| Old `user_experience()` param | New method | New param name | Instance attribute |
|---|---|---|---|
| `scene_header` | `content()` | `scene_header` | `self.scene_header` |
| `scene_body` | `content()` | `scene_body` | `self.scene_body` |
| `scene_body_filepath` | `content()` | `scene_body_filepath` | `self.scene_body` (via file read) |
| `in_game_scene_body` | `content()` | `in_game_scene_body` | `self.in_game_scene_body` |
| `in_game_scene_body_filepath` | `content()` | `in_game_scene_body_filepath` | `self.in_game_scene_body` (via file read) |
| `game_page_html_fn` | `content()` | `game_page_html_fn` | `self.game_page_html_fn` |
| `waitroom_timeout` | `waitroom()` | `timeout` | `self.waitroom_timeout` |
| `waitroom_timeout_redirect_url` | `waitroom()` | `timeout_redirect_url` | `self.waitroom_timeout_redirect_url` |
| `waitroom_timeout_scene_id` | `waitroom()` | `timeout_scene_id` | `self.waitroom_timeout_scene_id` |
| `waitroom_timeout_message` | `waitroom()` | `timeout_message` | `self.waitroom_timeout_message` |

### rendering() -> rendering() + assets()

| Old `rendering()` param | New method | New param name | Instance attribute |
|---|---|---|---|
| `fps` | `rendering()` | `fps` | `self.fps` |
| `env_to_state_fn` | `rendering()` | `env_to_state_fn` | `self.env_to_state_fn` |
| `hud_text_fn` | `rendering()` | `hud_text_fn` | `self.hud_text_fn` |
| `hud_score_carry_over` | `rendering()` | `hud_score_carry_over` | `self.hud_score_carry_over` |
| `location_representation` | `rendering()` | `location_representation` | `self.location_representation` |
| `game_width` | `rendering()` | `game_width` | `self.game_width` |
| `game_height` | `rendering()` | `game_height` | `self.game_height` |
| `background` | `rendering()` | `background` | `self.background` |
| `rollback_smoothing_duration` | `rendering()` | `rollback_smoothing_duration` | `self.rollback_smoothing_duration` |
| `preload_specs` | `assets()` | `preload_specs` | `self.preload_specs` |
| `assets_dir` | `assets()` | `assets_dir` | `self.assets_dir` |
| `assets_to_preload` | `assets()` | `assets_to_preload` | `self.assets_to_preload` |
| `animation_configs` | `assets()` | `animation_configs` | `self.animation_configs` |
| `state_init` | `assets()` | `state_init` | `self.state_init` |

### Merged methods -> multiplayer()

| Old method | Old params | `multiplayer()` param name | Instance attribute |
|---|---|---|---|
| `matchmaking()` | `hide_lobby_count` | `hide_lobby_count` | `self.hide_lobby_count` |
| `matchmaking()` | `max_rtt` | `max_rtt` | `self.matchmaking_max_rtt` |
| `matchmaking()` | `matchmaker` | `matchmaker` | `self._matchmaker` |
| `player_grouping()` | `wait_for_known_group` | `wait_for_known_group` | `self.wait_for_known_group` |
| `player_grouping()` | `group_wait_timeout` | `group_wait_timeout` | `self.group_wait_timeout` |
| `continuous_monitoring()` | `max_ping` | `continuous_max_ping` | `self.continuous_max_ping` |
| `continuous_monitoring()` | `ping_violation_window` | `continuous_ping_violation_window` | `self.continuous_ping_violation_window` |
| `continuous_monitoring()` | `ping_required_violations` | `continuous_ping_required_violations` | `self.continuous_ping_required_violations` |
| `continuous_monitoring()` | `tab_warning_ms` | `continuous_tab_warning_ms` | `self.continuous_tab_warning_ms` |
| `continuous_monitoring()` | `tab_exclude_ms` | `continuous_tab_exclude_ms` | `self.continuous_tab_exclude_ms` |
| `continuous_monitoring()` | `exclusion_messages` | `continuous_exclusion_messages` | `self.continuous_exclusion_messages` |
| `exclusion_callbacks()` | `continuous_callback` | `continuous_callback` | `self.continuous_exclusion_callback` |
| `exclusion_callbacks()` | `continuous_callback_interval_frames` | `continuous_callback_interval_frames` | `self.continuous_callback_interval_frames` |
| `reconnection_config()` | `timeout_ms` | `reconnection_timeout_ms` | `self.reconnection_timeout_ms` |
| `partner_disconnect_message_config()` | `message` | `partner_disconnect_message` | `self.partner_disconnect_message` |
| `partner_disconnect_message_config()` | `show_completion_code` | `partner_disconnect_show_completion_code` | `self.partner_disconnect_show_completion_code` |
| `focus_loss_config()` | `timeout_ms` | `focus_loss_timeout_ms` | `self.focus_loss_timeout_ms` |
| `focus_loss_config()` | `message` | `focus_loss_message` | `self.focus_loss_message` |
| `focus_loss_config()` | `pause_on_partner_background` | `pause_on_partner_background` | `self.pause_on_partner_background` |

## Call Sites Inventory

Files that call old methods and will need updating in Phase 69 (examples) or that reference attributes in Phase 67 (server code to leave alone):

### `pyodide()` callers (25 call sites)

- `interactive_gym/examples/slime_volleyball/slimevb_human_human.py` (1)
- `interactive_gym/examples/slime_volleyball/human_ai_pyodide_boost.py` (1)
- `interactive_gym/examples/mountain_car/mountain_car_experiment.py` (1)
- `interactive_gym/examples/cogrid/scenes/scenes.py` (11)
- `interactive_gym/examples/cogrid/scenes/controllable_scenes.py` (7)
- `interactive_gym/examples/cogrid/overcooked_human_human_multiplayer_test.py` (1)
- `interactive_gym/examples/cogrid/overcooked_human_human_multiplayer_scene_isolation_test.py` (1)
- `interactive_gym/examples/cogrid/overcooked_human_human_multiplayer_multi_episode_test.py` (1)
- `interactive_gym/examples/cogrid/overcooked_human_human_multiplayer_focus_timeout_test.py` (1)

### `user_experience()` callers (29 call sites)

- `interactive_gym/examples/slime_volleyball/slimevb_human_human.py` (1)
- `interactive_gym/examples/slime_volleyball/human_ai_pyodide_boost.py` (1)
- `interactive_gym/examples/mountain_car/mountain_car_experiment.py` (1)
- `interactive_gym/examples/cogrid/scenes/scenes.py` (16)
- `interactive_gym/examples/cogrid/scenes/controllable_scenes.py` (8)
- `interactive_gym/examples/cogrid/overcooked_controllable_demo.py` (1)

### `rendering()` callers (21 call sites)

- All in examples (scenes.py, controllable_scenes.py, slimevb, mountain_car)

### `matchmaking()` callers (7 call sites, + 3 test references)

- Various examples and test files

### `focus_loss_config()` callers (5 call sites)

- Various multiplayer example/test files

### `partner_disconnect_message_config()` callers (1 call site)

- `interactive_gym/examples/cogrid/scenes/scenes.py` (1)

### `player_grouping()`, `continuous_monitoring()`, `exclusion_callbacks()`, `reconnection_config()` callers

- No external callers found (only defined, not called by examples)

## Existing Tests

| Test file | What it tests | Relevance to Phase 67 |
|---|---|---|
| `tests/unit/test_latency_fifo_integration.py` | `GymScene().matchmaking(matchmaker=...)` | Will need old method to still work (Phase 67 adds new, Phase 68 removes old) |
| `tests/unit/test_latency_fifo_matchmaker.py` | LatencyFIFOMatchmaker standalone | No direct GymScene API impact |
| `tests/e2e/*` | End-to-end multiplayer tests | Use scene configs from example files |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|---|---|---|---|
| `pyodide()` with 12 params | `runtime()` (6 params) + `multiplayer()` (sync params) | Phase 67 | Cleaner separation of concerns |
| 7 separate multiplayer methods | Single `multiplayer()` method | Phase 67 | Fewer methods to discover |
| `user_experience()` with mixed concerns | `content()` + `waitroom()` | Phase 67 | Semantic clarity |
| `rendering()` with 14 params | `rendering()` (9 params) + `assets()` (5 params) | Phase 67 | Logical grouping |

## Open Questions

1. **`multiplayer()` param naming for `continuous_monitoring` params**
   - What we know: The old `continuous_monitoring()` method used short param names like `max_ping`, `ping_violation_window`. But the instance attributes are prefixed: `self.continuous_max_ping`, `self.continuous_ping_violation_window`.
   - What's unclear: Should the new `multiplayer()` use the short names (e.g., `max_ping`) or the long attribute-matching names (e.g., `continuous_max_ping`)?
   - Recommendation: Use the longer prefixed names in `multiplayer()` to avoid ambiguity with the entry-screening `max_ping` attribute that exists on RemoteConfig. This also makes the mapping to instance attributes clearer.

2. **Side effect of `continuous_monitoring_enabled`**
   - What we know: Calling `continuous_monitoring()` currently sets `self.continuous_monitoring_enabled = True` unconditionally.
   - What's unclear: In `multiplayer()`, should any monitoring-related param trigger this, or should there be an explicit `continuous_monitoring_enabled` param?
   - Recommendation: Add an explicit `continuous_monitoring_enabled` param to `multiplayer()`. Also auto-enable it when any `continuous_*` monitoring param is provided (matching current behavior).

3. **`matchmaker` property preservation**
   - What we know: There is a `@property matchmaker` that returns `self._matchmaker`.
   - Recommendation: Keep the property as-is. It is not a builder method, just an accessor.

## Sources

### Primary (HIGH confidence)

- Direct source code analysis of `interactive_gym/scenes/gym_scene.py` (1023 lines, full read)
- Direct source code analysis of `interactive_gym/scenes/scene.py` (base class, 243 lines)
- Direct source code analysis of `interactive_gym/scenes/utils.py` (NotProvided sentinel)
- Direct source code analysis of `interactive_gym/configurations/remote_config.py` (legacy config class)
- Direct source code analysis of `interactive_gym/scenes/static_scene.py` (sibling scene type)
- Grep analysis of all callers across entire codebase for all 12 builder methods
- Grep analysis of all attribute references in `interactive_gym/server/` directory

### Secondary (MEDIUM confidence)

- `.planning/REQUIREMENTS.md` - Requirements definitions
- `.planning/ROADMAP.md` - Phase descriptions and dependencies

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - No external dependencies, pure Python refactoring
- Architecture: HIGH - Full source code analysis, every method and parameter documented
- Pitfalls: HIGH - Complete server attribute reference analysis, all edge cases identified
- Parameter mapping: HIGH - Every parameter traced from old method to new method to instance attribute
- Call sites: HIGH - Full grep of all callers across codebase

**Research date:** 2026-02-07
**Valid until:** Indefinite (internal codebase, no external dependency changes)
