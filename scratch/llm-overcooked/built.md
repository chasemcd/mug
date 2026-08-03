# What was built, and what it found

The sketches in this directory are what the plan looked like. This is what shipped,
and where the plan was wrong.

## The platform

**A coarser action level.** `LLMAgent.decides_among()` and `LLMAgent.carry_out()`,
both defaulting to the environment's own actions so nothing written before changes.
`ScheduledSeat` now holds a **choice** rather than an action, and asks `carry_out`
for this frame's action. `available_actions` keeps its documented meaning -- the
environment's names -- so the runtime goes on naming every seat's move in the
environment's own words.

Two things the plan got wrong:

- The sketch put the executor on the seating (`Model(does=...)`) and set a
  `_default_action` attribute on the agent. **A study's agent instance is shared by
  every participant**, so anything written onto it is shared too. It is gone:
  `carry_out` answers `None` for "nothing to do this frame", and the seat takes the
  game's own default action. The two `None`s read the same way round -- nothing
  chosen in, nothing to do out -- and a study never has to know what the idle action
  is in order to say "stand still".
- A **fallback** had to be read through the agent's own rule. `REPEAT_LAST` keeps
  the choice, which for a job that lasts is "carry on to the pot". `WAIT` leaves the
  seat with **no** choice, which is not the same as choosing the idle action --
  applying the fallback action as a choice made action 0 into job 0, so a partner
  whose every decision failed walked the whole corridor.

**The deadline.** `LLMAgent.answers_within`, default 1.0. The mount takes the longest
among an activity's model seats. Confirmed by measurement before the change:
`decision_timeout: 1.0`, unreachable from a study.

**A message wakes the seat**, and a wake that lands mid-decision is kept.

**What a seat carries between rounds.** `SeatMemory`, held by the table. Both halves
were broken and I had predicted only one: `_run_table` builds a fresh episode per
round, so the **transcript** was thrown away as well as the plan. The history is
deliberately not carried -- a round is its own episode.

**The conversation surface.** `Game(chat=Chat(...))` and
`build_study_app(chat=Chat(...))`; a `ChatSpec` at the author surface is refused by
name. Every construction in the repo now compiles from `Chat(...)` through
`tests/support/chat.py`.

## Two bugs the work turned up on its own

**`Chat("talk", channel_key="x")` crashed inside the mount** with a TypeError naming
a runtime field. `chat_for` now refuses a settings key that duplicates one `Chat`
already writes, and says which.

**The participant's transcript was wiped when the next round started.** The rest page
says "your partner remembers what you said, and you can carry on the same
conversation", and then `startNextRound` called `startComposed`, which rebuilt both
panes and replaced the log with an empty one. The intent was already written at
`mountPanes` -- "a round ending repaints one and leaves the other alone" -- and not
honoured. Fixed in both clients.

## One thing I called a bug and was not

The first browser walk reported a study that hangs after round one. It does not. The
**walk** read the chat pane's message box as a survey form, because a composer is a
`<form>` and it stays on screen through the rest between rounds. The client was
right; `_showing` was wrong.

## Four tests that proved nothing until mutation

1. The `WAIT`-fallback test: the episode finished before any decision could time out,
   so no fallback was ever applied and the test passed whatever the fallback did.
2. The carried-plan test compared the **last** prompt with the **first**, which grows
   within one round anyway. It had to be compared where each round starts.
3. The headline example test -- what it says must not steer what it does -- passed
   with the study's own parser deleted, because the reply had "deliver" in the PLAN
   line and the default parser got the right answer by luck.
4. The wake-while-busy case was not covered at all until the episode was given real
   frame time.

## Where the sketches went

The four Python sketches in this directory were the plan. They are gone, because
each one is now shipped code and a near-copy of shipped code is a second source
that nothing keeps true:

| sketch | shipped as |
| --- | --- |
| `chef_agent.py` | `examples/cogrid/chef_agent.py` |
| `kitchen_text.py` | `examples/cogrid/kitchen_text.py` |
| `study.py` | `examples/cogrid/overcooked_llm_chat.py` |
| `executor.py` | folded into `TalkingChef.carry_out`, over `partners.Chef` |

`platform-gaps.md` and `decisions.md` are kept as they were written, so what was
predicted can be read against what was found.
