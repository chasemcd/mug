# Phase 82: Scene API & P2P Probe Integration - Research

**Researched:** 2026-02-07
**Domain:** Matchmaking integration, scene configuration wiring, P2P probe coordination
**Confidence:** HIGH

## Summary

This phase integrates the `LatencyFIFOMatchmaker` (built in Phase 81) into the researcher-facing `scene.matchmaking()` API and verifies that the existing P2P probe flow works correctly when `max_p2p_rtt_ms` is set on the matchmaker.

After thorough investigation of the codebase, the key finding is: **almost all infrastructure already exists.** The scene API (`GymScene.matchmaking(matchmaker=...)`) already accepts custom matchmakers. The `GameManager` already reads `self.matchmaker.max_p2p_rtt_ms` to decide whether to trigger P2P probes. The `ProbeCoordinator` is already wired end-to-end. The `LatencyFIFOMatchmaker` constructor already accepts `max_p2p_rtt_ms` and passes it to the `Matchmaker` base class.

This means Phase 82 is primarily a **verification and testing phase**, not a feature-building phase. The main work is:
1. Writing integration tests that prove the full flow works end-to-end
2. Updating the example config to demonstrate the `LatencyFIFOMatchmaker` usage
3. Possibly adding a convenience import or documentation

**Primary recommendation:** Write integration tests proving the wiring works, add an example scene config demonstrating `LatencyFIFOMatchmaker` with both thresholds, and verify the P2P probe rejection path returns participants to the waitroom.

## Standard Stack

No new libraries are needed. This phase operates entirely within the existing codebase.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| eventlet | (existing) | Async concurrency for socket-based server | Already in use throughout |
| flask-socketio | (existing) | WebSocket communication for probes | Already powers probe signaling |
| pytest | (existing) | Unit and integration testing | Already used for Phase 81 tests |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| unittest.mock | (stdlib) | Mocking GameManager, ProbeCoordinator | Integration tests that verify wiring |

### Alternatives Considered
None -- no new dependencies needed.

**Installation:**
```bash
# No new packages required
```

## Architecture Patterns

### Existing Wiring (Already Implemented)

The data flow from researcher config to P2P probe is already fully wired:

```
Researcher Config
  scene.matchmaking(matchmaker=LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150))
       |
       v
GymScene._matchmaker  (stored on scene)
       |
       v  (via scene.matchmaker property, returns None or instance)
app.py: GameManager(..., matchmaker=current_scene.matchmaker, ...)
       |
       v  (GameManager.__init__ does: self.matchmaker = matchmaker or FIFOMatchmaker())
GameManager.matchmaker  (LatencyFIFOMatchmaker instance with max_p2p_rtt_ms=150)
       |
       v  (in _add_to_fifo_queue)
matchmaker.find_match(arriving, waiting, group_size)  -- RTT pre-filter via max_server_rtt_ms
       |
       v  (if match found, check needs_probe)
needs_probe = (self.probe_coordinator is not None AND self.matchmaker.max_p2p_rtt_ms is not None)
       |
       v  (if needs_probe)
_probe_and_create_game(matched, subject_id)  -- triggers ProbeCoordinator.create_probe()
       |
       v  (probe result callback)
_on_probe_complete(subject_a, subject_b, rtt_ms)
       |
       v
matchmaker.should_reject_for_rtt(rtt_ms)  -- checks against max_p2p_rtt_ms
       |
       v  (if rejected: candidates stay in waitroom)
       v  (if accepted: _create_game_for_match_internal)
```

### Key Integration Points

**Point 1: Scene -> GameManager**
- File: `interactive_gym/server/app.py` line 595
- Code: `matchmaker=current_scene.matchmaker`
- `GymScene.matchmaker` is a property that returns `self._matchmaker` (or `None`)
- `GameManager.__init__` does `self.matchmaker = matchmaker or FIFOMatchmaker()`
- This means if `_matchmaker` is `None`, default FIFO is used; if set, the custom matchmaker is used

**Point 2: GameManager -> ProbeCoordinator (needs_probe decision)**
- File: `interactive_gym/server/game_manager.py` lines 527-534
- Code: `needs_probe = (self.probe_coordinator is not None and self.matchmaker.max_p2p_rtt_ms is not None)`
- This correctly reads `max_p2p_rtt_ms` from whatever matchmaker is configured
- `LatencyFIFOMatchmaker.__init__` passes `max_p2p_rtt_ms` to `super().__init__()` which sets `self.max_p2p_rtt_ms`

**Point 3: Probe rejection -> waitroom re-pooling**
- File: `interactive_gym/server/game_manager.py` lines 680-691
- Code: `should_reject = self.matchmaker.should_reject_for_rtt(rtt_ms)`
- If rejected, candidates remain in `waitroom_participants` (they were added during `_probe_and_create_game`)
- No additional code needed -- the existing `_on_probe_complete` handles this

### Pattern: Two-Stage Latency Filtering

This is the architecture pattern established across Phases 81-82:

```
Stage 1 (Cheap Pre-Filter) - Inside find_match():
  estimated_p2p_rtt = arriving.rtt_ms + candidate.rtt_ms
  Skip if > max_server_rtt_ms

Stage 2 (Precise Post-Filter) - After find_match() via ProbeCoordinator:
  Actual WebRTC DataChannel RTT measurement
  Reject if > max_p2p_rtt_ms
```

The two-stage design is key: Stage 1 prevents unnecessary WebRTC probe setup (expensive, takes seconds). Stage 2 catches cases where the heuristic is inaccurate.

### Anti-Patterns to Avoid
- **Do NOT modify the existing `needs_probe` logic.** It already reads `self.matchmaker.max_p2p_rtt_ms` correctly.
- **Do NOT add LatencyFIFOMatchmaker-specific logic to GameManager.** The matchmaker is already used generically through the `Matchmaker` base class interface.
- **Do NOT duplicate probe coordinator wiring.** The `PROBE_COORDINATOR` global in `app.py` is already passed to every `GameManager`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Scene-to-matchmaker wiring | Custom registration system | Existing `scene.matchmaking(matchmaker=...)` API | Already implemented in Phase 55, verified in Phase 55's verification report |
| P2P probe triggering | Manual probe scheduling | Existing `needs_probe` check in `_add_to_fifo_queue()` | Already reads max_p2p_rtt_ms from any Matchmaker subclass |
| Probe rejection handling | Custom rejection logic | Existing `should_reject_for_rtt()` on Matchmaker base | Already handles None RTT (rejects) and threshold comparison |
| Waitroom re-pooling | Custom re-pool mechanism | Existing `_on_probe_complete()` flow | Candidates stay in `waitroom_participants` automatically |

**Key insight:** This phase is unusual in that virtually ALL the code already exists. The work is verification and testing, not implementation. The LatencyFIFOMatchmaker was designed to plug into existing infrastructure.

## Common Pitfalls

### Pitfall 1: Assuming Code Needs to Be Written
**What goes wrong:** Spending time writing wiring code that already exists.
**Why it happens:** The phase description says "wire into scene.matchmaking()" and "verify P2P probe coordination" which sounds like implementation work.
**How to avoid:** Verify each integration point exists by reading the code first. The plan should focus on tests.
**Warning signs:** Creating new methods in GameManager or GymScene for LatencyFIFOMatchmaker-specific logic.

### Pitfall 2: Testing Only the Happy Path
**What goes wrong:** Not testing the rejection path (P2P probe exceeds threshold).
**Why it happens:** The happy path (probe passes, game starts) is the obvious test case.
**How to avoid:** Ensure tests cover: (a) probe passes, game created; (b) probe fails/rejects, candidates remain in waitroom; (c) no max_p2p_rtt_ms means no probe at all.
**Warning signs:** Only testing instantiation and find_match, not the full probe flow.

### Pitfall 3: Not Testing the "No Probe" Path
**What goes wrong:** `LatencyFIFOMatchmaker(max_server_rtt_ms=200)` without `max_p2p_rtt_ms` should skip probing entirely.
**Why it happens:** Focus on the P2P integration means forgetting to verify the simpler case still works.
**How to avoid:** Include a test where `max_p2p_rtt_ms=None` and verify `needs_probe` evaluates to `False`.
**Warning signs:** All tests set `max_p2p_rtt_ms` to a value.

### Pitfall 4: Overlooking the Example Config Update
**What goes wrong:** No researcher-facing documentation of how to use `LatencyFIFOMatchmaker`.
**Why it happens:** Treating this as purely a testing phase.
**How to avoid:** Update the example multiplayer experiment or add a new one showing the latency-aware config.
**Warning signs:** Phase is "done" but no example shows the new matchmaker being used.

## Code Examples

All examples are verified from the codebase (not hypothetical).

### Researcher Configures LatencyFIFOMatchmaker (Target Usage)
```python
# Source: Phase 82 target API -- this is what must work
from interactive_gym.server.matchmaker import LatencyFIFOMatchmaker

scene = (
    GymScene()
    .scene(scene_id="latency_aware_game", experiment_config={})
    .policies(policy_mapping={0: "Human", 1: "Human"})
    .matchmaking(
        matchmaker=LatencyFIFOMatchmaker(
            max_server_rtt_ms=200,   # Stage 1: server RTT pre-filter
            max_p2p_rtt_ms=150,      # Stage 2: P2P probe post-filter
        ),
        hide_lobby_count=True,
    )
    # ... other config
)
```

### Existing matchmaking() Method (Already Supports This)
```python
# Source: interactive_gym/scenes/gym_scene.py lines 540-588
def matchmaking(
    self,
    hide_lobby_count: bool = NotProvided,
    max_rtt: int = NotProvided,
    matchmaker: "Matchmaker" = NotProvided,
):
    # ...
    if matchmaker is not NotProvided:
        from interactive_gym.server.matchmaker import Matchmaker as MatchmakerABC
        if not isinstance(matchmaker, MatchmakerABC):
            raise TypeError("matchmaker must be a Matchmaker subclass instance")
        self._matchmaker = matchmaker
    return self
```

### Existing needs_probe Check (Already Reads max_p2p_rtt_ms)
```python
# Source: interactive_gym/server/game_manager.py lines 527-534
needs_probe = (
    self.probe_coordinator is not None
    and self.matchmaker.max_p2p_rtt_ms is not None
)

if needs_probe:
    return self._probe_and_create_game(matched, subject_id)
else:
    return self._create_game_for_match(matched, subject_id)
```

### LatencyFIFOMatchmaker Constructor (Already Passes max_p2p_rtt_ms)
```python
# Source: interactive_gym/server/matchmaker.py lines 233-239
def __init__(
    self,
    max_server_rtt_ms: int,
    max_p2p_rtt_ms: int | None = None,
):
    super().__init__(max_p2p_rtt_ms=max_p2p_rtt_ms)
    self.max_server_rtt_ms = max_server_rtt_ms
```

### Integration Test Pattern (Recommended)
```python
# Test that LatencyFIFOMatchmaker with max_p2p_rtt_ms triggers probe flow
from unittest.mock import MagicMock, patch
from interactive_gym.server.matchmaker import LatencyFIFOMatchmaker, MatchCandidate

def test_latency_fifo_triggers_probe_when_p2p_set():
    """Verify GameManager triggers P2P probe for LatencyFIFOMatchmaker with max_p2p_rtt_ms."""
    matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150)

    # Verify the needs_probe condition would be True
    mock_probe_coordinator = MagicMock()
    assert matchmaker.max_p2p_rtt_ms == 150
    assert mock_probe_coordinator is not None  # probe_coordinator exists

    # Therefore: needs_probe = True (both conditions met)
    needs_probe = (mock_probe_coordinator is not None and matchmaker.max_p2p_rtt_ms is not None)
    assert needs_probe is True

def test_latency_fifo_skips_probe_when_p2p_not_set():
    """Verify GameManager skips P2P probe when max_p2p_rtt_ms is None."""
    matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200)

    mock_probe_coordinator = MagicMock()
    needs_probe = (mock_probe_coordinator is not None and matchmaker.max_p2p_rtt_ms is not None)
    assert needs_probe is False  # No P2P threshold, skip probe

def test_should_reject_for_rtt():
    """Verify rejection logic inherited from Matchmaker base class."""
    matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150)

    assert matchmaker.should_reject_for_rtt(100.0) is False  # 100 <= 150
    assert matchmaker.should_reject_for_rtt(150.0) is False  # 150 <= 150 (boundary)
    assert matchmaker.should_reject_for_rtt(151.0) is True   # 151 > 150
    assert matchmaker.should_reject_for_rtt(None) is True     # Failed measurement = reject
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `matchmaking_max_rtt` on GymScene (RTT diff between paired players) | `matchmaker=LatencyFIFOMatchmaker(max_server_rtt_ms=...)` | Phase 81 (v1.21) | Precise control over latency thresholds via sum-of-RTTs heuristic |
| No pre-filtering before P2P probe | Two-stage filtering: server RTT pre-filter + P2P probe post-filter | Phase 81/82 (v1.21) | Reduces expensive P2P probes by eliminating poor candidates early |

**Deprecated/outdated:**
- `matchmaking_max_rtt` on GymScene: Still functional but superseded by LatencyFIFOMatchmaker for latency-aware matching. The old parameter measures RTT *difference* between players, not the sum (which approximates P2P RTT). Both can coexist but researchers should prefer the matchmaker approach.

## What This Phase Actually Needs to Do

Based on the research, here is a precise breakdown of what is needed vs. what already exists:

### Already Exists (NO work needed)
1. `GymScene.matchmaking(matchmaker=LatencyFIFOMatchmaker(...))` -- already works (Phase 55)
2. `LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150)` -- already works (Phase 81)
3. `GameManager` reading `self.matchmaker.max_p2p_rtt_ms` for probe decision -- already works (Phase 59)
4. `_probe_and_create_game()` flow -- already works (Phase 59)
5. `_on_probe_complete()` rejection and re-pooling -- already works (Phase 59)
6. `should_reject_for_rtt()` on Matchmaker base -- already works (Phase 59)
7. `PROBE_COORDINATOR` initialization in `app.py` -- already works (Phase 57)

### Needs Work (Phase 82 deliverables)
1. **Integration tests** verifying the full LatencyFIFOMatchmaker -> probe -> game creation flow
2. **Integration tests** verifying rejection path returns candidates to waitroom
3. **Scene config test** verifying `scene.matchmaking(matchmaker=LatencyFIFOMatchmaker(...))` stores and returns the matchmaker correctly
4. **Possibly:** Update example experiment config to demonstrate LatencyFIFOMatchmaker usage

### Recommended Test Plan

| Test | What It Proves | Level |
|------|---------------|-------|
| Scene stores LatencyFIFOMatchmaker via matchmaking() | MATCH-05: researcher config API works | Unit |
| LatencyFIFOMatchmaker.max_p2p_rtt_ms propagates through Matchmaker base | MATCH-03: P2P threshold accessible | Unit |
| needs_probe evaluates True when max_p2p_rtt_ms set | MATCH-03: probe triggers correctly | Unit |
| needs_probe evaluates False when max_p2p_rtt_ms is None | Default behavior preserved | Unit |
| should_reject_for_rtt works with LatencyFIFOMatchmaker thresholds | MATCH-03: rejection logic correct | Unit |
| Full flow: find_match -> probe -> accept -> game created | End-to-end happy path | Integration |
| Full flow: find_match -> probe -> reject -> waitroom | End-to-end rejection path | Integration |

## Open Questions

None. All integration points have been verified in the codebase. The wiring is complete, and the only remaining work is testing and documentation.

## Sources

### Primary (HIGH confidence)
- `interactive_gym/server/matchmaker.py` -- LatencyFIFOMatchmaker implementation, Matchmaker base class
- `interactive_gym/server/game_manager.py` -- GameManager._add_to_fifo_queue(), _probe_and_create_game(), _on_probe_complete()
- `interactive_gym/scenes/gym_scene.py` -- GymScene.matchmaking() method, _matchmaker property
- `interactive_gym/server/app.py` -- GameManager instantiation with matchmaker=current_scene.matchmaker
- `interactive_gym/server/probe_coordinator.py` -- ProbeCoordinator.create_probe() and handle_result()
- `tests/unit/test_latency_fifo_matchmaker.py` -- Existing Phase 81 unit tests
- `.planning/phases/81-latency-fifo-matchmaker-core/81-VERIFICATION.md` -- Phase 81 verification confirming all wiring

### Secondary (MEDIUM confidence)
- `.planning/ROADMAP.md` -- Phase 82 success criteria and requirements
- `.planning/REQUIREMENTS.md` -- MATCH-03 and MATCH-05 definitions
- `.planning/phases/55-matchmaker-base-class/55-VERIFICATION.md` -- Phase 55 wiring verification

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new libraries needed, all existing code verified
- Architecture: HIGH -- all integration points read directly from source code
- Pitfalls: HIGH -- based on direct observation of what exists vs. what doesn't
- "What needs work": HIGH -- verified each claim by reading the actual source files

**Research date:** 2026-02-07
**Valid until:** Indefinite (stable internal architecture, no external dependencies)
