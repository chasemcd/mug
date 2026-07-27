# Let participants talk to a model

*For study authors. You name the model and its persona. MUG runs the conversation
over the live socket, records every message as canonical evidence, and puts the
transcript in your export -- you never touch channels, sequences, digests, or the
data store.*

> Status: **built and mounted.** The conversation runtime (`mug.conversation`), the
> agent turn (`mug.agents.chat.ChatAgent`), and the transport mount
> (`mug.participant_chat`) all run, and a participant reaches the conversation over
> the same `/ws` socket a game runs on. Proven by `tests/unit/app/test_chat_flow.py`
> (a participant plays the whole flow and talks to a model) and
> `tests/unit/conversation/test_chat_mount.py` (the mount against a scripted socket).
> Not yet built: a chat *screen* in the shipped browser client, so today a study
> supplies its own client frames or uses the test client.

---

## The whole thing

You write one agent definition and one chat activity:

```python
from mug.app import build_app_from_env
from mug.authoring import Fallback, LLMAgent, Provider
from mug.agents import AgentIds
from mug.participant_chat import ChatSeatSpec, ChatSpec


class Interviewer(LLMAgent):
    """The partner your participants talk to."""

    provider = Provider.ANTHROPIC
    model = "claude-sonnet-5"
    on_timeout = Fallback.REPEAT_LAST

    def get_prompt(self, env, agent_id, history, chat, thoughts) -> str:
        return "You interview a participant about their week. Ask one question."


app = build_app_from_env(
    chat=ChatSpec(
        seat=ChatSeatSpec(
            agent=Interviewer(),
            adapter=my_adapter,          # your provider adapter
            ids=my_published_ids,        # what `mug publish` gave you
            actor_id=my_agent_actor_id,
        ),
        greeting="Hello. Tell me about your week.",
    )
)
```

That is the entire thing. The participant now plays your forms, reaches the
conversation, talks to the model, and goes on to the debrief and the completion code.

Everything else has a sensible default, so you change only what you mean to change:

| You write | Default | What it does |
| --- | --- | --- |
| `seat=` | — | the model the participant talks to |
| `channel_key=` | `"chat"` | the channel name that the recorded messages carry |
| `policy=` | answer once per message | when the model may speak (see below) |
| `greeting=` | none | an opening message the model posts first |
| `max_messages=` | `20` | how many messages a participant may send |
| `max_message_length=` | `4000` | longer text is trimmed, not refused |
| `context_messages=` | `20` | how much of the transcript the model reads |
| `mention_token=` | none | the word a `mention` policy listens for |
| `compose=` | the transcript | build your own model payload |
| `render_reply=` | the `text` field | read your own model output shape |

---

## When the model speaks

A `TurnPolicy` says when the model may answer. The default lets it answer each
message once. To make it answer only when a participant names it:

```python
from mug.conversation import TurnPolicy

ChatSpec(
    seat=...,
    policy=TurnPolicy(
        channel_key="chat", activation="mention", max_model_activations_per_turn=1
    ),
    mention_token="partner",
)
```

The four activation modes are `free` (always), `mention` (only when named),
`round-robin` (only on its own turn), and `moderated` (only when a moderator clears
the turn). This mount has no moderator, so a `moderated` channel stays silent: that
is the truthful result, because nothing cleared the turn.

---

## What the participant sees

**You need no client code.** Both shipped clients render the conversation: a
transcript, a message box, and an "End the conversation" button that advances the
flow to your next activity. The two authors are labelled "You" and "Them" -- the
screen never says whether the other party is a person or a model, because only your
study knows that and only your study may say it. Tell the participant who they are
talking to on the page before it, in the words your ethics approval uses.

The opening message is yours: set `greeting=` and the seat speaks first, so nobody
faces an empty box.

## What the client sends and receives

A study that supplies its own client speaks these frames. The mount owns the socket
during the conversation. The client sends:

```json
{"type": "chat", "text": "hello"}
{"type": "chat_end"}
```

and receives one frame per message the model posts:

```json
{"type": "chat", "message_id": "message_...", "author_actor_id": "actor_...",
 "sequence": 2, "text": "Hello. Tell me about your week."}
```

An empty message costs no turn. A frame that is not valid json is dropped, and the
conversation continues. The activity ends on `chat_end`, on the message bound, or
when the participant closes the tab -- and in every case what was already said stays
recorded.

---

## What gets recorded

Every exchange writes canonical API-08 evidence through the same command spine a game
uses, so a conversation replays and exports like an episode:

- a **chat message** per turn, in one total sequence order across both authors;
- a **delivery receipt** per recipient, so you can prove what reached whom;
- a **context snapshot** per model reply, naming the exact messages the model read.

The ledger records the message **digest**, never the text. That is deliberate: the
platform names content and does not hold it. The text lives in the connection for as
long as the conversation runs. If your study must keep the text, write it to your own
content store behind the `compose` seam:

```python
def compose(recent):
    return {"messages": [my_store.read(m.message_id) for m in recent]}

ChatSpec(seat=..., compose=compose)
```

A model reply is recorded by the model output's **own** digest, so the reply and the
call that produced it are named by the same value, and the durable output tape
(API-16) rehydrates the verbatim reply on a replay.

---

## Trying it without a provider key

The adapter is yours, so a test or a local run needs no vendor and no key:

```python
from mug.providers import ModelCall, ModelCompletion, Usage

async def my_adapter(call: ModelCall) -> ModelCompletion:
    return ModelCompletion(
        outcome="completed",
        resolved_model="fake-local",
        usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
        output={"text": "Tell me more."},
    )
```

Set `provider = Provider.OSS` on your agent and leave `secret` unset for a keyless
local runner (Ollama or your own endpoint). A hosted provider without a credential is
refused at publish time, not at run time.

---

## What is not built yet

- **More than one model seat in one channel.** The mount seats one model beside one
  participant. The runtime under it (`ConversationChannel`) already orders any number
  of authors, so this is mount work, not runtime work.
- **A moderator.** A `moderated` policy therefore stays silent.
- **Chat beside a game.** A study runs a conversation *or* a game as its interactive
  activity, not both, because the demo flow holds one interactive step.
