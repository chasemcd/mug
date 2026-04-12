# Rendering System

You need to render your Gymnasium environment in the browser so that human participants can see and interact with it. MUG solves this with a Surface-based rendering pipeline that sends structured draw commands instead of raw pixels.

If you have used Gymnasium before, you are familiar with `render_mode`. When `render_mode="rgb_array"`, calling `render()` returns a NumPy array of pixel data -- fine for local visualization, but expensive to transmit over a network and incompatible with Pyodide (which cannot use compiled rendering libraries like PyOpenGL). MUG introduces `render_mode="mug"`, where `render()` returns a lightweight dictionary of draw commands that the browser's Phaser.js engine renders natively on a canvas element.

This approach has three advantages over pixel-based rendering:

- **Efficient.** A handful of JSON draw commands is orders of magnitude smaller than a full RGB frame buffer. Bandwidth stays low even at high frame rates.
- **Resolution-independent.** Draw commands describe shapes and positions, not pixels. The browser renders them at whatever resolution the client window provides.
- **Pyodide-compatible.** No compiled C extensions are needed. The entire rendering path is pure Python on the environment side and JavaScript on the display side.

The Surface class is the single entry point for all rendering. It follows a PyGame-inspired imperative pattern: you call draw methods to describe what should appear on screen, then call `commit()` to produce a delta-compressed packet ready for transmission.


## Pipeline Overview

The rendering pipeline has four stages, from your Python code to the browser canvas:

```text
Stage 1                Stage 2                Stage 3               Stage 4
Python Draw Calls      RenderPacket Delta     Wire Transmission     Phaser JS Rendering
--------------------   --------------------   -------------------   --------------------
surface.rect()         surface.commit()       SocketIO / Pyodide    Browser canvas
surface.circle()       Compares against       JSON serialization    Phaser game objects
surface.polygon()       last committed state  Sends only changes    Tweened animations
surface.text()         Produces RenderPacket
...
```

**Stage 1 -- Python Draw Calls.** Your environment's `render()` method calls draw methods on a `Surface` instance. Each call records a draw command in an internal buffer.

**Stage 2 -- RenderPacket Delta.** Calling `surface.commit()` compares persistent objects against their last committed state. Only new or changed objects are included in the output `RenderPacket`. Ephemeral (temporary) objects are always included.

**Stage 3 -- Wire Transmission.** The `RenderPacket` is serialized to JSON and sent to the browser. In server mode, this happens over SocketIO. In browser-side mode, it passes directly within the browser runtime.

**Stage 4 -- Phaser JS Rendering.** The browser-side JavaScript receives the packet, creates or updates Phaser game objects on the canvas, and applies tweened animations for objects whose positions changed.


## The Surface Workflow

Here is the core pattern. Every MUG environment that renders follows these steps: create a Surface, call draw methods, commit, and return the resulting packet as a dictionary.

```python
from mug.rendering import Surface

def render_frame():
    surface = Surface(width=600, height=400)

    # Draw a blue circle in the center
    surface.circle(x=300, y=200, radius=50, color="blue")

    # Draw a green rectangle in the top-left
    surface.rect(x=10, y=10, w=100, h=60, color=(0, 128, 0))

    # Finalize the frame
    packet = surface.commit()
    return packet.to_dict()
```

Breaking this down:

1. `Surface(width=600, height=400)` creates a rendering surface with a logical size of 600 by 400 pixels. All draw calls use this coordinate space.
2. `surface.circle(...)` and `surface.rect(...)` record draw commands into the surface's internal buffer. Nothing is sent yet.
3. `surface.commit()` finalizes the frame, performs delta compression against the previous commit, and returns a `RenderPacket`.
4. `packet.to_dict()` serializes the packet into the dictionary format expected by the wire layer and the Phaser JS renderer.

In practice, you create the Surface once in `__init__` and reuse it across frames. The example above creates a fresh Surface each call for clarity; the "Putting It Together" section below shows the realistic pattern.


## Key Concepts

### Persistent vs Temporary Objects

Every draw command is either persistent or temporary. The distinction controls how the object behaves across frames and how delta compression treats it.

| Property | Temporary (default) | Persistent |
|----------|-------------------|------------|
| How to create | Omit `persistent` or set `persistent=False` | Set `persistent=True` and provide `id="..."` |
| Lifespan | Cleared after each `commit()` | Survives across commits until explicitly removed |
| Delta behavior | Always included in every packet | Only included when new or changed |
| Typical use | Dynamic elements that change every frame (player position, score text) | Static elements drawn once (background, walls, field lines) |
| `id` required? | No (auto-generated if omitted) | Yes (raises `ValueError` without one) |

```python
# Persistent background -- drawn once, sent only on first commit
surface.rect(
    id="background",
    x=0, y=0, w=600, h=400,
    color="skyblue",
    persistent=True,
)

# Temporary player -- redrawn and sent every frame
surface.circle(x=player_x, y=player_y, radius=20, color="red")
```


### The id Parameter and Tweened Movement

The `id` parameter identifies an object across frames. When the Phaser JS renderer receives an update for an object with the same `id` but a different position, it can smoothly animate (tween) the movement rather than snapping to the new location.

The `tween_duration` parameter controls how long the animation takes, in milliseconds. A value of 100 means the object takes 100ms to glide from its old position to its new one. This produces fluid motion even when the environment runs at a modest frame rate.

```python
# Frame N: player is at x=100
surface.circle(
    id="player",
    x=100, y=200,
    radius=20,
    color="red",
    persistent=True,
    tween_duration=100,
)

# Frame N+1: player moved to x=150
# The browser animates from (100, 200) to (150, 200) over 100ms
surface.circle(
    id="player",
    x=150, y=200,
    radius=20,
    color="red",
    persistent=True,
    tween_duration=100,
)
```

If `tween_duration` is omitted or `None`, the object snaps to its new position instantly.


### Pixel vs Relative Coordinates

By default, the Surface works in pixel coordinates: you specify positions using the logical width and height you set in the constructor. When `commit()` serializes the frame, it automatically normalizes pixel coordinates to the 0-1 range for the wire format. The browser then maps these relative values to whatever canvas size is available.

If you prefer to work directly in the 0-1 relative space, pass `relative=True` to any draw call. In that case, no conversion is performed -- your coordinates pass through as-is.

| Property | Pixel coordinates (default) | Relative coordinates |
|----------|---------------------------|---------------------|
| How to use | Pass coordinates in the Surface's pixel space | Pass `relative=True` to the draw call |
| Coordinate range | `0` to `width` / `0` to `height` | `0.0` to `1.0` on both axes |
| Normalization | Surface divides by width/height before sending | No conversion -- values sent as-is |
| When to choose | Most environments (think in pixels, let Surface handle the math) | When your data is already normalized or you want direct 0-1 control |

```python
# Pixel coordinates (default) -- circle at pixel position (300, 200)
surface = Surface(width=600, height=400)
surface.circle(x=300, y=200, radius=50, color="red")

# Relative coordinates -- circle at the center (0.5, 0.5)
surface.circle(x=0.5, y=0.5, radius=0.08, color="red", relative=True)
```

Both draw calls place a circle at the center of the canvas. In pixel mode, `x=300` on a 600-wide surface becomes `0.5` on the wire. In relative mode, `x=0.5` is already in wire format.


### Delta Compression

Each time you call `commit()`, the Surface compares the current persistent objects against their state at the last commit. Only objects that are new or whose parameters have changed are included in the output `RenderPacket`. Temporary objects, by contrast, are always included because they do not persist between commits.

This delta compression minimizes the data sent over the wire. In a typical environment where the background and walls are persistent, only the few dynamic objects (player position, score, ball) generate network traffic each frame.

Two methods help manage persistent object state:

- `surface.remove(id="wall_3")` marks a persistent object for removal. On the next `commit()`, the client is told to destroy that object.
- `surface.reset()` clears all internal state -- both the persistent object cache and the ephemeral buffer. This is useful at episode boundaries so that all objects are retransmitted fresh in the next commit.


## Available Draw Methods

The Surface provides eight draw methods covering common shapes, text, and images. Each method accepts keyword-only arguments.

| Method | Description | Key parameters |
|--------|-------------|----------------|
| `rect` | Draw a rectangle | `x`, `y`, `w`, `h`, `color`, `border_radius`, `stroke_color`, `stroke_width` |
| `circle` | Draw a circle (center-origin) | `x`, `y`, `radius`, `color`, `stroke_color`, `stroke_width` |
| `line` | Draw a multi-segment line | `points` (list of (x, y) tuples), `color`, `width` |
| `polygon` | Draw a filled polygon | `points` (list of (x, y) tuples), `color`, `stroke_color`, `stroke_width` |
| `text` | Draw a text label | `text`, `x`, `y`, `size`, `color`, `font` |
| `image` | Draw a sprite image (top-left origin) | `image_name`, `x`, `y`, `w`, `h`, `frame`, `angle` |
| `arc` | Draw an arc | `x`, `y`, `radius`, `start_angle`, `end_angle`, `color` |
| `ellipse` | Draw an ellipse | `x`, `y`, `rx`, `ry`, `color` |

For full parameter details, types, and default values, see the [Surface API](surface-api.md) page.


## Common Parameters

All draw methods accept these shared parameters in addition to their shape-specific ones:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `id` | Auto-generated | String identifier for this object. Required when `persistent=True`. Used by the JS renderer to track objects across frames. |
| `persistent` | `False` | When `True`, the object survives across commits and is only retransmitted when changed. Requires `id`. |
| `relative` | `False` | When `True`, coordinates are in the 0-1 range and no pixel-to-relative conversion is performed. |
| `depth` | `0` | Integer controlling render order. Higher values are drawn on top of lower values. |
| `tween_duration` | `None` | Duration in milliseconds for smooth position animation. When set, the JS renderer tweens from the old position to the new one. |

The `depth` parameter determines layering. A typical pattern is to use negative depths for backgrounds (`depth=-1`), zero for game objects, and positive depths for UI overlays (`depth=1` or higher).


## Color Inputs

Surface draw methods accept colors in three formats. All are normalized internally to lowercase `#rrggbb` hex strings before being sent over the wire.

- **RGB tuples:** `(255, 0, 0)` -- integer values from 0 to 255 for red, green, and blue.
- **Hex strings:** `"#FF0000"` or the shorthand `"#F00"` -- standard CSS hex color notation.
- **Named CSS colors:** `"red"`, `"skyblue"`, `"teal"` -- a subset of common CSS color names.

```python
# These three calls produce identical output on the wire
surface.circle(x=100, y=100, radius=30, color=(255, 0, 0))
surface.circle(x=100, y=100, radius=30, color="#FF0000")
surface.circle(x=100, y=100, radius=30, color="red")
```


## Putting It Together

Here is a more realistic example showing how an environment integrates the Surface into its `render()` and `reset()` methods. The Surface is created once in `__init__`, cleared on `reset()`, and used to draw each frame.

```python
import gymnasium as gym
from mug.rendering import Surface

class SimpleChaseEnv(gym.Env):
    metadata = {"render_modes": ["mug"]}

    def __init__(self, render_mode="mug"):
        super().__init__()
        self.render_mode = render_mode
        self.surface = Surface(width=600, height=400)

        self.player_x = 300
        self.player_y = 200
        self.target_x = 500
        self.target_y = 100
        self.score = 0
        # ... observation_space, action_space, etc.

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.player_x = 300
        self.player_y = 200
        self.score = 0
        self.surface.reset()  # Clear all persistent state for the new episode
        # ... return observation, info

    def step(self, action):
        # ... update player_x, player_y, score based on action
        pass

    def render(self):
        # Persistent background -- only sent on first frame (or after reset)
        self.surface.rect(
            id="bg",
            x=0, y=0, w=600, h=400,
            color="white",
            persistent=True,
            depth=-1,
        )

        # Dynamic player -- redrawn every frame with tween for smooth motion
        self.surface.circle(
            id="player",
            x=self.player_x, y=self.player_y,
            radius=20,
            color="blue",
            persistent=True,
            tween_duration=100,
        )

        # Target -- persistent, changes position occasionally
        self.surface.circle(
            id="target",
            x=self.target_x, y=self.target_y,
            radius=15,
            color="green",
            persistent=True,
        )

        # Score text -- temporary, redrawn every frame
        self.surface.text(
            text=f"Score: {self.score}",
            x=10, y=10,
            size=20,
            color="black",
            depth=1,
        )

        packet = self.surface.commit()
        return packet.to_dict()
```

Key points in this example:

- The Surface is created once in `__init__` and reused for the lifetime of the environment.
- `self.surface.reset()` is called in the environment's `reset()` method to clear the persistent state cache. This ensures all objects are retransmitted fresh at the start of each episode.
- The background is persistent and only sent on the first commit after a reset.
- The player uses `persistent=True` with `tween_duration=100` so the browser smoothly animates position changes.
- The score text is temporary (the default) because its content changes every frame. It is always included in the packet.
- `commit()` produces the delta, and `to_dict()` serializes it for the wire.


## Next Steps

- [Surface API](surface-api.md) -- Full parameter details for every Surface draw method
- [Quick Start](../getting-started/quick-start.md) -- Quick Start tutorial demonstrating a complete environment with rendering
- [Server Mode](server-mode.md) -- Server Mode: how the server-authoritative pipeline transmits render packets to thin clients
- [Browser-Side Execution](pyodide-mode.md) -- Browser-Side Execution: how rendering works when the environment runs client-side in the browser
