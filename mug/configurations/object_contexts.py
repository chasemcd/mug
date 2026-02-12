from __future__ import annotations

import dataclasses
import typing


@dataclasses.dataclass
class Sprite:
    """
    Context for a sprite object to render it.

    This class represents a sprite object with various attributes that define its appearance and behavior in the rendered environment.

    :param uuid: Unique identifier for the sprite
    :type uuid: str
    :param x: X-coordinate of the sprite's position
    :type x: int
    :param y: Y-coordinate of the sprite's position
    :type y: int
    :param height: Height of the sprite
    :type height: int
    :param width: Width of the sprite
    :type width: int
    :param image_name: Name of the texture to be used for the sprite
    :type image_name: str or None
    :param frame: Current frame of the sprite animation
    :type frame: str or int or None
    :param object_size: Size of the object
    :type object_size: int or None
    :param angle: Rotation angle of the sprite in degrees
    :type angle: int or None
    :param depth: Rendering depth of the sprite. Higher values are rendered on top
    :type depth: int
    :param animation: Name of the animation to play
    :type animation: str or None
    :param object_type: Type of the object
    :type object_type: str
    :param tween: Whether to use tweening for smooth transitions
    :type tween: bool
    :param tween_duration: Duration of the tween animation in milliseconds
    :type tween_duration: int
    :param permanent: Whether the sprite should persist across steps.
    :type permanent: bool

    .. testcode::

        sprite = Sprite(
            uuid="player1",
            x=100,
            y=200,
            height=64,
            width=64,
            image_name="player_texture",
            frame=0,
            object_size=64,
            angle=45,
            depth=2,
            animation="walk",
            tween=True,
            tween_duration=100,
            permanent=True
        )

    """

    uuid: str
    x: int
    y: int
    height: int
    width: int
    image_name: str | None = None  # texture name
    frame: str | int | None = None
    object_size: int | None = None
    angle: int | None = None
    depth: int = 1
    animation: str | None = None
    object_type: str = "sprite"
    tween: bool = False
    tween_duration: int = 50
    permanent: bool = False

    def as_dict(self) -> dict[str, typing.Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Line:
    """
    Context for a line object to render it.

    :param uuid: Unique identifier for the line
    :type uuid: str
    :param color: Color of the line
    :type color: str
    :param width: Width of the line
    :type width: int
    :param points: List of points defining the line
    :type points: list[tuple[float, float]]

    .. testcode::

        line = Line(
            uuid="line1",
            color="#FF0000",
            width=2,
            points=[(0, 0), (100, 100), (200, 0)],
            fill_below=True,
            depth=1
        )

    """

    uuid: str
    color: str
    width: int
    points: list[tuple[float, float]]
    object_type: str = "line"
    fill_below: bool = False
    fill_above: bool = False
    depth: int = -1
    permanent: bool = False

    def as_dict(self) -> dict[str, typing.Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Circle:
    """
    Context for a circle object to render it.

    :param uuid: Unique identifier for the circle
    :type uuid: str
    :param color: Color of the circle
    :type color: str
    :param x: X-coordinate of the circle's center
    :type x: float
    :param y: Y-coordinate of the circle's center
    :type y: float
    :param radius: Radius of the circle
    :type radius: int
    :param alpha: Alpha value for the circle's transparency
    :type alpha: float
    :param object_type: Type of the object
    :type object_type: str
    :param depth: Rendering depth of the circle. Higher values are rendered on top
    :type depth: int
    :param permanent: Whether the circle should persist across steps.

    .. testcode::

        circle = Circle(
            uuid="circle1",
            color="#00FF00",
            x=150.0,
            y=150.0,
            radius=50,
            alpha=0.8,
            depth=2,
            permanent=True
        )
    """

    uuid: str
    color: str
    x: float
    y: float
    radius: int
    alpha: float = 1
    object_type: str = "circle"
    depth: int = -1
    permanent: bool = False

    def as_dict(self) -> dict[str, typing.Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Polygon:
    """
    Context for a polygon object to render it.

    :param uuid: Unique identifier for the polygon
    :type uuid: str
    :param color: Color of the polygon
    :type color: str
    :param points: List of points defining the polygon
    :type points: list[tuple[float, float]]
    :param alpha: Alpha value for the polygon's transparency
    :type alpha: float
    :param object_type: Type of the object
    :type object_type: str
    :param depth: Rendering depth of the polygon. Higher values are rendered on top
    :type depth: int
    :param permanent: Whether the polygon should persist across steps.
    :type permanent: bool

    .. testcode::

        polygon = Polygon(
            uuid="polygon1",
            color="#0000FF",
            points=[(0, 0), (100, 0), (100, 100), (0, 100)],
            alpha=0.5,
            depth=3,
            permanent=False
        )

    """

    uuid: str
    color: str
    points: list[tuple[float, float]]
    alpha: float = 1
    object_type: str = "polygon"
    depth: int = -1
    permanent: bool = False

    def as_dict(self) -> dict[str, typing.Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Text:
    """
    Context for a text object to render it.

    :param uuid: Unique identifier for the text
    :type uuid: str
    :param text: Text to display
    :type text: str

    .. testcode::

        text = Text(
            uuid="text1",
            text="Hello, World!",
            x=50,
            y=50,
            size=24,
            color="#000000",
            font="Arial",
            depth=4,
            permanent=True
        )

    """

    uuid: str
    text: str
    x: float | int
    y: float | int
    size: int = 16
    color: str = "#000000"
    font: str = "Arial"
    depth: int = -1
    object_type: str = "text"
    permanent: bool = False

    def as_dict(self) -> dict[str, typing.Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class AtlasSpec:
    """
    Context for an atlas spec object to render it.

    :param name: Name of the atlas
    :type name: str
    :param img_path: Path to the image file
    :type img_path: str
    :param atlas_path: Path to the atlas file
    :type atlas_path: str

    .. testcode::

        atlas_spec = AtlasSpec(
            name="player_atlas",
            img_path="assets/player_spritesheet.png",
            atlas_path="assets/player_atlas.json"
        )

    """

    name: str
    img_path: str
    atlas_path: str
    object_type: str = "atlas_spec"

    def as_dict(self) -> dict[str, typing.Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class MultiAtlasSpec:
    """
    Context for a multi atlas spec object to render it.

    :param name: Name of the atlas
    :type name: str
    :param img_path: Path to the image file
    :type img_path: str
    :param atlas_path: Path to the atlas file
    :type atlas_path: str

    .. testcode::

        multi_atlas_spec = MultiAtlasSpec(
            name="game_assets",
            img_path="assets/game_spritesheet.png",
            atlas_path="assets/game_multi_atlas.json"
        )

    """

    name: str
    img_path: str
    atlas_path: str
    object_type: str = "multi_atlas_spec"

    def as_dict(self) -> dict[str, typing.Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class ImgSpec:
    """
    Context for an img spec object to render it.

    :param name: Name of the image.
    :type name: str
    :param img_path: Path to the image file
    :type img_path: str

    .. testcode::

        img_spec = ImgSpec(
            name="background",
            img_path="assets/background.png"
        )

    """

    name: str
    img_path: str
    object_type: str = "img_spec"

    def as_dict(self) -> dict[str, typing.Any]:
        return dataclasses.asdict(self)
