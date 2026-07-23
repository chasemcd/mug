# Example: an LLM that plays a turn-based game

*For study authors. A worked example: an agent that plays Tic-Tac-Toe against a
human, or against another agent. You write the same small `LLMAgent` class you
write for a real-time game -- the turn-based discipline is handled for you.*

> Status: **built.** The turn-based runtime (`mug.game.aec`,
> `mug.agents.TurnBasedAgentEpisode`) runs an LLM against a human or against
> another LLM over one shared, server-authoritative game. See
> [aec-turn-based-lifecycle.md](aec-turn-based-lifecycle.md) for how it runs under
> the surface (you do not read it to write the agent below).

---

## What is the same, and what is different

Writing a turn-based agent is writing an [`LLMAgent`](llm-agent-quickstart.md) --
the same class, the same five inputs to `get_prompt`, the same `history`, `chat`,
and `thoughts`. You do not touch the loop, the scheduler, or the turn order.

One thing is different, and it is in your favor: the game **waits for the model on
its turn**. In a real-time game a slow model repeats its last move; in a turn-based
game the turn is held open until the model answers, so its first move is already its
real move. You write nothing for this -- it is the discipline of the game.

The other difference is what your `history` reads: one move per turn, not a whole
frame. Each step names the one player who moved, so the opponent's moves are simply
the moves that are not yours -- you read them with your own `agent_id`, and never
need to be told who the opponent is.

---

## The whole agent

The game is Tic-Tac-Toe. The environment names the nine cells `0`..`8` as its
actions and renders the board as text. The agent plays one mark; it reads the board
and the opponent's moves, then names a cell. It is not told which mark it is or who
the opponent is -- it works both out from its own `agent_id`.

```python
from mug.authoring import LLMAgent, Provider, Fallback, Actor

class TicTacToePlayer(LLMAgent):
    provider = Provider.ANTHROPIC
    model = "claude-sonnet-4-5"
    secret = "chat-provider-key"          # a name; the value is set at deploy

    def get_prompt(self, env, agent_id, history, chat, thoughts):
        their_moves = ", ".join(
            move                                             # the opponent's cells, in order
            for step in history.last(9)                      # a game is at most nine moves
            for who, move in step.actions.items()
            if who != agent_id                               # whoever moved and is not me is the opponent
        )
        return (
            "You play Tic-Tac-Toe. Win, or block your opponent.\n\n"
            f"Your read so far: {thoughts.latest or '(first move)'}\n"      # your own reasoning, carried forward
            f"Opponent has played: {their_moves or '(nothing yet)'}\n\n"   # the game history, one move per turn
            f"{env.text_view(agent_id)}\n\n"                               # the board now, in words
            "Think in one line, then end with 'Move: <cell number>'.\n"
            f"Open cells: {', '.join(self.available_actions(env, agent_id))}"  # the legal moves you place
        )

    def reflect(self, reply, env, agent_id):
        return reply     # carry your reasoning to your next turn (the default)
```

That is the whole agent -- no fields to set per seat, no constructor. The opponent's
moves are read straight from the history as "the moves that are not mine," so the
one class plays either mark. `parse_reply` is not written: the default reads the last
legal cell the reply names, so a reply that reasons first and ends with `Move: 4`
just works.

---

## Casting it

Cast the one class into a seat the same way as any agent. The same
`TicTacToePlayer()` fills either seat -- it reads its own mark and its opponent from
`agent_id`, so nothing is passed to it.

**An agent against a human.** The human takes `x`, the model takes `o`; they
alternate, and the game waits for whoever is in turn.

```python
Interaction(
    key="match",
    seats=["x", "o"],
    cast={"x": Actor.human(),
          "o": Actor.agent(TicTacToePlayer())},
)
```

**An agent against another agent.** Because the agent holds no per-seat state, the
**same instance** fills both seats -- you build it once and cast it twice.

```python
player = TicTacToePlayer()                 # one instance...
Interaction(
    key="match",
    seats=["x", "o"],
    cast={"x": Actor.agent(player),
          "o": Actor.agent(player)},        # ...drives both seats
)
```

This is the rule for every agent, not just this one: **an agent instance is never
seat-specific.** It is a definition -- frozen, stateless, shared. MUG gives each
seat its own history, chat, and thoughts, and hands them to the agent's methods with
that seat's `agent_id` on every call, so the one `player` reasons as `x` on `x`'s
turn and as `o` on `o`'s turn without holding either. Write the methods to read
their inputs (never `self`), and one object safely drives any number of seats.

The game being turn-based comes from the **environment**: a turn-based (AEC)
environment is driven by the turn-based runtime, and a real-time environment by the
real-time runtime. You choose the environment; the runtime follows.

---

## What you get in the data

Every turn is recorded, so your data reads back the whole match: whose turn it was,
the move they made, and the board that resulted. Because MUG records the model's
outputs, the match replays exactly -- the same run always reads the same history.
For a two-agent match you also get, per seat, the reasoning it carried forward in
`thoughts`, so you can read *why* each side moved as it did.

---

## The rules that still hold

Everything the [quickstart](llm-agent-quickstart.md) says still holds, because this
is the same surface:

- **You build the whole prompt.** The board, the moves, the open cells, and the
  model's own thoughts reach the model only if you put them in `get_prompt`.
- **The agent is a definition.** It is frozen and versioned with your study, and it
  holds no per-move state, so one `TicTacToePlayer` can drive many matches. Write
  the methods as pure functions of their inputs, and the study stays reproducible.
- **You never touch keys, the scheduler, or the turn order.** The credential is read
  by name at deploy; the turn cadence is the game's; the record of which model call
  made which move is kept for you.

**Run it free while you build.** Set `provider = Provider.OLLAMA` and `model` to a
local model you have pulled, and leave `secret` unset -- MUG reaches the local
runner with no key, so you can watch two local models play a full match before you
spend on a hosted model.
