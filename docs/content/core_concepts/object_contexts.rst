Object Contexts
===============

Object contexts are lightweight dataclasses that define visual elements for rendering in MUG. Instead of sending RGB images, you describe **what** to render using objects like circles, lines, polygons, and sprites.

Why Object Contexts?
--------------------

**Efficiency**: Sending ``{uuid: "car", x: 0.5, y: 0.3, radius: 16}`` is much smaller than a 600x400 RGB array.

**Flexibility**: Browser can render at any resolution, objects scale smoothly.

**Simplicity**: No need for pygame, matplotlib, or other rendering libraries in your environment.

**Pyodide-compatible**: Works in the browser without compiled dependencies.

Available Object Types
----------------------

Circle
^^^^^^

Draw circular objects.

.. code-block:: python

    from mug.configurations.object_contexts import Circle

    ball = Circle(
        uuid="ball1",            # Unique identifier (required)
        color="#FF0000",         # Hex color code (required)
        x=0.5,                   # X position, 0-1 (required)
        y=0.5,                   # Y position, 0-1 (required)
        radius=20,               # Radius in pixels (required)
        alpha=1.0,               # Transparency, 0-1 (default: 1)
        depth=0,                 # Render order (default: -1)
        permanent=False,         # Persist across frames (default: False)
    )

    # Convert to dictionary for rendering
    ball.as_dict()

**Use for:** Players, balls, coins, targets, indicators

Line
^^^^

Draw lines, paths, or filled areas.

.. code-block:: python

    from mug.configurations.object_contexts import Line

    path = Line(
        uuid="path1",            # Unique identifier (required)
        color="#0000FF",         # Hex color code (required)
        points=[                 # List of (x, y) tuples (required)
            (0.1, 0.5),
            (0.5, 0.3),
            (0.9, 0.5)
        ],
        width=2,                 # Line thickness in pixels (required)
        fill_below=False,        # Fill area below line (default: False)
        fill_above=False,        # Fill area above line (default: False)
        depth=-1,                # Render order (default: -1)
        permanent=False,         # Persist across frames (default: False)
    )

**Use for:** Terrain, boundaries, trajectories, graphs, filled backgrounds

Polygon
^^^^^^^

Draw filled shapes with arbitrary vertices.

.. code-block:: python

    from mug.configurations.object_contexts import Polygon

    triangle = Polygon(
        uuid="tri1",             # Unique identifier (required)
        color="#00FF00",         # Hex color code (required)
        points=[                 # List of (x, y) tuples (required)
            (0.5, 0.2),
            (0.3, 0.6),
            (0.7, 0.6)
        ],
        alpha=0.8,               # Transparency, 0-1 (default: 1)
        depth=0,                 # Render order (default: -1)
        permanent=False,         # Persist across frames (default: False)
    )

**Use for:** Flags, arrows, platforms, obstacles, UI elements

Text
^^^^

Display text labels or HUD elements.

.. code-block:: python

    from mug.configurations.object_contexts import Text

    label = Text(
        uuid="score",            # Unique identifier (required)
        text="Score: 100",       # Text content (required)
        x=0.1,                   # X position, 0-1 (required)
        y=0.1,                   # Y position, 0-1 (required)
        size=24,                 # Font size in pixels (default: 16)
        color="#000000",         # Hex color code (default: "#000000")
        font="Arial",            # Font family (default: "Arial")
        depth=1,                 # Render order (default: -1)
        permanent=False,         # Persist across frames (default: False)
    )

**Use for:** Scores, timers, instructions, debug info, labels

Sprite
^^^^^^

Display images or animated sprites.

.. code-block:: python

    from mug.configurations.object_contexts import Sprite

    player = Sprite(
        uuid="player1",          # Unique identifier (required)
        x=100,                   # X position in pixels (required)
        y=200,                   # Y position in pixels (required)
        width=64,                # Width in pixels (required)
        height=64,               # Height in pixels (required)
        image_name="player_tex", # Texture name (must be preloaded)
        frame=0,                 # Animation frame (default: None)
        object_size=64,          # Sprite size (default: None)
        angle=45,                # Rotation in degrees (default: None)
        depth=1,                 # Render order (default: 1)
        animation="walk",        # Animation name (default: None)
        tween=True,              # Smooth interpolation (default: False)
        tween_duration=100,      # Tween time in ms (default: 50)
        permanent=False,         # Persist across frames (default: False)
    )

**Use for:** Characters, items, animated objects, textured elements

**Note:** Sprites require preloaded textures via ``preload_specs`` in ``.rendering()``.

Key Concepts
------------

UUID (Unique Identifier)
^^^^^^^^^^^^^^^^^^^^^^^^^

Each object needs a unique ``uuid``:

- Used to track objects across frames
- If an object with the same UUID exists, it's updated (not duplicated)
- Choose descriptive names: ``"player_car"`` not ``"obj1"``

.. code-block:: python

    # Good UUIDs
    Circle(uuid="player_avatar", ...)
    Line(uuid="ground_terrain", ...)
    Text(uuid="score_display", ...)

    # Bad UUIDs (ambiguous)
    Circle(uuid="circle1", ...)
    Line(uuid="line", ...)
    Text(uuid="text123", ...)

Coordinates
^^^^^^^^^^^

**Relative Coordinates (0-1):**

Most objects use relative positioning:

- ``x=0`` is left edge, ``x=1`` is right edge
- ``y=0`` is top, ``y=1`` is bottom
- Independent of canvas size

.. code-block:: python

    Circle(uuid="center", x=0.5, y=0.5, radius=20)  # Center of screen

**Pixel Coordinates:**

Sprites use absolute pixel coordinates:

.. code-block:: python

    Sprite(uuid="icon", x=50, y=50, width=32, height=32)

**Switching to pixel mode for all objects:**

.. code-block:: python

    .rendering(location_representation="pixels")

Then all objects use pixel coordinates.

Color
^^^^^

Colors are hex codes:

.. code-block:: python

    "#FF0000"  # Red
    "#00FF00"  # Green
    "#0000FF"  # Blue
    "#FFFFFF"  # White
    "#000000"  # Black
    "#FF8800"  # Orange
    "#808080"  # Gray

Alpha (Transparency)
^^^^^^^^^^^^^^^^^^^^

Control transparency with ``alpha`` (0 to 1):

.. code-block:: python

    Circle(uuid="ghost", color="#FF0000", alpha=0.5)  # Semi-transparent red
    Polygon(uuid="overlay", color="#000000", alpha=0.3)  # 30% opaque

Depth (Layering)
^^^^^^^^^^^^^^^^

Control render order with ``depth``:

- **Higher depth = rendered on top**
- Default: ``-1`` (background)
- Typical layering:

  - Background: ``depth=-1``
  - Game objects: ``depth=0``
  - Players: ``depth=1``
  - UI/HUD: ``depth=2``

.. code-block:: python

    Line(uuid="ground", depth=-1, ...)      # Drawn first (back)
    Circle(uuid="player", depth=1, ...)     # Drawn on top
    Text(uuid="score", depth=2, ...)        # Drawn last (front)

Permanent Objects
^^^^^^^^^^^^^^^^^

By default, objects are cleared every frame. Use ``permanent=True`` to persist:

.. code-block:: python

    # Redrawn every frame (default)
    Circle(uuid="ball", x=ball_x, y=ball_y, permanent=False)

    # Drawn once, stays until removed
    Line(uuid="static_boundary", points=[...], permanent=True)

**Use permanent for:**

- Static backgrounds
- Unchanging UI elements
- One-time overlays

**Remove permanent objects:**

Return an empty list or omit the object from ``render()``.

Using Object Contexts
---------------------

In Your Environment
^^^^^^^^^^^^^^^^^^^

Your environment's ``render()`` method returns a list of object dictionaries:

.. code-block:: python

    def render(self):
        assert self.render_mode == "interactive-gym"

        # Create objects
        player = Circle(uuid="player", x=self.player_x, y=self.player_y, radius=20, color="#FF0000")
        ground = Line(uuid="ground", points=self.get_ground_points(), color="#8B4513", width=2, fill_below=True)
        score = Text(uuid="score", text=f"Score: {self.score}", x=0.05, y=0.05, size=20)

        # Return as list of dictionaries
        return [
            player.as_dict(),
            ground.as_dict(),
            score.as_dict(),
        ]

The Frame Loop
^^^^^^^^^^^^^^

.. code-block:: text

    1. Environment.render() called
       ↓
    2. Returns list of object dicts
       ↓
    3. Sent to browser via SocketIO
       ↓
    4. JavaScript renders objects with Phaser.js
       ↓
    5. Non-permanent objects cleared
       ↓
    6. Repeat next frame

Object Updates
^^^^^^^^^^^^^^

Objects with the same UUID are updated, not duplicated:

.. code-block:: python

    # Frame 1
    return [Circle(uuid="ball", x=0.3, y=0.5, radius=10, color="#FF0000")]

    # Frame 2 - ball moves
    return [Circle(uuid="ball", x=0.4, y=0.5, radius=10, color="#FF0000")]

    # Frame 3 - ball changes color and size
    return [Circle(uuid="ball", x=0.5, y=0.5, radius=15, color="#00FF00")]

The ball is updated, not replicated.

Complete Examples
-----------------

Simple Platformer
^^^^^^^^^^^^^^^^^

.. code-block:: python

    def render(self):
        objects = []

        # Ground (permanent, drawn once)
        if not hasattr(self, "_ground_drawn"):
            ground = Line(
                uuid="ground",
                color="#8B4513",
                points=[(0, 0.8), (1, 0.8)],
                width=5,
                fill_below=True,
                permanent=True,
                depth=-1
            )
            objects.append(ground.as_dict())
            self._ground_drawn = True

        # Player (moves every frame)
        player = Circle(
            uuid="player",
            color="#FF0000",
            x=self.player_x,
            y=self.player_y,
            radius=20,
            depth=1
        )
        objects.append(player.as_dict())

        # Platforms
        for i, platform in enumerate(self.platforms):
            plat = Polygon(
                uuid=f"platform_{i}",
                color="#654321",
                points=platform.get_corners(),
                depth=0
            )
            objects.append(plat.as_dict())

        return objects

Multi-Agent Game
^^^^^^^^^^^^^^^^

.. code-block:: python

    def render(self):
        objects = []

        # Each agent as a different colored circle
        colors = ["#FF0000", "#0000FF", "#00FF00", "#FFFF00"]

        for agent_id, pos in self.agent_positions.items():
            agent = Circle(
                uuid=f"agent_{agent_id}",
                color=colors[agent_id],
                x=pos[0],
                y=pos[1],
                radius=15,
                depth=1
            )
            objects.append(agent.as_dict())

        # Shared goal
        goal = Polygon(
            uuid="goal",
            color="#FFD700",
            points=self.goal_polygon,
            alpha=0.7,
            depth=0
        )
        objects.append(goal.as_dict())

        return objects

Visualization with HUD
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    def render(self):
        objects = []

        # Game objects
        car = Circle(uuid="car", x=self.car_x, y=self.car_y, radius=16, color="#000000")
        objects.append(car.as_dict())

        # HUD text
        speed_text = Text(
            uuid="speed",
            text=f"Speed: {self.speed:.1f}",
            x=0.05,
            y=0.05,
            size=18,
            depth=2
        )
        objects.append(speed_text.as_dict())

        distance_text = Text(
            uuid="distance",
            text=f"Distance: {self.distance:.0f}m",
            x=0.05,
            y=0.10,
            size=18,
            depth=2
        )
        objects.append(distance_text.as_dict())

        # Progress bar (line with fill)
        progress = Line(
            uuid="progress_bar",
            color="#00FF00",
            points=[(0.1, 0.95), (0.1 + self.progress * 0.8, 0.95)],
            width=10,
            depth=2
        )
        objects.append(progress.as_dict())

        return objects

Best Practices
--------------

1. **Use descriptive UUIDs**: ``"player_health_bar"`` not ``"obj5"``
2. **Set appropriate depths**: Background (-1), objects (0), UI (1+)
3. **Use permanent wisely**: Only for truly static elements
4. **Normalize coordinates**: Keep positions in 0-1 range for consistency
5. **Limit object count**: Too many objects (>1000) can slow rendering
6. **Reuse UUIDs**: Same UUID = update, not duplicate
7. **Test different screen sizes**: Relative coordinates scale better

Common Patterns
---------------

Animated Objects
^^^^^^^^^^^^^^^^

.. code-block:: python

    # Change size based on state
    radius = 10 + int(self.energy * 5)
    player = Circle(uuid="player", x=self.x, y=self.y, radius=radius, color="#FF0000")

    # Change color based on condition
    color = "#00FF00" if self.health > 50 else "#FF0000"
    health_bar = Circle(uuid="health", x=0.1, y=0.1, radius=20, color=color)

Trails/Paths
^^^^^^^^^^^^

.. code-block:: python

    # Show trajectory
    trail = Line(
        uuid="trajectory",
        color="#FF0000",
        points=self.past_positions,  # List of recent positions
        width=2,
        alpha=0.5
    )

Bounding Boxes (Debug)
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    # Visualize hitboxes
    if self.debug_mode:
        for i, entity in enumerate(self.entities):
            bbox = Polygon(
                uuid=f"bbox_{i}",
                color="#FF0000",
                points=entity.get_corners(),
                alpha=0.3
            )
            objects.append(bbox.as_dict())

Dynamic Text
^^^^^^^^^^^^

.. code-block:: python

    # Countdown timer
    timer = Text(
        uuid="timer",
        text=f"Time: {int(self.remaining_time)}s",
        x=0.5,
        y=0.05,
        size=32,
        color="#FF0000" if self.remaining_time < 10 else "#000000"
    )

Troubleshooting
---------------

**Objects not appearing**

- Check ``render_mode="interactive-gym"`` is set
- Verify coordinates are in valid range (0-1 or valid pixels)
- Make sure ``.as_dict()`` is called
- Check browser console (F12) for errors

**Objects flickering**

- Don't recreate permanent objects every frame
- Ensure consistent UUID across frames

**Objects in wrong order**

- Set ``depth`` parameter appropriately
- Higher depth = rendered on top

**Performance issues**

- Reduce number of objects (<500 recommended)
- Use permanent objects for static elements
- Simplify polygons (fewer points)

**Objects too small/large**

- Check if using pixels vs relative coordinates
- Adjust radius/width values
- Verify ``location_representation`` setting

Next Steps
----------

- **Learn about rendering**: :doc:`rendering_system` for how it all works
- **See examples**: :doc:`../quick_start` uses object contexts
- **Advanced rendering**: :doc:`../guides/rendering/custom_rendering`
