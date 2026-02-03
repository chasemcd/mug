# Research Summary: v1.12 Waiting Room Overhaul

**Project:** Interactive Gym — P2P Multiplayer
**Milestone:** v1.12 Waiting Room Overhaul
**Researched:** 2026-02-02
**Overall confidence:** HIGH

---

## Executive Summary

The "Start button disappears but nothing happens" bug is a **stale GameManager capture** problem. When `GAME_MANAGERS` is keyed by `scene_id` and reused across participant sessions, new participants get routed to a GameManager whose internal state (`waiting_games`, `subject_games`, `active_games`) reflects completed games. The fix requires:

1. **Explicit session lifecycle** — Each game gets a Session object that is destroyed (not reused) when the game ends
2. **Participant state tracking** — Single source of truth for "what state is this participant in?"
3. **Comprehensive cleanup** — All state cleaned on every exit path, not just `games` dict

For the Matchmaker abstraction, the oTree pattern (callback-based `find_match()` method) is ideal for research use cases — simple, Pythonic, and researchers already know Python.

---

## Key Findings by Dimension

### Stack (Session Lifecycle)

| Finding | Confidence |
|---------|------------|
| Root cause: GameManager reuse without state reset | HIGH |
| Pattern: Explicit state machine (WAITING → MATCHED → PLAYING → ENDED → DISPOSED) | HIGH |
| Library: `python-statemachine` for lifecycle callbacks | MEDIUM |
| Anti-pattern: Cleanup in multiple uncoordinated places | HIGH |

**Critical insight:** The current code has 4+ cleanup paths (`_remove_game()`, `cleanup_game()`, `leave_game()`, `remove_player()`) that don't clean all state consistently.

### Features (Matchmaker API)

| Finding | Confidence |
|---------|------------|
| Research matchmaking ≠ game matchmaking (validity > engagement) | HIGH |
| oTree's callback pattern is the right model | HIGH |
| Table stakes: FIFO, timeout, configurable group size | HIGH |
| Differentiator: Custom attributes, historical performance access | MEDIUM |
| Anti-features: SBMM, global pools, backfill, complex DSLs | HIGH |

**Recommended API:**
```python
class Matchmaker(ABC):
    @abstractmethod
    def find_match(self, arriving: ParticipantData, waiting: list[ParticipantData], group_size: int) -> list | None:
        """Return matched group or None to keep waiting."""

    def on_timeout(self, participant: ParticipantData) -> TimeoutAction: ...
    def on_dropout(self, dropped: ParticipantData, remaining: list) -> DropoutAction: ...
```

### Architecture (Component Separation)

| Finding | Confidence |
|---------|------------|
| Session-per-game (not manager-per-scene) is industry standard | HIGH |
| Need ParticipantStateTracker as single source of truth | HIGH |
| Cleanup chain must be explicit and idempotent | HIGH |
| Matchmaker extraction can be deferred (works, just coupled) | MEDIUM |

**Recommended separation:**
- **Matchmaker** — Matching logic, queue management
- **Session** — Single game lifecycle (destroyed when game ends)
- **ParticipantStateTracker** — States: IDLE → IN_WAITROOM → VALIDATING_P2P → IN_GAME → GAME_ENDED

### Pitfalls (Bug Prevention)

| Finding | Confidence |
|---------|------------|
| Stale `waiting_games` list is likely root cause | HIGH |
| Stale `subject_games`/`subject_rooms` not cleaned on disconnect | HIGH |
| 4 race condition patterns documented with prevention code | HIGH |
| Invariant assertions catch bugs early | HIGH |

**Likely root cause path:**
1. Previous game completed, `cleanup_game()` called
2. Removed from `games` dict but `subject_games` not cleaned
3. New participant joins, gets captured by stale mapping
4. No `waiting_room` event emitted due to inconsistent state

---

## Implications for Roadmap

Based on research, suggested phase structure for v1.12:

### Phase 51: Diagnostic Logging & State Validation

**Goal:** Understand exact failure path and add immediate prevention

- Add logging at `join_game` entry: `subject_id in subject_games?`
- Add state validation before routing to GameManager
- Add invariant assertions after state mutations
- Emit error event to client when state is invalid

**Addresses:** PITFALLS.md Strategy 1, 2
**Uses:** Existing logging infrastructure
**Risk:** Low (observation only)

### Phase 52: Comprehensive Cleanup

**Goal:** All exit paths clean all state

- Make `cleanup_game()` clean `subject_games`, `subject_rooms`, `active_games`
- Make `_remove_game()` idempotent
- Cancel timeout handlers on game start
- Clean PyodideCoordinator state on game end
- Add `assert_invariants()` after cleanup

**Addresses:** PITFALLS.md Failure 1-4
**Uses:** Existing cleanup methods
**Avoids:** Cleanup failure pitfalls
**Risk:** Medium (touches critical paths)

### Phase 53: Session Lifecycle

**Goal:** Each game has explicit lifecycle, Session destroyed when game ends

- Create `Session` class wrapping game lifecycle
- Session has explicit states: WAITING → MATCHED → VALIDATING → PLAYING → ENDED
- Session is destroyed (not reused) when game ends
- GameManager creates Session per-game, not per-scene

**Addresses:** ARCHITECTURE.md state machine, STACK.md Pattern 1
**Uses:** Potentially `python-statemachine` library
**Avoids:** Stale state reuse
**Risk:** Medium (new abstraction layer)

### Phase 54: ParticipantStateTracker

**Goal:** Single source of truth prevents routing to wrong game

- Create `ParticipantStateTracker` singleton
- Track participant states: IDLE, IN_WAITROOM, VALIDATING_P2P, IN_GAME, GAME_ENDED
- Check state before routing to GameManager
- Update state at every transition point

**Addresses:** ARCHITECTURE.md state ownership
**Uses:** STACK.md Pattern 2 (ownership tracking)
**Avoids:** Routing bugs
**Risk:** Low (additive, non-breaking)

### Phase 55: Matchmaker Base Class

**Goal:** Pluggable matchmaking abstraction

- Create `Matchmaker` abstract base class
- Create `FIFOMatchmaker` default implementation (refactor existing logic)
- Create `ParticipantData` container with session metadata
- Add `on_timeout()` and `on_dropout()` hooks
- Wire into GameManager

**Addresses:** FEATURES.md recommendations
**Uses:** oTree callback pattern
**Avoids:** Over-engineering (no DSL, no global pools)
**Risk:** Medium (API design)

### Phase 56: Custom Attributes & Assignment Logging

**Goal:** Researchers can pass attributes and analyze match decisions

- Propagate custom attributes from URL params to matchmaker
- Add assignment logging (who matched with whom)
- Expose RTT and prior partners to matchmaker
- Documentation and examples

**Addresses:** FEATURES.md differentiators
**Uses:** Existing `ParticipantSession` data
**Risk:** Low (additive)

---

## Phase Ordering Rationale

1. **Diagnostic first (51)** — Can't fix what you can't see. Logging reveals exact failure path.
2. **Cleanup before new abstractions (52)** — Fixes immediate bug with minimal risk.
3. **Session lifecycle (53)** before **StateTracker (54)** — Session provides the boundaries that StateTracker tracks.
4. **Matchmaker (55)** after lifecycle is solid — Don't build new features on broken foundation.
5. **Attributes/logging (56)** last — Polish once core is stable.

---

## Research Flags for Phases

| Phase | Research Needed? | Reason |
|-------|------------------|--------|
| 51 Diagnostic | No | Standard logging patterns |
| 52 Cleanup | No | Codebase-specific, patterns documented |
| 53 Session | Maybe | `python-statemachine` integration with Flask-SocketIO async |
| 54 StateTracker | No | Simple state tracking |
| 55 Matchmaker | No | oTree pattern well-documented |
| 56 Attributes | No | Extension of existing data flow |

---

## Open Questions

1. **Should GameManagers be deleted entirely or just reset?** — Research suggests per-session is cleaner, but reset() is less disruptive.

2. **Which cleanup path(s) actually run on normal completion?** — Need diagnostic logging to confirm.

3. **Is `waiting_games_lock` consistently used on all paths?** — Race condition risk if not.

4. **How should Matchmaker be configured per-scene?** — Property on GymScene vs separate config file.

---

## Files Created

| File | Purpose |
|------|---------|
| `.planning/research/STACK.md` | Session lifecycle patterns, cleanup strategies |
| `.planning/research/FEATURES.md` | Matchmaker API design, table stakes vs differentiators |
| `.planning/research/ARCHITECTURE.md` | Component separation, state machine, build order |
| `.planning/research/PITFALLS.md` | Bug patterns, race conditions, prevention strategies |
| `.planning/research/SUMMARY.md` | This synthesis with roadmap implications |

---

## Next Steps

1. `/gsd:define-requirements` — Finalize checkable requirements from this research
2. `/gsd:create-roadmap` — Create phases 51-56 based on implications above

<sub>`/clear` first for fresh context</sub>
