from __future__ import annotations

import dataclasses
import inspect


@dataclasses.dataclass(frozen=True)
class InputModes:
    SingleKeystroke = "single_keystroke"
    PressedKeys = "pressed_keys"


@dataclasses.dataclass(frozen=True)
class PolicyTypes:
    Human = "human"
    Random = "random"


# Prefix used in policy_mapping values to mark heuristic (Python code) policies.
# A HeuristicPolicy named "chaser" decomposes to the mapping value "heuristic:chaser".
HEURISTIC_POLICY_PREFIX = "heuristic:"


@dataclasses.dataclass(frozen=True)
class ActionSettings:
    PreviousSubmittedAction = "previous_submitted_action"
    DefaultAction = "default_action"


@dataclasses.dataclass
class ModelConfig:
    """Configuration for an ONNX model's tensor names and shapes.

    Researchers use this to declare the observation input, logit output,
    and optional hidden state tensor names/shapes for each ONNX policy.

    ModelConfig instances can be used directly as values in ``policy_mapping``
    (with ``onnx_path`` set). The ``policies()`` method will automatically
    decompose them into ONNX path strings and config dicts for the JS client.

    Required fields:
        obs_input: Name of the observation input tensor (e.g., "obs").
        logit_output: Name of the logit output tensor (e.g., "output").

    Optional fields:
        onnx_path: Path to the ONNX model file (e.g.,
            "examples/cogrid/assets/overcooked/models/sp_cramped_room_00.onnx").
            When set, the ModelConfig can be used directly as a
            ``policy_mapping`` value instead of a bare path string.

    Optional fields (for recurrent models):
        state_inputs: Names of hidden state input tensors
            (e.g., ["state_in_0", "state_in_1"]).
        state_outputs: Names of hidden state output tensors
            (e.g., ["state_out_0", "state_out_1"]).
        state_shape: Shape of each hidden state tensor (e.g., [1, 256]).

    Optional fields (for fixed inputs):
        fixed_inputs: A dictionary mapping input tensor names to their fixed
            scalar values. These are passed to every inference call as
            ``Float32Array([value])`` with shape ``[1]``. Useful for inputs
            like ``seq_lens`` that are constant during single-step inference.

    Optional fields (for custom inference):
        custom_inference_fn: An inline JavaScript function body string that
            receives ``(session, observation, modelConfig)`` and must return
            the selected action (integer). When set, this function completely
            replaces the declarative inference path. The function body may
            use ``await`` for async ONNX operations. obs_input and
            logit_output remain required but may be ignored by the custom
            function.

    Examples::

        # Template config (onnx_path=None, used as base for dataclasses.replace)
        base = ModelConfig(
            obs_input="obs",
            logit_output="output",
            state_inputs=["state_in_0", "state_in_1"],
            state_outputs=["state_out_0", "state_out_1"],
            state_shape=[1, 256],
            fixed_inputs={"seq_lens": 1},
        )

        # Use in policy_mapping with onnx_path set
        import dataclasses
        policy_mapping = {
            0: PolicyTypes.Human,
            1: dataclasses.replace(base, onnx_path="static/assets/model.onnx"),
        }

        # Custom inference escape hatch
        ModelConfig(
            obs_input="obs",
            logit_output="output",
            custom_inference_fn='''
                const inputTensor = new ort.Tensor(
                    'float32', observation, [1, observation.length]
                );
                const results = await session.run({obs: inputTensor});
                const logits = results['output'].data;
                return logits.indexOf(Math.max(...logits));
            ''',
        )
    """

    obs_input: str
    logit_output: str
    onnx_path: str | None = None
    state_inputs: list[str] | None = None
    state_outputs: list[str] | None = None
    state_shape: list[int] | None = None
    fixed_inputs: dict[str, float] | None = None
    custom_inference_fn: str | None = None

    def __post_init__(self):
        # Validate required string fields
        if not isinstance(self.obs_input, str) or not self.obs_input.strip():
            raise ValueError("obs_input must be a non-empty string")
        if not isinstance(self.logit_output, str) or not self.logit_output.strip():
            raise ValueError("logit_output must be a non-empty string")

        # Validate onnx_path when provided
        if self.onnx_path is not None:
            if not isinstance(self.onnx_path, str) or not self.onnx_path.strip():
                raise ValueError("onnx_path must be a non-empty string when provided")

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

        # Validate custom_inference_fn when provided
        if self.custom_inference_fn is not None:
            if not isinstance(self.custom_inference_fn, str) or not self.custom_inference_fn.strip():
                raise ValueError(
                    "custom_inference_fn must be a non-empty string when provided"
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


class HeuristicPolicy:
    """Base class for heuristic (Python code) policies.

    Subclass and implement :meth:`compute_action`, which receives the live
    environment instance and an agent ID and returns an action for that
    agent::

        class BallChaser(HeuristicPolicy):
            def compute_action(self, env, agent_id):
                ...
                return action

    Like ``ModelConfig``, heuristic policies are used directly as values in
    ``policy_mapping`` -- pass the subclass itself (not an instance)::

        policy_mapping = {
            "agent_left": PolicyTypes.Human,
            "agent_right": BallChaser,
        }

    The ``policies()`` method automatically decomposes the class: the mapping
    value becomes ``"heuristic:<ClassName>"`` and the source code of the
    module that defines the subclass is stored in ``policy_configs``.

    The policy executes wherever the environment lives: inside the Pyodide
    interpreter for browser (P2P) games, or on the server for
    server-authoritative games. Because the defining module's source is
    shipped as text and re-executed there:

    - Define the subclass in its own self-contained module (not in the
      experiment script / ``__main__``) -- include any imports the module
      needs and do not reference variables from other modules.
    - The subclass must be instantiable with no constructor arguments.

    One instance is created per agent, so instance attributes may hold
    per-agent state across steps. In multiplayer P2P games each client runs
    the heuristic locally, so it should be deterministic given the
    environment state (avoid ``random``/unseeded RNG), and stateless policies
    are safest since rollback corrections re-execute steps.
    """

    def compute_action(self, env, agent_id):
        """Return an action for ``agent_id`` given the live env instance."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement compute_action(env, agent_id)."
        )

    # -- Decomposition/serialization machinery (used by GymScene.policies()) --

    @classmethod
    def policy_id(cls) -> str:
        """The policy_mapping value this policy class decomposes to."""
        return f"{HEURISTIC_POLICY_PREFIX}{cls.__name__}"

    @classmethod
    def to_config(cls) -> dict:
        """Return a plain dict (including module source) for serialization.

        Raises:
            ValueError: If the subclass is defined in ``__main__`` or its
                source file cannot be located.
        """
        if cls.__module__ == "__main__":
            raise ValueError(
                f"HeuristicPolicy subclass '{cls.__name__}' is defined in the "
                f"main script. Define it in its own importable module so its "
                f"source can be shipped to where the environment runs."
            )
        try:
            source_file = inspect.getsourcefile(cls)
        except TypeError:
            source_file = None
        if source_file is None:
            raise ValueError(
                f"Cannot locate the source file for HeuristicPolicy subclass "
                f"'{cls.__name__}'. Define it in a .py module on disk."
            )
        with open(source_file, encoding="utf-8") as f:
            code = f.read()
        return {
            "type": "heuristic",
            "name": cls.__name__,
            "code": code,
        }

    @staticmethod
    def load_from_config(config: dict) -> HeuristicPolicy:
        """Execute a to_config() payload and return a policy instance.

        Raises:
            ValueError: If the code does not define a class named
                ``config["name"]`` with a compute_action method.
        """
        namespace = {}
        exec(config["code"], namespace)
        policy_cls = namespace.get(config["name"])
        if not (
            isinstance(policy_cls, type)
            and callable(getattr(policy_cls, "compute_action", None))
        ):
            raise ValueError(
                f"Heuristic policy code must define a class named "
                f"'{config['name']}' with a compute_action(env, agent_id) "
                f"method."
            )
        return policy_cls()
