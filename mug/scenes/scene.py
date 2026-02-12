from __future__ import annotations
import os
import copy
import json
import random
from datetime import datetime
from mug.utils.sentinels import NotProvided

import flask_socketio


class SceneStatus:
    Inactive = 0
    Active = 1
    Done = 2


class Scene:
    """
    A Scene defines an stage of interaction that a participant will have with the application.
    """

    def __init__(self, **kwargs):
        self.scene_id = None
        self.experiment_config: dict = {}
        self.experiment_id: str | None = None
        self.socketio: flask_socketio.SocketIO | None = None
        self.room: str | int | None = None
        self.status = SceneStatus.Inactive

        # These are the elements IDs that we'll log the values of at the end of every scene
        self.element_ids = []
        self.should_export_metadata: bool = False

    def scene(
        self,
        scene_id: str = NotProvided,
        experiment_config: dict = NotProvided,
        should_export_metadata: bool = NotProvided,
        **kwargs,
    ):
        if scene_id is not NotProvided:
            self.scene_id = scene_id
        if experiment_config is not NotProvided:
            self.experiment_config = experiment_config
        if should_export_metadata is not NotProvided:
            self.should_export_metadata = should_export_metadata

        return self

    def build(self) -> list[Scene]:
        """
        Build the Scene.
        """
        return [self.copy()]

    def copy(self) -> Scene:
        """
        Copy the scene.
        """
        return copy.deepcopy(self)

    def unpack(self) -> list[Scene]:
        """
        Unpack a scene, in the base class this just returns the scene in a list.
        """
        return [self]

    def activate(self, socketio: flask_socketio.SocketIO, room: str | int):
        """
        Activate the current scene.
        """
        self.status = SceneStatus.Active
        self.socketio = socketio
        self.room = room
        self.socketio.emit("activate_scene", {**self.scene_metadata}, room=room)

    def deactivate(self):
        """
        Deactivate the current scene.
        """
        self.status = SceneStatus.Done
        self.socketio.emit(
            "terminate_scene", {**self.scene_metadata}, room=self.room
        )

    def on_connect(self, socketio: flask_socketio.SocketIO, room: str | int):
        """
        A hook that is called when the client connects to the server.
        """
        pass

    @property
    def scene_metadata(self) -> dict:
        """
        Return the metadata for the current scene that will be passed through the Flask app.
        """
        serialized_vars = serialize_dict(vars(self))
        metadata = copy.deepcopy(serialized_vars)
        return {
            "scene_id": self.scene_id,
            "scene_type": self.__class__.__name__,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            **metadata,
        }

    def export_metadata(self, subject_id: str):
        """Save the metadata for the current scene."""
        if self.experiment_id:
            base_dir = f"data/{self.experiment_id}/{self.scene_id}"
        else:
            base_dir = f"data/{self.scene_id}"
        os.makedirs(base_dir, exist_ok=True)
        with open(f"{base_dir}/{subject_id}_metadata.json", "w") as f:
            json.dump(self.scene_metadata, f)

    def on_client_callback(
        self, data, socketio: flask_socketio.SocketIO, room: str | int
    ):
        """
        A hook that is called when the client sends a callback to the server.
        """
        pass


def serialize_dict(data):
    """
    Serialize a dictionary to JSON, removing unserializable keys recursively.

    :param data: Dictionary to serialize.
    :return: Serialized object with unserializable elements removed.
    """
    if isinstance(data, dict):
        # Use dictionary comprehension to process each key-value pair
        return {
            key: serialize_dict(value)
            for key, value in data.items()
            if is_json_serializable(value)
        }
    elif isinstance(data, list):
        # Use list comprehension to process each item
        return [
            serialize_dict(item) for item in data if is_json_serializable(item)
        ]
    elif is_json_serializable(data):
        return data
    else:
        return None  # or some other default value


def is_json_serializable(value):
    """
    Check if a value is JSON serializable.

    :param value: The value to check.
    :return: True if the value is JSON serializable, False otherwise.
    """
    try:
        json.dumps(value)
        return True
    except (TypeError, OverflowError):
        return False


class SceneWrapper:
    """
    The SceneWrapper class is used to wrap a Scene(s) with additional functionality.
    """

    def __init__(self, scenes: Scene | SceneWrapper | list[Scene], **kwargs):

        if isinstance(scenes, Scene):
            scenes = [scenes]

        self.scenes: Scene | SceneWrapper = scenes

    def build(self) -> SceneWrapper:
        """
        Build the SceneWrapper for a participant.
        """

        scenes = []
        for scene in self.unpack():
            scenes.extend(scene.build())

        return scenes

    def unpack(self) -> list[Scene]:
        """
        Recursively unpack all scenes from this wrapper.
        """
        unpacked_scenes = []
        for scene in self.scenes:
            unpacked_scene = scene.unpack()
            unpacked_scenes.extend(unpacked_scene)
        return unpacked_scenes


class RandomizeOrder(SceneWrapper):
    """Randomize the order of the Scenes in the sequence."""

    def __init__(
        self,
        scenes: Scene | SceneWrapper | list[Scene],
        keep_n: int | None = None,
        seed: int | None = None,
        **kwargs,
    ):
        super().__init__(scenes, **kwargs)
        self.keep_n = keep_n

    def build(self) -> RandomizeOrder:
        """
        Randomize the order before building the SceneWrapper.
        """
        random.shuffle(self.scenes)

        if self.keep_n is not None:
            self.scenes = self.scenes[: self.keep_n]

        return super().build()

    def unpack(self) -> list[Scene]:
        """
        Recursively unpack all scenes from this wrapper.
        """
        random.shuffle(self.scenes)

        return super().unpack()


class RepeatScene(SceneWrapper):
    def __init__(
        self,
        scenes: Scene | SceneWrapper | list[Scene],
        n: int | None = None,
        **kwargs,
    ):
        super().__init__(scenes, **kwargs)
        self.n = n

    def build(self) -> SceneWrapper:
        """
        Randomize the order before building the SceneWrapper.
        """
        self.scenes = self.scenes * self.n
        return super().build()
