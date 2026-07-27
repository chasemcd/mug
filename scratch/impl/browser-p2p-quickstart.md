# Run a multiplayer study in the participants' browsers

*For study authors. You write the study -- your consent, your instructions, your
surveys, your debrief -- and one of its activities is a game two participants play
together, each browser stepping its own copy and agreeing with the other over a
direct connection. No game server sits in the middle.*

> Status: **built and proven end to end.** Two real Chromium browsers walk the
> study below -- consent, instructions, pre-survey, the game, post-survey, debrief
> -- boot Pyodide, open real WebRTC data channels, play, and the server records it
> (`tests/e2e_native/test_browser_mesh_browser.py`). The deterministic suite beside
> it drives the same vertical with simulated channels, so latency, packet loss, and
> a hidden tab are stated rather than hoped for
> (`tests/e2e_native/test_browser_mesh_e2e.py`).

---

## The study

A study is the ordered activities a participant meets. You write them; the game is
one of them. This is `examples/tandem/study.py`, complete:

```python
from mug.app import build_app_from_env
from mug.content import Choice, Form, Game, Likert, Page, Study, Text
from mug.participant_p2p_types import BrowserP2PConfig

from examples.tandem.browser_mesh_env import tandem_mesh_spec


def tandem_study() -> Study:
    return Study(
        Form(
            "consent",
            Choice("agree", "I have read the information sheet and agree to take"
                            " part.", ["yes", "no"]),
            Choice("data-sharing", "I agree that my anonymised data may be shared"
                                   " with other researchers.", ["yes", "no"]),
        ),
        Page("instructions", INSTRUCTIONS),          # your markdown
        Form(
            "pre-survey",
            Likert("games-experience", "How often do you play video games?", scale=5),
            Likert("cooperation-comfort",
                   "How comfortable are you working with someone you cannot talk"
                   " to?", scale=7),
        ),
        Game("play"),                                 # <- the multiplayer game
        Form(
            "post-survey",
            Likert("teamwork", "How well do you feel you and your partner worked"
                               " together?", scale=7),
            Likert("partner-strategy", "How predictable did your partner's moves"
                                       " feel?", scale=7),
            Text("strategy", "What were you trying to do? (optional)"),
        ),
        Page("debrief", DEBRIEF),
    )


app = build_app_from_env(
    study=tandem_study(),
    browser_p2p=BrowserP2PConfig(
        channel_key="tandem", size=2, game=tandem_mesh_spec(), seed=7
    ),
    require_launch=True,        # peer-to-peer needs a durable enrollment
)
```

Run it with `uvicorn examples.tandem.study:app`.

There is no client code. The bundled browser client renders each activity from its
specification: a `Choice` becomes radio buttons, a `Likert` becomes a numbered
scale, a `Page` becomes rendered markdown, and the game mounts a canvas.

**The order is yours.** Put the game first if the study needs no preamble, put
three surveys after it, put a page between them. `Study` refuses what it cannot
run honestly -- an empty study, two activities with the same key, and a form that
asks nothing.

**Play more than once if the study needs it.** A practice round before the real one
is two game activities, and each is recorded as its own episode:

```python
    Page("instructions", INSTRUCTIONS),
    Game("practice", replace(tandem_mesh_spec(), max_steps=30)),
    Form("check", Choice("ready", "Ready for the real round?", ["yes", "no"])),
    Game("play"),
```

Each round forms its own room and records its own run. A round that names no
settings of its own runs whatever the application mounted, so a study that plays
the same game twice writes `Game("practice")` and `Game("play")` and configures it
once. Naming settings per round is read by the single-participant modes today; a
peer-to-peer round runs the mounted game whatever it names.

`build_app_from_env` reads the store and the return-link key from the environment,
so the same file runs on the in-memory store for a local try and on Postgres for a
real deployment. To inject those yourself, call `build_study_app` instead --
`build_app_from_env` is a thin wrapper over it. `build_demo_app` runs a built-in
demo study; use it for a five-minute look, not for a study.

---

## The game

The game activity runs a `BrowserMeshSpec`: the Python every browser runs and the
keys that drive it.

| You write | Default | What it does |
| --- | --- | --- |
| `source_bundle=` | — | the Python every browser runs |
| `action_bindings=` | — | which key means which action |
| `requires=` | none | pinned packages the browser installs once |
| `default_action=` | `0` | the action for a frame with no key held |
| `fps=` | `30` | frames a second |
| `max_steps=` | `200` | the step cap |
| `input_delay=` | `2` | frames of delay before an input applies |
| `snapshot_interval=` | `5` | how often the replica is snapshotted |
| `redundancy=` | `10` | how many past inputs each packet repeats |

The bundle is plain Python. It defines `make_replica`, and optionally `draw`:

```python
class Tandem:
    def __init__(self, peer_actor_ids, seed):
        self.peers = tuple(sorted(peer_actor_ids))
        ...

    def step(self, actions):
        """Take one action per player. Return five values."""
        return (observation, rewards, terminated, truncated, info)

    def snapshot(self):
        """Return everything a replay must restore -- including any generator."""
        ...

    def restore(self, snapshot):
        ...


def make_replica(peer_actor_ids, seed):
    return Tandem(peer_actor_ids, seed)


def draw(replica):
    """Return the surface commands for the replica's current state."""
    ...
```

`examples/tandem/browser_mesh_env.py` is the worked example, with no package to
install.

**The one rule that matters: `snapshot` must cover everything the environment
reads.** Each browser predicts what the other player did and re-runs the frames
when it turns out to be wrong. A replay restores your snapshot and steps forward
again, so anything the snapshot misses -- a random-number generator especially --
makes the two browsers disagree. They will not paper over it: the frames report a
disagreement and the run is refused rather than half-recorded.

---

## What the platform does

- **Ships its own runtime.** The browser does not carry a second copy of the
  rollback logic. It runs the platform's own `mug.game.mesh`, `mug.game.wire`, and
  `mug.game.browser_mesh_driver` verbatim in Pyodide. So a browser peer and a
  server peer are the same code and cannot drift apart.
- **Boots during your forms.** The runtime downloads while the participant reads
  the consent page, so nobody waits at a blank canvas -- and nobody holds up their
  partner.
- **Matches, signals, and starts together.** Participants who reach the game
  activity join a waiting room; the server relays the connection setup and releases
  every browser at one barrier.
- **Checks what comes back.** The browsers each report the run they played, and
  the server re-derives its identity from the frames themselves. Two browsers that
  disagree abort the room rather than have a winner picked for them.
- **Records it.** The agreed trajectory becomes one peer-authority episode beside
  the form answers of the same visit, so the whole study exports together.

---

## Deploying it

Two browsers on one machine reach each other directly, which is why the tests need
no extra infrastructure. Participants on different networks usually do not:

- **STUN** lets each browser learn its public address. Set `ice=IceServerConfig(
  stun_urls=("stun:stun.example.org:3478",))`.
- **TURN** relays when a direct path is impossible (roughly one connection in
  ten). It needs a server and a secret: `turn_urls=(...)`, `turn_secret=...`.
  MUG derives a short-lived credential per participant and never sends the secret
  to a browser.

Without either, a study works on a local network and fails elsewhere. That is a
deployment decision, not a code change.

---

## What is not built yet

- **Branching.** The activities run in order; there is no "skip the game if they
  declined consent" yet. A study that must branch checks the answer itself.
- **One episode per room.** A room plays one episode and finishes. A second round
  is a second room, which re-matches the participants: a study cannot yet hold one
  pair together across two rounds.
- **A peer round is not named on the visit's flow.** The episode is recorded, and
  it exports; the flow does not list its stream the way a server round's is listed.
- **Bots beside browsers in a mesh.** The bot-authority runtime exists
  (`mug/game/bot_authority.py`) but the browser executor does not seat one yet. A
  study that wants a bot beside a human today uses the server-authoritative mode.
- **Rejoining a room after a disconnect.** A browser that drops out ends the room
  for everyone in it, and the others are returned to the waiting room.
