from mug.scenes import unity_scene
import flask_socketio
import dataclasses
import random

from mug.scenes.scene import Scene


@dataclasses.dataclass
class OpponentConfig:
    model_path: str
    frame_skip: int = 4
    obs_delay: int = 16
    inference_cadence: int = 4
    softmax_temperature: float = 1.0


DIFFICULTY_LEVEL_OPPONENTS = [
    OpponentConfig(
        model_path="4sf-16od-1c73fcc-0.03to0.01-500m-00",
        frame_skip=24 - i * 2,
        obs_delay=16,
        inference_cadence=4,
        softmax_temperature=2.0 - i * 0.1,
    )
    for i in range(11)
]


class FootsiesScene(unity_scene.UnityScene):
    def __init__(self):
        super().__init__()
        self.winners: list[str] = []
        self.opponent_sequence: list[OpponentConfig] = (
            DIFFICULTY_LEVEL_OPPONENTS[-1:]
        )

        self.randomize_opponents: bool = False

    def build(self) -> list[Scene]:
        if self.randomize_opponents:
            random.shuffle(self.opponent_sequence)
        return super().build()

    def set_opponent_sequence(
        self, opponents: list[OpponentConfig], randomize: bool = False
    ):
        self.opponent_sequence = opponents
        self.randomize_opponents = randomize
        return self

    def on_unity_episode_start(
        self, data: dict, socketio: flask_socketio.SocketIO, room: str
    ):

        if len(self.opponent_sequence) == 0:
            super().on_unity_episode_start(data, socketio, room)
            return

        opponent_config = self.opponent_sequence.pop(0)

        socketio.emit(
            "updateBotSettings",
            {
                "modelPath": opponent_config.model_path,
                "frameSkip": opponent_config.frame_skip,
                "inferenceCadence": opponent_config.inference_cadence,
                "observationDelay": opponent_config.obs_delay,
                "softmaxTemperature": opponent_config.softmax_temperature,
            },
            room=room,
        )


class FootsiesDynamicDifficultyScene(FootsiesScene):
    def __init__(self):
        super().__init__()
        self.winners: list[str] = []
        self.cur_difficulty_index: int = 5  # start at medium difficulty

        self.opponent_sequence: list[OpponentConfig] = [
            DIFFICULTY_LEVEL_OPPONENTS[self.cur_difficulty_index]
        ]

    def on_unity_episode_end(
        self, data: dict, socketio: flask_socketio.SocketIO, room: str
    ):
        winner = data["winner"]
        self.winners.append(winner)

        if len(self.winners) >= 2:

            # If P1 (human) won twice in a row, make the opponent harder.
            if all(w == "P1" for w in self.winners[-2:]):
                self.cur_difficulty_index = min(
                    len(DIFFICULTY_LEVEL_OPPONENTS) - 1,
                    self.cur_difficulty_index + 1,
                )

            # If P2 (bot) won twice in a row, make the opponent easier.
            elif all(w == "P2" for w in self.winners[-2:]):
                self.cur_difficulty_index = max(
                    0,
                    self.cur_difficulty_index - 1,
                )

            self.opponent_sequence.append(
                DIFFICULTY_LEVEL_OPPONENTS[self.cur_difficulty_index]
            )

        super().on_unity_episode_end(data, socketio, room)


class FootsiesDynamicEmpowermentScene(FootsiesScene):
    def __init__(self):
        super().__init__()
        self.winners: list[str] = []
        self.model_path: str = "4sf-16od-1c73fcc-0.03to0.01-500m-00"
        self.cur_frame_skip: int = 4
        self.cur_obs_delay: int = 16
        self.cur_inference_cadence: int = 4
        self.cur_softmax_temperature: float = 1.0
        self.cur_model_idx = 0

        self.model_paths: list[str] = [
            "esr-1.0alpha-00",
            "esr-0.75alpha-00",
            "esr-0.5alpha-00",
            "esr-0.25alpha-00",
            # "esr-0.1alpha-00",
            "4sf-16od-1c73fcc-0.03to0.01-500m-00",
        ]

        self.opponent_sequence: list[OpponentConfig] = [
            OpponentConfig(
                model_path=self.model_paths[self.cur_model_idx],
                frame_skip=self.cur_frame_skip,
                obs_delay=self.cur_obs_delay,
                inference_cadence=self.cur_inference_cadence,
                softmax_temperature=self.cur_softmax_temperature,
            )
        ]

    def set_initial_settings(
        self,
        model_path: str,
        frame_skip: int = 4,
        obs_delay: int = 16,
        inference_cadence: int = 4,
        softmax_temperature: float = 1.0,
    ):
        self.model_path = model_path
        self.cur_frame_skip = frame_skip
        self.cur_obs_delay = obs_delay
        self.cur_inference_cadence = inference_cadence
        self.cur_softmax_temperature = softmax_temperature

    def on_unity_episode_end(
        self, data: dict, socketio: flask_socketio.SocketIO, room: str
    ):
        winner = data["winner"]
        self.winners.append(winner)

        if len(self.winners) >= 2:

            # If P1 (human) won twice in a row, make the opponent harder.
            if all(w == "P1" for w in self.winners[-2:]):
                self.cur_model_idx = min(
                    len(self.model_paths) - 1,
                    self.cur_model_idx + 1,
                )

            # If P2 (bot) won twice in a row, make the opponent easier.
            elif all(w == "P2" for w in self.winners[-2:]):
                self.cur_model_idx = max(0, self.cur_model_idx - 1)

        self.opponent_sequence.append(
            OpponentConfig(
                model_path=self.model_paths[self.cur_model_idx],
                frame_skip=(
                    8
                    if self.cur_model_idx == len(self.model_paths) - 2
                    else self.cur_frame_skip
                ),
                obs_delay=self.cur_obs_delay,
                inference_cadence=self.cur_inference_cadence,
                softmax_temperature=self.cur_softmax_temperature,
            )
        )
        super().on_unity_episode_end(data, socketio, room)


class FootsiesRandomDifficultyScene(FootsiesScene):
    def __init__(self):
        super().__init__()
        self.winners: list[str] = []
        self.model_path: str = "4sf-16od-1c73fcc-0.03to0.01-500m-00"
        self.fs_temp_options: list[tuple[int, float]] = [
            (32, 1.7),  # Easiest
            (24, 1.6),
            (14, 1.5),
            (12, 1.4),
            (10, 1.3),
            (8, 1.2),
            (6, 1.1),
            (4, 1.0),  # Hardest
        ]
        self.cur_obs_delay: int = 16
        self.cur_inference_cadence: int = 4

    def on_unity_episode_start(
        self, data: dict, socketio: flask_socketio.SocketIO, room: str
    ):
        sampled_difficulty = random.choice(DIFFICULTY_LEVEL_OPPONENTS)
        self.opponent_sequence.append(sampled_difficulty)
        super().on_unity_episode_start(data, socketio, room)


class FootsiesControllableDifficultyScene(FootsiesScene):
    def __init__(self):
        super().__init__()

        # Initialize with the easiest opponent
        self.opponent_sequence: list[OpponentConfig] = [
            DIFFICULTY_LEVEL_OPPONENTS[0]
        ]

    def on_client_callback(
        self, data: dict, socketio: flask_socketio.SocketIO, room: str
    ):
        if data.get("type") == "updateFootsiesDifficulty":
            difficulty_idx = data["difficulty"] - 1
            opponent_config = DIFFICULTY_LEVEL_OPPONENTS[difficulty_idx]
            self.opponent_sequence = [opponent_config]

            socketio.emit(
                "updateBotSettings",
                {
                    "modelPath": opponent_config.model_path,
                    "frameSkip": opponent_config.frame_skip,
                    "inferenceCadence": opponent_config.inference_cadence,
                    "observationDelay": opponent_config.obs_delay,
                    "softmaxTemperature": opponent_config.softmax_temperature,
                },
                room=room,
            )
