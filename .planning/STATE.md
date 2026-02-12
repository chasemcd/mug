# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-11)

**Core value:** Researchers can configure and deploy multiplayer browser experiments with minimal code
**Current focus:** v1.28 Configurable Inference

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-02-11 — Milestone v1.28 started

## Accumulated Context

### Decisions

- [87-01] Anchor-based snapshot pruning: highest snapshot <= confirmedFrame retained, all before deleted
- [87-01] Input buffer prunes at confirmedFrame boundary only, no hardcoded frame offset
- [87-01] Removed maxSnapshots (30), inputBufferMaxSize (120), pruneThreshold (frameNumber-60)

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-02-11
Stopped at: Milestone v1.28 initialization
Resume file: None
Next action: Define requirements
