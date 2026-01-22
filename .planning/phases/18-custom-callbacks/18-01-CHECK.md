---
phase: 18-custom-callbacks
plan: 01
verification_status: issues_found
checked: 2026-01-21
---

# Phase 18 Plan 01: Verification Report

**Phase Goal:** Researcher-defined arbitrary exclusion logic via Python callbacks
**Plans Verified:** 1
**Status:** ISSUES FOUND

## Coverage Summary

| Requirement | ID | Tasks | Status |
|-------------|-----|-------|--------|
| Researcher can define custom exclusion rules via Python callback functions | EXT-01 | Task 1 | COVERED |
| Callbacks receive full participant context (ping, browser, focus state, etc.) | EXT-02 | Tasks 2,3,4 | COVERED |
| Callbacks return exclusion decision with optional message | EXT-03 | Tasks 2,3,4 | COVERED |

All three requirements have clear implementation paths in the plan.

## Plan Summary

| Plan | Tasks | Files | Wave | Status |
|------|-------|-------|------|--------|
| 01   | 4     | 4     | 1    | Issues Found |

## Dimension Analysis

### Dimension 1: Requirement Coverage - PASSED

All three phase requirements (EXT-01, EXT-02, EXT-03) have corresponding tasks:

- **EXT-01 (Custom rules via Python callbacks):** Task 1 adds `exclusion_callbacks()` method to GymScene with `entry_callback` and `continuous_callback` parameters.
- **EXT-02 (Receive participant context):** Tasks 3 and 4 specify context fields:
  - Entry: ping, browser_name, browser_version, device_type, os_name, subject_id, scene_id
  - Continuous: ping, is_tab_hidden, tab_hidden_duration_ms, frame_number, episode_number, subject_id, scene_id
- **EXT-03 (Return exclusion decision with message):** Tasks 2, 3, 4 specify return formats:
  - Entry: `{"exclude": bool, "message": str|None}`
  - Continuous: `{"exclude": bool, "warn": bool, "message": str|None}`

### Dimension 2: Task Completeness - PASSED

All tasks have required fields (files, action, verify, done):

| Task | Files | Action | Verify | Done |
|------|-------|--------|--------|------|
| 1    | Yes   | Yes (detailed) | Yes (Python one-liner) | Yes |
| 2    | Yes   | Yes (detailed) | Yes (grep command) | Yes |
| 3    | Yes   | Yes (detailed) | Yes (syntax check) | Yes |
| 4    | Yes   | Yes (detailed) | Yes (grep commands) | Yes |

### Dimension 3: Dependency Correctness - PASSED

- Plan 01 has `depends_on: []` (Wave 1)
- Phase 18 depends on Phase 17 (Multiplayer Exclusion) per ROADMAP.md
- Phase 17 is marked complete, so dependency is satisfied
- No circular dependencies

### Dimension 4: Key Links Planned - WARNING

The plan's `key_links` specify:

1. `index.js -> app.py` via `socket.emit.*execute_entry_callback`
2. `continuous_monitor.js -> app.py` via `socket.emit.*execute_continuous_callback`

**Issue:** The key_link patterns reference `continuous_monitor.js` but Task 4 action shows the socket.emit happening in `pyodide_multiplayer_game.js`, not `continuous_monitor.js`. The `continuous_monitor.js` only adds helper methods (`shouldExecuteCallback`, `setCallbackResult`), while the actual socket emission is in `pyodide_multiplayer_game.js`.

This is a minor inconsistency in the plan documentation, not a blocker - the actual wiring is planned correctly in Task 4's action.

### Dimension 5: Scope Sanity - PASSED

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Tasks/plan | 4 | 2-3 | Warning (borderline) |
| Files/plan | 4 | 5-8 | Good |

4 tasks is at the upper threshold but acceptable given each task is focused:
- Task 1: GymScene Python config
- Task 2: Server handlers
- Task 3: Entry callback client integration
- Task 4: Continuous callback client integration

### Dimension 6: Verification Derivation - WARNING

The `must_haves.truths` are mostly user-observable:
- "Researcher can define custom entry exclusion logic via Python callback" - GOOD
- "Researcher can define custom continuous exclusion logic via Python callback" - GOOD
- "Callbacks receive full participant context (ping, browser, device, focus state)" - GOOD
- "Callbacks return exclusion decision with optional custom message" - GOOD

The `must_haves.artifacts` and `key_links` are present and reasonable.

## Issues Found

### Warning 1: Scene Access Pattern Not Fully Specified

```yaml
issue:
  plan: "01"
  dimension: task_completeness
  severity: warning
  description: "Task 2 action mentions 'get_current_scene()' helper but doesn't specify the exact implementation"
  task: 2
  fix_hint: |
    The existing pattern in app.py uses:
    - participant_stager = STAGERS.get(subject_id, None)
    - current_scene = participant_stager.current_scene
    
    Task 2 should follow this exact pattern. The plan says "Check how other handlers
    in app.py access the experiment/scene configuration" which is correct guidance,
    but the implementation must use STAGERS + current_scene, not a hypothetical
    get_current_scene() function or EXPERIMENT global.
```

**Analysis:** The plan's Task 2 action shows pseudo-code with `get_current_scene(session_id, scene_id)` and mentions "You'll need to implement this lookup". Looking at `app.py`, the actual pattern is:

```python
subject_id = get_subject_id_from_session_id(flask.request.sid)
participant_stager = STAGERS.get(subject_id, None)
current_scene = participant_stager.current_scene
```

The plan does acknowledge this ("Check existing code patterns in app.py") but the pseudo-code may mislead the executor. This is a warning, not a blocker, as the executor guidance is present.

### Warning 2: Entry Screening Already Synchronous

```yaml
issue:
  plan: "01"
  dimension: task_completeness
  severity: warning
  description: "Task 3 makes runEntryScreening async but existing code is synchronous"
  task: 3
  fix_hint: |
    The existing runEntryScreening() in index.js is synchronous:
      const screeningResult = runEntryScreening(data);
    
    Making it async requires updating the call site in startGymScene() to await it.
    The plan does mention this ("Update startGymScene() to handle async screening")
    but should explicitly note this is a breaking change to the function signature.
```

**Analysis:** The plan correctly identifies that `startGymScene` needs to become async, and Task 3 action includes this. However, the plan could be more explicit that this changes the function signature from sync to async.

### Warning 3: Timeout Race Condition

```yaml
issue:
  plan: "01"
  dimension: task_completeness
  severity: warning
  description: "executeEntryCallback has potential race condition between socket response and timeout"
  task: 3
  fix_hint: |
    The plan shows:
      socket.once('entry_callback_result', resolve);
      setTimeout(() => resolve({exclude: false}), 5000);
    
    If the response arrives AFTER timeout fires, socket.once listener remains
    active (unless resolve prevents it). Consider using a resolved flag or
    clearing the timeout on response. The plan should specify handling this.
```

**Analysis:** The timeout pattern is reasonable for fail-open behavior, but the implementation should clear the timeout when response arrives, or use a flag to prevent double-resolution. This is a minor implementation detail.

### Info 1: key_links Documentation Mismatch

```yaml
issue:
  plan: "01"
  dimension: key_links_planned
  severity: info
  description: "key_links says continuous_monitor.js emits socket event, but Task 4 shows pyodide_multiplayer_game.js does"
  fix_hint: "Update key_links to reference pyodide_multiplayer_game.js for the continuous callback emission"
```

## Verification by Success Criteria

### SC-1: Researcher can define custom exclusion rules via Python callback functions

**Implementation Path:**
1. Task 1 adds `exclusion_callbacks()` method to GymScene
2. Stores callbacks as `self.entry_exclusion_callback` and `self.continuous_exclusion_callback`
3. Returns self for chaining (fluent API consistent with existing methods)

**Status:** Clear implementation path exists. COVERED.

### SC-2: Callbacks receive full participant context

**Implementation Path:**
1. Task 3 (entry): Client gathers context via UAParser (ping, browser, device, OS)
2. Task 4 (continuous): Client gathers context (ping, tab hidden, frame/episode)
3. Task 2 (server): Adds subject_id and scene_id to context before calling callback

**Context Fields Specified:**
- Entry: ping, browser_name, browser_version, device_type, os_name, os_version, subject_id, scene_id
- Continuous: ping, is_tab_hidden, tab_hidden_duration_ms, frame_number, episode_number, subject_id, scene_id

**Status:** Comprehensive context specified. COVERED.

### SC-3: Callbacks return exclusion decision with optional message

**Implementation Path:**
1. Task 1 documents callback signatures with return types
2. Task 2 validates and extracts `exclude`, `warn`, `message` from callback return
3. Tasks 3, 4 handle the result and integrate with existing exclusion UI

**Return Formats:**
- Entry: `{"exclude": bool, "message": str|None}`
- Continuous: `{"exclude": bool, "warn": bool, "message": str|None}`

**Status:** Clear return format, integrates with existing exclusion messaging. COVERED.

## Gaps Analysis

### No Missing Requirements

All three requirements (EXT-01, EXT-02, EXT-03) have clear implementation tasks.

### Minor Implementation Gaps

1. **Error handling in callbacks:** Task 2 shows try/except with fail-open behavior, which is appropriate.
2. **Callback validation:** Task 1 mentions "validate callback is callable" - should reject non-callable.

### Integration Points Verified

1. **GymScene pattern:** Follows existing `entry_screening()` and `continuous_monitoring()` patterns
2. **Socket.IO pattern:** Follows existing event handler patterns in app.py
3. **ContinuousMonitor integration:** Extends existing class with new methods
4. **Exclusion UI:** Reuses existing `showExclusionMessage()` and `_handleMidGameExclusion()`

## Recommendation

**Status: PASSED WITH WARNINGS**

The plan will achieve the phase goal. All requirements have clear implementation paths. The warnings are implementation details that the executor should handle but are not blockers:

1. Use the correct STAGERS pattern for scene access (documented in plan's guidance)
2. Handle async/await conversion carefully for entry screening
3. Clear timeout when socket response arrives

The plan is ready for execution. The warnings should be addressed during implementation but do not require plan revision.

---

## Structured Issues (for orchestrator)

```yaml
issues:
  - plan: "01"
    dimension: task_completeness
    severity: warning
    description: "Scene access pattern uses pseudo-code; executor must follow STAGERS.get() pattern"
    task: 2
    fix_hint: "Use participant_stager = STAGERS.get(subject_id); current_scene = participant_stager.current_scene"

  - plan: "01"
    dimension: task_completeness
    severity: warning
    description: "Entry screening becomes async - breaking change to function signature"
    task: 3
    fix_hint: "Explicitly document that startGymScene must become async function"

  - plan: "01"
    dimension: task_completeness
    severity: warning
    description: "Timeout/socket race condition should be handled"
    task: 3
    fix_hint: "Clear timeout on socket response or use resolved flag"

  - plan: "01"
    dimension: key_links_planned
    severity: info
    description: "key_links references continuous_monitor.js but emission is in pyodide_multiplayer_game.js"
    fix_hint: "Update key_links from field to pyodide_multiplayer_game.js"
```

---
*Verification completed: 2026-01-21*
*Verifier: gsd-plan-checker*
