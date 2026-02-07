# Phase 55: Matchmaker Base Class - Research

**Researched:** 2026-02-03
**Domain:** Python abstract base class design, multiplayer matchmaking patterns
**Confidence:** HIGH

## Summary

Phase 55 introduces a pluggable matchmaking abstraction that allows researchers to customize how participants are grouped together. The current codebase uses a hard-coded FIFO matching strategy with optional RTT filtering in `GameManager._add_to_fifo_queue()`. This phase extracts that logic into an abstract `Matchmaker` base class with a `FIFOMatchmaker` default implementation.

The design follows oTree's successful `group_by_arrival_time_method()` pattern, where a function receives the arriving participant, the current waiting list, and returns either a matched group or None to continue waiting. Python's `abc.ABC` provides the standard mechanism for defining the abstract interface.

**Primary recommendation:** Use Python's `abc.ABC` with `@abstractmethod` decorator for the Matchmaker base class. The `find_match()` method receives (arriving_participant, waiting_list, group_size) and returns either a list of matched participants or None. Configuration happens via the scene's existing `matchmaking()` method.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `abc` | Built-in | Abstract base class support | Python standard library, no dependencies |
| `typing` | Built-in | Type hints for ABC methods | Enables IDE support, documentation |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `dataclasses` | Built-in | Participant context objects | Structured data for matchmaker input |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ABC inheritance | Protocol (structural typing) | Protocol is more flexible but ABC enforces implementation at instantiation time |
| Function-based (oTree style) | Class-based | Class allows state/config; function is simpler for stateless matching |

**Installation:**
No additional dependencies required - uses Python standard library.

## Architecture Patterns

### Recommended Module Structure
```
interactive_gym/server/
    matchmaker.py          # NEW: Matchmaker ABC and FIFOMatchmaker
    game_manager.py        # MODIFIED: Uses Matchmaker via delegation
```

### Pattern 1: Abstract Base Class with abstractmethod
**What:** Define interface via ABC inheritance with @abstractmethod decorator
**When to use:** Enforcing method implementation at instantiation time
**Example:**
```python
# Source: https://docs.python.org/3/library/abc.html
from abc import ABC, abstractmethod
from typing import TypeVar, Generic
from dataclasses import dataclass

SubjectID = str

@dataclass
class MatchCandidate:
    """Context for matchmaking decisions."""
    subject_id: SubjectID
    rtt_ms: int | None = None
    # Future: custom attributes from Phase 56

class Matchmaker(ABC):
    """Abstract base class for matchmaking strategies.

    Subclasses implement find_match() to determine when and how
    participants are grouped together for a game.
    """

    @abstractmethod
    def find_match(
        self,
        arriving: MatchCandidate,
        waiting: list[MatchCandidate],
        group_size: int,
    ) -> list[MatchCandidate] | None:
        """Attempt to form a group including the arriving participant.

        Args:
            arriving: The participant who just arrived at waitroom
            waiting: List of participants already waiting
            group_size: Number of participants needed for a full group

        Returns:
            List of exactly group_size MatchCandidates if match found,
            None if arriving participant should wait.
        """
        ...
```

### Pattern 2: Strategy Pattern via Dependency Injection
**What:** Pass Matchmaker instance to GameManager at construction time
**When to use:** Configuration should happen at scene setup, not runtime
**Example:**
```python
# Source: interactive_gym codebase patterns
class GameManager:
    def __init__(
        self,
        scene: gym_scene.GymScene,
        matchmaker: Matchmaker | None = None,  # NEW parameter
        ...
    ):
        # Use provided matchmaker or default to FIFO
        self.matchmaker = matchmaker or FIFOMatchmaker()
```

### Pattern 3: oTree-Inspired Return Semantics
**What:** Return matched list or None (not throw/raise for "no match yet")
**When to use:** Distinguish "no match possible" from "wait for more participants"
**Example:**
```python
# Source: https://otree.readthedocs.io/en/latest/multiplayer/waitpages.html
def find_match(self, arriving, waiting, group_size) -> list | None:
    # Return None = "keep waiting"
    if len(waiting) + 1 < group_size:
        return None

    # Return list = "these participants form a group"
    return [arriving] + waiting[:group_size - 1]
```

### Anti-Patterns to Avoid
- **Hard-coded matching in GameManager:** Current pattern couples matching logic to game management
- **Exception-based flow control:** Don't throw "NoMatchYet" exceptions - use None return
- **Stateful matchmakers without clear lifecycle:** If matchmaker has state, clarify when it resets
- **Accessing GameManager internals from Matchmaker:** Matchmaker should only use provided context

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Abstract class enforcement | NotImplementedError in base | `@abstractmethod` from abc | Catches missing implementations at instantiation, not runtime |
| Type checking for subclasses | isinstance() everywhere | ABC registration mechanism | ABC handles this automatically |
| Configuration validation | Manual validation code | Pydantic or dataclasses with validators | More robust, less error-prone |

**Key insight:** Python's abc module provides everything needed for abstract interfaces. Don't reinvent method enforcement - @abstractmethod does it better.

## Common Pitfalls

### Pitfall 1: Forgetting @abstractmethod Makes Methods Optional
**What goes wrong:** Base class method without decorator can be called, returning None
**Why it happens:** Python doesn't enforce method implementation by default
**How to avoid:** Always use @abstractmethod for interface methods
**Warning signs:** Subclass instantiates without implementing all methods

### Pitfall 2: Mutating the Waiting List
**What goes wrong:** Matchmaker modifies waiting list, causing race conditions
**Why it happens:** List passed by reference, intuitive to remove matched participants
**How to avoid:** Matchmaker returns new list of matched participants; GameManager handles removal
**Warning signs:** Duplicate participants, missing participants, index errors

### Pitfall 3: Not Including Arriving Participant in Result
**What goes wrong:** Returns only existing waiting participants, arriving is lost
**Why it happens:** Method receives arriving separately from waiting
**How to avoid:** Clear documentation: result MUST include arriving if match succeeds
**Warning signs:** Group has group_size-1 participants

### Pitfall 4: RTT Data Stale or Missing
**What goes wrong:** Matchmaker uses None RTT, makes wrong pairing decisions
**Why it happens:** RTT measurement is async, may not be ready when participant arrives
**How to avoid:** MatchCandidate includes rtt_ms: int | None, matchmaker handles None case
**Warning signs:** RTT-based matchmaker pairs participants with very different latencies

## Code Examples

Verified patterns from official sources and codebase analysis:

### FIFOMatchmaker Default Implementation
```python
# Based on current _add_to_fifo_queue() logic
class FIFOMatchmaker(Matchmaker):
    """First-in-first-out matchmaking (current default behavior).

    Matches participants in arrival order without any filtering.
    """

    def find_match(
        self,
        arriving: MatchCandidate,
        waiting: list[MatchCandidate],
        group_size: int,
    ) -> list[MatchCandidate] | None:
        # Need enough participants to form a group
        if len(waiting) + 1 < group_size:
            return None

        # Take first (group_size - 1) waiting participants + arriving
        matched = waiting[:group_size - 1] + [arriving]
        return matched
```

### RTT-Filtered Matchmaker Example
```python
# Based on current _is_rtt_compatible() logic
class RTTMatchmaker(Matchmaker):
    """Matches participants with similar network latency."""

    def __init__(self, max_rtt_difference_ms: int = 100):
        self.max_rtt_diff = max_rtt_difference_ms

    def find_match(
        self,
        arriving: MatchCandidate,
        waiting: list[MatchCandidate],
        group_size: int,
    ) -> list[MatchCandidate] | None:
        if arriving.rtt_ms is None:
            # No RTT data - fall back to FIFO
            return self._fifo_match(arriving, waiting, group_size)

        # Find compatible participants
        compatible = [
            w for w in waiting
            if w.rtt_ms is not None
            and abs(w.rtt_ms - arriving.rtt_ms) <= self.max_rtt_diff
        ]

        if len(compatible) + 1 < group_size:
            return None

        return compatible[:group_size - 1] + [arriving]
```

### Integration Point in GameManager
```python
# Existing: game_manager.py add_subject_to_game()
def add_subject_to_game(self, subject_id: SubjectID) -> RemoteGameV2 | None:
    # ... existing group waitroom logic ...

    # Build MatchCandidate for arriving participant
    arriving = MatchCandidate(
        subject_id=subject_id,
        rtt_ms=self.get_subject_rtt(subject_id) if self.get_subject_rtt else None,
    )

    # Build waiting list
    waiting = [
        MatchCandidate(
            subject_id=sid,
            rtt_ms=self.get_subject_rtt(sid) if self.get_subject_rtt else None,
        )
        for sid in self._get_waiting_subject_ids()
    ]

    # Delegate to matchmaker
    matched = self.matchmaker.find_match(arriving, waiting, self._get_group_size())

    if matched is None:
        # Add to waiting, no match yet
        return self._add_to_waitroom(subject_id)

    # Create game with matched participants
    return self._create_game_for_matched(matched)
```

### Scene Configuration
```python
# Proposed: gym_scene.py matchmaking() method extension
def matchmaking(
    self,
    hide_lobby_count: bool = NotProvided,
    max_rtt: int = NotProvided,
    matchmaker: Matchmaker = NotProvided,  # NEW
):
    """Configure matchmaking and lobby settings."""
    # ... existing logic ...

    if matchmaker is not NotProvided:
        self._matchmaker = matchmaker

    return self
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Callback functions (oTree style) | ABC classes | Python 3.4+ | Type safety, IDE support |
| Protocol (structural typing) | ABC (nominal typing) | Both valid | ABC catches errors at instantiation |

**Deprecated/outdated:**
- `ABCMeta` metaclass: Use `ABC` class inheritance instead (cleaner syntax)
- `raise NotImplementedError`: Use `@abstractmethod` instead (catches errors earlier)

## Open Questions

Things that couldn't be fully resolved:

1. **Should Matchmaker have access to full participant data?**
   - What we know: Current RTT is available via ParticipantSession
   - What's unclear: Future phases may need custom attributes (Phase 56)
   - Recommendation: Use extensible MatchCandidate dataclass that can grow

2. **How to handle matchmaker state between requests?**
   - What we know: Matchmaker is per-GameManager, GameManager is per-scene
   - What's unclear: Should matchmaker reset when scene resets?
   - Recommendation: Keep matchmaker stateless for simplicity; if state needed, document lifecycle

3. **Thread safety for custom matchmakers?**
   - What we know: GameManager uses locks around add_subject_to_game
   - What's unclear: Custom matchmaker may introduce race conditions
   - Recommendation: Document that find_match() is called under lock; matchmaker should not spawn threads

## Sources

### Primary (HIGH confidence)
- [Python abc module documentation](https://docs.python.org/3/library/abc.html) - ABC patterns, @abstractmethod usage
- `interactive_gym/server/game_manager.py` - Current FIFO matching implementation
- `interactive_gym/server/participant_state.py` - ParticipantState patterns

### Secondary (MEDIUM confidence)
- [oTree wait pages documentation](https://otree.readthedocs.io/en/latest/multiplayer/waitpages.html) - group_by_arrival_time_method pattern
- [oTree groups documentation](https://otree.readthedocs.io/en/latest/multiplayer/groups.html) - Group matching extensibility points

### Tertiary (LOW confidence)
- WebSearch for ABC best practices 2025 - General patterns confirmed with official docs

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Uses Python standard library only
- Architecture: HIGH - Based on existing codebase patterns and oTree precedent
- Pitfalls: HIGH - Derived from analyzing current implementation

**Research date:** 2026-02-03
**Valid until:** 2026-03-03 (stable domain, 30 days)
