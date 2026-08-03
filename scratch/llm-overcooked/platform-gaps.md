# Three gaps between "the plumbing exists" and "a study can write this"

Every runtime piece this example needs is already built and tested. `LLMAgent.say`
reads words out of the same reply as the action (W7). `MultiAgentEpisode.post_message`
feeds a participant's typed message into every model seat's `Transcript`, and
`_Conversing.publish` posts what the seats said back onto the chat channel (W6).
`Game(seats={...: Model(...)})` resolves to the `agent_game` mount and compiles the
seat's identity through the gateway (W8).

What is missing is the **author's** end of three of those. Each was found by writing
the study, and each is measured below rather than asserted.

---

## Gap 1 -- the conversation beside a game has no author surface

`Game(chat=...)` takes a `ChatSpec`: a runtime dataclass with 20 fields
(`mug/participant_chat.py:211`). Every shipped study and every test writes one:

```python
Game("play", game, chat=ChatSpec(channel_key="talk"))          # tests
Game("play", game, chat=ChatSpec(seat=ChatSeatSpec(...)))      # tests
```

Meanwhile the author's own word for a conversation, `Chat(...)`, exists
(`mug/content/study.py:559`) and produces a `Step` -- a whole activity. It cannot be
passed to `chat=`, and if it were, `Conversations.spec_at` would silently drop it:

```python
# mug/participant.py:4928
spec = self._study.chats.get(key)
return spec if isinstance(spec, ChatSpec) else None      # <- a Chat() vanishes here
```

A study that wrote `Game(..., chat=Chat("talk"))` today gets **no conversation and no
complaint**. That is the fourth failure kind -- a capability with no expression in the
author API -- with a value that has no reader on top of it.

Related, and worth checking in the same pass: `with_speakers`, which compiles an
author's `Model` speaker into a chat seat, is called on the top-level `chat=` keyword
(`mug/app.py:796`) but **not** on `study.chats`. So `ChatSpec(speaker=Model(...))`
written on a game activity compiles to a room with no model in it.

**Proposal.** `chat=` accepts a `Chat(...)`, compiled where `chats_for` already
compiles a standalone conversation. `ChatSpec` keeps working for studies that pin a
published build. Identity stays the scope rule, which already works and is tested
(`tests/unit/app/test_game_and_chat.py:380`). `Chat` gains `placement=`, which
`ChatSpec` already has and the author's word does not.

---

## Gap 2 -- a model seat can only decide a primitive action, and holds it for ever

Two halves of one gap.

**It holds.** Measured, not read:

```
mount.agent_game.input_mode           -> single_keystroke   # the study said one press one move
ScheduledSeat.decide over 5 frames    -> [3, 3, 3, 3, 3]    # after one apply(3)
```

`ScheduledSeat.decide` returns the last applied action for ever
(`mug/game/controllers.py:241`). A `Bot` never has this problem, because the study
writes the answer into its controller: `HeuristicController(policy, decide_every=5,
between=NOOP)` (`examples/cogrid/partners.py:230`). `Pace` even has the doctrine
written down (`mug/game/controllers.py:63`): holding suits a slime that must keep
pressing left, and the idle action suits a grid, where "repeating one step of a walk
five times walks five squares". A `Model` seat cannot say either.

**And it can only decide a grid move.** `parse_reply` returns "the action's position
in `available_actions`", and `available_actions` is the environment's action set. So
the only thing a model may decide is one primitive move -- which, at one to five
seconds a decision, is about ten moves in a 600 frame round.

The owner's answer collapses both halves: **the model makes macro decisions, not
motor control.** It chooses a job; the study walks it.

**Proposal.** The platform learns one distinction -- what a seat **chose** and what the
environment **steps** need not be the same thing -- as two methods on `LLMAgent`, with
no new type and no new noun for the level:

```python
class LLMAgent:
    def decides_among(self, env, agent_id) -> list[str]:
        """What this agent decides among. Defaults to available_actions()."""

    def carry_out(self, env, agent_id, chosen: int | None) -> int:
        """One environment action that carries the choice forward, this frame."""
```

- `parse_reply` returns an index into `decides_among`, and the seat holds that choice.
- `carry_out` is called on every frame the seat is asked for an action, against the
  live environment, and returns the primitive action for that frame.
- `available_actions` keeps its documented meaning -- the **environment's** names --
  so `_record_step` goes on naming what every seat did in the environment's own
  words. This is the part that would have gone wrong quietly: if `available_actions`
  became the coarser list, the model's history would name its human partner's grid
  moves with job names and nothing would say so.
- A choice of `None` (before the first decision, or after one that fell back) is
  handed to `carry_out` as `None`, which is a seat that has not been told what to do.
- Nothing written today changes: with neither method overridden, a model seat decides
  an environment action and holds it, exactly as now.

Left as a follow-on, not folded in: a model seat that overrides neither method, in a
`held_actions=False` game, still holds. That is the same latent defect as the shipped
`InputScheme.mode` one, and deriving the answer from `held_actions` would close it --
but it is a change to every existing model-seat study, so it wants its own pass.

---

## Gap 3 -- a model decision has a fixed 1.0 second deadline

Measured:

```
mount_for(...).agent_game.decision_timeout   ->  1.0
```

`MultiSeatGame.decision_timeout` defaults to `1.0` (`mug/content/seats.py:112`) and
`mounts._multiseat` never sets it (`mug/mounts.py:270`). Nothing on `Game` or on
`LLMAgent` can change it.

A local Ollama answering a kitchen prompt takes one to five seconds; a hosted model
over the network is no faster. So **every decision in this study would miss its
deadline and fall back**, and the study would still run: the participant would see a
partner that never chose anything, the records would show a decision per second, and
nothing anywhere would say the model was never waited for.

The asymmetry makes the case on its own -- `LLMAgent.on_timeout` is authored (what to
do when the deadline is missed) and the deadline itself is not.

**Proposal.** `LLMAgent.answers_within: float = 1.0`, beside `on_timeout` and
`decides_every`, which are the two things already there about this seat's cadence.
The mount reads the longest deadline among the activity's model seats, because the
scheduler is shared. The default keeps every existing study identical.

---

## What is already right, and needs nothing

- One reply, three readings -- action, words, carried thought -- and the action and
  the words judged apart (`mug/agents/runtime.py:228`).
- A participant's typed message reaching every model seat's next prompt, with private
  channels respected (`mug/participant.py:3499`).
- What a seat says committed on the same channel, anchored into the run, and never
  delivered back to itself (`mug/participant.py:3521`).
- The seat speaking on the cadence it decides at, not once a frame.
- Two panes sharing one keyboard, in both clients, proven in a real browser
  (`tests/e2e_native/test_game_and_chat_browser.py`).

## What has to be checked before it is believed

- **Does the transcript survive an interval?** Three rounds of one activity is one
  interaction, so it should. `tests/unit/app/test_game_and_chat.py:204` runs
  `episodes=2` with a chat, but asserts about the messages rather than about what the
  model reads in round two.
- **Do the model's `Thoughts` survive an interval?** If controllers are rebuilt per
  episode, the partner forgets its plan between rounds while the conversation
  remembers -- a partner that contradicts what it just agreed to. Unknown; to be
  measured, not assumed.
