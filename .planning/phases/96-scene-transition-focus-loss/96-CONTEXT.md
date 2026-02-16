# Phase 96: Scene Transition on Focus Loss - Context

**Gathered:** 2026-02-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix out-of-focus player not advancing scenes after episode ends, which blocks CSV data export. Both players must advance to the next scene after episode completion regardless of tab focus state. The fix should ensure all critical game lifecycle events process reliably in background tabs, mirroring P2P behavior for focus-loss handling.

</domain>

<decisions>
## Implementation Decisions

### Background tab policy
- Robust background handling: all critical game lifecycle events (episode end, scene transitions, data export) must process reliably even when the tab is backgrounded
- Use mechanisms that bypass browser throttling (e.g., Web Workers, MessageChannel) so events fire immediately in background tabs -- no waiting for refocus
- Handle any backgrounding scenario (mid-episode or at episode boundary), not just the specific episode-boundary case
- Mirror P2P behavior: if one client is out of focus, do not advance to the next episode until they return; time out if out of focus for too long
- Reuse existing P2P timeout settings (e.g., reconnection_timeout_ms) -- no new configuration needed

### CSV export guarantees
- CSV export stays coupled to scene transitions (fix the transition, fix the export)
- If a backgrounded player times out and is removed, still export whatever data was collected -- partial data is better than no data for researchers
- Add a per-step focus flag to the CSV: each row/step includes a boolean indicating whether the player was focused at that moment (useful for researchers analyzing attention effects)

### Regression safety
- Strictly target the 5 failing E2E tests -- do not add new test cases for this phase
- Intermediate validation runs the 5 target tests; final validation runs the full test suite (all 33 E2E + 39 unit tests)
- Zero regression tolerance: phase isn't done until target tests pass AND no existing tests regressed
- If an unrelated failing test is discovered during this phase, fix it regardless of effort -- the milestone goal is all tests green

### Claude's Discretion
- Specific mechanism for bypassing browser throttling (Web Workers, MessageChannel, or other approach)
- How to detect focus state per-step for the CSV flag
- Internal architecture of the fix (which modules to modify, event flow changes)

</decisions>

<specifics>
## Specific Ideas

- Focus-loss handling should mirror existing P2P disconnect behavior -- same timeout, same "wait for return" policy
- Per-step focus boolean in CSV enables researchers to filter or analyze attention effects in experiment data

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 96-scene-transition-focus-loss*
*Context gathered: 2026-02-16*
