# Requirements: Interactive Gym — GymScene Config Cleanup

**Defined:** 2026-02-07
**Core Value:** Researchers can configure and deploy multiplayer browser experiments with minimal code — a chained scene config and a Python environment are all that's needed.

## v1 Requirements

Requirements for v1.22 milestone. Each maps to roadmap phases.

### API Consolidation

- [ ] **APIC-01**: `pyodide()` method is renamed to `runtime()` containing only browser execution params (code, packages, restart flag)
- [ ] **APIC-02**: Sync/rollback params (input_buffer_size, input_delay, input_confirmation_timeout_ms, server_authoritative, state_broadcast_interval, realtime_mode, multiplayer) are moved out of `pyodide()` into the new `multiplayer()` method
- [ ] **APIC-03**: `matchmaking()`, `player_grouping()`, `continuous_monitoring()`, `exclusion_callbacks()`, `reconnection_config()`, `partner_disconnect_message_config()`, and `focus_loss_config()` are merged into a single `multiplayer()` method
- [ ] **APIC-04**: `user_experience()` is split into `content()` (scene header, body, in-game body, game_page_html_fn) and `waitroom()` (timeout, redirect, timeout message, timeout scene)
- [ ] **APIC-05**: `rendering()` is split into `rendering()` (fps, env_to_state_fn, hud_text_fn, hud_score_carry_over, location_representation, game_width, game_height, background, rollback_smoothing_duration) and `assets()` (preload_specs, assets_dir, assets_to_preload, animation_configs, state_init)
- [ ] **APIC-06**: `policies()` and `gameplay()` are kept as separate methods with no changes to names or param grouping

### Clean Break

- [ ] **CLNB-01**: All old method names (`pyodide`, `user_experience`, `player_grouping`, `continuous_monitoring`, `exclusion_callbacks`, `reconnection_config`, `partner_disconnect_message_config`, `focus_loss_config`, `player_pairing`) are removed entirely — no deprecation aliases
- [ ] **CLNB-02**: No backwards-compatibility shims or redirect methods exist in the codebase after cleanup

### Examples Updated

- [ ] **EXMP-01**: `interactive_gym/examples/cogrid/scenes/scenes.py` uses new API methods
- [ ] **EXMP-02**: `interactive_gym/examples/slime_volleyball/slimevb_human_human.py` uses new API methods
- [ ] **EXMP-03**: `interactive_gym/examples/mountain_car/mountain_car_experiment.py` uses new API methods
- [ ] **EXMP-04**: `interactive_gym/examples/cogrid/overcooked_human_human_multiplayer.py` uses new API methods
- [ ] **EXMP-05**: `interactive_gym/examples/slime_volleyball/human_ai_pyodide_boost.py` uses new API methods

### Verification

- [ ] **VERF-01**: All existing tests pass with new API (zero functionality change)
- [ ] **VERF-02**: Every parameter from the old API is accessible through the new API (no params lost)
- [ ] **VERF-03**: All builder methods return `self` for method chaining

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Further Simplification

- **SIMP-01**: Consider splitting `multiplayer()` if it accumulates too many params after merge
- **SIMP-02**: Consider parameter objects/dataclasses for methods with >10 params (e.g., `rendering()`)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| New functionality or capabilities | This milestone is API cleanup only |
| Changes to server, game_manager, or runtime behavior | Pure surface refactor |
| Changes to non-GymScene scene types (StartScene, StaticScene, FeedbackScene) | Out of milestone scope |
| Parameter renaming within methods | Only method-level grouping/naming changes |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| APIC-01 | Phase 67 | Complete |
| APIC-02 | Phase 67 | Complete |
| APIC-03 | Phase 67 | Complete |
| APIC-04 | Phase 67 | Complete |
| APIC-05 | Phase 67 | Complete |
| APIC-06 | Phase 67 | Complete |
| CLNB-01 | Phase 68 | Complete |
| CLNB-02 | Phase 68 | Complete |
| EXMP-01 | Phase 69 | Complete |
| EXMP-02 | Phase 69 | Complete |
| EXMP-03 | Phase 69 | Complete |
| EXMP-04 | Phase 69 | Complete |
| EXMP-05 | Phase 69 | Complete |
| VERF-01 | Phase 70 | Pending |
| VERF-02 | Phase 70 | Pending |
| VERF-03 | Phase 70 | Pending |

**Coverage:**
- v1 requirements: 16 total
- Mapped to phases: 16
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-07*
*Last updated: 2026-02-07 after roadmap creation*
