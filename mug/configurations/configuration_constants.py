from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class InputModes:
    SingleKeystroke = "single_keystroke"
    PressedKeys = "pressed_keys"


@dataclasses.dataclass(frozen=True)
class PolicyTypes:
    Human = "human"
    Random = "random"


@dataclasses.dataclass(frozen=True)
class ActionSettings:
    PreviousSubmittedAction = "previous_submitted_action"
    DefaultAction = "default_action"
