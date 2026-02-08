# Phase 71: Documentation Migration - Research

**Researched:** 2026-02-07
**Domain:** Documentation find-and-replace, API migration
**Confidence:** HIGH

## Summary

This research catalogs every documentation file that references old/removed GymScene method names and maps each occurrence to its correct new API equivalent. The old API used 9+ fine-grained builder methods (`.pyodide()`, `.user_experience()`, `.continuous_monitoring()`, `.exclusion_callbacks()`, `.focus_loss_config()`, `.player_grouping()`, `.reconnection_config()`, `.partner_disconnect_message_config()`, `.player_pairing()`). These have been consolidated into 3 new methods: `.runtime()`, `.multiplayer()`, and `.content()` (with `.waitroom()` for waitroom-specific params).

The migration is mechanical but requires understanding which old parameters map to which new method. 13 source documentation files contain old method references (excluding `docs/_build/` which is gitignored and auto-generated). The changes range from simple method name renames to more complex restructuring where parameters moved between methods (e.g., `multiplayer` param moved from `.pyodide()` to `.multiplayer()`, `scene_header`/`scene_body` moved from `.user_experience()` to `.content()`).

**Primary recommendation:** Process files in two batches: (1) RST files in `docs/content/` which are user-facing Sphinx docs, and (2) standalone MD files in `docs/` which are internal/design docs. The `_build/` directory is gitignored and should not be edited. The HTML file `docs/multiplayer-sync-optimization.html` is a Quarto export and should be regenerated or deleted after the MD source is updated.

## Standard Stack

No external libraries needed. This is pure find-and-replace documentation work.

### Tools Used
| Tool | Purpose |
|------|---------|
| Text editor | Replace old method calls with new equivalents |
| grep/search | Verify zero remaining references after migration |

## Architecture Patterns

### New API Method Signatures (from `interactive_gym/scenes/gym_scene.py`)

The current new API has these builder methods on GymScene:

```python
# Browser runtime configuration (was .pyodide())
.runtime(
    run_through_pyodide: bool,
    environment_initialization_code: str,
    environment_initialization_code_filepath: str,
    on_game_step_code: str,
    packages_to_install: list[str],
    restart_pyodide: bool,
)

# Display content (was .user_experience() for scene_header, scene_body, etc.)
.content(
    scene_header: str,
    scene_body: str,
    scene_body_filepath: str,
    in_game_scene_body: str,
    in_game_scene_body_filepath: str,
    game_page_html_fn: Callable,
)

# Waitroom settings (was .user_experience() for waitroom_timeout_*)
.waitroom(
    timeout: int,                    # was waitroom_timeout
    timeout_redirect_url: str,       # was waitroom_timeout_redirect_url
    timeout_scene_id: str,           # was waitroom_timeout_scene_id
    timeout_message: str,            # was waitroom_timeout_message
)

# Multiplayer - consolidated from 8 old methods
.multiplayer(
    # Sync/rollback (was in .pyodide())
    multiplayer: bool,               # was pyodide(multiplayer=True)
    server_authoritative: bool,
    state_broadcast_interval: int,
    realtime_mode: bool,
    input_buffer_size: int,
    input_delay: int,
    input_confirmation_timeout_ms: int,
    # Matchmaking
    hide_lobby_count: bool,
    max_rtt: int,
    matchmaker: Matchmaker,
    # Player grouping
    wait_for_known_group: bool,
    group_wait_timeout: int,
    # Continuous monitoring
    continuous_monitoring_enabled: bool,
    continuous_max_ping: int,
    continuous_ping_violation_window: int,
    continuous_ping_required_violations: int,
    continuous_tab_warning_ms: int,
    continuous_tab_exclude_ms: int,
    continuous_exclusion_messages: dict,
    # Exclusion callbacks
    continuous_callback: Callable,
    continuous_callback_interval_frames: int,
    # Reconnection
    reconnection_timeout_ms: int,
    # Partner disconnect
    partner_disconnect_message: str,
    partner_disconnect_show_completion_code: bool,
    # Focus loss
    focus_loss_timeout_ms: int,
    focus_loss_message: str,
    pause_on_partner_background: bool,
)
```

### Mapping: Old Method -> New Method + Parameter Changes

| Old Method | New Method | Parameter Changes |
|---|---|---|
| `.pyodide(run_through_pyodide=...)` | `.runtime(run_through_pyodide=...)` | Same params, just method rename |
| `.pyodide(environment_initialization_code=...)` | `.runtime(environment_initialization_code=...)` | Same |
| `.pyodide(environment_initialization_code_filepath=...)` | `.runtime(environment_initialization_code_filepath=...)` | Same |
| `.pyodide(packages_to_install=...)` | `.runtime(packages_to_install=...)` | Same |
| `.pyodide(restart_pyodide=...)` | `.runtime(restart_pyodide=...)` | Same |
| `.pyodide(multiplayer=True)` | `.multiplayer(multiplayer=True)` | Moved to `.multiplayer()` |
| `.pyodide(server_authoritative=...)` | `.multiplayer(server_authoritative=...)` | Moved to `.multiplayer()` |
| `.pyodide(state_sync_frequency_frames=...)` | `.multiplayer(state_broadcast_interval=...)` | Renamed param |
| `.user_experience(scene_header=...)` | `.content(scene_header=...)` | Method rename |
| `.user_experience(scene_body=...)` | `.content(scene_body=...)` | Method rename |
| `.user_experience(scene_body_filepath=...)` | `.content(scene_body_filepath=...)` | Method rename |
| `.user_experience(in_game_scene_body=...)` | `.content(in_game_scene_body=...)` | Method rename |
| `.user_experience(in_game_scene_body_filepath=...)` | `.content(in_game_scene_body_filepath=...)` | Method rename |
| `.user_experience(game_page_html_fn=...)` | `.content(game_page_html_fn=...)` | Method rename |
| `.user_experience(waitroom_timeout=...)` | `.waitroom(timeout=...)` | Split to `.waitroom()`, param shortened |
| `.user_experience(waitroom_timeout_redirect_url=...)` | `.waitroom(timeout_redirect_url=...)` | Split + param shortened |
| `.continuous_monitoring(...)` | `.multiplayer(continuous_monitoring_enabled=True, ...)` | Merged into `.multiplayer()`, param names changed |
| `.exclusion_callbacks(...)` | `.multiplayer(continuous_callback=..., continuous_callback_interval_frames=...)` | Merged into `.multiplayer()` |
| `.focus_loss_config(...)` | `.multiplayer(focus_loss_timeout_ms=..., ...)` | Merged into `.multiplayer()` |

## File-by-File Change Catalog

### Batch 1: RST Files in docs/content/ (User-facing Sphinx docs)

#### 1. `docs/content/core_concepts/scenes.rst`
**Old references found:** `.user_experience()` (lines 247, 254, 445), `.pyodide()` (lines 262, 269)
**Changes needed:**
- Line 247: Rename section header `.user_experience()` to `.content()`
- Lines 254-260: Change `.user_experience(...)` code block to `.content(...)`
- Line 262: Rename section header `.pyodide()` to `.runtime()`
- Lines 269-275: Change `.pyodide(...)` code block to `.runtime(...)`
- Lines 445-448: Change `.user_experience(...)` to `.content(...)`

#### 2. `docs/content/core_concepts/pyodide_mode.rst`
**Old references found:** `.pyodide()` (lines 50, 67, 249, 272, 285, 458, 492, 585), `.user_experience()` (lines 366, 574)
**Changes needed:**
- All `.pyodide(...)` calls -> `.runtime(...)` (pure browser execution params only)
- Where `.pyodide(multiplayer=True)` appears, split into `.runtime()` + `.multiplayer(multiplayer=True)`
- Lines 366-376: Change `.user_experience(...)` to `.content(...)`
- Lines 574-583: Change `.user_experience(...)` to `.content(...)`
- Lines 585-589: Change `.pyodide(...)` to `.runtime(...)`

#### 3. `docs/content/core_concepts/index.rst`
**Old references found:** `.pyodide()` (lines 89, 167), `.user_experience()` (line 166)
**Changes needed:**
- Line 89: Change `gym_scene.GymScene().pyodide(run_through_pyodide=True)` to `gym_scene.GymScene().runtime(run_through_pyodide=True)`
- Line 166: Change `.user_experience(scene_header="...")` to `.content(scene_header="...")`
- Line 167: Change `.pyodide(run_through_pyodide=True)` to `.runtime(run_through_pyodide=True)`

#### 4. `docs/content/core_concepts/server_mode.rst`
**Old references found:** `.pyodide()` (line 126), `.user_experience()` (line 204)
**Changes needed:**
- Line 126: Change comment `# No .pyodide() call = server mode by default` to `# No .runtime() call = server mode by default`
- Lines 204-207: Change `.user_experience(...)` to `.content(...)` + `.waitroom(...)` (waitroom params need to be split out)

#### 5. `docs/content/quick_start.rst`
**Old references found:** `.user_experience()` (line 195), `.pyodide()` (lines 200, 330)
**Changes needed:**
- Lines 195-199: Change `.user_experience(...)` to `.content(...)`
- Lines 200-203: Change `.pyodide(...)` to `.runtime(...)`
- Line 330: Change text reference ``.pyodide()`` to ``.runtime()``

#### 6. `docs/content/examples/slime_volleyball.rst`
**Old references found:** `.user_experience()` (line 170), `.pyodide()` (lines 179, 410)
**Changes needed:**
- Lines 170-178: Change `.user_experience(...)` to `.content(...)`
- Lines 179-188: Change `.pyodide(...)` to `.runtime(...)`
- Line 410: Change comment `# No .pyodide() configuration` to `# No .runtime() configuration`

#### 7. `docs/content/examples/mountain_car.rst`
**Old references found:** `.user_experience()` (line 180), `.pyodide()` (line 189)
**Changes needed:**
- Lines 180-188: Change `.user_experience(...)` to `.content(...)`
- Lines 189-194: Change `.pyodide(...)` to `.runtime(...)`

#### 8. `docs/content/examples/overcooked_multiplayer.rst`
**Old references found:** `.user_experience()` (line 262)
**Changes needed:**
- Lines 262-270: Change `.user_experience(...)` to `.content(...)`

#### 9. `docs/content/examples/overcooked_human_ai.rst`
**Old references found:** `.user_experience()` (line 247)
**Changes needed:**
- Lines 247-255: Change `.user_experience(...)` to `.content(...)`

### Batch 2: Standalone MD Files in docs/ (Design/internal docs)

#### 10. `docs/participant-exclusion.md`
**Old references found:** `.continuous_monitoring()` (lines 40, 113, 160, 359), `.exclusion_callbacks()` (lines 226, 272, 365)
**Changes needed:**
- Line 40: Change `.continuous_monitoring(...)` to `.multiplayer(continuous_monitoring_enabled=True, continuous_max_ping=200, continuous_tab_exclude_ms=10000)`
- Line 113: Change text `GymScene.continuous_monitoring()` to `GymScene.multiplayer()` with continuous monitoring params
- Lines 117-126: Update method signature from `continuous_monitoring()` to show these are now params on `.multiplayer()`
- Lines 160-171: Change `.continuous_monitoring(...)` to `.multiplayer(...)`
- Line 226: Change text `GymScene.exclusion_callbacks()` to `GymScene.multiplayer()`
- Lines 272-275: Change `.exclusion_callbacks(...)` to `.multiplayer(continuous_callback=..., continuous_callback_interval_frames=...)`
- Lines 355-368: Complete example needs full rewrite with `.multiplayer()` consolidation
- **Note:** The overall structure of this doc (method signatures, parameter tables) will need significant reworking since the separate methods no longer exist.

#### 11. `docs/multiplayer-sync-optimization.md`
**Old references found:** `.pyodide()` (lines 110, 473)
**Changes needed:**
- Lines 110-114: Change `.pyodide(state_sync_frequency_frames=20, ...)` to appropriate new API (`.multiplayer(state_broadcast_interval=20)` + `.runtime(...)`)
- Lines 473-475: Change `.pyodide(state_sync_frequency_frames=60, ...)` to `.multiplayer(state_broadcast_interval=60)`
- **Note:** There is also a tracked HTML file `docs/multiplayer-sync-optimization.html` (Quarto export) that will become stale. It should be regenerated from the updated MD or deleted.

#### 12. `docs/multiplayer_pyodide_implementation.md`
**Old references found:** `.pyodide()` (lines 808, 820-834, 1202, 1252), `.user_experience()` (line 1237)
**Changes needed:**
- Line 808: Change text reference from `.pyodide()` to `.multiplayer()` for the multiplayer param
- Lines 820-834: Change the code example showing `def pyodide(...)` method signature to show the new split: `.runtime()` for browser exec params + `.multiplayer(multiplayer=True)` for sync
- Lines 1202-1217: Change `.pyodide(run_through_pyodide=True, multiplayer=True, ...)` to `.runtime(run_through_pyodide=True, ...).multiplayer(multiplayer=True)`
- Lines 1237-1241: Change `.user_experience(...)` to `.content(...)` + `.waitroom(timeout=60000)`
- Lines 1252-1256: Change `.pyodide(run_through_pyodide=True, multiplayer=True, ...)` to `.runtime(...).multiplayer(multiplayer=True)`

#### 13. `docs/server-frame-aligned-stepper.md`
**Old references found:** `.pyodide()` (lines 601, 700, 780)
**Changes needed:**
- Lines 595-614: Update `pyodide()` method code to show new `.runtime()` + `.multiplayer()` split
- Lines 700-708: Change `.pyodide(run_through_pyodide=True, multiplayer=True, server_authoritative=True, ...)` to `.runtime(run_through_pyodide=True, ...).multiplayer(multiplayer=True, server_authoritative=True, ...)`
- Line 780: Change checklist item `Update pyodide() method to accept new parameters` to reference the new methods

#### 14. `docs/server-authoritative-architecture.md`
**Old references found:** `.pyodide()` (lines 666, 708)
**Changes needed:**
- Lines 666-677: Change `.pyodide(run_through_pyodide=True, multiplayer=True, server_authoritative=True, ...)` to `.runtime(...).multiplayer(...)`
- Line 708: Change checklist item `Add server_authoritative option to GymScene.pyodide()` to reference `.multiplayer()`

### Batch 3: README Files

#### 15. `interactive_gym/examples/cogrid/README.md`
**Old references found:** `.pyodide()` (lines 157-161)
**Changes needed:**
- Lines 157-161: Change `.pyodide(run_through_pyodide=True, multiplayer=True, ...)` to `.runtime(run_through_pyodide=True, ...).multiplayer(multiplayer=True)`

### Files NOT Needing Changes (verified clean)

- `docs/multiplayer_state_sync_api.md` - No old method references
- `docs/MANUAL_TEST_PROTOCOL.md` - No old method references
- `docs/content/core_concepts/object_contexts.rst` - No old method references
- `docs/content/core_concepts/rendering_system.rst` - No old method references
- `docs/content/core_concepts/stager.rst` - No old method references
- `docs/content/examples/footsies.rst` - No old method references
- `docs/content/examples/index.rst` - No old method references
- `docs/content/getting_started.rst` - No old method references
- `docs/content/getting_started_index.rst` - No old method references
- `docs/content/installation.rst` - No old method references
- `docs/content/resources_index.rst` - No old method references
- `docs/index.rst` - No old method references
- `docs/conf.py` - No old method references
- `interactive_gym/examples/slime_volleyball/README.md` - No old method references
- `interactive_gym/examples/cogrid/policies/README.md` - No old method references

### Files to SKIP (auto-generated, gitignored)

- `docs/_build/html/_sources/*.rst` - Copies of source RST, regenerated by Sphinx build
- `docs/_build/html/*.html` - Sphinx-generated HTML, regenerated by Sphinx build

### Files to Note (tracked but auto-generated)

- `docs/multiplayer-sync-optimization.html` - Quarto-generated HTML of the MD file. Tracked by git but should be regenerated after the MD source is updated, or deleted if Quarto is no longer used.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Complex parameter re-mapping | Manual memory of param mappings | Reference the mapping table above | Easy to miss subtle param renames like `waitroom_timeout` -> `timeout` |
| Verifying zero old references | Manual reading | `grep -r "\.pyodide\(\|\.user_experience\(\|\.continuous_monitoring\(\|\.exclusion_callbacks\("` | Catches references in comments and text, not just code |

## Common Pitfalls

### Pitfall 1: Missing the multiplayer param split from .pyodide()
**What goes wrong:** When converting `.pyodide(run_through_pyodide=True, multiplayer=True, ...)`, ALL params must be split: browser-exec params to `.runtime()`, multiplayer/sync params to `.multiplayer()`.
**Why it happens:** The old `.pyodide()` contained both browser execution AND multiplayer sync params.
**How to avoid:** For each `.pyodide()` call, categorize every param: `run_through_pyodide`, `environment_initialization_code`, `environment_initialization_code_filepath`, `packages_to_install`, `restart_pyodide` go to `.runtime()`. Everything else goes to `.multiplayer()`.
**Warning signs:** A `.runtime()` call that contains `multiplayer=True` or `server_authoritative=True`.

### Pitfall 2: Missing the user_experience -> content + waitroom split
**What goes wrong:** `.user_experience()` params that relate to waitroom (like `waitroom_timeout`) need to go to `.waitroom()`, not `.content()`.
**Why it happens:** The old `.user_experience()` mixed UI content with waitroom behavior.
**How to avoid:** `scene_header`, `scene_body`, `scene_body_filepath`, `in_game_scene_body`, `in_game_scene_body_filepath`, `game_page_html_fn` go to `.content()`. `waitroom_timeout` goes to `.waitroom(timeout=...)`. `waitroom_timeout_redirect_url` goes to `.waitroom(timeout_redirect_url=...)`.
**Warning signs:** A `.content()` call that contains `waitroom_timeout`.

### Pitfall 3: Forgetting parameter name changes in .waitroom()
**What goes wrong:** The `.waitroom()` method uses shortened param names since the method name provides context.
**Why it happens:** Old params were `waitroom_timeout`, `waitroom_timeout_redirect_url`, etc. New params drop the `waitroom_` prefix.
**How to avoid:** Always use the short names: `timeout`, `timeout_redirect_url`, `timeout_scene_id`, `timeout_message`.

### Pitfall 4: Forgetting text/prose references
**What goes wrong:** Method names appear not just in code blocks but in text descriptions, comments, and section headers.
**Why it happens:** Easy to focus on code blocks and miss surrounding prose.
**How to avoid:** After updating code blocks, re-read surrounding text for method name references. Search for backtick-quoted references like `` `.pyodide()` `` and ``.pyodide()`` (RST double-backtick).
**Warning signs:** `grep` still finds matches after code block edits.

### Pitfall 5: The _build directory
**What goes wrong:** Editing files in `docs/_build/` which are auto-generated and gitignored.
**Why it happens:** Grep results include `_build` files.
**How to avoid:** Only edit source files in `docs/content/` and `docs/*.md`. Never touch `docs/_build/`.

### Pitfall 6: The participant-exclusion.md doc structure
**What goes wrong:** This doc has method signature sections and parameter tables for `.continuous_monitoring()` and `.exclusion_callbacks()` as standalone methods. A simple find-replace won't work.
**Why it happens:** The doc was structured around the old method-per-concern API.
**How to avoid:** This doc needs structural rework: the "Continuous Monitoring" and "Custom Exclusion Callbacks" sections should explain that these are now parameters on `.multiplayer()`, and the method signatures/parameter tables need updating.

## Code Examples

### Example 1: Converting a simple .pyodide() call

**Before (old API):**
```python
.pyodide(
    run_through_pyodide=True,
    environment_initialization_code_filepath="env.py",
    packages_to_install=["gymnasium==1.0.0"],
)
```

**After (new API):**
```python
.runtime(
    run_through_pyodide=True,
    environment_initialization_code_filepath="env.py",
    packages_to_install=["gymnasium==1.0.0"],
)
```

### Example 2: Converting a multiplayer .pyodide() call

**Before (old API):**
```python
.pyodide(
    run_through_pyodide=True,
    multiplayer=True,
    environment_initialization_code_filepath="env.py",
    packages_to_install=["cogrid"],
)
```

**After (new API):**
```python
.runtime(
    run_through_pyodide=True,
    environment_initialization_code_filepath="env.py",
    packages_to_install=["cogrid"],
)
.multiplayer(
    multiplayer=True,
)
```

### Example 3: Converting .user_experience() with mixed params

**Before (old API):**
```python
.user_experience(
    scene_header="Game Title",
    scene_body="<p>Loading...</p>",
    in_game_scene_body="<p>Play!</p>",
    waitroom_timeout=60000,
)
```

**After (new API):**
```python
.content(
    scene_header="Game Title",
    scene_body="<p>Loading...</p>",
    in_game_scene_body="<p>Play!</p>",
)
.waitroom(
    timeout=60000,
)
```

### Example 4: Converting .continuous_monitoring() + .exclusion_callbacks()

**Before (old API):**
```python
scene.continuous_monitoring(
    max_ping=200,
    ping_violation_window=5,
    ping_required_violations=3,
    tab_warning_ms=3000,
    tab_exclude_ms=10000,
).exclusion_callbacks(
    continuous_callback=my_check,
    continuous_callback_interval_frames=30,
)
```

**After (new API):**
```python
scene.multiplayer(
    continuous_max_ping=200,
    continuous_ping_violation_window=5,
    continuous_ping_required_violations=3,
    continuous_tab_warning_ms=3000,
    continuous_tab_exclude_ms=10000,
    continuous_callback=my_check,
    continuous_callback_interval_frames=30,
)
```

### Example 5: Full fluent chain (index.rst pattern)

**Before (old API):**
```python
scene = (
    gym_scene.GymScene()
    .scene(scene_id="my_game")
    .environment(env_creator=make_env)
    .rendering(fps=30, game_width=600)
    .gameplay(num_episodes=5)
    .policies(policy_mapping={...})
    .user_experience(scene_header="...")
    .pyodide(run_through_pyodide=True)
)
```

**After (new API):**
```python
scene = (
    gym_scene.GymScene()
    .scene(scene_id="my_game")
    .environment(env_creator=make_env)
    .rendering(fps=30, game_width=600)
    .gameplay(num_episodes=5)
    .policies(policy_mapping={...})
    .content(scene_header="...")
    .runtime(run_through_pyodide=True)
)
```

## Quantitative Summary

| Category | Count | Notes |
|----------|-------|-------|
| Files with `.pyodide()` refs | 11 | RST: 6, MD: 4, README: 1 |
| Files with `.user_experience()` refs | 9 | RST: 7, MD: 2 |
| Files with `.continuous_monitoring()` refs | 1 | `participant-exclusion.md` |
| Files with `.exclusion_callbacks()` refs | 1 | `participant-exclusion.md` |
| Files with `.focus_loss_config()` refs | 0 | Already clean |
| Files with `.player_grouping()` refs | 0 | Already clean |
| Files with `.reconnection_config()` refs | 0 | Already clean |
| Files with `.partner_disconnect_message_config()` refs | 0 | Already clean |
| Files with `.player_pairing()` refs | 0 | Already clean |
| **Total unique files needing edits** | **15** | 9 RST + 5 MD + 1 README |
| Total `.pyodide()` occurrences | ~30 | Across all files |
| Total `.user_experience()` occurrences | ~15 | Across all files |
| Total `.continuous_monitoring()` occurrences | 4 | In participant-exclusion.md only |
| Total `.exclusion_callbacks()` occurrences | 3 | In participant-exclusion.md only |

## Verification Strategy

After all changes, run these verification commands to confirm zero remaining references:

```bash
# Must return zero matches (excluding _build/ directory)
grep -r --include="*.rst" --include="*.md" \
  -e '\.pyodide(' -e '\.user_experience(' \
  -e '\.continuous_monitoring(' -e '\.exclusion_callbacks(' \
  -e '\.focus_loss_config(' -e '\.player_grouping(' \
  -e '\.reconnection_config(' -e '\.partner_disconnect_message_config(' \
  -e '\.player_pairing(' \
  docs/ interactive_gym/examples/ \
  --exclude-dir=_build

# Also check for backtick-quoted references in text
grep -r --include="*.rst" --include="*.md" \
  -e 'pyodide()' -e 'user_experience()' \
  -e 'continuous_monitoring()' -e 'exclusion_callbacks()' \
  docs/ interactive_gym/examples/ \
  --exclude-dir=_build
```

## Open Questions

1. **`docs/multiplayer-sync-optimization.html`** - This is a Quarto-generated HTML file tracked by git. Should it be regenerated from the updated MD or deleted? The planner should decide. If Quarto is available, regenerate; otherwise, consider removing the HTML and keeping only the MD source.

2. **`participant-exclusion.md` structural rework depth** - This doc's entire structure is built around the old per-method API (with separate "Method Signature" and "Parameters" sections for `.continuous_monitoring()` and `.exclusion_callbacks()`). A simple find-replace won't work. The planner should decide whether to do a full structural rewrite or a minimal update that notes these are now params on `.multiplayer()`.

3. **Design docs vs user docs** - The MD files in `docs/` (multiplayer-sync-optimization, server-frame-aligned-stepper, server-authoritative-architecture, multiplayer_pyodide_implementation) are design/implementation docs, not user-facing. Some contain outdated code snippets showing old `GymScene` class internals (like `def pyodide(self, ...)`). These may need deeper updates or could be marked as "historical design docs" rather than current API references.

## Sources

### Primary (HIGH confidence)
- `interactive_gym/scenes/gym_scene.py` - Current API source code, verified all method signatures
- Direct grep of all documentation files - Verified every match

### Metadata

**Confidence breakdown:**
- File catalog: HIGH - Direct grep search, exhaustive
- Parameter mappings: HIGH - Read directly from source code
- Change descriptions: HIGH - Based on comparing old references with new API
- Structural rework needs: MEDIUM - `participant-exclusion.md` needs judgment calls on restructuring depth

**Research date:** 2026-02-07
**Valid until:** Stable - documentation migration is a point-in-time task
