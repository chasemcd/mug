# Coding Conventions

**Analysis Date:** 2025-01-16

## Naming Patterns

**Files:**
- snake_case for all Python files: `remote_game.py`, `game_manager.py`, `static_scene.py`
- Descriptive module names matching content: `configuration_constants.py`, `pyodide_game_coordinator.py`

**Functions:**
- snake_case for all functions and methods: `add_subject_to_game()`, `process_pressed_keys()`
- Private/internal methods prefixed with underscore: `_create_game()`, `_build_env()`, `_load_policies()`
- Hook methods use `on_` prefix: `on_connect()`, `on_episode_start()`, `on_client_callback()`

**Variables:**
- snake_case for variables: `subject_id`, `game_id`, `socket_id`
- UPPER_SNAKE_CASE for module-level constants: `SERVER_SESSION_ID`, `MAX_CONCURRENT_SESSIONS`
- Global state dictionaries in UPPER_SNAKE_CASE: `STAGERS`, `SUBJECTS`, `GAME_MANAGERS`

**Classes:**
- PascalCase for classes: `GameManager`, `RemoteGameV2`, `PyodideGameCoordinator`
- Status/enum-like classes use frozen dataclasses: `GameStatus`, `InputModes`, `PolicyTypes`

**Types:**
- Type aliases defined in `interactive_gym/utils/typing.py` as simple assignments:
  ```python
  SubjectID = str
  GameID = str
  RoomID = int
  SceneID = str
  ```

## Code Style

**Formatting:**
- Uses pre-commit hooks for automatic formatting
- Configured in `.pre-commit-config.yaml`
- Key hooks:
  - `isort` (5.12.0) for import sorting with `from __future__ import annotations`
  - `pyupgrade` for Python 3.7+ syntax
  - `pycln` for unused import removal
  - `codespell` for typo checking
  - `trailing-whitespace` and `end-of-file-fixer`

**Linting:**
- Pre-commit hooks from `pygrep-hooks`:
  - `python-check-blanket-noqa`
  - `python-check-blanket-type-ignore`
  - `python-no-log-warn`
  - `python-no-eval`
  - `python-use-type-annotations`

**Line Length:**
- No explicit max line length configured
- Code typically stays under 100 characters per line

## Import Organization

**Order:**
1. Future imports (always first): `from __future__ import annotations`
2. Standard library imports: `import dataclasses`, `import logging`, `import threading`
3. Third-party imports: `import flask`, `import flask_socketio`, `import eventlet`
4. Local imports: `from interactive_gym.server import utils`, `from interactive_gym.scenes import scene`

**Path Aliases:**
- None configured; uses relative imports within package

**Import Style:**
```python
from __future__ import annotations

import dataclasses
import logging
import threading
import time

import eventlet
import flask
import flask_socketio

from interactive_gym.configurations import configuration_constants
from interactive_gym.server import utils
from interactive_gym.scenes import scene
```

## Type Hints

**Usage Pattern:**
- Modern Python 3.10+ union syntax: `str | int | None`
- Generic types with lowercase: `dict[str, Any]`, `list[str]`
- Optional trailing return type: `def method(self) -> ReturnType:`
- Callable type hints: `typing.Callable | None`

**Examples from codebase:**
```python
# Function parameters
def add_subject_to_game(self, subject_id: SubjectID) -> remote_game.RemoteGameV2 | None:

# Class attributes
self.env_creator: typing.Callable | None = None
self.policy_mapping: dict[str, typing.Any] = dict()

# Dataclass fields
@dataclasses.dataclass
class ParticipantSession:
    subject_id: str
    stager_state: dict | None
    is_connected: bool
```

## Error Handling

**Patterns:**
- Assertions for invariant checking: `assert game_id is not None`
- Try/except for external operations:
  ```python
  try:
      self.pending_actions[subject_id].put(action, block=False)
  except queue.Full:
      pass  # Silent drop when queue is full
  ```
- Logging for recoverable errors: `logger.error(f"Error message: {e}")`
- Raising ValueError/NotImplementedError for invalid states

**Validation Style:**
```python
if env_creator is not NotProvided:
    self.env_creator = env_creator

assert isinstance(run_through_pyodide, bool)
assert type(num_episodes) == int and num_episodes >= 1
```

## Logging

**Framework:** Standard library `logging` module

**Logger Setup:**
```python
logger = logging.getLogger(__name__)
```

**Custom Setup in `app.py`:**
```python
def setup_logger(name, log_file, level=logging.INFO):
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler = logging.FileHandler(log_file)
    handler.setFormatter(formatter)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    return logger
```

**Log Levels Used:**
- `logger.debug()` - Detailed action tracking
- `logger.info()` - Normal operations (player joins, game starts)
- `logger.warning()` - Recoverable issues (player not found)
- `logger.error()` - Errors requiring attention

**Message Format:**
- F-strings with context: `f"Subject {subject_id} joined game {game_id}"`
- Variable interpolation for debugging: `f"Game status: {game.status}"`

## Comments

**When to Comment:**
- Module-level docstrings explaining purpose
- Class docstrings with attribute descriptions
- Complex methods with parameter/return documentation
- TODO comments for future work (author-tagged): `# TODO(chase): description`

**Docstring Style (Google-style with Sphinx):**
```python
def environment(
    self,
    env_creator: Callable = NotProvided,
    env_config: dict[str, Any] = NotProvided,
    seed: int = NotProvided,
):
    """Specify the environment settings for the scene.

    :param env_creator: A function that creates the environment, defaults to NotProvided.
    :type env_creator: Callable, optional
    :param env_config: Configuration for the environment.
    :type env_config: dict[str, Any], optional
    :return: This scene object
    :rtype: GymScene
    """
```

## Function Design

**Size:**
- Methods typically 10-50 lines
- Complex logic split into helper methods (prefixed with `_`)

**Parameters:**
- Use sentinel value `NotProvided` for optional builder-pattern parameters
- Default values for simple types: `int = 42`, `str = ""`
- Dict/list defaults use empty constructors: `dict()`, `list()` not `{}`, `[]`

**Return Values:**
- Methods in builder pattern return `self` for chaining
- Query methods return appropriate type or `None`
- State-modifying methods often return nothing (void)

**Builder Pattern Example:**
```python
class GymScene(scene.Scene):
    def environment(self, env_creator=NotProvided, ...):
        if env_creator is not NotProvided:
            self.env_creator = env_creator
        return self

    def rendering(self, fps=NotProvided, ...):
        if fps is not NotProvided:
            self.fps = fps
        return self
```

## Module Design

**Exports:**
- Minimal `__init__.py` files (mostly empty)
- Direct imports from modules rather than package-level re-exports

**Barrel Files:**
- Not used; import directly from module files

**Class Organization:**
- One primary class per file typically
- Related helper classes in same file (e.g., `Scene` and `SceneWrapper`)
- Constants in dedicated module: `configuration_constants.py`

## Thread Safety

**Pattern:**
- Custom thread-safe collections in `interactive_gym/server/utils.py`:
  ```python
  class ThreadSafeDict(dict):
      def __init__(self, *args, **kwargs):
          super().__init__(*args, **kwargs)
          self.lock = Lock()

      def __setitem__(self, *args, **kwargs):
          with self.lock:
              retval = super().__setitem__(*args, **kwargs)
          return retval
  ```
- Per-object locks for game state: `self.lock = threading.Lock()`
- Context managers for critical sections: `with game.lock:`

## Dataclasses

**Usage:**
- Configuration/status enums as frozen dataclasses:
  ```python
  @dataclasses.dataclass(frozen=True)
  class GameStatus:
      Done = "done"
      Active = "active"
      Inactive = "inactive"
  ```
- State containers with default values:
  ```python
  @dataclasses.dataclass
  class ParticipantSession:
      subject_id: str
      is_connected: bool
      created_at: float = dataclasses.field(default_factory=time.time)
  ```

## Sentinel Values

**NotProvided Pattern:**
- Used in builder-pattern methods for optional parameters
- Defined in `interactive_gym/scenes/utils.py`:
  ```python
  class _NotProvided:
      class __NotProvided:
          pass
      instance = None
      def __init__(self):
          if _NotProvided.instance is None:
              _NotProvided.instance = _NotProvided.__NotProvided()

  NotProvided = _NotProvided
  ```
- Checked with `is not NotProvided` (identity check)

## Socket.IO Event Naming

**Pattern:**
- snake_case for event names: `register_subject`, `advance_scene`, `join_game`
- Descriptive action verbs: `send_pressed_keys`, `emit_remote_game_data`
- Prefixes for grouped events: `pyodide_player_action`, `pyodide_hud_update`

---

*Convention analysis: 2025-01-16*
