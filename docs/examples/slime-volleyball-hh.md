# Slime Volleyball: Human-Human

<div align="center">
  <video src="../assets/images/slime_vb_hh_experiment.webm" autoplay loop muted playsinline width="600">
    Your browser does not support the video tag.
  </video>
</div>

Two human participants play Slime Volleyball against each other. Each browser runs its own copy of the environment via Pyodide; inputs are exchanged peer-to-peer and GGPO rollback keeps the two simulations in sync.

**Source:** [`examples/slime_volleyball/slimevb_human_human.py`](https://github.com/chasemcd/mug/blob/main/examples/slime_volleyball/slimevb_human_human.py)

This page only calls out the differences from the [Human-AI version](slime-volleyball-hai.md) — refer there for environment rendering, action mapping, and general structure.

## What's Different

### Policy mapping — both seats are human

To enable multi-human experiments, we simply set both agent IDs to `PolicyTypes.Human`:

```python
POLICY_MAPPING = {
    "agent_right": PolicyTypes.Human,
    "agent_left":  PolicyTypes.Human,
}
```

### `.multiplayer(input_delay=2)` — P2P with rollback

A cllient-side scene with multiple humans relies on our implementation of [GGPO rollback netcode](https://en.wikipedia.org/wiki/GGPO). A trick to get this to work well is to use input delay: when a user selects an action, it isn't executed immediately, but rather delayed by a few frames. This gives the other participant enough time to send their action, so that both participants execute the same actions at the same time. `input_delay=2` delays every input by 2 frames so the remote peer's input is more likely to arrive on time, cutting how often the engine has to roll back and client-side corrections are needed.

### Waitroom & Matchmaking

With two humans the scene needs a wait room. MUG opens one automatically whenever `POLICY_MAPPING` contains more than one human, then invokes a `Matchmaker` each time a participant arrives.

```python
.waitroom(
    timeout=120000,  # 2 minutes
    timeout_message=(
        "We couldn't find another participant for you to play with. "
        "Thanks for waiting — please close this tab."
    ),
)
.multiplayer(
    input_delay=2,
    matchmaker=FIFOMatchmaker(max_p2p_rtt_ms=100),
)
```

The defaults that stay untouched:

- **Group size: 2.** Inferred from the two `PolicyTypes.Human` entries in `POLICY_MAPPING`.
- **`timeout=120000`.** Milliseconds a participant will wait before the waitroom gives up.

**Handling unpaired participants.** `.waitroom()` offers three ways to resolve participants whose timer expires — pick whichever matches your recruitment flow. They are mutually usable in combination:

- **`timeout_message`** (used here). The participant stays on the waitroom page but sees the custom copy you provide instead of the generic fallback. Best when the participant doesn't need to go anywhere afterward.
- **`timeout_redirect_url`**. The browser redirects to the given URL when the timer fires. Use this for crowdsourcing platforms with a return URL for unfinished work — e.g. `.waitroom(timeout=120000, timeout_redirect_url="https://app.prolific.com/submissions/complete?cc=XXXXX")`.
- **`timeout_scene_id`**. Jumps the participant to another scene in the same stager. Use this if you have follow-up content for unpaired participants (a short solo task, a thank-you page, or a completion code scene). Example: `.waitroom(timeout=120000, timeout_scene_id="solo_fallback")` — `"solo_fallback"` must be the `scene_id` of another scene in the stager.

**Matchmaker: `FIFOMatchmaker(max_p2p_rtt_ms=100)`.**

Slime Volleyball is fast-paced and frame-sensitive, so we cap pairings by measured peer-to-peer latency. `FIFOMatchmaker` proposes a match in arrival order; `max_p2p_rtt_ms=100` then tells the game manager to probe the real P2P RTT between the two browsers over WebRTC and reject the pair if it exceeds 100 ms. When a pair is rejected, the candidates are returned to the queue for the next round of matchmaking.

### Rendering — carry HUD score across episodes, smooth rollbacks

```python
.rendering(
    fps=30,
    game_width=600,
    game_height=250,
    hud_score_carry_over=True,
    rollback_smoothing_duration=300,
)
```

- `hud_score_carry_over=True` — running score persists across the 10 episodes instead of resetting each one, so participants track a match total.
- `rollback_smoothing_duration=300` — when GGPO corrects a mis-prediction, interpolate visual positions over 300 ms instead of snapping. Keeps the slimes/ball from teleporting on the screen.

### Gameplay — use the previous action when an input is late

```python
.gameplay(
    ...
    num_episodes=3,
    action_population_method=ActionSettings.PreviousSubmittedAction,
)
```

- `action_population_method=PreviousSubmittedAction` — if an input hasn't arrived when the frame runs, reuse the participant's last submitted action instead of the default NOOP. For a held key this keeps the slime moving through brief network hiccups rather than freezing.

### Per-player in-game text — each participant sees their own slime color

`in_game_scene_body` renders the same HTML for every participant. With two humans that means both players would see the same "you control [red] vs [blue]" copy, leaving them to figure out which side is theirs by moving. To show each participant their specific slime color, pass `game_page_html_fn` — a callable `(game, subject_id) -> str` that is called after each participant is placed in a player slot. The returned HTML replaces `sceneBody` for that participant only.

```python
def slime_game_page_html_fn(game, subject_id) -> str:
    agent_id = None
    for aid, sid in game.human_players.items():
        if sid == subject_id:
            agent_id = aid
            break

    if agent_id == "agent_left":
        slime_img, side = RED_SLIME_IMG, "left"
    elif agent_id == "agent_right":
        slime_img, side = BLUE_SLIME_IMG, "right"
    else:
        return ""  # spectator / not yet placed — keep the fallback

    return f"""
    <p>You are <img src="{slime_img}" …> on the <b>{side}</b> — …</p>
    {CONTROLS_LEGEND_HTML}
    """

.content(
    ...,
    in_game_scene_body=<red vs blue fallback>,
    game_page_html_fn=slime_game_page_html_fn,
)
```

`game.human_players` is a dict keyed by agent ID with the subject ID of the human assigned to that slot. Reverse-looking up `subject_id` gives the agent ID this participant is playing, which you can map to any per-player content. `in_game_scene_body` is still needed as the fallback shown before slot assignment and to spectators (when the function returns `""`).
