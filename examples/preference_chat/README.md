# Preference elicitation inside a conversation

A participant talks to a model. On each turn the model writes **two** replies; the
participant reads both, says which one they would rather have had, rates the pair
on the study's own axes, and **the conversation carries on from the reply they
chose**. The reply they did not choose is kept, with everything the platform knows
about where it came from.

These documents use ASD-STE100 Simplified Technical English.

## The two studies

They are the **same study**. Only the model it runs on differs.

| File | Model | Credential |
| --- | --- | --- |
| `ollama.py` | A model on your own machine | none |
| `anthropic.py` | A hosted Anthropic model | `ANTHROPIC_API_KEY` |

```bash
# Local: no key, no per-token cost, no participant text leaving the machine.
ollama serve
ollama pull llama3.2
uv run uvicorn examples.preference_chat.ollama:app

# Hosted.
export ANTHROPIC_API_KEY=sk-ant-...
uv run uvicorn examples.preference_chat.anthropic:app
```

`MUG_OLLAMA_URL` and `MUG_OLLAMA_MODEL` point the local study elsewhere;
`MUG_ANTHROPIC_MODEL` picks a different hosted model.

## Why elicit inside the conversation

An offline preference set asks somebody to rank two replies to a prompt they never
sent, in a conversation they were not having. Here the judgement is made by the
person who has to live with it: **the reply they pick is the reply they get**, and
the next turn is shaped by it.

That gives two things a static corpus cannot:

- the preference is attached to a real context — the participant's own words, and
  everything that was said before;
- the branch not taken is kept, so the pair is a genuine counterfactual rather than
  two replies that were never in competition.

## What the participant is asked

```python
AXES = [
    Axis("helpful", "Which reply is more helpful?"),
    Axis("honest", "Which reply is more careful about what it does not know?"),
    Axis("tone", "How well does each reply match the tone you wanted?", each=True),
]

Elicit.replies(n=2, ties=True, on=AXES, sample=1.0, skippable=True)
```

- A plain axis is a **slider between the two replies**. `each=True` rates each reply
  on its own, which is what a reward model reads as an absolute score rather than a
  comparison — both shapes are asked here because they are different data.
- `ties=True` matters more than it looks. Without it, a participant who thought both
  replies were equally good has to invent a preference, and the data then records
  one they did not have.
- `sample=1.0` elicits on every turn. A longer study lowers it, and which turns are
  elicited is then **derived** from the study and the message rather than drawn — so
  the same conversation always elicits at the same places, and a refresh does not
  move them.
- **An answer names the reply, never the side of the screen.** The order is shuffled
  per participant, so an answer that meant "the left one" could not be read back.

## The files

- `agent.py` — the model definition and the axes. One file, both studies.
- `study.py` — consent, instructions, the conversation, a survey, a debrief.
- `ollama.py` / `anthropic.py` — the two entry points. Read them side by side; the
  difference is three lines.

## The credential

`anthropic.py` is worth reading for this alone. The key is resolved by a
**function**, at call time:

```python
def read_api_key(name: str) -> str:
    ...
    return os.environ["ANTHROPIC_API_KEY"]

preference_chat(HostedCounsellor(), resolve_secret=read_api_key)
```

A string would be captured wherever the study is captured — the compiled study
version, the published bundle, the recorded agent build — which for a platform that
compiles, publishes, and exports is several places a key has no business being. A
function is read once per call and put into one request header. What the ledger
records is the request digest and the **name** of the secret, never its value.

`tests/unit/app/test_preference_chat_examples.py` proves it: the key reaches the
`x-api-key` header of every request, and appears in nothing the deployment wrote
down. Those tests drive both studies end to end through the **real** provider
adapters with a fake HTTP transport, so no test here needs a network or a key.
A live local runner is exercised separately in
`tests/unit/agents/test_provider_adapters.py`.

## What comes out

`mug export` writes the pairs as the rows the field trains on — `prompt`, `chosen`,
`rejected`, and the conversational `messages` — plus what no published corpus
carries: the verdict, whether a tie was offered at all, each axis resolved to which
reply it favoured, which reply was shown first, the response time, and the full
lineage back to the conversation it came from.
