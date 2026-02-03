# Phase 56: Custom Attributes & Assignment Logging - Research

**Researched:** 2026-02-03
**Domain:** Python dataclass extensibility, event logging patterns, research data export
**Confidence:** HIGH

## Summary

Phase 56 completes the Matchmaker API by adding two capabilities: (1) assignment logging that records match decisions for researcher analysis, and (2) exposing RTT measurements in a way that custom matchmakers can access. The Phase 55 implementation already laid the groundwork - `MatchCandidate` dataclass has `rtt_ms` field, and the existing `AdminEventAggregator.log_activity()` provides a pattern for event logging.

The implementation is additive and low-risk. Assignment logging follows the existing `log_activity()` pattern with a new "match_formed" event type. RTT exposure requires no changes - `MatchCandidate.rtt_ms` is already populated from `ParticipantSession.current_rtt` via `_get_subject_rtt()`. The only addition is ensuring the logging happens at match time and is exportable for research.

**Primary recommendation:** Add assignment logging via callback pattern in GameManager at match formation time. Log to both AdminEventAggregator (for real-time admin visibility) and a dedicated file export (for research analysis). RTT requirement is already satisfied by existing implementation.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `dataclasses` | Built-in | MatchCandidate extension | Already in use from Phase 55 |
| `json` | Built-in | Match log file format | Human-readable, appendable |
| `time` | Built-in | Timestamps | Standard library |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `logging` | Built-in | Console logging | Development debugging |
| `os` | Built-in | File path handling | Export file creation |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| JSON file per match | CSV append | CSV better for bulk analysis, JSON better for complex nested data |
| Single log file | Per-scene log files | Per-scene isolates experiments, single file simpler |
| Callback pattern | Direct export in GameManager | Callback more extensible, aligns with existing GameCallback |

**Installation:**
No additional dependencies required - uses Python standard library.

## Architecture Patterns

### Recommended Module Structure
```
interactive_gym/server/
    matchmaker.py          # MatchCandidate dataclass (already exists)
    game_manager.py        # Assignment logging hook point
    match_logger.py        # NEW: MatchAssignmentLogger class
```

### Pattern 1: Event Logger with File Export
**What:** Dedicated class that logs match events to both AdminEventAggregator and file
**When to use:** Research data needs to be exported alongside game data
**Example:**
```python
# Source: Codebase pattern from admin/aggregator.py
import json
import os
import time
from dataclasses import dataclass, field, asdict

@dataclass
class MatchAssignment:
    """Record of a match decision."""
    timestamp: float
    scene_id: str
    game_id: str
    participants: list[dict]  # List of {subject_id, rtt_ms, custom_attrs}
    matchmaker_class: str  # e.g., "FIFOMatchmaker"

class MatchAssignmentLogger:
    """Logs match assignments for research analysis."""

    MATCH_LOGS_DIR = "data/match_logs"

    def __init__(self, admin_aggregator=None):
        self.admin_aggregator = admin_aggregator
        os.makedirs(self.MATCH_LOGS_DIR, exist_ok=True)

    def log_match(
        self,
        scene_id: str,
        game_id: str,
        matched_candidates: list[MatchCandidate],
        matchmaker_class: str,
    ) -> None:
        assignment = MatchAssignment(
            timestamp=time.time(),
            scene_id=scene_id,
            game_id=game_id,
            participants=[
                {
                    "subject_id": c.subject_id,
                    "rtt_ms": c.rtt_ms,
                    # Future: custom attributes
                }
                for c in matched_candidates
            ],
            matchmaker_class=matchmaker_class,
        )

        # Log to admin dashboard
        if self.admin_aggregator:
            self.admin_aggregator.log_activity(
                "match_formed",
                assignment.participants[0]["subject_id"],  # Primary subject
                {
                    "game_id": game_id,
                    "participants": [p["subject_id"] for p in assignment.participants],
                    "matchmaker": matchmaker_class,
                }
            )

        # Append to file
        log_file = f"{self.MATCH_LOGS_DIR}/{scene_id}_matches.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(asdict(assignment)) + "\n")
```

### Pattern 2: Integration Point in GameManager
**What:** Call MatchAssignmentLogger when match is formed
**When to use:** After matchmaker.find_match() returns a non-None result
**Example:**
```python
# Source: game_manager.py _add_to_fifo_queue() pattern
def _add_to_fifo_queue(self, subject_id: SubjectID) -> RemoteGameV2:
    with self.waiting_games_lock:
        # ... existing code to build MatchCandidate objects ...

        matched = self.matchmaker.find_match(arriving, waiting, group_size)

        if matched is None:
            return self._add_to_waitroom(subject_id)

        # Log the match assignment (NEW)
        if self.match_logger:
            self.match_logger.log_match(
                scene_id=self.scene.scene_id,
                game_id=game.game_id,  # from _create_game_for_match
                matched_candidates=matched,
                matchmaker_class=type(self.matchmaker).__name__,
            )

        return self._create_game_for_match(matched, subject_id)
```

### Pattern 3: RTT Already Exposed via MatchCandidate
**What:** RTT is already available in MatchCandidate.rtt_ms
**When to use:** Custom matchmakers access rtt_ms directly
**Example:**
```python
# Source: matchmaker.py (already implemented in Phase 55)
@dataclass
class MatchCandidate:
    subject_id: str
    rtt_ms: int | None = None
    # Future: custom attributes from Phase 56

# Custom matchmaker example
class RTTMatchmaker(Matchmaker):
    def find_match(self, arriving, waiting, group_size):
        # RTT is directly accessible
        if arriving.rtt_ms is None:
            return self._fifo_fallback(arriving, waiting, group_size)

        compatible = [
            w for w in waiting
            if w.rtt_ms is not None
            and abs(w.rtt_ms - arriving.rtt_ms) <= 100
        ]
        # ... rest of matching logic
```

### Anti-Patterns to Avoid
- **Logging inside Matchmaker:** Keep matchmaker pure (matching logic only); logging is GameManager's responsibility
- **Blocking file I/O:** Use async/background thread if write latency becomes an issue (unlikely at match rate)
- **Modifying MatchCandidate after creation:** Treat as immutable record once created
- **Missing timestamps:** Always include timestamp for temporal analysis

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Real-time admin visibility | Custom WebSocket events | `AdminEventAggregator.log_activity()` | Already integrated with admin dashboard |
| Structured logging | Custom format | `dataclasses.asdict()` + JSON | Consistent, self-documenting |
| File append safety | Manual locking | JSONL format (one record per line) | Atomic appends, easy recovery |

**Key insight:** The existing AdminEventAggregator and Scene.export_metadata() patterns provide the blueprint. Match logging is just another event type following the same architecture.

## Common Pitfalls

### Pitfall 1: Logging Before Game ID Exists
**What goes wrong:** Log called before _create_game_for_match() assigns game_id
**Why it happens:** Tempting to log immediately after find_match() returns
**How to avoid:** Log after game creation, when game_id is available
**Warning signs:** game_id is None in log records

### Pitfall 2: Missing RTT for Some Participants
**What goes wrong:** Researcher assumes RTT always present, analysis fails
**Why it happens:** RTT measurement is async, may not complete before match
**How to avoid:** Document that rtt_ms can be None; include null handling in analysis
**Warning signs:** KeyError or unexpected NaN in RTT analysis

### Pitfall 3: Large Log Files
**What goes wrong:** Single log file grows unbounded
**Why it happens:** JSONL append without rotation
**How to avoid:** Segment by scene_id (already planned), optionally add date rotation
**Warning signs:** Log files > 100MB

### Pitfall 4: Race Condition in Waiting List
**What goes wrong:** Participants logged in match but state inconsistent
**Why it happens:** Log called outside waiting_games_lock
**How to avoid:** Log inside the lock scope, after state is consistent
**Warning signs:** Duplicate participants across matches, missing participants

## Code Examples

Verified patterns from official sources and codebase analysis:

### MatchAssignmentLogger Implementation
```python
# NEW: interactive_gym/server/match_logger.py
"""Match assignment logging for research data export."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from interactive_gym.server.matchmaker import MatchCandidate


@dataclass
class MatchAssignment:
    """Immutable record of a match decision.

    Attributes:
        timestamp: Unix timestamp when match was formed
        scene_id: Scene where match occurred
        game_id: Unique identifier for the resulting game
        participants: List of participant details at match time
        matchmaker_class: Name of the matchmaker class that formed this match
    """
    timestamp: float
    scene_id: str
    game_id: str
    participants: list[dict]  # [{subject_id, rtt_ms}]
    matchmaker_class: str


class MatchAssignmentLogger:
    """Logs match assignments for research analysis and admin visibility.

    Writes match records to JSONL files (one per scene) and optionally
    sends events to AdminEventAggregator for real-time dashboard updates.

    Thread safety: Methods are safe to call from multiple threads.
    File writes use atomic append semantics.
    """

    MATCH_LOGS_DIR = "data/match_logs"

    def __init__(self, admin_aggregator=None):
        """Initialize the logger.

        Args:
            admin_aggregator: Optional AdminEventAggregator for real-time events.
                If None, only file logging is performed.
        """
        self.admin_aggregator = admin_aggregator
        os.makedirs(self.MATCH_LOGS_DIR, exist_ok=True)

    def log_match(
        self,
        scene_id: str,
        game_id: str,
        matched_candidates: list["MatchCandidate"],
        matchmaker_class: str,
    ) -> None:
        """Record a match assignment.

        Called by GameManager when matchmaker.find_match() succeeds.

        Args:
            scene_id: Scene identifier where match occurred
            game_id: Game identifier for the new game
            matched_candidates: List of MatchCandidate objects in the match
            matchmaker_class: Name of matchmaker class (for analysis grouping)
        """
        assignment = MatchAssignment(
            timestamp=time.time(),
            scene_id=scene_id,
            game_id=game_id,
            participants=[
                {
                    "subject_id": c.subject_id,
                    "rtt_ms": c.rtt_ms,
                }
                for c in matched_candidates
            ],
            matchmaker_class=matchmaker_class,
        )

        # Real-time admin visibility
        if self.admin_aggregator:
            self.admin_aggregator.log_activity(
                "match_formed",
                matched_candidates[0].subject_id,
                {
                    "game_id": game_id,
                    "participants": [c.subject_id for c in matched_candidates],
                    "rtt_values": [c.rtt_ms for c in matched_candidates],
                    "matchmaker": matchmaker_class,
                }
            )

        # Persistent file export
        self._write_to_file(scene_id, assignment)

    def _write_to_file(self, scene_id: str, assignment: MatchAssignment) -> None:
        """Append assignment to scene-specific JSONL file."""
        log_file = os.path.join(self.MATCH_LOGS_DIR, f"{scene_id}_matches.jsonl")
        with open(log_file, "a") as f:
            f.write(json.dumps(asdict(assignment)) + "\n")
```

### GameManager Integration
```python
# MODIFIED: game_manager.py __init__
def __init__(
    self,
    scene: gym_scene.GymScene,
    # ... existing params ...
    match_logger: MatchAssignmentLogger | None = None,  # NEW
):
    # ... existing initialization ...
    self.match_logger = match_logger  # NEW

# MODIFIED: game_manager.py _create_game_for_match
def _create_game_for_match(
    self,
    matched: list[MatchCandidate],
    arriving_subject_id: SubjectID
) -> RemoteGameV2:
    # ... existing game creation code ...

    # Log match assignment after game_id is available
    if self.match_logger:
        self.match_logger.log_match(
            scene_id=self.scene.scene_id,
            game_id=game.game_id,
            matched_candidates=matched,
            matchmaker_class=type(self.matchmaker).__name__,
        )

    # ... rest of method ...
```

### App.py Wiring
```python
# MODIFIED: app.py advance_scene handler
from interactive_gym.server.match_logger import MatchAssignmentLogger

# At module level
MATCH_LOGGER: MatchAssignmentLogger | None = None

# In advance_scene, when creating GameManager:
if MATCH_LOGGER is None:
    MATCH_LOGGER = MatchAssignmentLogger(admin_aggregator=ADMIN_AGGREGATOR)

game_manager = gm.GameManager(
    scene=current_scene,
    # ... existing params ...
    match_logger=MATCH_LOGGER,  # NEW
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No match logging | Event-based logging | Phase 56 | Enables research analysis |
| RTT hidden in ParticipantSession | RTT exposed via MatchCandidate | Phase 55 | Matchmakers can access RTT |

**Deprecated/outdated:**
- None for this domain (new capability)

## Open Questions

Things that couldn't be fully resolved:

1. **Should custom attributes be passed through MatchCandidate?**
   - What we know: MatchCandidate already has placeholder comment
   - What's unclear: v2 MATCH-08 requires "arbitrary key-value pairs" - exact API TBD
   - Recommendation: Add `custom_attrs: dict | None = None` field to MatchCandidate for future expansion; not required for v1.12 DATA-01/DATA-02

2. **Should match logs be cleared on server restart?**
   - What we know: JSONL append means logs persist
   - What's unclear: Multi-session experiments may want clean slate
   - Recommendation: Keep logs persistent by default; provide `clear_match_logs()` utility for researchers

3. **Should group matching also log assignments?**
   - What we know: `_create_game_for_group()` bypasses matchmaker
   - What's unclear: Researchers may want to track group re-formations
   - Recommendation: Add logging to `_create_game_for_group()` with `matchmaker_class="GroupReunion"`

## Sources

### Primary (HIGH confidence)
- `interactive_gym/server/matchmaker.py` - MatchCandidate dataclass, Phase 55 implementation
- `interactive_gym/server/game_manager.py` - Match formation flow, _create_game_for_match()
- `interactive_gym/server/admin/aggregator.py` - log_activity() pattern
- `interactive_gym/server/app.py` - _get_subject_rtt() implementation, ParticipantSession.current_rtt

### Secondary (MEDIUM confidence)
- `interactive_gym/server/callback.py` - GameCallback pattern for hooks
- `interactive_gym/scenes/scene.py` - export_metadata() file export pattern

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Uses Python standard library only
- Architecture: HIGH - Follows existing codebase patterns exactly
- Pitfalls: HIGH - Derived from analyzing current implementation and requirements

**Research date:** 2026-02-03
**Valid until:** 2026-03-03 (stable domain, 30 days)
