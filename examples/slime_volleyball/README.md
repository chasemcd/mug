# Slime Volleyball

Two slimes, one ball, one fence. It is fast and frame-sensitive, which makes it
the example worth reading for the peer-to-peer path: a rollback correction is
visible here in a way it is not in a turn-based game.

These documents use ASD-STE100 Simplified Technical English.

## Install the environment

```bash
uv pip install slimevb
```

The exported-network study also needs `onnxruntime`. The platform depends on
neither: an environment and its policies are the study's own choice.

## The three studies

| File | Who plays the other slime | Execution |
| --- | --- | --- |
| `human_heuristic.py` | A policy this example wrote | server |
| `human_ai.py` | A trained network, exported to ONNX | server |
| `human_human.py` | Another participant | browser peer-to-peer |

```bash
uv run uvicorn examples.slime_volleyball.human_heuristic:app
```

`human_human` gates entry on a launch ticket: the application prints one at
start, and the second participant needs a second ticket against the same store.

## The pieces

- `env.py` — the court a study hands over (`slime_court`), its scene, and its
  drawing on the platform's surface primitives. The peer-to-peer study still carries
  a Python bundle, because a browser run supplies the program it runs.
- `policies.py` — the ball-chasing heuristic and the exported-network partner.
  Both satisfy one seam, `decide(observation)`, which is all the platform knows
  about either of them.

## The court says what it is

`SlimeVolleyEnv` subclasses `gymnasium.Env`, which acts **one** agent, and then asks
for one action each for `agent_left` and `agent_right`. It is a multi-agent
environment wearing a single-agent base class, so read as it declares itself it
derives as one agent whose action is a whole dictionary — which no key can bind to.

The platform refuses that rather than deriving something wrong, and names what to
write. `SlimeCourt` is it: about twenty lines that declare the environment a
PettingZoo `ParallelEnv`, name its `possible_agents`, and unwrap the `{"obs": ...}`
each seat is handed so a seat sees the array its network was trained on.

## The drawing reads a scene, not the environment

`court_scene()` returns one frame of the court as plain numbers — the ball, where it
is going, the two slimes, the fence, the ground — and `render()` reads only that. The
study names it as the activity's `scene=`, and the platform calls it once a frame and
puts the answer in that frame's own metrics. A frame is **recorded**, so what the
drawing reads must be data a record can hold; that is also what lets a replay redraw
the court with no `slime_volleyball` installed.

The ball-chasing partner reads the same scene, through `sees`. A slime decides where
to stand from where the ball is **going**, and a velocity is not in an observation —
so the loop shows it the court it is stepping, rather than the study holding a court
of its own. One study object serves every participant, so a study that kept its court
would hand one participant's rally to another participant's partner.

The package keeps a second object for its own pixel renderer, and builds it only
when something asks it to draw. A study that read that object read `None` on every
frame and drew nothing at all.

The court is also wider than it is tall — the environment's own window is 1200 by
500 at one scale — so the two axes are scaled apart. A drawing that divided both by
the width put the whole game in the bottom quarter of the canvas.

## Chorded keys

This is the example that needed them. A jump is the up arrow and a direction is a
left or right arrow, and holding both means **jump that way** — which is its own
action and not either key alone:

```python
ACTION_BINDINGS = {
    "ArrowLeft": LEFT,
    "ArrowRight": RIGHT,
    "ArrowUp": UP,
    "ArrowUp+ArrowLeft": UPLEFT,
    "ArrowUp+ArrowRight": UPRIGHT,
}
```

A binding name that holds a `+` is a chord: every key in it must be held. A chord
beats a single key and a longer chord beats a shorter one, so the most specific
thing the participant is doing is what the seat does. The server and both shipped
clients resolve it the same way, which they have to: a browser run is verified by
re-executing it, so a client that read a different action would make an honest
participant's run unverifiable.
