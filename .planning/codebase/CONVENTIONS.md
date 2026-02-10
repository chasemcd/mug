# Coding Conventions

**Analysis Date:** 2026-02-07

## Naming Patterns

**Files:**
- Use `snake_case.py` for all Python modules: `remote_game.py`, `gym_scene.py`, `player_pairing_manager.py`
- Test files use `test_` prefix: `test_latency_fifo_matchmaker.py`, `test_multiplayer_basic.py`
- Configuration files use descriptive names: `configuration_constants.py`, `experiment_config.py`
- Example/experiment scripts use long descriptive names: `overcooked_human_human_multiplayer_test.py`

**Classes:**
- PascalCase for all classes: `GameManager`, `RemoteGameV2`, `GymScene`, `PlayerGroupManager`
- Status/enum-like classes use PascalCase: `GameStatus`, `SessionState`, `ParticipantState`
- Singleton sentinels use `_PascalCase` with double underscore inner class: `_NotProvided`, `_Available`
- Abstract base classes use plain PascalCase: `Matchmaker`
- Dataclasses use PascalCase: `MatchCandidate`, `PlayerGroup`, `ParticipantSession`

**Functions/Methods:**
- Use `snake_case` for all functions and methods: `find_match()`, `create_probe()`, `get_game_state()`
- Private methods use single underscore prefix: `_build_env()`, `_load_policies()`, `_create_game()`
- Property methods use `@property` decorator with `snake_case`: `scene_metadata`, `simulate_waiting_room`
- Predicate methods use `is_` prefix: `is_at_player_capacity()`, `is_idle()`, `can_join_waitroom()`

**Variables:**
- Use `snake_case` for instance variables: `self.human_players`, `self.current_scene_index`
- Module-level constants use `UPPER_SNAKE_CASE`: `CONFIG`, `GENERIC_STAGER`, `SUBJECTS`, `LOADING_TIMEOUT_S`
- Module-level mutable globals also use `UPPER_SNAKE_CASE`: `GAME_MANAGERS`, `STAGERS`, `USER_LOCKS`

**Type Aliases:**
- Simple type aliases in `interactive_gym/utils/typing.py`: `SubjectID = str`, `GameID = str`, `RoomID = int`, `SceneID = str`

## Code Style

**Formatting:**
- No auto-formatter configured (no `.prettierrc`, `black`, `ruff` config detected)
- Indentation: 4 spaces (Python standard)
- Line length: approximately 88-100 characters observed, no enforced limit
- String quotes: Double quotes for strings (`"string"`) as primary convention
- F-strings used for string interpolation: `f"Port {port} occupied by unkillable process"`

**Linting:**
- No linting tool configured (no `.flake8`, `ruff.toml`, `.pylintrc` detected)
- Follow PEP 8 conventions by convention, not enforcement

**Imports:**
- Use `from __future__ import annotations` at the top of most files for forward reference support
- Type checking imports guarded with `TYPE_CHECKING`:
```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from interactive_gym.server.matchmaker import Matchmaker
```

## Import Organization

**Order:**
1. `from __future__ import annotations` (when used)
2. Standard library imports (`os`, `time`, `threading`, `uuid`, `logging`, `dataclasses`)
3. Third-party imports (`flask`, `flask_socketio`, `eventlet`, `numpy`, `gymnasium`)
4. Internal imports (`from interactive_gym.server import utils`, `from interactive_gym.scenes import scene`)

**Path Style:**
- Absolute imports from package root: `from interactive_gym.server import utils`
- Some aliased imports: `from interactive_gym.server import game_manager as gm`
- Relative imports are NOT used; always use full package paths

**Path Aliases:**
- None configured (no `pyproject.toml` path mapping)

## Builder/Fluent API Pattern

**The primary configuration API uses method chaining (fluent/builder pattern).**

This is the dominant API design pattern in the codebase. All configuration classes (`GymScene`, `ExperimentConfig`, `RemoteConfig`) use this pattern.

**Pattern:**
```python
# Each method returns `self` for chaining
scene = (
    GymScene()
    .scene(scene_id="my_scene")
    .environment(env_creator=create_env, env_config={...})
    .rendering(fps=30, game_width=600, game_height=400)
    .gameplay(action_mapping={...}, num_episodes=3)
    .policies(policy_mapping={...})
    .multiplayer(...)
)
```

**Key files using this pattern:**
- `interactive_gym/scenes/gym_scene.py` - `GymScene` class with `.environment()`, `.rendering()`, `.gameplay()`, `.policies()`, `.content()`, `.assets()`, `.matchmaking()`, `.multiplayer()`, `.focus_loss_config()` etc.
- `interactive_gym/configurations/experiment_config.py` - `ExperimentConfig` with `.experiment()`, `.hosting()`, `.webrtc()`, `.entry_screening()`
- `interactive_gym/configurations/remote_config.py` - `RemoteConfig` with `.environment()`, `.rendering()`, `.hosting()`, `.policies()`, `.gameplay()`, `.user_experience()`, `.pyodide()`, `.webrtc()`

**NotProvided Sentinel Pattern:**
- Instead of `None` defaults (which would be ambiguous), the codebase uses a `NotProvided` sentinel from `interactive_gym/scenes/utils.py`
- Method parameters default to `NotProvided`, and only set values if not `NotProvided`:
```python
def environment(
    self,
    env_creator: Callable = NotProvided,
    env_config: dict[str, Any] = NotProvided,
    seed: int = NotProvided,
):
    if env_creator is not NotProvided:
        self.env_creator = env_creator
    if env_config is not NotProvided:
        self.env_config = env_config
    return self
```
- `RemoteConfig` (older API) uses `None` defaults instead of `NotProvided`; newer code (`GymScene`, `ExperimentConfig`) uses `NotProvided`

## Error Handling

**Patterns:**
- **Assertions for configuration validation:** Use `assert` statements for configuration-time checks in builder methods:
```python
assert location_representation in ["relative", "pixels"], "Must pass either relative or pixel location!"
assert type(num_episodes) == int and num_episodes >= 1, "Must pass an int >=1 to num episodes."
```
- **ValueError/TypeError for API misuse:** Some newer code raises explicit exceptions:
```python
if rollback_smoothing_duration is not None and rollback_smoothing_duration < 0:
    raise ValueError("rollback_smoothing_duration must be None or >= 0")
```
- **Logging + graceful degradation for runtime errors:** Server code logs warnings/errors and continues rather than crashing:
```python
logger.error(f"Invalid session transition: {self.session_state} -> {new_state}")
return False
```
- **Broad exception catches in teardown/cleanup:** Test fixtures and cleanup code uses broad `except Exception` to prevent teardown failures:
```python
except Exception:
    pass  # Page may already be closed
```
- **State machine validation:** Use explicit valid transition maps for state machines:
```python
VALID_TRANSITIONS = {
    SessionState.WAITING: {SessionState.MATCHED, SessionState.ENDED},
    SessionState.MATCHED: {SessionState.VALIDATING, SessionState.ENDED},
    ...
}
```

## Logging

**Framework:** Python `logging` module

**Patterns:**
- Module-level logger: `logger = logging.getLogger(__name__)`
- App-level custom logger setup in `interactive_gym/server/app.py`: `setup_logger(__name__, "./iglog.log", level=logging.DEBUG)`
- Log format: `"%(asctime)s - %(name)s - %(levelname)s - %(message)s"`
- Bracket-prefixed context tags in log messages: `[StateValidation]`, `[ParticipantState]`, `[FIFOMatchmaker]`, `[Grace]`
- F-string formatting (not lazy `%` formatting): `logger.info(f"Session {self.game_id}: {old_state.name} -> {new_state.name}")`
- Use `logger.warning()` for recoverable issues, `logger.error()` for invalid states, `logger.info()` for lifecycle events

## Comments

**When to Comment:**
- Phase/ticket references in comments: `# Phase 57: P2P Probe Infrastructure`, `# Completes DATA-01`, `# Session lifecycle state (SESS-01)`
- Inline `# ...` comments for non-obvious logic
- TODO comments with author attribution: `# TODO(chase): add callback typehint but need to avoid circular import`

**Docstrings:**
- Use triple-double-quote docstrings for all public classes and methods
- Class docstrings describe purpose and list key attributes
- Two docstring styles coexist:
  - **Sphinx/reST style** (newer code): `:param name: description\n:type name: type\n:return: description\n:rtype: type`
  - **Google style** (newer server code): `Args:\n    name: description\nReturns:\n    description`
- For new code, use **Google-style docstrings** (more prevalent in recent additions)

## Function Design

**Size:** No hard limit, but most methods are 10-50 lines. Exceptions: `app.py` functions can be 50-100+ lines due to complex socket event handlers.

**Parameters:**
- Builder methods use `NotProvided` sentinel defaults (see Builder/Fluent API Pattern above)
- Older code uses `None` defaults
- Type hints on all parameters in newer code: `subject_id: str`, `new_state: ParticipantState`
- Union types use `|` syntax (Python 3.10+): `str | int | None`, `Callable | None`

**Return Values:**
- Builder methods return `self` for chaining
- Predicate methods return `bool`
- State transition methods return `bool` (success/failure)
- Factory methods return the created object
- Getter methods return `dict | None` pattern

## Module Design

**Exports:**
- No `__all__` definitions used
- `interactive_gym/__init__.py` is empty
- Subpackage `__init__.py` files are empty

**Barrel Files:**
- Not used. Import directly from the specific module: `from interactive_gym.server.matchmaker import MatchCandidate`

**Constants:**
- Use frozen dataclasses for constant groups in `interactive_gym/configurations/configuration_constants.py`:
```python
@dataclasses.dataclass(frozen=True)
class PolicyTypes:
    Human = "human"
    Random = "random"
```
- Use `Enum` with `auto()` for state enums in newer code:
```python
class ParticipantState(Enum):
    IDLE = auto()
    IN_WAITROOM = auto()
    IN_GAME = auto()
    GAME_ENDED = auto()
```

## Thread Safety

- Use `ThreadSafeDict` and `ThreadSafeSet` from `interactive_gym/server/utils.py` for shared mutable state
- Use `threading.Lock()` for complex multi-step operations
- Use `eventlet.semaphore.Semaphore()` for eventlet-compatible locking in server code
- Use `threading.Lock()` for atomicity in multi-step operations: `self.lock = threading.Lock()`

## Data Classes

- Use `@dataclasses.dataclass` for simple data containers: `MatchCandidate`, `PlayerGroup`, `ParticipantSession`
- Use `@dataclasses.dataclass(frozen=True)` for immutable constants: `GameStatus`, `InputModes`, `PolicyTypes`
- Use `field(default_factory=...)` for mutable defaults: `field(default_factory=list)`, `field(default_factory=time.time)`

---

*Convention analysis: 2026-02-07*
