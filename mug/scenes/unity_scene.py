from __future__ import annotations

import copy
import json
from typing import Any, Callable

import flask_socketio

from mug.configurations import configuration_constants, remote_config
from mug.scenes import scene
from mug.utils.sentinels import NotProvided


class UnityScene(scene.Scene):
    """
    UnityScene is a Scene that represents an interaction with a Unity-based environment.

    This is particularly focused on settings where we have a game, e.g., a Unity game built
    with WebGL, and we want users to interact with it in an MUG experiment.
    """

    def __init__(self):
        super().__init__()
        # The main header text for the scene
        self.scene_header: str = ""
        # A subheader text for the scene
        self.scene_subheader: str = ""
        # The main content body of the scene, which can be HTML
        self.scene_body: str = ""  # Fixed typo: 'self_body' to 'scene_body'

        # The path to the WebGL build
        self.build_path: str | None = None
        # The condition(s) under which the user can continue on to the next scene
        self.allow_continue_on: list[str] = []

        # The number of episodes to run
        self.num_episodes: int | None = 1

        # The number of episodes completed
        self.episodes_completed: int = 0

        # If we track score, we'll use it and display it in the HUD
        self.score_fn: Callable[[], float] | None = None
        self.score: float | None = None

        # If we preload the game, we'll send a message to the client to preload the game
        self.preload_game: bool = False

        self.is_unity_scene: bool = True

    def display(
        self,
        scene_header: str = NotProvided,
        scene_subheader: str = NotProvided,
        scene_body: str = NotProvided,
        scene_body_filepath: str = NotProvided,
    ) -> UnityScene:
        """Sets the content to be displayed in the static scene.

        This method allows you to set the header, subheader, and body content of the static scene.
        You can provide the body content directly as a string or specify a filepath to load the content from.

        :param scene_header: The main header text for the scene, defaults to NotProvided
        :type scene_header: str, optional
        :param scene_subheader: A subheader text for the scene, defaults to NotProvided
        :type scene_subheader: str, optional
        :param scene_body: The main content body of the scene as a string (can be HTML), defaults to NotProvided
        :type scene_body: str, optional
        :param scene_body_filepath: Path to a file containing the scene body content, defaults to NotProvided
        :type scene_body_filepath: str, optional
        :return: The current UnityScene instance for method chaining
        :rtype: UnityScene

        :raises AssertionError: If both scene_body and scene_body_filepath are provided
        """
        if scene_body_filepath is not NotProvided:
            assert (
                scene_body is NotProvided
            ), "Cannot set both filepath and html_body."

            with open(scene_body_filepath, encoding="utf-8") as f:
                self.scene_body = f.read()

        if scene_body is not NotProvided:
            assert (
                scene_body_filepath is NotProvided
            ), "Cannot set both filepath and html_body."
            self.scene_body = scene_body

        if scene_header is not NotProvided:
            self.scene_header = scene_header

        if scene_subheader is not NotProvided:
            self.scene_subheader = scene_subheader

        return self

    def webgl(
        self,
        build_name: str = NotProvided,
        height: int = NotProvided,
        width: int = NotProvided,
        allow_continue_on: str | list[str] = NotProvided,
        preload_game: bool = NotProvided,
    ) -> UnityScene:
        """
        Specify the settings for the WebGL build.

        :param build_name: The name of the WebGL build, defaults to NotProvided
        :type build_name: str, optional
        :param height: The height of the WebGL build, defaults to NotProvided
        :type height: int, optional
        :param width: The width of the WebGL build, defaults to NotProvided
        :type width: int, optional
        :param allow_continue_on: The condition(s) under which the user can continue on to the next scene, defaults to NotProvided
        :type allow_continue_on: str | list[str], optional
        :return: The current UnityScene instance for method chaining
        :rtype: UnityScene
        """
        if build_name is not NotProvided:
            self.build_name = build_name

        if height is not NotProvided:
            self.height = height

        if width is not NotProvided:
            self.width = width

        if allow_continue_on is not NotProvided:
            self.allow_continue_on = (
                allow_continue_on
                if isinstance(allow_continue_on, list)
                else [allow_continue_on]
            )

        if preload_game is not NotProvided:
            self.preload_game = preload_game

        return self

    def game(
        self,
        num_episodes: int = NotProvided,
        score_fn: Callable[[], float] = NotProvided,
    ):
        """
        Specify the number of episodes to run.
        """
        if num_episodes is not NotProvided:
            self.num_episodes = num_episodes

        if score_fn is not NotProvided:
            self.score_fn = score_fn
            self.score = 0.0

        return self

    def on_unity_episode_start(
        self, data: dict, socketio: flask_socketio.SocketIO, room: str
    ):
        """
        This method is called when the Unity episode starts.
        """
        pass

    def on_unity_episode_end(
        self, data: dict, socketio: flask_socketio.SocketIO, room: str
    ):
        """
        This method is called when the Unity episode ends.
        """
        self.episodes_completed += 1

        socketio.emit(
            "unity_episode_end",
            {
                "all_episodes_done": self.episodes_completed
                >= self.num_episodes,
                **data,
                **self.scene_metadata,
            },
            room=room,
        )

        if self.score_fn is None:
            return

        score_this_round = self.score_fn(data)
        if self.score is None:
            self.score = score_this_round
        else:
            self.score += score_this_round

        socketio.emit(
            "update_unity_score",
            {
                "score": self.score,
                "num_episodes": self.num_episodes,
            },
            room=room,
        )

    def on_connect(self, socketio: flask_socketio.SocketIO, room: str | int):
        """
        A hook that is called when the client connects to the server.
        """
        if self.preload_game:
            socketio.emit("preload_unity_game", {**self.scene_metadata}, room=room)
