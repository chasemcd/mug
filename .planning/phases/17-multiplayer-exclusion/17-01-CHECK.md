# Phase 17 Plan Verification: 17-01-PLAN.md

**Verified:** 2026-01-21
**Plan Checker:** gsd-plan-checker
**Phase Goal:** Coordinated game termination when one player excluded

---

## VERIFICATION PASSED

**Phase:** 17-multiplayer-exclusion
**Plans verified:** 1
**Status:** All checks passed

---

## Dimension 1: Requirement Coverage

| Requirement | Description | Plans | Tasks | Status |
|-------------|-------------|-------|-------|--------|
| MULTI-01 | Non-excluded player sees clear partner notification message | 01 | Task 2 | COVERED |
| MULTI-02 | Game terminates cleanly for both players when one is excluded | 01 | Task 1, Task 2 | COVERED |
| MULTI-03 | Valid game data preserved and marked as partial session | 01 | Task 3 | COVERED |

**Analysis:**

- **MULTI-01 (Partner Notification):** Task 2 explicitly creates `socket.on('partner_excluded')` handler with `_showPartnerExcludedUI()` method showing "Your partner experienced a technical issue" in neutral UI (dark gray, not red). Requirement fully addressed.

- **MULTI-02 (Clean Termination):** Task 1 implements server-side `handle_player_exclusion()` which stops server_runner, deletes game from `self.games`, and uses `eventlet.sleep(0.1)` before cleanup (existing pattern). Task 2 ensures client-side cleanup: sets `state = "done"`, `episodeComplete = true`, pauses continuousMonitor, and closes webrtcManager. Both players are covered.

- **MULTI-03 (Data Preservation):** Task 3 adds `sessionStatus` object to `exportMultiplayerMetrics()` with `isPartial`, `terminationReason`, and `terminationFrame`. Task 2's `trigger_data_export` handler sets `sessionPartialInfo` before calling `emitMultiplayerMetrics()`. Task 3 also modifies `_handleMidGameExclusion()` to set `sessionPartialInfo` for the excluded player.

**Verdict:** All requirements have clear task coverage.

---

## Dimension 2: Task Completeness

### Task 1: Server-side exclusion handler and coordinator method

| Field | Present | Assessment |
|-------|---------|------------|
| `<files>` | Yes | `app.py`, `pyodide_game_coordinator.py` |
| `<action>` | Yes | Specific: line numbers (~1297, ~552), method signatures, event payloads |
| `<verify>` | Yes | 3 grep commands to confirm code exists |
| `<done>` | Yes | 4 measurable acceptance criteria |

**Assessment:** Complete. Action is specific with insertion points and follows existing `remove_player()` pattern.

### Task 2: Client-side partner notification handling

| Field | Present | Assessment |
|-------|---------|------------|
| `<files>` | Yes | `pyodide_multiplayer_game.js` |
| `<action>` | Yes | Specific: handler placement, data flow, UI styling details |
| `<verify>` | Yes | 3 grep commands |
| `<done>` | Yes | 4 measurable criteria |

**Assessment:** Complete. Action includes specific UI styling guidance (neutral vs alarming).

### Task 3: Partial session marking in metrics export

| Field | Present | Assessment |
|-------|---------|------------|
| `<files>` | Yes | `pyodide_multiplayer_game.js` |
| `<action>` | Yes | Specific code snippets for `sessionStatus` object |
| `<verify>` | Yes | 3 grep commands |
| `<done>` | Yes | 4 measurable criteria including both players covered |

**Assessment:** Complete. Action includes specific code examples and covers both excluded player and partner paths.

**Verdict:** All tasks have complete field coverage with specific, actionable instructions.

---

## Dimension 3: Dependency Correctness

| Plan | depends_on | Wave | Valid |
|------|------------|------|-------|
| 01 | [] | 1 | Yes |

**Analysis:**
- Single plan, no dependencies declared
- Plan depends on Phase 16 infrastructure (ContinuousMonitor, `_handleMidGameExclusion`, `mid_game_exclusion` emit) which is complete
- No circular dependencies possible (single plan)

**Verdict:** Dependency graph is valid.

---

## Dimension 4: Key Links Planned

| From | To | Via | Task | Status |
|------|-----|-----|------|--------|
| `app.py mid_game_exclusion handler` | `PyodideGameCoordinator.handle_player_exclusion()` | PYODIDE_COORDINATOR method call | Task 1 | PLANNED |
| `handle_player_exclusion()` | partner's socket | emit partner_excluded event | Task 1 | PLANNED |
| `partner_excluded handler` | `exportMultiplayerMetrics()` | sessionPartialInfo assignment | Tasks 2,3 | PLANNED |

**Analysis:**

1. **Server event chain:** Task 1 action explicitly states:
   - "Calls `PYODIDE_COORDINATOR.handle_player_exclusion(game_id, excluded_player_id, reason, frame_number)`"
   - "Emits `partner_excluded` to each partner socket"
   - Wiring is explicit.

2. **Client event chain:** Task 2 action explicitly states:
   - `socket.on('trigger_data_export')` handler "Sets `this.sessionPartialInfo`"
   - "Calls `this.emitMultiplayerMetrics(this.sceneId)` to export data immediately"
   - Wiring is explicit.

3. **Both player paths covered:** Task 3 modifies `_handleMidGameExclusion()` to set `sessionPartialInfo` before export for the excluded player, ensuring both paths mark sessions as partial.

**Verdict:** All key links are explicitly planned in task actions.

---

## Dimension 5: Scope Sanity

| Metric | Plan 01 | Target | Status |
|--------|---------|--------|--------|
| Tasks | 3 | 2-3 | Good |
| Files modified | 3 | 5-8 | Good |
| Estimated context | ~40% | <70% | Good |

**Analysis:**
- 3 tasks is within optimal range
- 3 files is minimal and focused
- All files are existing (no new file creation)
- Each task is focused on one logical unit

**Verdict:** Scope is appropriate for single plan execution.

---

## Dimension 6: Verification Derivation

### must_haves.truths Assessment

| Truth | User-Observable? | Testable? | Assessment |
|-------|------------------|-----------|------------|
| "Non-excluded player sees 'Your partner experienced a technical issue' message" | Yes | Yes (visible UI) | Good |
| "Game terminates cleanly for both players when one is excluded" | Yes | Yes (game stops) | Good |
| "Valid game data up to exclusion point is preserved" | Indirectly (researcher) | Yes (check metrics) | Acceptable |
| "Session data marked as partial with termination reason" | Indirectly (researcher) | Yes (check JSON) | Acceptable |

**Analysis:** Truths are appropriately user/researcher-observable, not implementation-focused. Data preservation truths are testable via exported metrics inspection.

### must_haves.artifacts Assessment

| Artifact | Provides | Contains | Assessment |
|----------|----------|----------|------------|
| `app.py` | mid_game_exclusion socket handler | `@socketio.on('mid_game_exclusion')` | Specific, verifiable |
| `pyodide_game_coordinator.py` | handle_player_exclusion method | `def handle_player_exclusion` | Specific, verifiable |
| `pyodide_multiplayer_game.js` | partner_excluded handler | `socket.on('partner_excluded'` | Specific, verifiable |

**Analysis:** Artifacts specify expected code patterns that can be verified with grep.

### must_haves.key_links Assessment

| Link | From | To | Pattern | Assessment |
|------|------|-----|---------|------------|
| Server delegation | app.py handler | coordinator method | `PYODIDE_COORDINATOR\.handle_player_exclusion` | Verifiable regex |
| Partner notification | handle_player_exclusion | socket emit | `emit.*partner_excluded` | Verifiable regex |
| Data export trigger | partner_excluded handler | exportMultiplayerMetrics | `sessionPartialInfo.*isPartial` | Verifiable regex |

**Analysis:** All key_links include regex patterns for verification.

**Verdict:** must_haves are properly derived and verifiable.

---

## Coverage Summary

| Success Criterion | Implementation Path | Status |
|-------------------|---------------------|--------|
| Non-excluded player sees clear partner notification message | Task 2: `partner_excluded` handler + `_showPartnerExcludedUI()` | Covered |
| Game terminates cleanly for both players | Task 1: server cleanup + Task 2: client cleanup | Covered |
| Valid game data preserved and marked as partial session | Task 3: `sessionStatus` in export + `sessionPartialInfo` tracking | Covered |

---

## Plan Summary

| Plan | Tasks | Files | Wave | Status |
|------|-------|-------|------|--------|
| 01 | 3 | 3 | 1 | Valid |

---

## Issues Found

**None.** All verification dimensions passed.

---

## Additional Observations

### Strengths

1. **Builds on established patterns:** The plan correctly references `remove_player()` as a template and uses existing `eventlet.sleep(0.1)` pattern for race condition mitigation.

2. **Both player paths covered:** Task 3 explicitly addresses both the excluded player (modifying `_handleMidGameExclusion`) and the partner (via `trigger_data_export` handler).

3. **UI differentiation:** Task 2 correctly specifies neutral styling for partner notification (gray, not red) to avoid alarming the non-excluded player.

4. **Research document alignment:** Plan aligns with 17-01-RESEARCH.md recommendations, including:
   - Using distinct `partner_excluded` event (not reusing `end_game`)
   - `trigger_data_export` event to ensure metrics are saved before cleanup
   - `eventlet.sleep(0.1)` before game deletion

5. **Race condition awareness:** Plan explicitly addresses the race between notification and cleanup in both verification section and task actions.

### Minor Observations (Not Blockers)

1. **Property initialization:** Task 3 mentions adding `this.sessionPartialInfo = null;` in constructor or initialization, but doesn't specify the exact location. The executor should add this near other property initializations in the class.

2. **Simultaneous exclusion edge case:** Research document notes potential race if both players excluded simultaneously. The plan handles this implicitly (first exclusion triggers cleanup, second is no-op since game removed), but this could be documented in code comments.

---

## Ready for Execution

Plans verified. The plan will achieve the Phase 17 goal when executed correctly.

Run `/gsd:execute-plan 17-01` to proceed.
