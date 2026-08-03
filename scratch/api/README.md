# The developer API: an author hands over their environment, and nothing else

Scratch. Nothing in `mug/` imports any of this.

```
uv run python scratch/api/derive.py     # what can be read off a real environment
uv run python scratch/api/study.py      # the study that reads, and every refusal
```

- `derive.py` — the derivation, run against the **installed** CoGrid, Gymnasium and
  PettingZoo. Every number below came out of it; none of it is assumed.
- `sprites.py` — sprites as assets addressed by **filename**, run against this
  repository's own Overcooked sheets.
- `proposed.py` — the activity surface on top of the derivation.
- `study.py` — one study with a PettingZoo kitchen in the browser, a Gymnasium hill
  on the server, and a standalone conversation. That study cannot be written today.

## 0. Decided

| question | decision |
| --- | --- |
| Is `runs=` written or inferred? | **Written**, `server` as the default. A browser run is a download the participant waits through and a different meaning of "verified", so it is not acquired silently. |
| How is an atlas frame addressed? | **By filename only.** `Atlas("terrain", "terrain.png", "terrain.json")`; the platform reads the atlas; a drawing says `frame="counter.png"`. No integer index. |
| How does a custom drawing reach a browser run? | **Its source is carried**, under the self-contained rule. Naming frames by filename is what makes that rule easy to satisfy. |
| Is there an escape hatch for a non-Gym/PZ environment? | **No.** Derive or refuse. An environment that is neither gets a small wrapper from its author. One path, always tested. |
| Who keeps the name `Chat`? | **The activity.** The agent's read-only transcript is renamed `Transcript`, which is the better name for it anyway. |
| How does a study say how long a press lasts? | **`Game(..., held_actions: bool)`** — a plain keyword on the activity beside a plain `keys={...}` map. Required when the study binds its own keys; there is no default, because a grid and a court want opposite answers. |
| Is the derived agent list pinned? | **Recorded, warn only.** The published study version carries the agent list it was compiled against; a deployment whose environment disagrees warns rather than refuses. |
| Can `decides_every` be randomized? | **It stays a plain number.** A study that varies it places a `Treatment` over the **whole seating**, which is the mechanism that already exists and keeps placement at one level. |
| Where are assets declared? | **On the activity that draws them** — `Game(..., assets=[Atlas(...)])`. `Study(assets=...)` is for study-wide pictures only. So an asset loads before the activity that needs it, instead of everything loading before anything. |
| What exactly may `env` be? | **`Callable[[], gymnasium.Env \| ParallelEnv \| AECEnv]`** — one kind of thing, taking no arguments. A class, a `functools.partial`, or the study's own function. A registered id string, a built environment, and a duck-typed look-alike are all refused. |

---

## 1. The requirement

An author gives MUG the Gymnasium- or PettingZoo-formatted environment they trained
in. MUG does the rest. No `BrowserGameSpec`, no `source_bundle`, no `MultiSeatGame`,
no hand-written package pin, no seat-to-index map.

The appeal of the platform is that the step from "my agent trains against this" to "a
participant plays this in a browser" is short. **Every specification an author writes
by hand is a piece of that step they are doing themselves.**

---

## 2. What can actually be read off an environment

All verified against installed packages by `derive.py`:

| the author writes this today | derived from | read as |
| --- | --- | --- |
| `requires=("numpy", "cogrid==0.3.2")` | `packages_distributions()` + `version()` | `cogrid==0.3.2` |
| `source_bundle` — 200+ lines of Python, **twice** in `examples/cogrid/env.py` | the class path / id / factory | one generic bundle |
| `MultiSeatGame` vs `GameSpec` vs `BrowserGameSpec` | `ParallelEnv` / `AECEnv` / `gymnasium.Env` base | `pettingzoo-parallel` |
| `CHEF_ONE`/`CHEF_TWO` + the `COGRID_ID = {…: 0, …: 1}` map | `env.possible_agents` | `[0, 1]` |
| the action count and `default_action` | `env.action_space(agent)` | `Discrete(7)` |
| `fps=30` | `metadata["render_fps"]` | `35` |
| `max_steps=600` | `spec.max_episode_steps` / `env.max_steps` | `600` |
| `draw_kitchen()` + `_MESH_BUNDLE`'s `draw()` + `_BROWSER_BUNDLE`'s `draw()` | `render_mode="rgb_array"` | a `(128, 160, 3)` uint8 frame |
| the HUD band and text, hand-written **twice** in the bundles (`env.py` 743-752, 970-979) | `mug/game/runtime.py:draw_hud` | the platform draws the band; a study writes the line |
| `ACTION_BINDINGS` | `get_keys_to_action()`, where declared | MountainCar: `{ArrowLeft: 0, ArrowRight: 2, ArrowRight+ArrowLeft: 1}`, default `1` |

Two of those are worth pausing on.

**The pin cannot drift any more.** A browser run is verified by the server
re-executing it, so the two must step identically. The browser pin and the server
package are written in different places today; they drifted once (the browser asked
for cogrid 0.2.1 while the server had 0.3.1), and the consequence is that *every
honest run is refused*. Derived from the installed class, one cannot differ from the
other. `Study.requires` merges them across environments, so a study with two cannot
pin one and forget the other.

**`get_keys_to_action` is already the platform's own binding shape.** MountainCar
returns `{(): 1, (276,): 0, (275,): 2, (275, 276): 1}` — a map from a **tuple of held
keys** to an action, with the empty tuple as the default. That is chords and a default
action, which is exactly what `mug.game.keys.Bindings` holds. An environment following
the `gymnasium.utils.play` convention needs no bindings written at all.

---

## 3. The eight game mounts collapse into two words and the seating

This is the part that surprised me. `build_study_app` takes nine mutually exclusive
keywords. None of them is a decision an author should be making, because each one
follows from the environment and the seats:

| today's keyword | is just |
| --- | --- |
| `game` | server + one Human |
| `server_game` | server + Human and Bot seats |
| `agent_game` | server + Model seats |
| `turnbased_game` | server + an **AEC** environment — read off the base class |
| `browser_game` | browser + one Human |
| `mesh_game` | browser + two or more Humans |
| `browser_p2p` | the same, with entry gated — a deployment concern, not a study one |
| `concurrent_mesh` | how many rooms run at once — many, always |
| `chat` | not a game at all → `Chat(...)` |

`study.py` prints the mount each activity resolves to, so the claim is checkable:

```
cook         game  in the participant's browser  [0=human, 1=bot]  -> browser_game
drive        game  on the server x2  [agent=human]                 -> game
practice     game  on the server  [0=human, 1=bot]                 -> server_game
real         game  in the participant's browser  [0=human, 1=bot]  -> browser_game
```

So `runs=` has two values, `Execution = "server" | "browser"`, and it stays on the
activity rather than moving to the builder because it is a study decision the
participant feels: a browser run downloads a Python runtime before the first round,
and it is verified by re-execution rather than recorded as it is stepped.

---

## 4. What the author still writes, and why each one is real

```python
Game("cook", kitchen, runs="browser",
     seats={0: Human(), 1: Bot(chef, decides_every=5)},
     keys=KITCHEN_KEYS, held_actions=False, default_action=NOOP,
     render=draw_kitchen, hud=kitchen_hud, assets=kitchen_sheets,
     caption=COOK_CAPTION)

Game("drive", hill, runs="server",
     seats={"agent": Human()}, render=draw_hill, episodes=2)
```

- **`seats=`** — which of the environment's own agents each player takes. The map is
  the study's most consequential decision, and it is now also the **only** place a
  study says somebody other than the participant is playing. Today a partner is
  written in three unrelated ways: a closure argument (`overcooked_game(partner)`), a
  specification field (`BrowserGameSpec.partner=BrowserPartner(...)`), and a seating
  map. Where a `Bot` is *scored* follows from `runs=` — the application on a server
  run, the participant's own inference runtime in a browser — so it is one seat kind,
  not two.
- **`keys=`, `held_actions=`, `default_action=`** — the three things no environment API
  can say. `keys` maps a key, or a chord, to an action; CoGrid declares no
  `get_keys_to_action`, so a study must. `held_actions` says whether a bound key acts on
  every frame it is down (a court) or once per press (a grid) — required, not defaulted,
  on the record that `InputScheme.mode` shipped with no producer and no reader, so every
  study read held keys and a 100 ms tap became three actions. `default_action` is what a
  frame with no bound key takes, also required: action `0` is a no-op in some
  environments and "walk north" in CoGrid, so guessing it makes a chef walk upward for a
  whole round. An environment that follows the `gymnasium.utils.play` convention
  declares its own bindings, and that convention means **held**, so a study naming such
  an environment writes none of the three.
- **`render=`** — only when the environment's own frames are not good enough, or not
  available at all. The study's sprites, drawn by name: `frame="counter.png"`.
- **`assets=`** — the pictures **this** activity draws, declared where they are used.
  It is not tidiness: `_PRESENTATION_POLICY` is already `"required_before_activity"`, but
  with every picture at study level that means *every* picture must load before *any*
  activity. A study with a kitchen and a court currently makes somebody download both
  sets before the first round. Two activities may declare the same sheet — a practice
  round and a real one draw the same kitchen — and it is read once; what is refused is
  one **name** standing for two different files, naming both activities.
- **`hud=`** — one line the participant reads **on** the game while they play, as a
  function of the step. The platform draws the band across the top, so a study writes
  only the words, and because it is drawn onto the same surface it is in the record and
  in a replay: what a participant was told is part of what happened to them. `caption=`
  is the different thing — markdown read *beside* the game, which does not change as
  they play.
- **`runs=`, `episodes=`, `between=`, `caption=`, `chat=`** — unchanged.

**The `rgb_array` default is cheapest exactly where it matters.** On a browser run the
pixels are drawn in the same browser that made them and never travel; the recording is
actions and hashes, not frames. So "your trained environment in a browser with no
drawing code" is the cheap path, not a fallback. On a server run a frame per step is a
real cost on the wire, which is a further argument for the browser.

---

## 5. The hard edge, stated plainly

There is one, and it is about **what travels**.

A **class** or a **registered id** travels as an import line — nothing of the study
moves at all. A **factory** is study code, so its own source is carried into the
bundle, and it must then be self-contained: every name it uses is a literal or
something it imports **inside itself**, from a package a browser can install.

That rule is checkable, and `derive.py` checks it by reading the factory's imports:

```
Game("cook", kitchen)  -- a self-contained factory
  requires      ['cogrid==0.3.2']
  in a browser  yes

Game("cook", kitchen)  -- the same, importing the study's own config
  in a browser  NO
    - the factory '_kitchen_factory' imports examples, which is the study's own code
      and a participant's browser cannot install it. Move what the factory needs into
      a published package, keep the factory to imports the browser can resolve, or run
      this activity on the server.
```

It is not a burden in practice: a factory that builds an environment is four imports
and a constructor. The refusal arrives while the author reads their own code, not as a
failed download in front of a participant.

**Why a callable rather than a class plus settings?** Because CoGrid's config holds live
objects — `"rewards": [DeliveryReward(coefficient=1.0, common_reward=True)]` — and a
live object has no written form that rebuilds it. Binding the construction inside a
zero-argument callable does not answer that question; it removes it.

**Two more limits found by running this, not by reasoning about it:**

- **A distribution holding compiled code cannot install in a browser.** Checked by
  scanning the installed distribution for `.so`/`.pyd`/`.dylib`, so it is refused up
  front rather than discovered as a failed `micropip` call.
- **An environment can declare `rgb_array` and still draw nothing.** Both Gymnasium
  classic-control environments do: they list it and render with pygame, which is not
  installed here and has no Pyodide wheel. So `draws` is answered by *drawing one*,
  not by reading `metadata`, and the reason is reported.

---

## 6. The refusals, all of which are silent today

`study.py` provokes each one; these are the real messages.

```
a seat the environment does not have
  the activity 'cook' seats 2, which its environment does not have; its agents are: 0, 1

a person at a keyboard bound to nothing
  the activity 'cook' seats a person, and nothing says which key is which action: its
  environment declares no get_keys_to_action, so write keys={...} and held=. Its
  action space is Discrete(7).

keys bound without saying how long a press lasts
  the activity 'cook' binds keys but does not say whether a key acts on every frame it
  is held (held=True, a court) or once per press (held=False, a grid). The two play
  completely differently, so there is no default worth guessing.

rounds a browser run plays once
  the activity 'cook' asks for 3 rounds, and a browser run plays one: the client
  writes the whole episode and reports it once. Write 3 game activities, or run it on
  the server.

a model seat where no provider can be reached
  the activity 'cook' gives 1 to a model, and a browser run cannot reach a provider: a
  credential must not travel to a participant's browser. Run it on the server, or seat
  an exported network with Bot(...).

a person with no picture at all
  the activity 'balance' seats a person and has no picture: the environment drew
  nothing (render() raised DependencyNotInstalled: pygame is not installed), so write
  render=. A participant cannot play a canvas that stays empty.
```

The last one is worth its own note: two shipped examples were unplayable while the
gate was green, one of them because a multi-seat game had no `render` at all. Reading
the drawing off the environment and refusing a person with no picture makes that
particular failure unwritable.

---

## 7. What is implicit today, exactly

The five faults the displaced environment causes, each verified against the code.

**a. One study can hold only one environment.** `mug/app.py:453-508` resolves the
builder's keywords through an `if / elif` chain to **one** `on_game` hook, and
`serve_session(..., on_game=on_game)` (`mug/app.py:527`) is the only hook a session
has.

**b. The execution cannot vary per activity.** Server, browser, and mesh are three
different builder keywords.

**c. Nine mutually exclusive keywords, with no mutual exclusion.** Checked:
`build_study_app(study=s, game=g, chat=ChatSpec())` is **accepted**; the chat arm wins
and the game is dropped with nothing said. The chain has no arm for `browser_game` at
all, so it ships its client manifest while a different hook owns the activity.

**d. A conversation is written as a game — or as an activity — depending on what else
is happening.** Beside a game it is `Game(..., chat=...)`; alone it is a builder
keyword that replaces the game hook. `examples/preference_chat/study.py` says so in a
comment. And `ActivityKind` (`mug/content/study.py:98`) has no `"chat"` while
`_COMPONENT_PROFILE` (`mug/content/components.py:82`) has both `"chat"` and
`"game-chat"`, so the recorded kind says the participant played a game.

**e. A partner is written in three places** — see §4.

**Also:** round validation reaches across the seam (`_refuse_unplayable_rounds`,
`mug/app.py:535`, needs the study *and* the builder's keywords together), and a
mistyped seat key survives the build to raise `KeyError` on a participant's first
frame.

**The precedent that already exists.** The seated path dispatches per activity:
`build_agent_on_game(..., specs: Mapping[str, AgentGameSpec])`
(`mug/participant.py:3177`). Then `mug/app.py:708` throws most of it away:

```python
if agent_game is None and seated:
    agent_game = next(iter(seated.values()))   # two seated activities -> the first, twice
```

---

## 8. What each example writes instead

| today | proposed |
| --- | --- |
| `examples/cogrid/env.py` — 1074 lines: two hand-written browser bundles, three env wrappers, a scene serializer, the drawing **three times**, the HUD band **three times**, a seat-to-index map | one `kitchen()` factory (~25 lines), one `draw_kitchen` (~60), one `kitchen_hud` (3), plus the three input keywords |
| `overcooked_game(partner)` / `overcooked_browser()` / `overcooked_mesh()` / `overcooked_two_seat()` | one factory; `runs=` and `seats=` on the activity pick the rest |
| `BrowserGameSpec(partner=BrowserPartner(model=..., decide_every=5))` | `seats={1: Bot(chef, decides_every=5)}` |
| `requires=("numpy", COGRID)` | derived |
| `Study(..., assets=overcooked_assets(policy=True))` | `Game(..., assets=[Atlas(...)])` on the activity that draws them; study level is for study-wide pictures only |
| `build_app_from_env(study=s, browser_game=...)` | `build_app_from_env(study=s)` |
| `Game("talk")` + `build_study_app(chat=...)` | `Chat("talk", Model(agent), ...)` |

---

## 9. What the platform has to change

1. **`mug/content/study.py`** — `Game(key, env, *, runs=, seats=, keys=, held=,
   render=, **settings)`; the six refusals; `Chat(...)` as an activity.
2. **A new derivation module** — `derive.py` is its prototype. It builds the
   environment once at publish time, reads it, and throws it away. It is also where a
   browser run's requirements and blocks come from.
3. **The generic browser bundle** — one copy for every environment, replacing the
   per-example `source_bundle`. It needs a surface command for "paint the frame the
   environment drew"; `derive.py` emits `{"op": "frame", ...}` as a placeholder, and
   whether that is a new op or an existing `image` over a data URI is an open call.
4. **`mug/app.py`** — build one runtime **per game activity** and dispatch on the
   activity the session is at. `_add_realtime` loses its `if / elif` chain;
   `_refuse_unplayable_rounds` moves onto the activity. The seated path (`specs=`) is
   the shape to generalize.
5. **`ActivityKind` gains `"chat"`** — a frozen-schema change, so a fixture restamp
   and a freeze-ledger rebuild.
6. **`mug/authoring/agents.py`** — rename `Chat` (the agent's read-only transcript
   view) to `Transcript`, freeing `Chat` for the activity beside `Form`, `Page`, and
   `Game`.
7. **Every example** — per §8. `examples/cogrid/env.py` mostly deletes.

---

## 10. Sprites: the legacy shape, restored

`sprites.py` runs this against the real sheets.

The legacy package registered a sheet by its **two files** and Phaser loaded them, so
every frame was known by the name it was packed under:

```python
surface.register_atlas("terrain", img_path=".../terrain.png",
                                  json_path=".../terrain.json")
# mug/server/static/js/phaser_gym_graphics.js:353
this.load.atlas(obj_config.name, obj_config.img_path, obj_config.atlas_path)
```

The legacy surface took `frame: str | int` and passed it through
(`sprite.setTexture(image_name, frame)`), so a drawing said `frame="counter.png"`.

The rewrite made the **study** parse the atlas and address frames by integer index —
`Atlas(name, path, frames=[(x, y, w, h), ...])`. Three costs, all paid in this
repository today:

1. `examples/cogrid/sprites.py` exists only to read the JSON and hand back a
   name-to-index map (`_sheet`, `frames_of`).
2. Each browser bundle carries that map serialized into its header —
   `TERRAIN_FRAMES`, `OBJECT_FRAMES`, `CHEF_FRAMES` at `examples/cogrid/env.py`
   1008–1010 — so the drawing can turn a name back into a number.
3. **An index means nothing on its own.** Re-pack a sheet with one more sprite, every
   index after it moves, the study still runs, and it draws the wrong pictures.

So: the platform reads the atlas, and a frame is its filename. Read from the real
files:

```
terrain      7 frames   counter.png, dishes.png, floor.png ...
objects     15 frames   dish.png, onion.png, pot-explosion.png ...
chefs       44 frames   EAST-bluehat.png, EAST-dish.png, EAST-greenhat.png ...
soups       27 frames   soup_cooked_tomato_0_onion_1.png ...

terrain / counter.png    -> (1, 1, 15, 15)
chefs   / EAST-onion.png -> (69, 1, 15, 15)

the sheet 'terrain' has no frame 'counter.PNG'; it holds 7 frames, including:
counter.png, dishes.png, floor.png, onions.png, pot.png, serve.png

the sheet 'tiles' names tiles.json, which declares no frames: it is neither a frame
mapping nor a texture list, so nothing can be drawn from it
```

Both packer shapes appear in this repository's own assets, so the reader handles
both — and `tiles.json` has neither, which today would declare zero frames and fail
at the first draw.

**The client change is one word.** Both shipped clients already funnel every lookup
through `assets.frame(image_name, frame)` (`mug/webclient/renderer.js:285`,
`ts/src/client/assets.ts:60`). `frames` in the manifest becomes an object keyed by
name rather than a list whose order is the contract, and the lookup is by name.

**This is also what makes the drawing travel.** With frames named, `draw_kitchen`
references asset names and literals and nothing else, so its source carries as it
stands — one drawing for the server and the browser both, where `examples/cogrid/env.py`
has the same drawing written **three times** (`draw_kitchen`, the `draw` in
`_MESH_BUNDLE`, the `draw` in `_BROWSER_BUNDLE`). The two bundled copies exist
*because* the server's version reaches `frames_of`, which cannot travel.

---

## 11. What the implementation found

Phases A to F are built. What follows is what building it taught, which is the part
worth reading: three of these were not visible from the design.

### Built, green, and end to end

`tests/unit/app/test_named_environment_plays.py` is the requirement as a test: a study
writes one `Game` line and a drawing, a participant connects, plays, and leaves a
recorded run. The agents, the action set, the key bindings, the frame rate, the episode
bound, and the package pin are all read.

`mug/mounts.py` resolves the nine keywords. `tests/unit/app/test_mount_resolution.py`
asserts each one from two words and a seating, and
`tests/unit/app/test_chat_activity.py` holds one study with a game **and** a
conversation -- which the keywords could not express at all.

### What porting the rest of the examples found

**1. `render_mode="rgb_array"` has nowhere to go.** The design's cheapest path does not
exist. The eight surface commands are shapes, text, and a **named sprite**; not one of
them paints a bitmap, in either client. So an environment that draws its own frames
still needs `render=`, and `Game` now says exactly that rather than accepting the study
and showing an empty canvas. Painting one needs a ninth op, which is a frozen-contract
change and an open call: on a browser run the pixels never travel, but on a server run
it is a bitmap per frame on the wire.

**2. A generic browser bundle needs a decision the design did not reach.** The client's
own driver (`mug/webclient/browser_game.js`) calls `make_env()` and `draw(observation)`
and reads the observation as **a flat list of floats** for the state hash. So:

- a single-agent environment in a browser is writable generically, and the drawing
  carries as source under the self-contained rule -- what it needs is the drawing
  surface carried too, which means `mug/game/surface.py`'s own source over a
  plain-dictionary command, plus a parity test that holds the two to the same output;
- a **multi-agent** environment in a browser is not, yet: the bundle must present a
  single-seat facade, and a drawing that needs environment state (a grid, a pot's
  timer) has no agreed way to reach it. `mug.mounts` therefore resolves a browser run
  and then refuses to build it, naming the two ways out. Nothing silently becomes a
  server run: the two are verified differently.

**3. The frame rate is the study's decision, and the environment is only its default.**
An environment declares `render_fps`, and some declare a non-standard key instead (Slime
Volleyball ships `video.frames_per_second: 50` and nothing else). Only the specified key
is read: an environment that says nothing there says nothing, and the rate falls to the
platform's own default. What settles it is `Game(..., fps=N)`, which outranks both --
how fast somebody plays is a property of the experiment, not of the task, and the same
environment is a training task at one rate and a study at another.

**4. A picture needs what an observation does not carry, so the study says what to
read.** A drawing is handed a stepped frame, and a frame holds the observation -- which
is what a **policy** is given. A kitchen's pots and counters, a court's ball, a board's
pieces all sit on the environment. So `Game(..., scene=)` is a function of the
environment, called once a frame, and what it returns rides in that frame's own metrics.
Putting it in the record rather than handing the drawing the live environment is the
whole point: a replay and an export then read the picture the participant saw. Every
multi-agent study here already had this function; each one had to write an adapter class
to get it into a frame.

**5. A seat that plans cannot be given only its observation -- and the study must not
hold the environment either.** The Overcooked partner walks a route and the Slime
Volleyball partner reads where the ball is going; neither is in an observation. The
first thing tried was for the study to keep the environment it built. **That is a
concurrency bug**: one study object serves every participant at once, so the second run
to start takes the first one's board. So a source may carry `sees`, a
`SeatView(env, agent_id)`, and every loop reads its seats through one helper
(`mug.game.seams.what_a_seat_reads`) -- the same shape an LLM seat's `TextView` already
had. Nothing changes for a policy: with no view, it is handed what it was always handed.

**6. A multi-agent environment wearing a single-agent base class is now refused.**
`slime_volleyball.SlimeVolleyEnv` subclasses `gymnasium.Env`, which acts one agent, and
asks for one action each for `agent_left` and `agent_right`. Read as it declares itself
it derives as **one** agent whose action is a whole dictionary -- which no key can bind
to, and which the loop would hand an integer. That was a silent wrong derivation; it is
a refusal now, and it names the wrapper to write. `SlimeCourt` in the example is that
wrapper, in about twenty lines.

**7. An environment that numbers its agents produced a record the contract refused --
and the contract was wrong.** CoGrid's agents are `0` and `1`, and a `seat_key` had to
match the authoring-key rule, which wants a leading letter. So the whole Overcooked port
failed on the **first drawn frame** with a validation error.

The first fix was to rename the seat (`agent-0`). The owner overruled it: numbering
agents is ordinary in both standard environment APIs, so refusing `0` was an oversight
in the contract rather than something a study should work around. The contract already
accepted `0` as an `env_agent_id` and refused it as a `seat_key`, which is the
inconsistency in one line.

So `SeatKey` is now its own type (`mug/kernel/refs.py`), split from `AuthoringKey` and
differing in exactly one way -- it may start with a digit. Four schema bundles gained a
`$defs/SeatKey` (api-04, api-05, api-07, api-09), eight `seat_key` properties were
repointed, and the bundle digests were restamped and the freeze ledger rebuilt. Both
`0` and `"0"` are accepted at the Python boundary and written down as text, so nothing
that reads a record has two shapes to handle. `seat_name` now **keeps** a name the
contract accepts, so `0` stays `0` and `agent_left` stays `agent_left`; it folds only
what cannot be carried (a capital, a space).

Two valid fixtures were added as evidence -- `api-05 seat-definition.numbered-agent` and
`api-07 render-packet.numbered-seat`, the record that actually failed.

**The change also found a hole in the freeze gate.** `check_bundle_binding` took a
hand-written set of schema names per family, and api-09's had not grown with the eleven
P2P records added later -- so half that family was no longer digest-checked. The digests
were still right, because the runtime conformance suite pins the same bundle, but that
is a second line of defence covering for a first that had quietly stopped looking. The
check now reads the names out of the corpus by family prefix and asserts the
hand-written set is a subset, so the list can no longer go stale in the direction that
hides work.

### What is ported, and what is not

Every **server-run** example is ported. What is left is the browser and mesh studies,
which are blocked on finding 2 and on nothing else.

| example | state |
| --- | --- |
| `mountain_car` (native) | **ported.** `native_demo.py` passes the study and nothing else |
| `preference_chat` (both backends) | **ported.** `Chat("counsel", Model(agent))` is a step; the `ChatSpec` factory is gone |
| `render_conformance` | **ported.** `conformance_spec()` stays for the tests that are about the drawing contract itself |
| `cogrid` `overcooked_human_ai`, `overcooked_server_auth` | **ported.** `overcooked_game()` and `overcooked_two_seat()` are gone, and so are `_OneChefKitchen`, `_TwoChefKitchen`, and the `COGRID_ID` map |
| `slime_volleyball` `human_ai`, `human_heuristic` | **ported**, over the `SlimeCourt` wrapper (finding 6). `slime_volleyball_game()` and `_OnePersonCourt` are gone |
| `mountain_car` (browser), `tandem`, `cogrid` browser + mesh, `slime_volleyball` mesh | not ported: each carries a Python bundle, which is finding 2 |

MountainCar in a browser is blocked on the bundle **writer alone** -- it derives
`requires=('gymnasium==1.3.0',)` and no blocks, so a generic single-agent bundle would
run it. Overcooked in a browser is blocked twice: its environment is built by a function
in the study's own repository, which is not an installed distribution, so the browser has
nothing to install. How much of a study's own code travels is the decision finding 2 is
waiting on.

`mountain_car`'s `mountain_car_spec()` stays as the `GameSpec` fixture 14 test files
use. Removing it belongs with the legacy removal the owner has deferred.

`tests/unit/test_examples_build.py` now plays each example **through the mount the
platform resolves for it**, so a study whose runtime resolved wrongly fails there rather
than in front of a participant.

### Still open

- **`runs=`** reads as "runs where", which is not quite English. `where=`, `steps=`, or
  `executes=` are the alternatives. Weakest word left in the surface.
- **`default_action=` required alongside `held_actions=`** is my call, not the owner's:
  it cannot be derived, and defaulting it to `0` makes a CoGrid chef walk north for a
  whole round.
- **The ninth surface op** (finding 1). Nothing else in the design is blocked on it, and
  everything shipped here works without it, but the "your trained environment needs no
  drawing code" story does not hold until it exists.


---

## Playing a whole study in a browser, 2026-07-30 (the owner: "nothing actually renders")

The owner watched the browser suite and doubted it was running anything. Measured: it
**is** rendering -- one shipped example painted 120,041 of 240,000 canvas pixels, 88
colours, 40 distinct pictures over 48 readings. The pixels were never the problem.

What was: **no browser test walked a whole study.** Every one played
`one_game_study` -- one page, one game shortened to 40 frames at 10 fps, one page -- or
a bespoke two-activity study written inline. A consent form, a survey, a debrief, and a
**round loop** had no browser coverage at all.

`tests/e2e_native/whole_study.py` walks a study the way a participant does: it answers
each screen by what it is (a form is filled and submitted, a page is read and continued
past, a rest between rounds is taken, a game is played with keys pressed while the
canvas is read) and reports what was met. `test_whole_study_browser.py` drives
`mountain_car_study()` and `overcooked_human_ai_study()` **as they ship** -- nothing
shortened, nothing mounted beside them -- plus a three-round study for the loop.

### The bug the first walk found, in both clients

**Every round after the first of a multi-round study was invisible and uncontrolled.**

`renderInterval` tears the game screen down between rounds (`stopGame()` nulls the
renderer and removes the keyboard listeners). The next round is the **same activity**,
so the server announces nothing more -- it steps and pushes `render` frames. The client
mounted a canvas only from a *delivery*, so:

- every frame of rounds 2..N hit `if (renderer) renderer.draw(...)` and was **dropped in
  silence**; the participant watched the previous rest screen for the whole round;
- the keyboard listeners were gone, so their keys were never read either. The recorded
  trajectory for those rounds is a participant doing nothing, at a blank screen.

That is a data-validity fault, not a display one, and it was shipped:
`overcooked_server_auth` writes `episodes=5` (four rounds affected) and both Slime
Volleyball studies write `episodes=2`.

Fixed in both clients: the game delivery is held (`playing`), the rest screen owns its
own element, and `startNextRound()` mounts the screen again when the participant asks
for the next round. A `render` frame that arrives with no canvas is now **reported**
rather than dropped -- the silence is what let this live.

STANDING RULE this adds: **a test that plays one round proves nothing about the second.**
