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


@dataclasses.dataclass
class ModelConfig:
    """Configuration for an ONNX model's tensor names and shapes.

    Researchers use this to declare the observation input, logit output,
    and optional hidden state tensor names/shapes for each ONNX policy.

    Required fields:
        obs_input: Name of the observation input tensor (e.g., "obs").
        logit_output: Name of the logit output tensor (e.g., "output").

    Optional fields (for recurrent models):
        state_inputs: Names of hidden state input tensors
            (e.g., ["state_in_0", "state_in_1"]).
        state_outputs: Names of hidden state output tensors
            (e.g., ["state_out_0", "state_out_1"]).
        state_shape: Shape of each hidden state tensor (e.g., [1, 256]).

    Example::

        ModelConfig(
            obs_input="obs",
            logit_output="output",
            state_inputs=["state_in_0", "state_in_1"],
            state_outputs=["state_out_0", "state_out_1"],
            state_shape=[1, 256],
        )
    """

    obs_input: str
    logit_output: str
    state_inputs: list[str] | None = None
    state_outputs: list[str] | None = None
    state_shape: list[int] | None = None

    def __post_init__(self):
        # Validate required string fields
        if not isinstance(self.obs_input, str) or not self.obs_input.strip():
            raise ValueError("obs_input must be a non-empty string")
        if not isinstance(self.logit_output, str) or not self.logit_output.strip():
            raise ValueError("logit_output must be a non-empty string")

        # Validate state_inputs / state_outputs pairing
        has_inputs = self.state_inputs is not None
        has_outputs = self.state_outputs is not None

        if has_inputs != has_outputs:
            raise ValueError(
                "state_inputs and state_outputs must both be provided or both be None"
            )

        if has_inputs and has_outputs:
            if len(self.state_inputs) != len(self.state_outputs):
                raise ValueError(
                    f"state_inputs length ({len(self.state_inputs)}) must equal "
                    f"state_outputs length ({len(self.state_outputs)})"
                )

            # state_shape is required when state tensors are provided
            if self.state_shape is None:
                raise ValueError(
                    "state_shape must be provided when state_inputs/state_outputs are set"
                )

        # Validate state_shape contents when provided
        if self.state_shape is not None:
            if not isinstance(self.state_shape, list) or not all(
                isinstance(x, int) and x > 0 for x in self.state_shape
            ):
                raise ValueError(
                    "state_shape must be a list of positive integers"
                )

    def to_dict(self) -> dict:
        """Return a plain dict of all fields for JSON serialization."""
        return dataclasses.asdict(self)
