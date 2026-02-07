# Phase 78: Group History Tracking - Research

**Researched:** 2026-02-07
**Domain:** Server-side group history persistence + matchmaker API extension
**Confidence:** HIGH

## Summary

Phase 78 requires the server to (1) record which participants were paired together after each GymScene completes, and (2) expose that history to custom matchmakers so they can re-pair previous partners. The codebase already has nearly all the infrastructure needed -- the critical finding is that `PlayerGroupManager` (in `player_pairing_manager.py`) already tracks groups and `GameManager.cleanup_game()` already calls `pairing_manager.create_group()` when a game ends. However, the matchmaker's `find_match()` method currently has no access to group history, and the `MatchCandidate` dataclass lacks group context.

The implementation is a narrow, well-scoped change: extend `MatchCandidate` with a `group_history` field, pass group history into the matchmaker at match time, and provide a concrete `GroupReunionMatchmaker` implementation. No new data stores, no new modules, no client-side changes.

**Primary recommendation:** Extend `MatchCandidate` with group history data, inject `PlayerGroupManager` reference into the matchmaker flow in `GameManager._add_to_fifo_queue()`, and provide a `GroupReunionMatchmaker` subclass that prioritizes re-pairing previous partners.

## Standard Stack

No new libraries needed. This phase uses only existing Python standard library and existing project infrastructure.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| dataclasses | stdlib | MatchCandidate extension | Already used for MatchCandidate |
| threading | stdlib | Thread-safe group history access | Already used for PlayerGroupManager.lock |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | existing | Unit tests for matchmaker and group tracking | Testing |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| In-memory PlayerGroupManager | Persistent database/file storage | In-memory is correct for session-scoped data; groups don't need to survive server restarts |
| Extending MatchCandidate | Separate group context parameter | Adding field to MatchCandidate is cleaner and forward-compatible per Phase 56 design comment |

## Architecture Patterns

### Current Architecture (What Exists)

```
PlayerGroupManager (player_pairing_manager.py)
  - subject_groups: dict[SubjectID -> group_id]
  - groups: dict[group_id -> PlayerGroup]
  - create_group(): Called by GameManager.cleanup_game() when game ends
  - get_group_members(): Returns other members of a subject's group
  - get_group_id(): Returns group_id for a subject

GameManager.cleanup_game() (game_manager.py:1388-1438)
  - Already calls self.pairing_manager.create_group(real_subjects, scene_id)
  - Records which subjects were paired after game ends
  - This is the P2P-03 hook -- it ALREADY EXISTS

Matchmaker.find_match() (matchmaker.py:93-121)
  - Receives: arriving: MatchCandidate, waiting: list[MatchCandidate], group_size: int
  - MatchCandidate has: subject_id, rtt_ms
  - No group history context currently available

GameManager._add_to_fifo_queue() (game_manager.py:448-518)
  - Builds MatchCandidate objects from waitroom_participants
  - Calls self.matchmaker.find_match()
  - Does NOT populate any group history onto MatchCandidate
```

### Pattern 1: Extend MatchCandidate with Group History
**What:** Add optional `group_history` field to `MatchCandidate` dataclass
**When to use:** Always -- this is the mechanism for passing group info to matchmakers
**Example:**
```python
# In matchmaker.py
@dataclass
class MatchCandidate:
    subject_id: str
    rtt_ms: int | None = None
    group_history: GroupHistory | None = None  # Phase 78


@dataclass
class GroupHistory:
    """Group membership history for a participant."""
    previous_partners: list[str]  # Subject IDs of previous partners
    source_scene_id: str | None = None  # Scene where group was formed
    group_id: str | None = None  # Group identifier
```

### Pattern 2: Populate Group History in GameManager
**What:** When building MatchCandidate objects in `_add_to_fifo_queue()`, look up group history from `pairing_manager` and attach it
**When to use:** Every time a MatchCandidate is constructed
**Example:**
```python
# In GameManager._add_to_fifo_queue()
def _build_match_candidate(self, subject_id: SubjectID) -> MatchCandidate:
    group_history = None
    if self.pairing_manager:
        partners = self.pairing_manager.get_group_members(subject_id)
        group_id = self.pairing_manager.get_group_id(subject_id)
        if partners:
            group = self.pairing_manager.groups.get(group_id)
            group_history = GroupHistory(
                previous_partners=partners,
                source_scene_id=group.source_scene_id if group else None,
                group_id=group_id,
            )
    return MatchCandidate(
        subject_id=subject_id,
        rtt_ms=self.get_subject_rtt(subject_id) if self.get_subject_rtt else None,
        group_history=group_history,
    )
```

### Pattern 3: GroupReunionMatchmaker
**What:** A concrete `Matchmaker` subclass that checks if the arriving participant's previous partners are in the waiting list, and prioritizes reuniting them
**When to use:** When a researcher wants to re-pair the same partners across scenes
**Example:**
```python
class GroupReunionMatchmaker(Matchmaker):
    """Re-pairs previous partners when possible, falls back to FIFO."""

    def __init__(self, max_p2p_rtt_ms: int | None = None, fallback_to_fifo: bool = True):
        super().__init__(max_p2p_rtt_ms=max_p2p_rtt_ms)
        self.fallback_to_fifo = fallback_to_fifo

    def find_match(
        self,
        arriving: MatchCandidate,
        waiting: list[MatchCandidate],
        group_size: int,
    ) -> list[MatchCandidate] | None:
        # Check if arriving has previous partners
        if arriving.group_history and arriving.group_history.previous_partners:
            previous_partner_ids = set(arriving.group_history.previous_partners)
            # Find previous partners in waiting list
            reunited = [w for w in waiting if w.subject_id in previous_partner_ids]
            if len(reunited) + 1 >= group_size:
                return reunited[:group_size - 1] + [arriving]

        # Fallback to FIFO if no reunion possible
        if self.fallback_to_fifo and len(waiting) + 1 >= group_size:
            return waiting[:group_size - 1] + [arriving]

        return None  # Wait
```

### Anti-Patterns to Avoid
- **Storing group history in a separate global dict:** The `PlayerGroupManager` already serves this purpose. Don't create a parallel tracking system.
- **Modifying `find_match()` signature:** The ABC signature must remain backward-compatible. Group history flows through `MatchCandidate`, not through new parameters.
- **Making group history mandatory:** `MatchCandidate.group_history` must be optional (`None`). Existing matchmakers and code paths that don't need group history should be unaffected.
- **Cleaning up groups on scene advance:** Groups must persist across scenes -- that's the whole point. `cleanup_subject()` (called on disconnect) is the only place groups should be removed.

### Recommended Project Structure
```
interactive_gym/server/
  matchmaker.py           # Extend MatchCandidate, add GroupHistory, add GroupReunionMatchmaker
  player_pairing_manager.py  # No changes needed (already has all required methods)
  game_manager.py         # Populate group_history when building MatchCandidate objects
```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Group tracking | New group history store | `PlayerGroupManager` (already exists) | Already tracks groups, has thread-safe access, called from `cleanup_game()` |
| Passing context to matchmaker | Custom parameter injection | `MatchCandidate.group_history` field | Extensible dataclass pattern already anticipated (see Phase 56 comment in code) |
| Thread safety for group queries | New locks/synchronization | `PlayerGroupManager.lock` | Already protects concurrent group operations |

**Key insight:** The hardest part of this feature (recording who was paired together, persisting across scenes) is already implemented. `GameManager.cleanup_game()` already calls `pairing_manager.create_group()` at line 1428. The only missing piece is making this data available to matchmakers.

## Common Pitfalls

### Pitfall 1: Breaking Backward Compatibility with Matchmaker ABC
**What goes wrong:** Adding a required parameter to `find_match()` or making `group_history` non-optional breaks all existing custom matchmakers.
**Why it happens:** Desire to make the API "clean" by requiring group history.
**How to avoid:** Keep `group_history` as an optional field on `MatchCandidate` (default `None`). The `find_match()` signature stays identical. Existing matchmakers simply ignore the new field.
**Warning signs:** Any change to the `find_match()` method signature.

### Pitfall 2: Group History Not Available for First Scene
**What goes wrong:** In the very first GymScene, no groups exist yet, and the matchmaker receives `group_history=None` for all participants.
**Why it happens:** Groups are only created when a game ends. Before any game completes, no groups exist.
**How to avoid:** `GroupReunionMatchmaker` must handle `group_history=None` gracefully by falling back to FIFO. This is a required behavior, not an edge case.
**Warning signs:** Matchmaker assumes group_history is always populated.

### Pitfall 3: Group Cleaned Up on Disconnect Before Next Scene
**What goes wrong:** When a participant advances from Scene A (GymScene) to Scene B (survey), the disconnect handler calls `GROUP_MANAGER.cleanup_subject()`, which removes the group before the participant reaches the next GymScene.
**Why it happens:** The disconnect handler in `app.py` calls `GROUP_MANAGER.cleanup_subject()` on every disconnect.
**How to avoid:** This is already handled correctly. Looking at `app.py`, `cleanup_subject()` is called on true disconnects, not on scene transitions. The `advance_scene` handler calls `GROUP_MANAGER.update_subject_scene()` (not cleanup). Groups persist across scene advances.
**Warning signs:** Actually, need to verify: if participant disconnects briefly during scene transition and reconnects, the group might get cleaned up. Session restoration logic should be examined.

### Pitfall 4: Race Condition Between Group Creation and Next Scene Entry
**What goes wrong:** Participant A finishes game, `cleanup_game()` creates group, participant A advances to survey, then to next GymScene. Meanwhile participant B is still in cleanup. When A enters the next GymScene's waitroom, B hasn't arrived yet and the group reunion times out.
**Why it happens:** `cleanup_game()` is called for both participants, but scene advancement is asynchronous per-participant.
**How to avoid:** `GroupReunionMatchmaker` should have a configurable timeout or fallback. If previous partners don't arrive within a reasonable window, fall back to FIFO matching. This is already anticipated in the existing `group_wait_timeout` config on GymScene (default 60000ms).
**Warning signs:** Tests only check the happy path where both partners arrive simultaneously.

### Pitfall 5: Overwriting Groups When Re-Matched
**What goes wrong:** If a participant plays in Scene 1 with Partner A, then in Scene 2 is matched via FIFO with Partner B (e.g., because Partner A disconnected), the Scene 2 group overwrites the Scene 1 group. Scene 3 now sees Partner B, not Partner A.
**Why it happens:** `PlayerGroupManager.create_group()` replaces existing groups (calls `_remove_from_existing_group` first).
**How to avoid:** This is actually correct behavior -- the most recent pairing is the one that should be used for reunion. But document this clearly. A researcher who wants to track ALL historical pairings would need a different data structure.
**Warning signs:** Confusion about whether group_history means "most recent partner" or "all historical partners".

## Code Examples

### Example 1: GroupHistory Dataclass
```python
# Source: New code for matchmaker.py
@dataclass
class GroupHistory:
    """Group membership history for a participant.

    Provided to matchmakers via MatchCandidate.group_history to enable
    re-pairing decisions. Contains the most recent group information.

    Attributes:
        previous_partners: Subject IDs of other members in the most recent group
        source_scene_id: Scene where the group was last formed
        group_id: Unique identifier for the group
    """
    previous_partners: list[str]
    source_scene_id: str | None = None
    group_id: str | None = None
```

### Example 2: Building MatchCandidate with Group History
```python
# Source: Extension to GameManager._add_to_fifo_queue() in game_manager.py
def _build_match_candidate(self, subject_id: SubjectID) -> MatchCandidate:
    """Build a MatchCandidate with group history if available."""
    from interactive_gym.server.matchmaker import GroupHistory

    group_history = None
    if self.pairing_manager:
        partners = self.pairing_manager.get_group_members(subject_id)
        if partners:
            group_id = self.pairing_manager.get_group_id(subject_id)
            group = self.pairing_manager.groups.get(group_id) if group_id else None
            group_history = GroupHistory(
                previous_partners=partners,
                source_scene_id=group.source_scene_id if group else None,
                group_id=group_id,
            )

    return MatchCandidate(
        subject_id=subject_id,
        rtt_ms=self.get_subject_rtt(subject_id) if self.get_subject_rtt else None,
        group_history=group_history,
    )
```

### Example 3: Researcher Usage in Experiment Config
```python
# Source: Researcher's experiment file
from interactive_gym.server.matchmaker import GroupReunionMatchmaker

scene_1 = (
    GymScene()
    .scene(scene_id="game_1")
    .gameplay(num_episodes=3, max_steps=450)
    # No special matchmaker -- FIFO for first pairing
)

scene_2 = (
    GymScene()
    .scene(scene_id="game_2")
    .gameplay(num_episodes=3, max_steps=450)
    .matchmaking(
        matchmaker=GroupReunionMatchmaker(fallback_to_fifo=True)
    )
    # Will try to re-pair partners from scene_1
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hard-coded group reunion in GameManager | Removed (Phase 60) | v1.13 | Group reunion was ~230 lines of dead code removed |
| wait_for_known_group flag + pairing manager | Deferred, logs warning | v1.13 Phase 60 | Flag exists but is no-op; matchmaker variant is the planned solution |
| MatchCandidate with only subject_id + rtt_ms | Current | v1.12 Phase 55 | Extensible dataclass, comment says "Future: custom attributes from Phase 56" |

**Key historical context:**
- Phase 60 explicitly removed group reunion code (~230 lines) and documented it should return as a matchmaker variant (REUN-01/REUN-02)
- Phase 55 designed the Matchmaker ABC specifically to be extensible for this use case
- `PlayerGroupManager` was kept intact even when reunion code was removed -- it still records groups on every game end
- The `wait_for_known_group` flag on GymScene currently logs a warning and falls through to FIFO

## Critical Code Observations

### 1. Groups Already Recorded (P2P-03 Partially Done)
`GameManager.cleanup_game()` lines 1418-1431 already records groups:
```python
if self.pairing_manager:
    subject_ids = list(game.human_players.values())
    real_subjects = [sid for sid in subject_ids if sid != utils.Available and sid is not None]
    if len(real_subjects) > 1:
        self.pairing_manager.create_group(real_subjects, self.scene.scene_id)
```
This means P2P-03 ("Server tracks group membership") is already working at the storage level. What's missing is persistence verification (does the group survive scene transitions?) and queryability (P2P-04).

### 2. Groups Persist Across Scenes
`advance_scene()` calls `GROUP_MANAGER.update_subject_scene()` but does NOT call `cleanup_subject()`. Groups are only cleaned up on true disconnect. This confirms groups survive scene transitions.

### 3. MatchCandidate Extensibility Was Planned
Line 39 of matchmaker.py: `# Future: custom attributes from Phase 56`. The dataclass was designed to be extended.

### 4. GameManager Already Has pairing_manager Reference
`GameManager.__init__()` accepts `pairing_manager` and stores it as `self.pairing_manager`. The reference is already available where MatchCandidates are built.

## Open Questions

1. **Should GroupReunionMatchmaker support timeout/fallback within a single match attempt?**
   - What we know: `GymScene.group_wait_timeout` exists (default 60000ms). The old reunion code used this to time out waiting for known group members.
   - What's unclear: Should the matchmaker itself track how long it's been waiting, or should this remain a GameManager concern (waitroom timeout)?
   - Recommendation: Keep timeout at the GameManager/waitroom level (already exists). The matchmaker should be stateless per-call -- it either finds a reunion match or falls back to FIFO.

2. **Should group_history contain full historical chain or just most recent pairing?**
   - What we know: `PlayerGroupManager.create_group()` replaces previous groups. Only the most recent group is stored.
   - What's unclear: Whether researchers need the full pairing chain (A played with B, then B played with C, etc.)
   - Recommendation: Start with most recent only (matches current PlayerGroupManager behavior). If full history is needed later, that's a separate enhancement to PlayerGroupManager, not a matchmaker concern.

## Sources

### Primary (HIGH confidence)
- `interactive_gym/server/matchmaker.py` - Matchmaker ABC, MatchCandidate, FIFOMatchmaker (read directly)
- `interactive_gym/server/player_pairing_manager.py` - PlayerGroupManager, PlayerGroup (read directly)
- `interactive_gym/server/game_manager.py` - GameManager, cleanup_game, _add_to_fifo_queue (read directly)
- `interactive_gym/server/app.py` - advance_scene, join_game, GROUP_MANAGER usage (read directly)
- `interactive_gym/scenes/gym_scene.py` - GymScene.matchmaking(), wait_for_known_group config (read directly)
- `.planning/ROADMAP.md` - Phase 78 requirements and success criteria (read directly)
- `.planning/REQUIREMENTS.md` - P2P-03, P2P-04 definitions (read directly)

### Secondary (MEDIUM confidence)
- `.planning/STATE.md` - Historical context about Phase 60 removing reunion code (read directly)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All existing infrastructure, no new libraries
- Architecture: HIGH - Direct code reading confirms integration points exist
- Pitfalls: HIGH - Based on reading actual code paths (cleanup_game, advance_scene, disconnect handler)

**Research date:** 2026-02-07
**Valid until:** 2026-03-07 (stable - no external dependencies, all internal code)
