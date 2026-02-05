# Features Research: Matchmaking Systems

**Domain:** Research experiment platforms with multiplayer participant matching
**Researched:** 2026-02-02
**Mode:** Ecosystem survey focused on features dimension

## Executive Summary

Matchmaking systems for research experiments differ fundamentally from game matchmaking: research prioritizes experimental validity (balanced groups, demographic criteria, counterbalancing) over engagement optimization (skill-based, low wait times). The core pattern across both domains is a pluggable matching function that receives participant metadata and returns grouped participants. Table stakes include FIFO queuing, timeout handling, and configurable group sizes. Research-specific differentiators include attribute-based matching (demographics, prior performance), constraint satisfaction, and reproducible assignment logs for analysis.

## Table Stakes Features

Features users expect. Missing = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **FIFO Queue Matching** | Default behavior that "just works" - first N participants paired together | Low | Current implementation exists |
| **Configurable Group Size** | Experiments vary from 2-player to N-player interactions | Low | Already supported via `PLAYERS_PER_GROUP` pattern |
| **Timeout Handling** | Participants cannot wait indefinitely; redirect after max wait | Low | Current implementation exists |
| **Participant Metadata Access** | Matchmaker needs info to make decisions (subject ID, session data) | Low | Already tracked in `PlayerGroupManager` |
| **Waiting Room Status Updates** | Participants need feedback while waiting (count, time remaining) | Low | Current implementation exists via `waiting_room` events |
| **Dropout Handling** | When waiting participant disconnects, remaining participants must be handled | Medium | Partially implemented; needs cleanup |
| **Thread Safety** | Concurrent participant arrivals must not cause race conditions | Medium | Current implementation uses locks |
| **Group Persistence** | Remember who was matched for multi-round experiments | Low | `PlayerGroupManager` already tracks this |

**Sources:**
- [oTree Groups documentation](https://otree.readthedocs.io/en/latest/multiplayer/groups.html): FIFO via `group_by_arrival_time`
- [PlayFab error handling](https://learn.microsoft.com/en-us/gaming/playfab/features/multiplayer/matchmaking/error-cases): Timeout and dropout patterns
- Current codebase `game_manager.py`: Existing waiting room implementation

## Differentiating Features

Features that set product apart for research use cases. Not expected, but valued.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Custom Attribute Matching** | Match by demographics, skill level, or researcher-defined criteria | Medium | oTree's `group_by_arrival_time_method` pattern |
| **Pluggable Matchmaker Base Class** | Researchers subclass to implement any matching logic | Medium | Core v1.12 goal |
| **Historical Performance Access** | Match based on prior game results (skill, cooperation level) | Medium | Requires data pipeline integration |
| **RTT-Based Matching** | Pair participants with similar network latency for fair experiments | Medium | Partially implemented in current code |
| **Constraint Satisfaction** | "2 men + 2 women per group" style constraints | High | Complex but valuable for research |
| **Wait Time Relaxation** | Progressively relax criteria as wait time increases | Medium | FlexMatch pattern; prevents deadlocks |
| **Reproducible Assignment Logs** | Export who was matched with whom for analysis | Low | Essential for research validity |
| **Blocking/Exclusion Rules** | Prevent specific participants from being matched (e.g., same IP) | Medium | Prevents collusion/repeated partners |
| **Priority Queuing** | Some participants get matched faster (compensation for prior wait) | Medium | Useful for dropout recovery |
| **Pre-Match Callbacks** | Hook to validate match before committing (P2P connection test) | Medium | Current v1.3 validation could integrate |

**Sources:**
- [oTree group_by_arrival_time_method](https://otree.readthedocs.io/en/latest/multiplayer/waitpages.html): Custom matching callback
- [Amazon FlexMatch rules](https://docs.aws.amazon.com/gameliftservers/latest/flexmatchguide/match-examples.html): Wait time relaxation
- [AccelByte matchmaking](https://docs.accelbyte.io/gaming-services/services/play/matchmaking/): Skill and role-based matching

## Anti-Features

Features to deliberately NOT build. Common mistakes in this domain.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Skill-Based Matchmaking (SBMM)** | Game industry pattern optimizing engagement, not research validity. Researchers need control over matching criteria, not opaque MMR algorithms. | Provide attribute-based matching where researchers define the criteria |
| **Global Player Pools** | Cross-experiment matching creates contamination. Each experiment needs isolation. | Scope matchmaking to individual scenes/experiments |
| **Automatic Backfill** | Adding new players mid-game invalidates experimental conditions | Only match at game start; handle dropouts via termination |
| **Match Quality Scoring** | Opaque "match quality" metrics hide researcher-relevant criteria | Expose raw attributes; let researchers define "quality" |
| **Engagement Optimization** | Optimizing for player retention irrelevant for one-shot experiments | Optimize for experimental validity (balanced groups, counterbalancing) |
| **Complex Rule DSLs** | FlexMatch-style JSON rule languages are powerful but over-engineered for research | Simple Python subclassing; researchers already know Python |
| **Async Match Notifications** | SSE/WebSocket complexity for "match found" events unnecessary when participants are already on waiting page | Synchronous matching on arrival; update waiting room directly |

**Sources:**
- [TrueSkill Wikipedia](https://en.wikipedia.org/wiki/TrueSkill): Game-focused skill rating systems
- [Skill-based matchmaking Wikipedia](https://en.wikipedia.org/wiki/Skill-based_matchmaking): Why SBMM is game-specific
- [Demographics and Behaviour research](https://www.cambridge.org/core/journals/experimental-economics/article/abs/demographics-and-behaviour/020B414B5508B54EB07EFD8E871704D4): Research matching priorities

## Matchmaker API Design Patterns

### Pattern 1: Callback-Based (oTree)

oTree uses a simple callback pattern where the matching function receives waiting players and returns a group or None.

```python
# oTree pattern
def group_by_arrival_time_method(subsession, waiting_players):
    """
    Called when a player arrives at wait page.

    Args:
        subsession: Current subsession context
        waiting_players: List of Player objects currently waiting

    Returns:
        List of players to form a group, or None to keep waiting
    """
    # Example: match 2 men + 2 women
    men = [p for p in waiting_players if p.participant.category == 'male']
    women = [p for p in waiting_players if p.participant.category == 'female']

    if len(men) >= 2 and len(women) >= 2:
        return men[:2] + women[:2]
    return None  # Keep waiting
```

**Pros:** Simple, Pythonic, easy to understand
**Cons:** Limited to synchronous matching, no explicit timeout handling

### Pattern 2: Ticket-Based (GameLift FlexMatch, PlayFab)

Players submit "tickets" with attributes; a background service matches tickets.

```python
# Ticket-based pattern (conceptual)
class MatchTicket:
    player_id: str
    attributes: dict[str, Any]  # {"skill": 1500, "region": "us-west"}
    latency: dict[str, int]  # {"us-west": 50, "us-east": 100}
    created_at: float

class MatchmakerService:
    def submit_ticket(self, ticket: MatchTicket) -> str:
        """Returns ticket_id, match found async via callback/polling"""

    def get_match_status(self, ticket_id: str) -> MatchStatus:
        """Poll for match result"""
```

**Pros:** Scales to millions of players, supports complex rules
**Cons:** Over-engineered for research, async complexity

### Pattern 3: Base Class with Hooks (Recommended for v1.12)

Combines simplicity of callback with extensibility of class inheritance.

```python
# Recommended pattern for Interactive Gym
class Matchmaker(ABC):
    """Base class for custom matchmaking logic."""

    @abstractmethod
    def find_match(
        self,
        arriving_participant: ParticipantData,
        waiting_participants: list[ParticipantData],
        group_size: int,
    ) -> list[ParticipantData] | None:
        """
        Called when a participant enters the waiting room.

        Args:
            arriving_participant: The newly arrived participant
            waiting_participants: Participants already waiting
            group_size: Target number of participants for a match

        Returns:
            List of participants to match (including arriving), or None to wait
        """
        pass

    def on_timeout(self, participant: ParticipantData) -> TimeoutAction:
        """Called when participant exceeds max wait time."""
        return TimeoutAction.REDIRECT

    def on_dropout(
        self,
        dropped: ParticipantData,
        remaining: list[ParticipantData]
    ) -> DropoutAction:
        """Called when a waiting participant disconnects."""
        return DropoutAction.CONTINUE_WAITING


class FIFOMatchmaker(Matchmaker):
    """Default: first N participants paired together."""

    def find_match(self, arriving, waiting, group_size):
        all_participants = waiting + [arriving]
        if len(all_participants) >= group_size:
            return all_participants[:group_size]
        return None
```

**Pros:**
- Familiar Python pattern (researchers subclass)
- Explicit hooks for edge cases (timeout, dropout)
- Synchronous (no async complexity)
- Type hints for IDE support

**Cons:**
- Less flexible than DSL-based rules
- Researchers must write Python (acceptable for this audience)

**Sources:**
- [oTree wait pages](https://otree.readthedocs.io/en/latest/multiplayer/waitpages.html): Callback pattern
- [GameLift Player API](https://docs.aws.amazon.com/gameliftservers/latest/apireference/API_Player.html): Ticket/attributes pattern
- Current `callback.py` in codebase: Existing hook pattern for game events

## Data Available to Matchmakers

### Tier 1: Session Metadata (Always Available)

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `subject_id` | `str` | Unique participant identifier | URL param or generated |
| `session_start` | `float` | When participant joined experiment | Server timestamp |
| `wait_start` | `float` | When participant entered waiting room | Server timestamp |
| `current_scene_id` | `str` | Which scene they're waiting in | Stager state |
| `socket_id` | `str` | Current WebSocket connection | Flask-SocketIO |

### Tier 2: Network Metrics (If Measured)

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `rtt_to_server` | `int` | Round-trip time to server (ms) | SocketIO ping |
| `connection_type` | `str` | "direct" or "relay" for prior P2P | WebRTC stats |
| `prior_p2p_latency` | `int` | Latency to previous partner | P2P measurement |

### Tier 3: Custom Attributes (Researcher-Defined)

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `custom_attributes` | `dict` | Arbitrary key-value pairs | URL params or prior scenes |
| Examples: `{"condition": "treatment", "gender": "female", "age_group": "18-25"}` | | |

### Tier 4: Historical Performance (If Available)

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `prior_games` | `int` | Number of games completed | Data export history |
| `prior_partners` | `list[str]` | Subject IDs of previous partners | `PlayerGroupManager` |
| `prior_scores` | `list[float]` | Scores from previous games | Callback aggregation |
| `cooperation_rate` | `float` | Fraction of cooperative actions | Computed metric |

**Sources:**
- [GameLift Player structure](https://docs.aws.amazon.com/gameliftservers/latest/apireference/API_Player.html): PlayerId, PlayerAttributes, LatencyInMs
- [PlayFab ticket attributes](https://learn.microsoft.com/en-us/gaming/playfab/multiplayer/matchmaking/ticket-attributes): Player vs User attribute types
- Current `player_pairing_manager.py`: `subject_id`, `group_id`, `source_scene_id`

## Feature Dependencies

```
Timeout Handling
      |
      v
FIFO Queue Matching  <----  Pluggable Matchmaker Base Class
      |                              |
      v                              v
Group Persistence  ------>  Custom Attribute Matching
      |                              |
      v                              v
Reproducible Logs  <-----  Historical Performance Access
                                     |
                                     v
                           Constraint Satisfaction
                                     |
                                     v
                           Wait Time Relaxation
```

**Dependency Notes:**
- FIFO is the base case; Matchmaker base class abstracts it
- Custom attributes require attributes to be passed through the system
- Historical performance requires data pipeline integration with exports
- Constraint satisfaction builds on attribute matching
- Wait time relaxation is an enhancement to constraint satisfaction

## Recommendations for v1.12

### Must Have (Table Stakes)

1. **Matchmaker Base Class** - Abstract class with `find_match()` method
2. **FIFOMatchmaker Default** - Current behavior as the default implementation
3. **ParticipantData Container** - Structured data passed to matchmaker
4. **Timeout Hook** - `on_timeout()` method with configurable behavior
5. **Dropout Hook** - `on_dropout()` method for waiting room disconnects

### Should Have (Differentiators)

1. **Custom Attributes** - Pass arbitrary key-value pairs to matchmaker
2. **RTT Access** - Expose server RTT measurement to matchmaker
3. **Prior Partners List** - Expose group history for blocking repeat matches
4. **Assignment Logging** - Record match decisions for research export

### Could Have (Stretch)

1. **Wait Time Relaxation** - Progressive criteria relaxation
2. **Priority Queuing** - Compensate participants who waited before dropout
3. **Pre-Match Validation Hook** - Run P2P test before committing match

### Won't Have (Anti-Features)

1. Skill-based MMR/Elo rating
2. Global player pools
3. Mid-game backfill
4. Complex rule DSLs

## Complexity Estimates

| Feature | Complexity | Rationale |
|---------|------------|-----------|
| Matchmaker base class | Medium | New abstraction layer over existing code |
| FIFOMatchmaker | Low | Refactor existing `_add_to_fifo_queue` |
| ParticipantData | Low | Data class with existing fields |
| Timeout hook | Low | Existing timeout handling, add hook |
| Dropout hook | Low | Existing dropout handling, add hook |
| Custom attributes | Medium | Need to propagate through URL/scenes |
| RTT access | Low | Already measured, expose to matchmaker |
| Prior partners | Low | Already in `PlayerGroupManager` |
| Assignment logging | Low | Add logging to match decisions |
| Wait time relaxation | Medium | Requires time-based state in matchmaker |
| Priority queuing | Medium | Requires queue ordering changes |
| Pre-match validation | High | Async P2P test integration |

## Confidence Assessment

| Area | Level | Reason |
|------|-------|--------|
| Table stakes features | HIGH | Well-documented patterns in oTree, verified in current codebase |
| Differentiating features | MEDIUM | Based on game industry patterns adapted for research; oTree precedent |
| Anti-features | HIGH | Clear distinction between game optimization and research validity |
| API design pattern | MEDIUM | Recommended pattern synthesized from multiple sources; not directly from authoritative docs |
| Data available | HIGH | Current codebase verified; GameLift/PlayFab patterns well-documented |
| Complexity estimates | MEDIUM | Based on codebase familiarity; actual complexity depends on edge cases |

## Sources

**Authoritative (HIGH confidence):**
- [oTree Groups documentation](https://otree.readthedocs.io/en/latest/multiplayer/groups.html)
- [oTree Wait Pages documentation](https://otree.readthedocs.io/en/latest/multiplayer/waitpages.html)
- [Amazon GameLift Player API](https://docs.aws.amazon.com/gameliftservers/latest/apireference/API_Player.html)
- [Amazon FlexMatch Guide](https://docs.aws.amazon.com/gameliftservers/latest/flexmatchguide/gamelift-match.html)
- [PlayFab Matchmaking Error Cases](https://learn.microsoft.com/en-us/gaming/playfab/features/multiplayer/matchmaking/error-cases)
- [PlayFab Ticket Attributes](https://learn.microsoft.com/en-us/gaming/playfab/multiplayer/matchmaking/ticket-attributes)

**Supporting (MEDIUM confidence):**
- [AccelByte Matchmaking Introduction](https://docs.accelbyte.io/gaming-services/services/play/matchmaking/)
- [Open Match Matchmaker Guide](https://open-match.dev/site/docs/guides/matchmaker/)
- [PsychoPy Multiplayer Demo Discussion](https://discourse.psychopy.org/t/online-multiplayer-experiment-demo-using-pavlovia-shelf/43118)

**Background (LOW confidence - context only):**
- [TrueSkill Wikipedia](https://en.wikipedia.org/wiki/TrueSkill)
- [Skill-based matchmaking Wikipedia](https://en.wikipedia.org/wiki/Skill-based_matchmaking)
- [Elo rating system Wikipedia](https://en.wikipedia.org/wiki/Elo_rating_system)
