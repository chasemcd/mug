Rendering System
================

MUG's rendering system converts environment state into visual elements displayed in the browser. This page explains how the rendering pipeline works, coordinate systems, and optimization strategies.

Overview
--------

**Traditional Rendering:**

.. code-block:: text

    Environment → RGB Array → Encode → Send → Display

**MUG:**

.. code-block:: text

    Environment → Object Contexts → JSON → Send → Render in Browser

This approach is:

- **More efficient**: Sending object descriptions vs full RGB arrays
- **More flexible**: Browser can render at any resolution
- **Pyodide-compatible**: No need for compiled rendering libraries

The Rendering Pipeline
-----------------------

Frame-by-Frame Process
^^^^^^^^^^^^^^^^^^^^^^

1. **Game loop ticks** (at specified FPS)
2. **Environment.render() called**
3. **Returns list of object dictionaries**
4. **Server sends objects to browser via SocketIO**
5. **Browser JavaScript receives objects**
6. **Phaser.js renders objects on canvas**
7. **Non-permanent objects cleared**
8. **Repeat for next frame**

.. code-block:: python

    # In your environment
    def render(self):
        assert self.render_mode == "interactive-gym"

        # Create visual objects
        player = Circle(uuid="player", x=self.x, y=self.y, radius=20, color="#FF0000")

        # Return as dictionaries
        return [player.as_dict()]

Server-Side Flow
^^^^^^^^^^^^^^^^

.. code-block:: python

    # mug/server/game_manager.py

    class GameManager:
        def game_loop(self):
            while self.running:
                # Step environment
                observations, rewards, dones, infos = self.env.step(actions)

                # Render
                visual_objects = self.env.render()

                # Send to all connected clients
                socketio.emit('render_state', {
                    'objects': visual_objects,
                    'frame': self.frame_count,
                })

                # Wait for next frame
                time.sleep(1.0 / self.fps)

Client-Side Flow
^^^^^^^^^^^^^^^^

.. code-block:: javascript

    // mug/server/static/js/game.js

    socket.on('render_state', (data) => {
        // Clear non-permanent objects
        clearTemporaryObjects();

        // Render each object
        data.objects.forEach(obj => {
            if (obj.object_type === 'circle') {
                renderCircle(obj);
            } else if (obj.object_type === 'line') {
                renderLine(obj);
            }
            // ... handle other types
        });
    });

Coordinate Systems
------------------

Relative Coordinates (Default)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Objects use normalized coordinates (0 to 1):

- ``x=0``: Left edge of canvas
- ``x=1``: Right edge of canvas
- ``y=0``: Top edge of canvas
- ``y=1``: Bottom edge of canvas

.. code-block:: python

    Circle(uuid="center", x=0.5, y=0.5, radius=20)  # Center
    Circle(uuid="top_left", x=0.0, y=0.0, radius=10)  # Top-left corner
    Circle(uuid="bottom_right", x=1.0, y=1.0, radius=10)  # Bottom-right corner

**Benefits:**

- Resolution-independent
- Scales to any canvas size
- Intuitive for layouts

**When to use:**

- Most environments
- When you want automatic scaling
- For relative positioning

Pixel Coordinates
^^^^^^^^^^^^^^^^^

Use absolute pixel coordinates:

.. code-block:: python

    # Enable pixel mode in scene config
    .rendering(location_representation="pixels")

Then all objects use pixel coordinates:

.. code-block:: python

    Circle(uuid="player", x=300, y=200, radius=20)  # 300px from left, 200px from top

**Benefits:**

- Precise positioning
- Familiar for game developers
- Direct control over sizes

**When to use:**

- Porting existing games
- When you need pixel-perfect layouts
- Working with fixed-size sprites

**Note:** Sprites always use pixel coordinates regardless of this setting.

Coordinate Conversion
^^^^^^^^^^^^^^^^^^^^^

Convert between relative and pixel coordinates:

.. code-block:: python

    class MyEnv(gym.Env):
        def __init__(self):
            self.game_width = 600
            self.game_height = 400

        def to_relative(self, pixel_x, pixel_y):
            """Convert pixels to relative coordinates"""
            rel_x = pixel_x / self.game_width
            rel_y = pixel_y / self.game_height
            return rel_x, rel_y

        def to_pixels(self, rel_x, rel_y):
            """Convert relative to pixel coordinates"""
            pixel_x = rel_x * self.game_width
            pixel_y = rel_y * self.game_height
            return pixel_x, pixel_y

        def render(self):
            # Environment uses pixel coordinates internally
            player_px, player_py = self.player_position

            # Convert to relative for rendering
            rel_x, rel_y = self.to_relative(player_px, player_py)

            player = Circle(uuid="player", x=rel_x, y=rel_y, radius=20, color="#FF0000")
            return [player.as_dict()]

Depth and Layering
------------------

Objects are rendered in depth order:

.. code-block:: python

    # Rendered in this order (back to front):
    background = Line(uuid="bg", depth=-1, ...)      # Drawn first (back)
    ground = Line(uuid="ground", depth=-1, ...)      # Same layer as bg
    player = Circle(uuid="player", depth=0, ...)     # Middle layer
    enemy = Circle(uuid="enemy", depth=0, ...)       # Same layer as player
    ui = Text(uuid="score", depth=1, ...)            # Front layer
    tooltip = Text(uuid="help", depth=2, ...)        # Drawn last (front)

**Default depths:**

- Background elements: ``depth=-1``
- Game objects: ``depth=0``
- UI/HUD: ``depth=1+``

**Within same depth:**

Objects at the same depth are rendered in the order they appear in the list:

.. code-block:: python

    return [
        circle1,  # Drawn first
        circle2,  # Drawn on top of circle1
        circle3,  # Drawn on top of circle2
    ]

Object Lifecycle
----------------

Temporary Objects (Default)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Most objects are cleared every frame:

.. code-block:: python

    def render(self):
        # This object is recreated every frame
        player = Circle(uuid="player", x=self.x, y=self.y, radius=20, color="#FF0000")
        return [player.as_dict()]

**Lifecycle:**

1. Created in ``render()``
2. Sent to browser
3. Rendered on canvas
4. Cleared before next frame
5. Repeat

Permanent Objects
^^^^^^^^^^^^^^^^^

Objects marked ``permanent=True`` persist:

.. code-block:: python

    def render(self):
        objects = []

        # Draw background once
        if not hasattr(self, '_bg_drawn'):
            background = Line(
                uuid="background",
                color="#87CEEB",
                points=[(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)],
                fill_below=True,
                permanent=True,
                depth=-2
            )
            objects.append(background.as_dict())
            self._bg_drawn = True

        # Player redrawn every frame
        player = Circle(uuid="player", x=self.x, y=self.y, radius=20, color="#FF0000")
        objects.append(player.as_dict())

        return objects

**Removing permanent objects:**

Stop including them in the return list or explicitly clear:

.. code-block:: python

    # Method 1: Don't return the object
    def render(self):
        # Background no longer returned, so it's removed
        return [player.as_dict()]

    # Method 2: Track and clear explicitly
    def render(self):
        if self.level_complete:
            self._bg_drawn = False  # Will be redrawn next time

Object Updates
^^^^^^^^^^^^^^

Objects with the same UUID are updated, not duplicated:

.. code-block:: python

    # Frame 1
    return [Circle(uuid="ball", x=0.3, y=0.5, radius=10, color="#FF0000")]

    # Frame 2 - position updated
    return [Circle(uuid="ball", x=0.4, y=0.5, radius=10, color="#FF0000")]

    # Frame 3 - position, size, and color updated
    return [Circle(uuid="ball", x=0.5, y=0.5, radius=15, color="#00FF00")]

Only one ball exists; it's updated each frame.

Performance Optimization
------------------------

Minimize Object Count
^^^^^^^^^^^^^^^^^^^^^

Fewer objects = faster rendering:

.. code-block:: python

    # BAD: Creating many small objects
    for x in range(100):
        for y in range(100):
            dot = Circle(uuid=f"dot_{x}_{y}", x=x/100, y=y/100, radius=1)
            objects.append(dot.as_dict())
    # 10,000 objects!

    # GOOD: Use fewer, larger objects
    # Draw a single filled polygon or use sprites

**Recommended limits:**

- < 100 objects: Excellent performance
- 100-500 objects: Good performance
- 500-1000 objects: Acceptable performance
- \> 1000 objects: May cause lag

Use Permanent Objects Wisely
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Static elements should be permanent:

.. code-block:: python

    # BAD: Redrawing static background every frame
    def render(self):
        background = Polygon(uuid="bg", points=[...], permanent=False)
        # Recreated 30 times per second!
        return [background.as_dict(), ...]

    # GOOD: Draw once, keep it
    def render(self):
        objects = []

        if not self._bg_drawn:
            background = Polygon(uuid="bg", points=[...], permanent=True)
            objects.append(background.as_dict())
            self._bg_drawn = True

        # Only dynamic objects here
        return objects

Batch Updates
^^^^^^^^^^^^^

Update related objects together:

.. code-block:: python

    # Create all objects in one pass
    def render(self):
        objects = []

        # Batch create enemies
        for i, enemy in enumerate(self.enemies):
            objects.append(Circle(
                uuid=f"enemy_{i}",
                x=enemy.x,
                y=enemy.y,
                radius=15,
                color="#FF0000"
            ).as_dict())

        # Batch create collectibles
        for i, coin in enumerate(self.coins):
            objects.append(Circle(
                uuid=f"coin_{i}",
                x=coin.x,
                y=coin.y,
                radius=8,
                color="#FFD700"
            ).as_dict())

        return objects

Simplify Geometry
^^^^^^^^^^^^^^^^^

Complex polygons are slower to render:

.. code-block:: python

    # BAD: Very detailed polygon
    points = [(i/1000, self.terrain_height(i/1000)) for i in range(1000)]
    terrain = Line(uuid="terrain", points=points, fill_below=True)
    # 1000 points!

    # GOOD: Simplified geometry
    points = [(i/50, self.terrain_height(i/50)) for i in range(50)]
    terrain = Line(uuid="terrain", points=points, fill_below=True)
    # 50 points, looks nearly identical

Custom Rendering Functions
---------------------------

Override Default Rendering
^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``env_to_state_fn`` for complete control:

.. code-block:: python

    def my_render_function(env):
        """Custom rendering function"""
        # Extract state
        player_pos = env.player_position
        enemies = env.enemies

        # Create objects
        objects = []

        player = Circle(uuid="player", x=player_pos[0], y=player_pos[1], radius=20, color="#00FF00")
        objects.append(player.as_dict())

        for i, enemy in enumerate(enemies):
            enemy_obj = Circle(uuid=f"enemy_{i}", x=enemy.x, y=enemy.y, radius=15, color="#FF0000")
            objects.append(enemy_obj.as_dict())

        return objects

    # Use in scene config
    .rendering(
        fps=30,
        env_to_state_fn=my_render_function,
    )

HUD and Overlay Text
^^^^^^^^^^^^^^^^^^^^

Use ``hud_text_fn`` for dynamic text:

.. code-block:: python

    def my_hud_function(env):
        """Generate HUD text based on environment state"""
        return f"Score: {env.score} | Lives: {env.lives} | Level: {env.level}"

    .rendering(
        fps=30,
        hud_text_fn=my_hud_function,
    )

The text appears as an overlay on the game canvas.

Preloading Assets (Sprites)
----------------------------

For sprite-based rendering, preload images:

.. code-block:: python

    from mug.configurations.object_contexts import ImgSpec

    .rendering(
        fps=30,
        preload_specs=[
            ImgSpec(name="player_texture", img_path="assets/player.png"),
            ImgSpec(name="enemy_texture", img_path="assets/enemy.png"),
            ImgSpec(name="background", img_path="assets/bg.png"),
        ],
    )

Then use in your environment:

.. code-block:: python

    def render(self):
        player = Sprite(
            uuid="player",
            x=self.player_x,
            y=self.player_y,
            width=64,
            height=64,
            image_name="player_texture",  # References preloaded image
        )
        return [player.as_dict()]

Debugging Rendering
-------------------

Check Object Output
^^^^^^^^^^^^^^^^^^^

Print what your render function returns:

.. code-block:: python

    def render(self):
        objects = [...]
        print(f"Rendering {len(objects)} objects")
        print(objects[0])  # Check first object structure
        return objects

Visualize Hitboxes
^^^^^^^^^^^^^^^^^^

Add debug visualization:

.. code-block:: python

    def render(self):
        objects = []

        # Normal rendering
        player = Circle(uuid="player", x=self.x, y=self.y, radius=20, color="#FF0000")
        objects.append(player.as_dict())

        # Debug: show hitbox
        if self.debug_mode:
            hitbox = Circle(
                uuid="player_hitbox",
                x=self.x,
                y=self.y,
                radius=self.hitbox_radius,
                color="#00FF00",
                alpha=0.3
            )
            objects.append(hitbox.as_dict())

        return objects

Browser Console
^^^^^^^^^^^^^^^

Check JavaScript console (F12) for errors:

- Missing object properties
- Invalid coordinates
- Rendering errors
- WebSocket connection issues

Common Issues
-------------

**Objects not appearing**

- Verify ``render_mode="interactive-gym"``
- Check coordinates are in valid range (0-1 for relative)
- Ensure ``.as_dict()`` is called
- Look for JavaScript errors in browser console

**Objects flickering**

- Don't recreate permanent objects every frame
- Keep UUID consistent across frames

**Performance lag**

- Reduce object count (< 500 recommended)
- Use permanent objects for static elements
- Simplify polygon geometry
- Check FPS setting (lower = less load)

**Objects rendering in wrong order**

- Set ``depth`` parameter appropriately
- Remember: higher depth = on top

**Coordinate issues**

- Check if using relative (0-1) vs pixels
- Verify ``location_representation`` setting
- Make sure environment dimensions match rendering config

Best Practices
--------------

1. **Use relative coordinates** unless you need pixel-perfect control
2. **Set appropriate depths** for layering (background: -1, objects: 0, UI: 1+)
3. **Mark static objects permanent** to avoid redrawing
4. **Keep object count low** (< 500 objects per frame)
5. **Use descriptive UUIDs** for debugging
6. **Test at different resolutions** to ensure scaling works
7. **Profile rendering** if experiencing lag

Rendering Comparison
--------------------

**Object-based (MUG):**

- ✅ Efficient (small data size)
- ✅ Resolution-independent
- ✅ Pyodide-compatible
- ✅ Easy to debug
- ❌ Limited to provided object types
- ❌ Not suitable for complex pixel art

**RGB-based (Traditional):**

- ✅ Can render anything
- ✅ Pixel-perfect control
- ✅ Works with existing rendering libraries
- ❌ Large data size
- ❌ Fixed resolution
- ❌ Requires compiled libraries (not Pyodide-compatible)

For most experiments, object-based rendering is sufficient and preferred.

Next Steps
----------

- **Learn object types**: :doc:`object_contexts` for all available objects
- **See examples**: :doc:`../quick_start` demonstrates rendering
- **Advanced techniques**: :doc:`../guides/rendering/custom_rendering`
