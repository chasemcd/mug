# Phase 60: Single Game Creation Path - Research

**Researched:** 2026-02-03
**Domain:** Python code refactoring, game manager architecture
**Confidence:** HIGH

## Summary

Phase 60 is a pure refactoring phase that consolidates game creation into a single code path. The codebase currently has **two distinct paths** for creating games:

1. **FIFO path** (`_add_to_fifo_queue` -> `matchmaker.find_match()` -> game creation)
2. **Group reunion path** (`_join_or_wait_for_group` -> `_create_game_for_group`)

The goal is to eliminate the group reunion path, making `matchmaker.find_match()` the **only** entry point for game creation. Group reunion functionality is documented as a future matchmaker variant (REUN-01/REUN-02 in REQUIREMENTS.md).

**Primary recommendation:** Remove `_join_or_wait_for_group` and `_create_game_for_group`, bypass the `wait_for_known_group` check in `add_subject_to_game()`, and document the deferred functionality.

## Standard Stack

This is a refactoring phase - no new libraries needed.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib | 3.11+ | Language | Existing codebase |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| eventlet | existing | Async/threading | Already in use |
| logging | stdlib | Diagnostics | Already in use |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Delete group reunion code | Comment out | Delete is cleaner, code is tracked in git |
| Deprecation warnings | Hard bypass | Hard bypass is simpler, feature is documented |

## Architecture Patterns

### Current Game Creation Flow (Before Phase 60)

```
add_subject_to_game(subject_id)
    |
    +-- [if wait_for_known_group && has group members]
    |       -> _join_or_wait_for_group()
    |           -> _create_game_for_group()  [SEPARATE PATH - PROBLEM]
    |
    +-- [else]
            -> _add_to_fifo_queue()
                -> matchmaker.find_match()
                    |
                    +-- [if match found && P2P probe needed]
                    |       -> _probe_and_create_game()
                    |           -> _on_probe_complete()
                    |               -> _create_game_for_match_internal()
                    |
                    +-- [if match found && no probe]
                    |       -> _create_game_for_match()
                    |
                    +-- [if no match]
                            -> _add_to_waitroom()
```

### Target Game Creation Flow (After Phase 60)

```
add_subject_to_game(subject_id)
    |
    +-- _add_to_fifo_queue()  [ALWAYS - SINGLE PATH]
            -> matchmaker.find_match()
                |
                +-- [if match && probe needed]
                |       -> _probe_and_create_game()
                |
                +-- [if match && no probe]
                |       -> _create_game_for_match()
                |
                +-- [if no match]
                        -> _add_to_waitroom()
```

### Pattern 1: Bypass Without Deletion

**What:** Comment out the group reunion branch but keep code for reference
**When to use:** When feature is documented for future implementation
**Example:**
```python
def add_subject_to_game(self, subject_id: SubjectID) -> remote_game.RemoteGameV2 | None:
    # Phase 60: Group reunion bypassed - see REQUIREMENTS.md REUN-01/REUN-02
    # Future: Implement as GroupReunionMatchmaker variant
    # if self.scene.wait_for_known_group and self.pairing_manager:
    #     group_members = self.pairing_manager.get_group_members(subject_id)
    #     if group_members:
    #         return self._join_or_wait_for_group(subject_id, group_members)

    return self._add_to_fifo_queue(subject_id)
```

### Pattern 2: Delete with Documentation

**What:** Remove the group reunion code entirely, document in docstring
**When to use:** When git history preservation is sufficient
**Example:**
```python
def add_subject_to_game(self, subject_id: SubjectID) -> remote_game.RemoteGameV2 | None:
    """Add a subject to a game and return it.

    All games are created through the matchmaker's find_match() method.

    Note: Group reunion (wait_for_known_group) was removed in Phase 60.
    This functionality is planned for future implementation as a
    GroupReunionMatchmaker variant. See REQUIREMENTS.md REUN-01/REUN-02.
    """
    return self._add_to_fifo_queue(subject_id)
```

### Anti-Patterns to Avoid
- **Keeping dead code paths:** Don't leave unreachable code that could confuse future maintainers
- **Silent deprecation:** Document why group reunion was removed and where to find the future plan
- **Incomplete cleanup:** Remove ALL group reunion code (methods, data structures, related tracking)

## Don't Hand-Roll

This is a refactoring phase - no custom solutions needed.

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Version control | Custom backup | Git history | Code is tracked, can be recovered |
| Deprecation | Custom warnings | Documentation | Feature is deferred, not deprecated |

## Common Pitfalls

### Pitfall 1: Orphaned Data Structures
**What goes wrong:** Removing methods but leaving their data structures (group_waitrooms, group_wait_start_times)
**Why it happens:** Focus on code flow, forget about state
**How to avoid:** Search for all usages of group_waitrooms before removing
**Warning signs:** ThreadSafeDict instances with no write operations

### Pitfall 2: Orphaned Helper Methods
**What goes wrong:** Leaving methods like `_broadcast_group_waiting_status` that are only called by removed code
**Why it happens:** Deletion stops at immediate callers
**How to avoid:** Trace the full call graph from removed entry points
**Warning signs:** Private methods with no callers

### Pitfall 3: Breaking wait_for_known_group Configuration
**What goes wrong:** Users with existing configs using `wait_for_known_group=True` get unexpected behavior
**Why it happens:** Config still exists, just doesn't work
**How to avoid:** Either deprecate the config property or make it no-op with warning log
**Warning signs:** Config property with no effect

### Pitfall 4: Match Logger Reference to GroupReunion
**What goes wrong:** Match logger references "GroupReunion" class name that no longer exists
**Why it happens:** Match logger was added to group reunion flow in Phase 56
**How to avoid:** Remove the match_logger.log_match() call in _create_game_for_group
**Warning signs:** Log entries referencing non-existent matchmaker_class

### Pitfall 5: Incomplete Test Coverage
**What goes wrong:** Tests for group reunion still exist and start failing
**Why it happens:** Test coverage includes the removed feature
**How to avoid:** Search for tests that exercise wait_for_known_group or group reunion
**Warning signs:** Test failures after removal

## Code Examples

### Current Entry Point (game_manager.py lines 287-308)
```python
# Source: interactive_gym/server/game_manager.py
def add_subject_to_game(
    self, subject_id: SubjectID
) -> remote_game.RemoteGameV2 | None:
    """Add a subject to a game and return it.

    If wait_for_known_group is enabled and the subject has known group members,
    they will be added to a group-specific waitroom. Returns None if waiting
    for group members.

    Supports groups of any size (2 or more players).
    """
    logger.info(f"add_subject_to_game called for {subject_id}. Current waiting_games: {self.waiting_games}")

    # Check if we should wait for known group members
    if self.scene.wait_for_known_group and self.pairing_manager:
        group_members = self.pairing_manager.get_group_members(subject_id)
        if group_members:
            logger.info(f"Subject {subject_id} has known group members: {group_members}. Using group waitroom.")
            return self._join_or_wait_for_group(subject_id, group_members)

    # Standard FIFO matching
    return self._add_to_fifo_queue(subject_id)
```

### Methods to Remove
```python
# game_manager.py - lines 310-469
def _join_or_wait_for_group(...)       # Lines 310-364
def _broadcast_group_waiting_status(...)  # Lines 366-388
def _create_game_for_group(...)        # Lines 390-469

# Additional methods related to group reunion
def remove_from_group_waitroom(...)    # Lines 1665-1691
def check_group_wait_timeouts(...)     # Lines 1696-1709
def handle_group_wait_timeout(...)     # Lines 1711-1732
```

### Data Structures to Remove
```python
# game_manager.py - lines 108-112
# Group waitrooms: group_id -> list of subject_ids waiting together
# Used when wait_for_known_group=True to reunite players from previous games
self.group_waitrooms: dict[str, list[SubjectID]] = utils.ThreadSafeDict()
# Track when each subject started waiting for their group members
self.group_wait_start_times: dict[SubjectID, float] = utils.ThreadSafeDict()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hard-coded FIFO matching | Pluggable matchmaker via find_match() | Phase 55 | Foundation for this refactor |
| Two game creation paths | Single matchmaker path | Phase 60 (this) | Cleaner architecture |
| Group reunion as special case | Future: GroupReunionMatchmaker | Phase 60 (this) | Deferred to v2 |

**Deprecated/outdated:**
- `wait_for_known_group` config: Should become no-op or emit warning
- `_join_or_wait_for_group`: Removed, replaced by future matchmaker variant
- `_create_game_for_group`: Removed, games created via `_create_game_for_match`

## Open Questions

1. **Configuration handling:**
   - What we know: `wait_for_known_group` is a GymScene config property
   - What's unclear: Should it be removed, deprecated with warning, or kept as no-op?
   - Recommendation: Keep property but log warning when True, no functional effect

2. **PlayerPairingManager fate:**
   - What we know: It's still used for group tracking (cleanup_game creates groups)
   - What's unclear: Is it still needed if group reunion is removed?
   - Recommendation: Keep it - groups are still tracked for future use

## Sources

### Primary (HIGH confidence)
- `interactive_gym/server/game_manager.py` - Analyzed full file, all game creation paths mapped
- `interactive_gym/server/matchmaker.py` - Matchmaker ABC and FIFOMatchmaker implementation
- `.planning/REQUIREMENTS.md` - GAME-01 through GAME-04 requirements
- `.planning/ROADMAP.md` - Phase 60 success criteria

### Secondary (MEDIUM confidence)
- `interactive_gym/server/player_pairing_manager.py` - Group tracking mechanism
- `interactive_gym/scenes/gym_scene.py` - wait_for_known_group configuration

## Metadata

**Confidence breakdown:**
- Code paths to remove: HIGH - Direct code inspection
- Requirements mapping: HIGH - Explicit in REQUIREMENTS.md
- Open questions: MEDIUM - Design decisions needed

**Research date:** 2026-02-03
**Valid until:** N/A (refactoring research, not library research)

---

## Appendix: Complete Code Removal Checklist

### Files to Modify

**game_manager.py:**
- [ ] Remove `_join_or_wait_for_group` method (lines 310-364)
- [ ] Remove `_broadcast_group_waiting_status` method (lines 366-388)
- [ ] Remove `_create_game_for_group` method (lines 390-469)
- [ ] Remove `_add_subject_to_specific_game` method (lines 471-529) - only used by group reunion
- [ ] Remove `remove_from_group_waitroom` method (lines 1665-1691)
- [ ] Remove `check_group_wait_timeouts` method (lines 1696-1709)
- [ ] Remove `handle_group_wait_timeout` method (lines 1711-1732)
- [ ] Remove `group_waitrooms` data structure (line 110)
- [ ] Remove `group_wait_start_times` data structure (line 112)
- [ ] Update `add_subject_to_game` to remove group reunion branch
- [ ] Update docstring to document deferred functionality

**gym_scene.py:**
- [ ] Keep `wait_for_known_group` property but document as future feature
- [ ] Add deprecation note to `group_wait_timeout` property
- [ ] Consider logging warning when wait_for_known_group=True

**app.py (if applicable):**
- [ ] Check for any direct references to group reunion handling

### Success Criteria Mapping

| Requirement | Implementation |
|-------------|----------------|
| GAME-01 | Remove group reunion branch from add_subject_to_game |
| GAME-02 | Delete _create_game_for_group, _join_or_wait_for_group |
| GAME-03 | Already satisfied by matchmaker flow (game created after match) |
| GAME-04 | Document in code and REQUIREMENTS.md as REUN-01/REUN-02 |
