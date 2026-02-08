from __future__ import annotations

from interactive_gym.server import remote_game


class GameCallback:
    def __init__(self, **kwargs) -> None:
        pass

    def on_episode_start(self, remote_game: remote_game.RemoteGameV2):
        pass

    def on_episode_end(self, remote_game: remote_game.RemoteGameV2):
        pass

    def on_game_tick_start(self, remote_game: remote_game.RemoteGameV2):
        pass

    def on_game_tick_end(self, remote_game: remote_game.RemoteGameV2):
        pass

    def on_graphics_start(self, remote_game: remote_game.RemoteGameV2):
        pass

    def on_graphics_end(self, remote_game: remote_game.RemoteGameV2):
        pass

    def on_waitroom_start(self, remote_game: remote_game.RemoteGameV2):
        pass

    def on_waitroom_join(self, remote_game: remote_game.RemoteGameV2):
        pass

    def on_waitroom_end(self, remote_game: remote_game.RemoteGameV2):
        pass

    def on_waitroom_timeout(self, remote_game: remote_game.RemoteGameV2):
        pass

    def on_game_end(self, remote_game: remote_game.RemoteGameV2):
        pass


class MultiCallback(GameCallback):
    def __init__(self, callbacks: list[GameCallback], **kwargs) -> None:

        # Initialize all callbacks
        self.callbacks = [callback() for callback in callbacks]

    def on_episode_start(self, remote_game: remote_game.RemoteGameV2):
        for callback in self.callbacks:
            callback.on_episode_start(remote_game)

    def on_episode_end(self, remote_game: remote_game.RemoteGameV2):
        for callback in self.callbacks:
            callback.on_episode_end(remote_game)

    def on_game_tick_start(self, remote_game: remote_game.RemoteGameV2):
        for callback in self.callbacks:
            callback.on_game_tick_start(remote_game)

    def on_game_tick_end(self, remote_game: remote_game.RemoteGameV2):
        for callback in self.callbacks:
            callback.on_game_tick_end(remote_game)

    def on_graphics_start(self, remote_game: remote_game.RemoteGameV2):
        for callback in self.callbacks:
            callback.on_graphics_start(remote_game)

    def on_graphics_end(self, remote_game: remote_game.RemoteGameV2):
        for callback in self.callbacks:
            callback.on_graphics_end(remote_game)

    def on_waitroom_start(self, remote_game: remote_game.RemoteGameV2):
        for callback in self.callbacks:
            callback.on_waitroom_start(remote_game)

    def on_waitroom_join(self, remote_game: remote_game.RemoteGameV2):
        for callback in self.callbacks:
            callback.on_waitroom_join(remote_game)

    def on_waitroom_end(self, remote_game: remote_game.RemoteGameV2):
        for callback in self.callbacks:
            callback.on_waitroom_end(remote_game)

    def on_waitroom_timeout(self, remote_game: remote_game.RemoteGameV2):
        for callback in self.callbacks:
            callback.on_waitroom_timeout(remote_game)

    def on_game_end(self, remote_game: remote_game.RemoteGameV2):
        for callback in self.callbacks:
            callback.on_game_end(remote_game)
