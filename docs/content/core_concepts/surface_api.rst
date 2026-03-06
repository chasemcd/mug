Surface API Reference
=====================

This page documents every method on the ``Surface`` class with full parameter signatures, types, default values, and usage examples. For conceptual background on how the rendering pipeline works, see :doc:`rendering_system`.


Quick Reference
---------------

.. list-table::
   :header-rows: 1
   :widths: 22 38 40

   * - Method
     - Description
     - Key Parameters
   * - ``Surface(width, height)``
     - Create a rendering surface
     - ``width``, ``height``
   * - ``commit()``
     - Finalize frame, return delta-compressed packet
     - --
   * - ``reset()``
     - Clear all internal state
     - --
   * - ``remove(id)``
     - Mark persistent object for removal
     - ``id``
   * - ``rect()``
     - Draw a rectangle
     - ``x``, ``y``, ``w``, ``h``, ``color``, ``border_radius``
   * - ``circle()``
     - Draw a circle (center-origin)
     - ``x``, ``y``, ``radius``, ``color``
   * - ``ellipse()``
     - Draw an ellipse
     - ``x``, ``y``, ``rx``, ``ry``, ``color``
   * - ``line()``
     - Draw a multi-segment line
     - ``points``, ``color``, ``width``
   * - ``polygon()``
     - Draw a filled polygon (auto-closes)
     - ``points``, ``color``, ``stroke_color``
   * - ``arc()``
     - Draw an arc
     - ``x``, ``y``, ``radius``, ``start_angle``, ``end_angle``
   * - ``text()``
     - Draw a text label
     - ``text``, ``x``, ``y``, ``size``, ``font``
   * - ``image()``
     - Draw a sprite image (top-left origin)
     - ``image_name``, ``x``, ``y``, ``w``, ``h``, ``frame``
   * - ``register_atlas()``
     - Register a sprite atlas for preloading
     - ``name``, ``img_path``, ``json_path``
   * - ``register_image()``
     - Register a standalone image for preloading
     - ``name``, ``path``
   * - ``get_asset_specs()``
     - Return registered asset specs
     - --


Common Parameters
-----------------

All draw methods accept the following keyword arguments in addition to their shape-specific parameters. These are passed through as ``**common`` in each method signature.

.. list-table::
   :header-rows: 1
   :widths: 18 22 12 48

   * - Parameter
     - Type
     - Default
     - Description
   * - ``id``
     - ``str | None``
     - ``None``
     - Identifier for tracking this object across frames. Auto-generated if omitted. Required when ``persistent=True``; raises ``ValueError`` without one.
   * - ``persistent``
     - ``bool``
     - ``False``
     - When ``True``, the object survives across commits and is only retransmitted when its parameters change. Requires ``id``.
   * - ``relative``
     - ``bool``
     - ``False``
     - When ``True``, coordinates are in the 0--1 range and no pixel-to-relative conversion is performed by ``commit()``.
   * - ``depth``
     - ``int``
     - ``0``
     - Render order. Higher values are drawn on top of lower values. Use negative values for backgrounds and positive values for UI overlays.
   * - ``tween_duration``
     - ``int | float | None``
     - ``None``
     - Duration in milliseconds for smooth position animation. When set, the JS renderer tweens from the old position to the new one. When ``None``, the object snaps to its new position instantly.

**Color inputs.** Every draw method that accepts a ``color``, ``stroke_color``, or similar parameter accepts colors in three formats. All are normalized internally to lowercase ``#rrggbb`` hex strings by ``normalize_color()`` before transmission.

- **RGB tuples:** ``(255, 0, 0)`` -- integer values from 0 to 255 for red, green, and blue.
- **Hex strings:** ``"#FF0000"`` or the shorthand ``"#F00"`` -- standard CSS hex color notation.
- **Named CSS colors:** ``"red"``, ``"skyblue"``, ``"teal"`` -- a subset of ~20 common CSS color names.


Surface Lifecycle
-----------------

.. py:class:: Surface(width, height)

   Create a rendering surface with a logical pixel space of *width* by *height*.

   All draw calls use this coordinate space. When ``commit()`` serializes the frame, pixel coordinates are automatically normalized to the 0--1 range for the wire format.

   .. list-table::
      :header-rows: 1
      :widths: 15 15 70

      * - Parameter
        - Type
        - Description
      * - ``width``
        - ``int``
        - Logical width of the rendering area in pixels.
      * - ``height``
        - ``int``
        - Logical height of the rendering area in pixels.

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)


.. py:method:: Surface.commit()

   Finalize the current frame and return a delta-compressed render packet.

   Ephemeral objects are always included in the output. Persistent objects are only included when new or changed since the last commit. After the call, the ephemeral buffer is cleared; persistent objects remain until explicitly removed.

   :returns: A ``RenderPacket`` with ``objects`` (list of wire-format dicts) and ``removed`` (list of IDs to destroy on the client). Call ``packet.to_dict()`` to serialize into the ``{"game_state_objects": [...], "removed": [...]}`` format expected by the JS renderer.
   :rtype: RenderPacket

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)
      surface.rect(x=0, y=0, w=600, h=400, color="white")
      packet = surface.commit()
      wire_dict = packet.to_dict()


.. py:method:: Surface.reset()

   Clear all internal state -- the ephemeral buffer, the persistent object store, and the committed-state cache.

   After a reset, persistent objects will be retransmitted in the next ``commit()`` because the committed-state cache is empty. Call this at episode boundaries so that all objects are retransmitted fresh.

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)
      surface.reset()  # clear everything for a new episode


.. py:method:: Surface.remove(id)

   Mark a persistent object for removal in the next ``commit()``.

   The client is told to destroy the object with this identifier. The object is also removed from the internal persistent store.

   .. list-table::
      :header-rows: 1
      :widths: 15 15 70

      * - Parameter
        - Type
        - Description
      * - ``id``
        - ``str``
        - The identifier of the persistent object to remove.

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)
      surface.remove("old_wall")


Draw Methods -- Basic Shapes
-----------------------------

.. py:method:: Surface.rect(*, x, y, w, h, color="white", border_radius=None, stroke_color=None, stroke_width=None, **common)

   Draw a rectangle.

   .. list-table::
      :header-rows: 1
      :widths: 18 28 14 40

      * - Parameter
        - Type
        - Default
        - Description
      * - ``x``
        - ``float | int``
        - --
        - X position of the top-left corner.
      * - ``y``
        - ``float | int``
        - --
        - Y position of the top-left corner.
      * - ``w``
        - ``float | int``
        - --
        - Width.
      * - ``h``
        - ``float | int``
        - --
        - Height.
      * - ``color``
        - ``tuple[int, int, int] | str``
        - ``"white"``
        - Fill color.
      * - ``border_radius``
        - ``float | int | None``
        - ``None``
        - Corner rounding radius. ``None`` means sharp corners.
      * - ``stroke_color``
        - ``tuple[int, int, int] | str | None``
        - ``None``
        - Border color. ``None`` means no border.
      * - ``stroke_width``
        - ``float | int | None``
        - ``None``
        - Border width. ``None`` means no border.
      * - ``id``
        - ``str | None``
        - ``None``
        - Object identifier. Required when ``persistent=True``.
      * - ``persistent``
        - ``bool``
        - ``False``
        - Survive across commits when ``True``.
      * - ``relative``
        - ``bool``
        - ``False``
        - Use 0--1 coordinates when ``True``.
      * - ``depth``
        - ``int``
        - ``0``
        - Render order (higher on top).
      * - ``tween_duration``
        - ``int | float | None``
        - ``None``
        - Smooth animation duration in ms.

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)
      surface.rect(x=50, y=50, w=200, h=100, color="blue", border_radius=8)


.. py:method:: Surface.circle(*, x, y, radius, color="white", stroke_color=None, stroke_width=None, **common)

   Draw a circle. The ``x`` and ``y`` coordinates specify the center.

   .. list-table::
      :header-rows: 1
      :widths: 18 28 14 40

      * - Parameter
        - Type
        - Default
        - Description
      * - ``x``
        - ``float | int``
        - --
        - X position of the center.
      * - ``y``
        - ``float | int``
        - --
        - Y position of the center.
      * - ``radius``
        - ``float | int``
        - --
        - Circle radius.
      * - ``color``
        - ``tuple[int, int, int] | str``
        - ``"white"``
        - Fill color.
      * - ``stroke_color``
        - ``tuple[int, int, int] | str | None``
        - ``None``
        - Border color. ``None`` means no border.
      * - ``stroke_width``
        - ``float | int | None``
        - ``None``
        - Border width. ``None`` means no border.
      * - ``id``
        - ``str | None``
        - ``None``
        - Object identifier. Required when ``persistent=True``.
      * - ``persistent``
        - ``bool``
        - ``False``
        - Survive across commits when ``True``.
      * - ``relative``
        - ``bool``
        - ``False``
        - Use 0--1 coordinates when ``True``.
      * - ``depth``
        - ``int``
        - ``0``
        - Render order (higher on top).
      * - ``tween_duration``
        - ``int | float | None``
        - ``None``
        - Smooth animation duration in ms.

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)
      surface.circle(x=300, y=200, radius=50, color="red")


.. py:method:: Surface.ellipse(*, x, y, rx, ry, color="white", **common)

   Draw an ellipse. The ``x`` and ``y`` coordinates specify the center. ``rx`` and ``ry`` are the horizontal and vertical radii.

   .. list-table::
      :header-rows: 1
      :widths: 18 28 14 40

      * - Parameter
        - Type
        - Default
        - Description
      * - ``x``
        - ``float | int``
        - --
        - X position of the center.
      * - ``y``
        - ``float | int``
        - --
        - Y position of the center.
      * - ``rx``
        - ``float | int``
        - --
        - Horizontal radius.
      * - ``ry``
        - ``float | int``
        - --
        - Vertical radius.
      * - ``color``
        - ``tuple[int, int, int] | str``
        - ``"white"``
        - Fill color.
      * - ``id``
        - ``str | None``
        - ``None``
        - Object identifier. Required when ``persistent=True``.
      * - ``persistent``
        - ``bool``
        - ``False``
        - Survive across commits when ``True``.
      * - ``relative``
        - ``bool``
        - ``False``
        - Use 0--1 coordinates when ``True``.
      * - ``depth``
        - ``int``
        - ``0``
        - Render order (higher on top).
      * - ``tween_duration``
        - ``int | float | None``
        - ``None``
        - Smooth animation duration in ms.

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)
      surface.ellipse(x=300, y=200, rx=80, ry=40, color="purple")


Draw Methods -- Lines and Paths
--------------------------------

.. py:method:: Surface.line(*, points, color="white", width=1, **common)

   Draw a multi-segment line connecting a sequence of points.

   .. list-table::
      :header-rows: 1
      :widths: 18 28 14 40

      * - Parameter
        - Type
        - Default
        - Description
      * - ``points``
        - ``list[tuple[float | int, float | int]]``
        - --
        - Sequence of ``(x, y)`` vertices defining the line path.
      * - ``color``
        - ``tuple[int, int, int] | str``
        - ``"white"``
        - Line color.
      * - ``width``
        - ``int``
        - ``1``
        - Line thickness in pixels.
      * - ``id``
        - ``str | None``
        - ``None``
        - Object identifier. Required when ``persistent=True``.
      * - ``persistent``
        - ``bool``
        - ``False``
        - Survive across commits when ``True``.
      * - ``relative``
        - ``bool``
        - ``False``
        - Use 0--1 coordinates when ``True``.
      * - ``depth``
        - ``int``
        - ``0``
        - Render order (higher on top).
      * - ``tween_duration``
        - ``int | float | None``
        - ``None``
        - Smooth animation duration in ms.

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)
      surface.line(points=[(10, 350), (300, 50), (590, 350)], color="green", width=3)


.. py:method:: Surface.polygon(*, points, color="white", stroke_color=None, stroke_width=None, **common)

   Draw a filled polygon. The shape is automatically closed -- the last point connects back to the first.

   .. list-table::
      :header-rows: 1
      :widths: 18 28 14 40

      * - Parameter
        - Type
        - Default
        - Description
      * - ``points``
        - ``list[tuple[float | int, float | int]]``
        - --
        - Sequence of ``(x, y)`` vertices defining the polygon boundary.
      * - ``color``
        - ``tuple[int, int, int] | str``
        - ``"white"``
        - Fill color.
      * - ``stroke_color``
        - ``tuple[int, int, int] | str | None``
        - ``None``
        - Border color. ``None`` means no border.
      * - ``stroke_width``
        - ``float | int | None``
        - ``None``
        - Border width. ``None`` means no border.
      * - ``id``
        - ``str | None``
        - ``None``
        - Object identifier. Required when ``persistent=True``.
      * - ``persistent``
        - ``bool``
        - ``False``
        - Survive across commits when ``True``.
      * - ``relative``
        - ``bool``
        - ``False``
        - Use 0--1 coordinates when ``True``.
      * - ``depth``
        - ``int``
        - ``0``
        - Render order (higher on top).
      * - ``tween_duration``
        - ``int | float | None``
        - ``None``
        - Smooth animation duration in ms.

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)
      # Triangle
      surface.polygon(
          points=[(300, 50), (100, 350), (500, 350)],
          color="orange",
          stroke_color="black",
          stroke_width=2,
      )

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)
      # Diamond shape
      surface.polygon(
          points=[(300, 50), (500, 200), (300, 350), (100, 200)],
          color=(0, 128, 255),
      )


.. py:method:: Surface.arc(*, x, y, radius, start_angle, end_angle, color="white", **common)

   Draw an arc. Angles are specified in radians. The arc is drawn counterclockwise from ``start_angle`` to ``end_angle``.

   .. list-table::
      :header-rows: 1
      :widths: 18 28 14 40

      * - Parameter
        - Type
        - Default
        - Description
      * - ``x``
        - ``float | int``
        - --
        - X position of the arc center.
      * - ``y``
        - ``float | int``
        - --
        - Y position of the arc center.
      * - ``radius``
        - ``float | int``
        - --
        - Arc radius.
      * - ``start_angle``
        - ``float``
        - --
        - Starting angle in radians.
      * - ``end_angle``
        - ``float``
        - --
        - Ending angle in radians.
      * - ``color``
        - ``tuple[int, int, int] | str``
        - ``"white"``
        - Arc color.
      * - ``id``
        - ``str | None``
        - ``None``
        - Object identifier. Required when ``persistent=True``.
      * - ``persistent``
        - ``bool``
        - ``False``
        - Survive across commits when ``True``.
      * - ``relative``
        - ``bool``
        - ``False``
        - Use 0--1 coordinates when ``True``.
      * - ``depth``
        - ``int``
        - ``0``
        - Render order (higher on top).
      * - ``tween_duration``
        - ``int | float | None``
        - ``None``
        - Smooth animation duration in ms.

   .. code-block:: python

      from mug.rendering import Surface
      import math

      surface = Surface(width=600, height=400)
      surface.arc(x=300, y=200, radius=80, start_angle=0, end_angle=math.pi, color="teal")


Draw Methods -- Content
------------------------

.. py:method:: Surface.text(*, text, x, y, size=16, color="black", font="Arial", **common)

   Draw a text label. The ``x`` and ``y`` coordinates specify the text origin. The text is rendered using the browser's font engine, so exact baseline behavior depends on the Phaser JS renderer.

   .. list-table::
      :header-rows: 1
      :widths: 18 28 14 40

      * - Parameter
        - Type
        - Default
        - Description
      * - ``text``
        - ``str``
        - --
        - The text string to display.
      * - ``x``
        - ``float | int``
        - --
        - X position of the text origin.
      * - ``y``
        - ``float | int``
        - --
        - Y position of the text origin.
      * - ``size``
        - ``int``
        - ``16``
        - Font size in pixels.
      * - ``color``
        - ``tuple[int, int, int] | str``
        - ``"black"``
        - Text color.
      * - ``font``
        - ``str``
        - ``"Arial"``
        - Font family name.
      * - ``id``
        - ``str | None``
        - ``None``
        - Object identifier. Required when ``persistent=True``.
      * - ``persistent``
        - ``bool``
        - ``False``
        - Survive across commits when ``True``.
      * - ``relative``
        - ``bool``
        - ``False``
        - Use 0--1 coordinates when ``True``.
      * - ``depth``
        - ``int``
        - ``0``
        - Render order (higher on top).
      * - ``tween_duration``
        - ``int | float | None``
        - ``None``
        - Smooth animation duration in ms.

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)
      surface.text(text="Score: 42", x=10, y=20, size=24, color="black")

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)
      surface.text(
          text="Game Over",
          x=300, y=200,
          size=48,
          color="red",
          font="Courier New",
          depth=10,
      )


.. py:method:: Surface.image(*, image_name, x, y, w, h, frame=None, angle=None, **common)

   Draw a sprite image. The ``x`` and ``y`` coordinates specify the top-left corner. The wire format uses ``object_type`` ``"sprite"`` for backward compatibility with the Phaser JS renderer. Images must be preloaded via ``register_atlas()`` or ``register_image()`` before use.

   .. list-table::
      :header-rows: 1
      :widths: 18 28 14 40

      * - Parameter
        - Type
        - Default
        - Description
      * - ``image_name``
        - ``str``
        - --
        - Logical name of the preloaded texture (must match a registered asset name).
      * - ``x``
        - ``float | int``
        - --
        - X position of the top-left corner.
      * - ``y``
        - ``float | int``
        - --
        - Y position of the top-left corner.
      * - ``w``
        - ``float | int``
        - --
        - Display width.
      * - ``h``
        - ``float | int``
        - --
        - Display height.
      * - ``frame``
        - ``str | int | None``
        - ``None``
        - Animation frame identifier or index within a sprite atlas. ``None`` uses the default frame.
      * - ``angle``
        - ``float | int | None``
        - ``None``
        - Rotation angle in degrees. ``None`` means no rotation.
      * - ``id``
        - ``str | None``
        - ``None``
        - Object identifier. Required when ``persistent=True``.
      * - ``persistent``
        - ``bool``
        - ``False``
        - Survive across commits when ``True``.
      * - ``relative``
        - ``bool``
        - ``False``
        - Use 0--1 coordinates when ``True``.
      * - ``depth``
        - ``int``
        - ``0``
        - Render order (higher on top).
      * - ``tween_duration``
        - ``int | float | None``
        - ``None``
        - Smooth animation duration in ms.

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)
      surface.register_image("player_tex", path="assets/player.png")
      surface.image(image_name="player_tex", x=100, y=150, w=64, h=64)

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)
      surface.register_atlas("sprites", img_path="assets/sheet.png", json_path="assets/sheet.json")
      surface.image(
          image_name="sprites",
          x=200, y=100, w=48, h=48,
          frame="walk_01",
          angle=45,
          persistent=True,
          id="hero",
      )


Asset Registration
------------------

.. py:method:: Surface.register_atlas(name, *, img_path, json_path)

   Register a sprite atlas for preloading. An atlas combines multiple sprite frames into a single image with a JSON descriptor that maps frame names to regions.

   .. list-table::
      :header-rows: 1
      :widths: 15 15 70

      * - Parameter
        - Type
        - Description
      * - ``name``
        - ``str``
        - Logical name used to reference this atlas in ``image()`` calls.
      * - ``img_path``
        - ``str``
        - Path to the atlas image file.
      * - ``json_path``
        - ``str``
        - Path to the atlas JSON descriptor.

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)
      surface.register_atlas("sprites", img_path="assets/sheet.png", json_path="assets/sheet.json")


.. py:method:: Surface.register_image(name, *, path)

   Register a standalone image for preloading.

   .. list-table::
      :header-rows: 1
      :widths: 15 15 70

      * - Parameter
        - Type
        - Description
      * - ``name``
        - ``str``
        - Logical name used to reference this image in ``image()`` calls.
      * - ``path``
        - ``str``
        - Path to the image file.

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)
      surface.register_image("background", path="assets/bg.png")


.. py:method:: Surface.get_asset_specs()

   Return the list of registered asset specs for use in the ``assets_to_preload`` configuration. Each entry is a dict with at minimum ``name`` and ``img_path`` keys. Atlas entries also include an ``atlas_path`` key.

   :returns: A shallow copy of the internal asset spec list.
   :rtype: list[dict]

   .. code-block:: python

      from mug.rendering import Surface

      surface = Surface(width=600, height=400)
      surface.register_image("bg", path="assets/bg.png")
      specs = surface.get_asset_specs()
