# 09 — Rendering & what participants see

| Field | Value |
| --- | --- |
| User | Researcher (writes the visuals); participant (sees them) |
| Goal | Turn game state into what each participant sees — preserving today's full imperative, client-side-Pyodide rendering power, not a weaker declarative subset |
| Backing contract | [API-07](../../docs/architecture/phase-0/api-07/index.md) (render packets) · [API-09](../../docs/architecture/phase-0/api-09/index.md) (delivery/uploads) |
| Status | ✅ all 8 decisions approved (see [DECISIONS.md](DECISIONS.md)) |

## Grounding: what current MUG rendering actually does (must not lose)

Audited the existing repo (`mug/rendering/`, `phaser_gym_graphics.js`, examples). The
current system is **imperative per-frame Python** — an env draws a frame with a
`Surface` and returns delta-compressed draw commands; **Phaser (JS) does the canvas
drawing**; the same wire format flows through three transports. Capabilities to
preserve:

- **Arbitrary per-frame Python rendering** (numpy curves in mountain car, trig
  eye-tracking in slime) — *the* headline capability; a static declarative scene can't express it.
- **`Surface` primitives:** `rect, circle, ellipse, line, polygon, arc, text, image(sprite)`,
  each with `id, persistent, relative, depth, tween_duration` and open params (`alpha`, `fill_below/above`).
- **Delta compression** (persistent vs ephemeral objects; only changed objects hit the wire).
- **Cross-frame object identity + tweening**, reused for **rollback smoothing** after P2P corrections.
- **Client-side Pyodide execution** (env + renderer + ONNX/heuristic bots run in the browser; Worker ticks survive tab backgrounding), plus **server-authoritative** and **P2P/WebRTC** transports of the *same* draw format.
- **Per-player HTML overlays + DOM HUD** (`game_page_html_fn`, `hud_text_fn`) — the only per-seat view differentiation today — plus arbitrary scene HTML/CSS/JS and form auto-collection.
- **Assets:** image / atlas / spritesheet / multi-atlas preload; pixel-vs-relative coords; **resolution independence**; RGB-array & JPEG fallbacks.
- **Unity/WebGL** as a separate, non-Surface render path (footsies).

## The model: headless env → per-frame Python renderer → delta packet

```text
ENV (headless logic, D08-7)  ── state ──▶  RENDERER  (per-frame Python, imperative Surface)
                                              │  draw rect/circle/sprite/… with id+depth+tween
                                              ▼
                                   delta-compressed RenderPacket  ──(API-09)──▶  Phaser draws canvas
                                              +
                                   per-seat HTML overlay + DOM HUD (who am I / legend / score)
```

Same `Surface` draw format regardless of where the env runs (Pyodide-local /
server-authoritative / P2P). The renderer is **separated from env logic** so headless
agent/sim runs (D07-8) need no renderer — but it stays **per-frame imperative Python**,
so nothing about today's power is lost.

## What the user writes

### The imperative draw API (primary — this is today's `Surface`, preserved)

```python
def render(state, surface, seat=None):         # runs per seat, every frame, client-side in Pyodide
    # `seat` lets you draw a per-seat view (D09-4); omit/ignore it for shared-view games.
    surface.rect(id="bg", x=0, y=0, w=W, h=H, color="#111", persistent=True, depth=0)   # static → sent once
    for berry in state.berries:                # arbitrary Python per frame
        surface.circle(x=berry.x, y=berry.y, radius=6, color="crimson", depth=1)
    surface.image(id="p1", image_name="forager", x=state.p1.x, y=state.p1.y,
                  angle=state.p1.heading, depth=2, tween_duration=80)                    # smooth motion

Game(key="board", env=ForagingEnv(...), render=render, mode=ExecutionMode.SERVER)
```

`persistent=True` objects are delta-compressed (retransmitted only when they change);
matching `id` across frames + `tween_duration` gives smooth motion and rollback
smoothing; `depth` is z-order; coords are pixels by default or `relative=True` for 0–1.

### Per-seat differentiation (HTML overlay + HUD — preserved)

```python
Game(
    key="board", env=ForagingEnv(...), render=render,
    seat_view=lambda seat: f"<b>You are the {seat.color} forager.</b>",   # per-seat HTML (today's game_page_html_fn)
    hud=lambda state: f"Score: {state.score}   Time: {state.clock}",       # DOM HUD (today's hud_text_fn)
)
```

### Declarative `Scene` (optional sugar for simple grid/sprite games)

```python
render = Scene(grid_from=lambda s: s.board,
               sprites={"forager": Sprite("forager.png"), "berry": Sprite("berry.png")})
# lowers to the same draw commands; drop to the render() function whenever you outgrow it.
```

## What happens behind the scenes

| Author action | Contract behavior (API-07 / API-09) |
| --- | --- |
| `render(state, surface)` | Per-frame Python builds a `Surface`; `commit()` **delta-compresses** into a `RenderPacket` (`game_state_objects` + `removed`). Preserves today's model exactly. |
| `mode=…` | Pyodide-local (env+render+bots in browser), server-authoritative (thin client renders a streamed packet), or P2P — **all emit the same draw format** (D08-4). |
| `id` + `tween_duration` | Cross-frame object identity → smooth tweening and **rollback smoothing** after P2P input corrections. |
| `seat_view` / `hud` | Per-seat **HTML overlay** and **DOM HUD** (not canvas) — today's `game_page_html_fn`/`hud_text_fn`, the mechanism by which players see role-specific info. |
| a `Seat` (surface 07) | Explicitly **bound to an env agent id** at casting time — untangling today's seat=agent-id conflation while the env keeps using agent ids internally. |
| assets | Atlas / spritesheet / multi-atlas / image, **bundled and versioned with the study**, content-addressed; resolution-independent draw coords. |

## Decisions to review

Mark each `Status:` line.

### D09-1 — Rendering stays imperative per-frame Python (the current model), separated from a headless env
The primary API is a per-frame `render(state, surface)` function using an imperative
`Surface` — preserving arbitrary-Python-per-frame rendering — but it's separate from
env logic so headless agent/sim runs need no renderer.
- **Why it matters:** keeps MUG's most powerful and heavily-used capability intact (mountain car, slime, overcooked all rely on it), while decoupling enables the all-agent runs from D07-8. A declarative-only design would be a hard regression.
- **Renderer language:** Python-in-Pyodide is the default (`render(state, surface)`, one language end-to-end); an **optional JS/HTML custom renderer** is supported for authors who want web-native visuals (WebGL/DOM/D3). Two render paths, Python-first.
- **Status:** ✅ approved

### D09-2 — The `Surface` primitive set and its semantics are preserved
`rect/circle/ellipse/line/polygon/arc/text/image` with `id, persistent, relative,
depth, tween_duration`, delta compression, object identity/tweening, alpha, area
fills, sprite frame/rotation, pixel-vs-relative coords, resolution independence.
- **Why it matters:** this is the concrete capability surface authors already use; dropping any of it breaks existing studies. Declarative `Scene` is optional sugar on top, not a replacement.
- **F-3 reconciliation (settled):** every *known* draw param is typed/constant; a single explicit `extras={...}` dict carries renderer-specific/forward-compat keys — no silent `**kwargs`. Promotes a key to a typed param once it's stable.
- **Status:** ✅ approved

### D09-3 — Client-side Pyodide execution is first-class; three transports, one draw format
Env + renderer + bots running in the browser (Pyodide) is a primary mode, not a
fallback; server-authoritative and P2P are alternate transports of the identical draw
format. Worker-timed ticks keep the loop alive when the tab is backgrounded.
- **Why it matters:** browser-side Python is central to current MUG (offline capable, zero-latency loop, cheap hosting). A server-only rendering design would drop it.
- **Status:** ✅ approved

### D09-4 — Per-seat rendering is a v0 goal: platform-enforced per-seat canvas + preserved HTML overlay/HUD
The renderer receives the seat (`render(state, surface, seat)`) and MUG builds **one
`RenderPacket` per seat** derived only from that seat's view — so a hidden-info
game's private state never reaches the other client. Today's per-seat **HTML overlay**
and **DOM HUD** are preserved alongside.
- **Why it matters:** platform-enforced partial observability makes hidden-information designs safe by construction (the other player's secrets aren't merely hidden client-side — they're never sent), while keeping the familiar HTML/HUD "you are the red slime / your score" mechanism. New machinery: per-seat packet derivation + delivery.
- **Status:** ✅ approved

### D09-5 — Assets are declared, bundled, and versioned with the study, content-addressed
Image/atlas/spritesheet/multi-atlas assets ship with the study version (client
manifest), content-addressed — preserving today's preload types; no arbitrary runtime URLs.
- **Why it matters:** the exact pixels a participant saw are reproducible, and existing atlas/spritesheet workflows (overcooked chefs, etc.) keep working.
- **Status:** ✅ approved

### D09-6 — Integrity is mode-specific, stated honestly (not "client is never trusted")
In **server-authoritative** mode the client is thin and cannot fabricate canonical
state. In **Pyodide/P2P** modes the client runs the env by design; correctness comes
from determinism + reconciliation (canonical vs. experienced streams), not from
distrusting the client.
- **Why it matters:** the earlier draft's blanket "client never computes authoritative state" was false for the browser-side modes that MUG depends on — the honest contract is per-mode.
- **Status:** ✅ approved

### D09-7 — Seat ↔ env agent-id binding is explicit (untangles today's conflation)
A `Seat` (authored role, surface 07) is explicitly bound to an environment **agent
id** at casting time. The env still uses agent ids internally; the platform no longer
conflates "role," "who fills it," and "which env slot."
- **Why it matters:** directly fixes the seat=agent-id tangle the user flagged — human/bot/LLM casting (surface 07) and env slots stay cleanly separable, which is what makes human↔AI swapping and per-seat routing robust.
- **Status:** ✅ approved

### D09-8 — Non-Surface render paths (e.g. Unity/WebGL) remain a supported alternate mode
The Unity/WebGL embed path (footsies) is preserved as a distinct render mode with its
own HUD/score/episode model, not forced through the Surface pipeline.
- **Why it matters:** a real existing capability that a Surface-only design would erase; some studies need a full game engine.
- **Status:** ✅ approved

## Settled (your calls)

- **`Surface` params vs F-3 → typed params + explicit `extras=` escape** (D09-2); no silent `**kwargs`.
- **Custom renderer language → Python-in-Pyodide default + optional JS/HTML renderer** (D09-1).
- **Per-seat canvas → a v0 goal** (D09-4): platform-enforced per-seat packets (partial observability), HTML/HUD preserved alongside.
- **Audio → explicitly out of scope for v0** (matches today; HTML/JS scene-body workaround remains). Revisit in a later version.
- **Input handling** (`InputModes`, composite keys, `frame_skip`, `input_delay`) → covered in **surface 10** (participant playing), where the step-loop coupling lives.
