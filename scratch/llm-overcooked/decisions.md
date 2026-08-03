# Settled decisions

Eleven questions, answered. This is what the work is.

## The macro layer

**Both halves on `LLMAgent`.** No new `Model` keyword: the seating stays exactly as it
is written today.

```python
class TalkingChef(LLMAgent):
    def decides_among(self, env, agent_id):
        """What this agent decides among. Defaults to available_actions()."""
        return ["FETCH_ONION", "FILL_POT", "DELIVER", ...]

    def carry_out(self, env, agent_id, chosen):
        """One environment action that carries the choice forward, this frame."""
```

**The level has no noun, on purpose.** "Intent" named a mental state where the thing is
an action at a coarser grain, and each of the standard replacements carries a meaning
this does not have: an *option*, a *skill* and a *macro action* all conventionally
bundle the name **with its own policy**, and here one `carry_out` serves every choice
in the list. So the two methods say the whole thing between them and the platform
learns no new word -- which is also why it needs no new type: `decides_among` returns
names and `carry_out` returns an environment action.

`available_actions` keeps its documented meaning -- the **environment's** names -- so
the history goes on naming what every seat did in the environment's own words.
`parse_reply` returns an index into `decides_among`. With neither method overridden, a
model seat decides an environment action and holds it, exactly as now.

Internally the platform needs one word for the thing a seat holds between decisions,
and it is **the choice**: a seat holds what it chose, and `carry_out` turns the choice
into the action the environment steps.

## The deadline

**`LLMAgent.answers_within: float = 1.0`**, beside `on_timeout` and `decides_every`.
The mount takes the longest among an activity's model seats, because the scheduler is
shared.

## What a fallback does

**The game's own default action.** A missed deadline or an unreadable reply gives the
seat what the study wrote as `default_action`, which for this kitchen is `NOOP`: the
chef stands still. So the agent declares `on_timeout = Fallback.WAIT`, and a fallback
is visible in the run as a pause rather than hidden as a job that carried on.

Consequence for `carry_out`: a choice may be absent, and absent means *nobody told this
seat what to do*. It stands by. `carry_out` receives `chosen=None` there rather than an
index it would have to range-check.

## Talking

**The model decides whether to speak, in its own prompt.** No platform rule and no
cadence keyword: `say()` already returns `None` for silence, and the prompt asks the
model to weigh up whether anything is worth saying now. It is part of the agent
design, which is where it belongs.

**A participant's message wakes the seat.** A message starts a decision as soon as one
is free, ignoring `decides_every`. Typing to your partner and waiting three seconds
for any sign it heard you is the difference between a teammate and a bot.

## Memory across rounds

Three rounds, one interaction, one conversation. **The model's carried plan
(`Thoughts`) persists across the interval too.** If the transcript persisted and the
plan did not, the partner could be reminded of what it agreed to and have no memory of
agreeing. Whether it persists today is unknown and will be measured, not assumed.

## The conversation surface

**`Chat(...)` only, and every construction in the repo ports.** `Game(chat=...)` and
`build_study_app(chat=...)` accept `Chat(...)` and refuse a `ChatSpec`; `ChatSpec`
remains what `chat_for` compiles to and what the conversation runtime reads, and every
test that builds one builds it by compiling a `Chat(...)`.

Scale: ~46 constructions across 20 files. Most are already reachable, because `Chat`
has a `**settings` catch-all that `chat_for` forwards straight into `ChatSpec` -- so
`channels=`, `policy=`, `compose=` and the rest already pass through. The port will
say plainly which fields, if any, no `Chat(...)` can reach.

`Chat` gains `placement=` as a written keyword rather than a settings passthrough.

## The example

One module, `examples/cogrid/overcooked_llm_chat.py`, defaulting to a local Ollama
chef, with the study taking `agent` / `adapter` / `resolve_secret` so a hosted model is
one argument. Default model **llama3.2**, the same as `preference_chat`.

The kitchen is the shipped one: `cramped_room`, 30 frames a second, 600 frames a
round, three rounds with an interval between them.

llama3.2 is 3B and will break the three-line format sometimes. Two answers, both in
scope: the prompt is written to be hard to break, and `parse_reply` is generous within
the `JOB:` line (any case, the name anywhere on that line) and reads nothing outside
it. A break is a fallback, and a fallback is a chef standing still for one decision.

## Tests

- **A live browser walk**: real Chromium, real Ollama, three rounds, shortened only in
  the environment's own episode bound. Skipped when no runner answers.
- **A scripted browser walk beside it**: the same study on a written adapter, so the
  study itself -- three rounds, every round painted, the transcript carrying the
  interval -- is proven with no model pulled. When the live walk fails, these two say
  which of the two broke.
- Unit: the `SAY:` line does not steer the chef; one decision drives a whole route;
  the deadline the study writes reaches the scheduler; a message wakes the seat; the
  transcript and the thoughts both survive the interval.

## Deferred, by decision

A model seat that overrides neither method, in a `held_actions=False` game, still holds its
action on every frame. This example never reaches it. The fix changes behaviour for
every existing model-seat study, so it gets its own pass.
