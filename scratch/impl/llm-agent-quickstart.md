# Add an LLM player to your study

*For study authors. You write one small class. MUG runs the model, keeps it on time,
and records everything -- you never touch providers, keys, or schedulers.*

> Status: **built.** `mug.authoring.LLMAgent` (this surface) and its runtime
> (`mug.agents`: `LLMController`, `compile_agent`, `AgentEpisode`) are implemented and
> tested against the built provider + scheduler. `AgentEpisode` runs a full episode:
> it steps the env, samples the seat every frame, decides at your `decides_every`
> cadence without blocking the frame, and feeds `history` (a step per frame) and
> `chat` (a posted message). **Real providers ship now** (`mug.agents.adapters`):
> `Provider.OLLAMA` (a free local model runner), `Provider.ANTHROPIC`, and
> `Provider.OPENAI` reach the model over HTTP -- you still write only the class.
> **Multi-seat now runs**: an LLM beside a human, or two agents, share one
> environment on one timeline (the cast below runs as written); a single-seat agent
> is just the one-seat case of the same runner, and the human-play render loop
> (`run_episode`) is now that one-seat case too -- one stepping loop under both.
> **Turn-based now runs**: an LLM against a human or another LLM takes turns over a
> turn-based (AEC) game -- see `turn-based-agent-example.md` and
> `aec-turn-based-lifecycle.md`. Not yet wired: the durable thought tape for exact
> cross-step replay. The plumbing under this surface is in
> `llm-provider-integration.md` (you do not read it).

---

## The whole thing

You make a class, set a few fields, and write `get_prompt` -- the text the model sees.
The model can also reason across steps: it reads its own earlier thoughts, and you keep
what you want with `reflect`.

```python
from mug.authoring import LLMAgent, Provider, Fallback, Actor

class CookingPartner(LLMAgent):
    provider = Provider.ANTHROPIC
    model = "claude-sonnet-4-5"
    secret = "chat-provider-key"          # a name; the value is set at deploy
    decides_every = 4                     # act every 4 game steps (optional)
    on_timeout = Fallback.REPEAT_LAST     # if the model is slow (optional)

    def get_prompt(self, env, agent_id, history, chat, thoughts):
        partner_moves = ", ".join(
            step.action_of("chef-1") or "-" for step in history.last(5)      # what the other player did
        )
        partner_said = "; ".join(m.text for m in chat.by("chef-1"))          # what the human told you
        return (
            "You play a cooperative cooking game with a human partner.\n\n"
            f"Your plan so far: {thoughts.latest or '(none yet)'}\n"            # your own reasoning, carried forward
            f"Partner's recent moves: {partner_moves}\n"                     # the game history
            f"Partner said: {partner_said or '(nothing yet)'}\n\n"           # the chat
            f"{env.text_view(agent_id)}\n\n"                                 # the game now, in words
            "In one line, update your plan and your read on the partner. "
            "Then end with 'Action: <one action word>'.\n"
            f"Actions: {', '.join(self.available_actions(env, agent_id))}"   # you place the actions
        )

    def reflect(self, reply, env, agent_id):
        return reply     # carry your reasoning to the next step (this is the default)
```

Then cast it into a seat, the same way you would any agent:

```python
Interaction(
    key="round",
    seats=["chef-1", "chef-2"],
    cast={"chef-1": Actor.human(),
          "chef-2": Actor.agent(CookingPartner())},     # the LLM plays chef-2
)
```

That is the entire agent.

---

## `get_prompt` -- you build the whole prompt

`get_prompt(self, env, agent_id, history, chat, thoughts)` returns a string. **MUG
sends the model exactly that string, and nothing more.** So the game, the action list,
the history, the chat, and the model's own thoughts are shown *only if you put them
in*. There is no hidden text.

Its five inputs -- use what you need, ignore the rest:

- `env` -- your environment *now*: the real state (grid, items, positions), not a
  number array.
- `agent_id` -- which player the model is, so it sees the game from that seat.
- `history` -- what happened earlier this episode: the game states, everyone's moves,
  the rewards (see [history](#history----what-happened-before)).
- `chat` -- messages on the chat channel, so a human partner can instruct the agent
  (see [chat](#chat----what-the-humans-said)).
- `thoughts` -- the model's **own** earlier reasoning, carried forward (see
  [thoughts](#thoughts----let-the-model-reason-across-steps)).

**How to tune it:** start by returning your env's built-in text view, run the study,
read exactly what the model sees, and improve the wording. That is the whole loop.

---

## `available_actions` -- the valid moves, for you to use

`available_actions(self, env, agent_id)` returns the list of legal actions for that
player. The base class reads it from your environment; override it only if your env
names actions differently:

```python
    def available_actions(self, env, agent_id):
        return env.legal_actions(agent_id)      # this is the default; usually you skip it
```

You use this list where you like -- in `get_prompt` to show the model its choices, and
in `parse_reply` to read the answer. It is never injected on its own.

---

## `history` -- what happened before

MUG records every step of the episode for you and hands you a read-only `history`:

```python
history.last(5)                 # the last 5 steps (fewer early on), oldest -> newest
len(history)                    # how many steps so far this episode
history.actions_of("chef-1")    # every past move by a given player, in order
```

Each step is easy to read:

```python
for step in history.last(5):
    step.tick                   # the step number
    step.action_of("chef-1")    # what that player did (an action name, or None)
    step.reward_of(agent_id)    # the reward at that step
    step.text_view(agent_id)    # the game as text at that step (same view as `env`)
```

You choose what to include and how far back. Because MUG already records the episode,
this is free and reproducible: the same run always replays the same history.

---

## `chat` -- what the humans said

If the interaction has a chat channel, a human partner can talk to the agent -- to
coordinate, or to instruct it on strategy -- and the agent reads that in `get_prompt`:

```python
chat.last(5)            # the last 5 messages, oldest -> newest
chat.by("chef-1")       # every message from a given player, in order
len(chat)               # how many messages so far
```

Each message has `.sender`, `.text`, and `.tick`. As with everything else, the chat
reaches the model only if you put it in the prompt. It is recorded, so what the human
said and what the model then did are both in your data. (If your interaction has no
chat channel, `chat` is simply empty -- ignore it.)

---

## `thoughts` -- let the model reason across steps

To plan, or to build a picture of the other players over time, a model needs to see
its **own** earlier thinking. That is `thoughts`: the text the model wrote on past steps,
carried forward so it can reason step by step.

Two halves, both in your control:

- **Read** the thoughts in `get_prompt` -- `thoughts.latest` (the most recent), or
  `thoughts.last(3)` for the last few, or `len(thoughts)`.
- **Write** the next thought with `reflect(self, reply, env, agent_id)` -- return the
  text to carry into the next step. The default returns the whole reply, so reasoning
  carries forward out of the box. Return `None` to keep nothing, or extract just a plan:

```python
    def reflect(self, reply, env, agent_id):
        return extract_between(reply, "<plan>", "</plan>")   # keep only the plan block
```

A good pattern: ask the model to think, then end with a clear action line (as in the
example above). Its reasoning is carried in `thoughts`; the action is read by
`parse_reply`. Over several steps the model refines its plan and its read on the
partner -- multi-step reasoning and theory-of-mind, with no extra machinery.

Thoughts are per player and per episode; the model never sees another player's private
thoughts. They stay reproducible because MUG records the model's outputs. (For memory
that lasts *across* episodes, see the separate `Memory(...)` feature -- you do not need
it for step-by-step reasoning.)

---

## `parse_reply` -- turn the model's answer into a move (optional)

By default MUG reads the reply and picks the **last legal action name** it finds, so a
reply that reasons first and ends with `Action: INTERACT` just works. Override this
only for a richer answer format:

```python
    def parse_reply(self, reply, env, agent_id):
        # `reply` is the model's text. Return one legal action, or None to fall back.
        last = reply.strip().splitlines()[-1]            # e.g. "Action: INTERACT"
        word = last.replace("Action:", "").strip().upper()
        actions = self.available_actions(env, agent_id)
        return word if word in actions else None         # None -> MUG uses on_timeout
```

Return `None` for anything you cannot read; MUG then applies your `on_timeout`
fallback instead of guessing.

---

## What you do NOT write

MUG fills these in, so you never see them:

| You might expect to handle | MUG does it for you |
|---|---|
| API keys / secrets | read from the deployment by name; never in your code |
| Keeping the game history and the model's own thoughts | recorded and handed to you |
| The model being slow or failing | applies your `on_timeout` (repeat the last move / wait) |
| Tokens, retries, cost, logging | automatic, and recorded for you |
| "Which model call goes with which move" | recorded, so your data is reproducible |
| Deadlines, the scheduler, the provider | entirely under the surface |

---

## The fields you can set

| Field | Meaning | Default |
|---|---|---|
| `provider` | `Provider.OLLAMA` (free, local) / `ANTHROPIC` / `OPENAI` / `OSS` / `HTTP` | required |
| `model` | the provider's own model id, e.g. `"claude-sonnet-4-5"` | required |
| `secret` | the credential name; the value is bound at deploy | required for a hosted provider; **omit for a local one** (Ollama) |
| `decides_every` | act every N game steps | `1` (every step) |
| `on_timeout` | `Fallback.REPEAT_LAST` or `Fallback.WAIT` | `REPEAT_LAST` |
| `temperature` | model sampling temperature | the model's default |

**Run it free on your own machine.** Set `provider = Provider.OLLAMA` and `model` to
an Ollama model you have pulled (e.g. `"llama3"`), and **leave `secret` unset** -- MUG
reaches the local runner at `http://localhost:11434` with no key. This is good for
building and testing a study before you spend on a hosted model:

```python
class LocalPartner(LLMAgent):
    provider = Provider.OLLAMA
    model = "llama3"                 # a model you have pulled; no `secret` needed

    def get_prompt(self, env, agent_id, history, chat, thoughts):
        return env.text_view(agent_id)
```

Anthropic and OpenAI use the same class; you add the bound `secret` and change
`provider` and `model`. (A hosted provider needs a key: if you name one and forget
`secret`, MUG tells you at build time rather than failing mid-study.)

---

## One rule that keeps your data clean

Your agent class is a **definition** -- it is frozen and versioned with your study, so
the same study always runs the same agent. That is why the methods take `env`,
`agent_id`, `history`, `chat`, and `thoughts` as arguments instead of storing them on
`self`: the definition holds no per-move state, so one agent can safely drive many
seats and many sessions, and the `history`, `chat`, and `thoughts` you read are the
exact recorded past. Write the methods as pure functions of their inputs (no wall
clock, no random module -- if you need randomness, MUG gives you a seeded source), and
your study stays reproducible.

Because of this, an agent instance is **never tied to one seat**: read `agent_id` to
know which player you are, and never store a seat on `self`. The same object can then
fill both sides of a two-player game -- see
[turn-based-agent-example.md](turn-based-agent-example.md), where one instance plays
both marks.

That is the entire surface an author touches. Providers, the scheduler, deadlines,
digests, and the decision record all live under it and stay out of your way.
