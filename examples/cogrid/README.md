# Overcooked (CoGrid)

Two chefs share a kitchen, make onion soup, and deliver it. It is a coordination
task: neither chef can finish a dish alone in the time given.

These documents use ASD-STE100 Simplified Technical English.

## Install the environment

```bash
uv pip install cogrid==0.3.2
```

The platform does not depend on it. An environment is the study's own choice, so
these modules say what is missing rather than failing part way through a run.

## The five studies

| File | What it shows | Execution |
| --- | --- | --- |
| `overcooked_human_ai.py` | A trained network and a written partner, one round each, then a judgement between them on five axes | server |
| `overcooked_llm_chat.py` | A **language model** in the second seat that the participant can **talk to while they cook**, over three rounds and one conversation | server |
| `overcooked_human_ai_browser.py` | The same task with **nothing on the server**: the kitchen and the trained partner both run in the participant's browser | browser (Pyodide) |
| `overcooked_human_human.py` | Two participants in one kitchen | browser peer-to-peer |
| `overcooked_server_auth.py` | The same two participants, with the server stepping the kitchen | server |

The server study needs `uv pip install onnxruntime`. The browser study needs
nothing extra to score the model: the browser loads the JavaScript build of the
same runtime and scores the same model file beside the environment. It also needs
no kitchen beside the application -- `cogrid` is installed into the participant's
browser, and the study composes without it on the server.

```bash
uv run uvicorn examples.cogrid.overcooked_human_ai:app
```

The talking study needs a model to talk to. It defaults to a local one, so there is
no key and no per-token cost, and no participant's words leave the deployment:

```bash
ollama serve
ollama pull llama3.2
uv run uvicorn examples.cogrid.overcooked_llm_chat:app
```

The peer-to-peer study gates entry on a launch ticket: the application prints one
at start, and the second participant needs a second ticket against the same store.

## The pieces

- `env.py` — the kitchen this study hands over, its scene, and its drawing. A
  server-run study names `overcooked_kitchen()` and nothing else; the browser and
  peer-to-peer studies still carry a Python bundle, because a browser run supplies
  the program it runs.
- `partners.py` — the policies a participant is compared between.
  `exported_partner` is the trained network the legacy study played against;
  `scripted_chef` fetches, cooks, and delivers, so it runs the kitchen on its own
  and goes wherever the next job is; `station_keeper` carries only what it is
  given, so it takes nothing the participant was going for and delivers nothing
  until they bring it something. The two written ones walk the floor rather than
  the straight line, so neither presses itself against a counter for the round.
- `chef_agent.py` — the partner that cooks **and** talks. One model call gives
  three things: the job it does, the words the participant reads, and the plan it
  carries into its next decision.
- `kitchen_text.py` — the kitchen in words, which is what a language model can act
  on. The platform hands a seat 892 numbers; that is right for a trained network
  and nothing a model can read, so the study says what the room looks like.
- `pages.py` — what a participant reads, with the pictures in it. A page names a
  declared asset (`![Chef with a blue hat](blue-chef =36x48)`), so the chef and
  the keys are shown rather than described.
- `sprites.py` — the sprite sheets. The platform draws an atlas frame by index;
  the sheets name their frames, so this reads each `.json` once and hands back the
  name-to-index map.

## The drawing reads a scene, not the environment

`kitchen_scene()` turns one frame of the kitchen into plain data — the tiles, the
things on them, what is in each pot, where the chefs are, and what the shift has
delivered — and `draw_kitchen()` reads only that. The study names it as the
activity's `scene=`, and the platform calls it once a frame and puts the answer in
that frame's own metrics. It is written this way because **a frame is recorded**:
what a study puts in a frame's metrics is written into the run, so a drawing that
read a live CoGrid object could not be recorded and could never be drawn again from
the record. A replay redraws this kitchen with no CoGrid installed.

Two things about CoGrid are worth knowing before you write against it:

- **It numbers its agents.** The seats are `0` and `1`. The study writes its seating
  over those, because they are the environment's own agents — there is no map from a
  study's word for a chef to CoGrid's number to get wrong. What the *records* call
  the seat is `agent-0`, which the platform derives, because an identifier in a
  record has to be a name.
- **It only writes its state back onto the grid objects when it is asked to draw.**
  Read `env.grid` without asking and you see the opening frame for the whole run:
  the chefs never move and the pots stay empty. `caught_up()` asks for the
  write-back alone, without making it produce a picture nobody reads.

## A partner that plans reads the kitchen

The platform hands a seat its own observation, which is right for a policy: the
trained partner in `partners.py` is scored on exactly the features CoGrid produced
for that seat. A partner that walks a route is not a policy — it needs the grid, the
pots, and where the other chef is standing — so it names a `sees`, and the loop shows
it the environment **it** is stepping.

That is why the study does not hold the environment itself. One study object serves
every participant at once, so a partner that kept the kitchen it built would hand one
participant's kitchen to another participant's partner.

## The comparison

`overcooked_human_ai.py` is worth reading even if you do not use Overcooked. The
whole partner judgement is one object:

```python
Comparison(
    key="which-partner",
    ask="Did you prefer your first or your second partner?",
    options={"First partner": "round-one", "Second partner": "round-two"},
    ties=True,
    on=[
        Axis("coordination", "We coordinated our actions well together."),
        Axis("helpful", "How helpful was each partner?", each=True, points=7),
    ],
)
```

The platform blinds the two partners, shuffles which is shown first, records the
answer **against the candidate rather than the screen position**, and exports it
beside the two trajectories it is about. The legacy version of this study needed a
custom slider scene, and recorded the answer as free-form scene data that nothing
could join back to a run.

## What changed from the legacy version

The five layouts are now a **deployment** choice rather than a per-pair one. Both
browsers must ship the same environment, and a room forms before either
participant could be told which layout they were given. A study that wants all
five runs one deployment for each and pools the exports. The legacy version drew
one layout per pair with `RandomizeOrder(keep_n=1)`, which worked because the
scene was chosen before matchmaking rather than after it.

## How often the partner decides, and why it matters here

Every partner takes `decide_every`, the frame skip. The Overcooked studies set it
to **5**, as the legacy study did: a partner asked for an action thirty times a
second changes its mind faster than a person can read it.

On the frames it does not decide on, a partner in this kitchen **stands still**
(`between=NOOP`) rather than repeating its last move. That is not a detail. A
kitchen is a grid, so repeating one step of a walk five times walks five squares,
and a partner asked to step towards a pot arrives somewhere past it.

**What the frame skip costs the trained partner.** It acts five times less often,
and that is what it means. Measured over a 600-frame round in `cramped_room`, with
a busy cook on the other seat:

| `decide_every` | dishes the pair delivered |
| --- | --- |
| 1 | 13 |
| 2 | 1 |
| 5 | 1 |
| no partner at all | 10 |

The network was trained to act once per environment step, so pacing it plays a
slower policy than the one that was trained — and in a room this small a slow
partner is in the way. The written `scripted_chef` is unaffected, because it
recomputes the next job from where it is standing. If a study wants the trained
partner to help rather than to be paced, `overcooked_human_ai.py` changes one
argument: `exported_partner(decide_every=1)`.

## The HUD

`kitchen_hud()` is the status line the legacy study showed: dishes delivered, and
time left. It is drawn onto the **game's own surface**, so it is in the render
packet, in the record, and in a replay — what the participant was being told is
part of what happened to them. The browser bundle draws the same line itself,
because in browser execution the study owns the whole drawing.

## Rounds, and which modes can play them

`Game(..., episodes=N)` loops only in the two **server-stepped** modes. A
browser-executed game is written by the client and captured once, and a
peer-to-peer room runs once to its end, so neither has a round loop on the server.
A study that asked for five rounds on either used to play **one** and say nothing;
`build_study_app` now refuses that pairing where the author can see it. A study
that wants several rounds of a browser or peer-to-peer game writes several game
activities.

## One press, one move

The Overcooked games set `input_mode="single_keystroke"`: **each press is one
action**, however long the key is held. A kitchen is a grid, so that is what a
participant means. Under the other reading -- `pressed_keys`, where a held key acts
on every frame -- a tap of the pick-up key that lasts a tenth of a second is three
actions at thirty frames a second, so a dish goes down and comes straight back up,
and a tap of an arrow crosses the room.

Slime volleyball keeps `pressed_keys`, and is right to: a slime holding left is
moving left, letting go is itself a decision, and its diagonal jumps are chords a
participant holds down.

A press is counted when the key **arrives**, so a chord still works: pressing up
while left is held is one press of the pair, not a second press of left.

A chord is written as the **sequence of keys** it is::

    ACTION_BINDINGS = {
        "ArrowLeft": LEFT,
        ("ArrowUp", "ArrowLeft"): UPLEFT,
    }

It was once one name with a ``+`` in it. That hid a sequence inside a string, put
a character with a meaning into a key name, and could not be written down in the
platform's own key-name rule, which allows no such character.


## A language model in a thirty-frame-a-second kitchen

`overcooked_llm_chat.py` puts a model in the second seat of the **shipped** kitchen
-- `cramped_room`, 600 frames, thirty a second -- and nothing about the kitchen was
slowed down to let it play. The reason it works is one decision:

**the model chooses jobs, not moves.**

A trained network is scored in under a millisecond, so it decides every fifth
frame. A language model answers in one to five seconds. Choosing grid moves it
would act about ten times in a round and would not be a teammate; choosing jobs it
makes about ten **decisions**, and ten jobs is a whole shift's cooking.

Two methods on the agent say the whole of it:

```python
class TalkingChef(LLMAgent):
    def decides_among(self, env, agent_id):
        return ["FETCH_ONION", "FILL_POT", "DELIVER", ...]

    def carry_out(self, env, agent_id, chosen):
        # one grid move that carries the chosen job forward, this frame
        ...
```

`carry_out` is asked once for every frame the seat is read, against the kitchen the
loop is stepping. It is not new code: `partners.Chef` already walks a kitchen full
of counters to a job and does it, and it is what `scripted_chef` is made of. The
only thing that changes under a model is *who chooses the job*.

The seating is written exactly as it is for a trained partner:

```python
seats={CHEF_ONE: Human(), CHEF_TWO: Model(TalkingChef(), text_view=kitchen_as_text)}
```

### The one thing to get right when an agent talks

`LLMAgent.parse_reply` defaults to "the last legal name anywhere in the reply".
That is right for an agent that only plays and **wrong** for one that also talks:

```
JOB: DELIVER
SAY: after this I will FETCH_ONION again
```

The default reads `FETCH_ONION` -- so the partner walks to the crates while telling
its teammate it is delivering, and the study blames the model. `TalkingChef` reads
the job only off the `JOB:` line and the words only off the `SAY:` line.

### Three rounds, one conversation

The activity plays three rounds, and they are one interaction -- so they are one
conversation. What each model seat carries across the rest between rounds is the
transcript and its own plan; the history is not carried, because a round is its own
episode with its own trajectory.

### A hosted model is one argument

```python
class HostedChef(TalkingChef):
    provider = Provider.ANTHROPIC
    model = "claude-sonnet-5"
    secret = "anthropic-api-key"

study = overcooked_llm_chat_study(
    HostedChef(), resolve_secret=lambda name: os.environ["ANTHROPIC_API_KEY"]
)
```

The credential is resolved by a function at call time and never written into the
study, so it is absent from the compiled study version, the published bundle, and
the recorded agent build.
