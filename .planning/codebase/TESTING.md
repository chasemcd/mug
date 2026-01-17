# Testing Patterns

**Analysis Date:** 2025-01-16

## Test Framework

**Runner:**
- No test framework detected
- No test files found in the codebase
- No pytest.ini, conftest.py, tox.ini, or similar configuration files

**Assertion Library:**
- Not applicable (no tests exist)

**Run Commands:**
```bash
# No test commands configured
```

## Test File Organization

**Location:**
- No test files detected
- No `tests/` directory
- No `*_test.py` or `test_*.py` files

**Naming:**
- Not established

**Structure:**
- Not established

## Current Testing Approach

**Status:** No automated tests implemented

**Pre-commit Hooks Only:**
The codebase relies on pre-commit hooks for quality checks:
- Import sorting (isort)
- Code style (pyupgrade)
- Unused import removal (pycln)
- Typo checking (codespell)
- Blanket noqa/type-ignore checks
- No eval usage enforcement

## Recommended Testing Setup

**Framework:** pytest (standard for Python projects)

**Installation:**
```bash
pip install pytest pytest-cov pytest-asyncio
```

**Recommended Directory Structure:**
```
tests/
├── conftest.py           # Shared fixtures
├── unit/
│   ├── test_scene.py
│   ├── test_stager.py
│   └── test_game_manager.py
├── integration/
│   └── test_app.py
└── fixtures/
    └── sample_configs.py
```

**Recommended pytest.ini:**
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

## Testable Components

**Core Classes (Unit Test Candidates):**

1. **Scene Classes** (`interactive_gym/scenes/scene.py`, `static_scene.py`, `gym_scene.py`)
   - Scene initialization and configuration
   - Builder pattern method chaining
   - Metadata serialization

2. **Stager** (`interactive_gym/scenes/stager.py`)
   - Scene sequencing and navigation
   - State persistence (get_state/set_state)
   - Build instance copying

3. **RemoteGameV2** (`interactive_gym/server/remote_game.py`)
   - Player management
   - Action queue handling
   - Game state transitions

4. **GameManager** (`interactive_gym/server/game_manager.py`)
   - Subject-to-game mapping
   - Waitroom logic
   - Group matching

5. **Configuration Classes** (`interactive_gym/configurations/`)
   - RemoteConfig builder pattern
   - Serialization (to_dict)
   - Validation logic

**Integration Test Candidates:**

1. **Flask App** (`interactive_gym/server/app.py`)
   - SocketIO event handling
   - Session management
   - Data persistence

2. **PyodideGameCoordinator** (`interactive_gym/server/pyodide_game_coordinator.py`)
   - Player coordination
   - Action broadcasting
   - Host election

## Mocking Considerations

**External Dependencies to Mock:**
- Flask-SocketIO (`flask_socketio.SocketIO`)
- Eventlet async primitives (`eventlet.event.Event`)
- File system operations (data export)
- Gymnasium environments

**Mock Pattern Example:**
```python
from unittest.mock import Mock, patch

@patch('flask_socketio.SocketIO')
def test_game_start(mock_sio):
    mock_sio.emit = Mock()
    manager = GameManager(scene=mock_scene, sio=mock_sio)
    # Test logic here
```

## Fixtures Needed

**Scene Fixtures:**
```python
@pytest.fixture
def basic_gym_scene():
    return GymScene().scene(scene_id="test_scene")

@pytest.fixture
def configured_gym_scene(basic_gym_scene):
    return (
        basic_gym_scene
        .environment(env_creator=lambda: Mock())
        .gameplay(action_mapping={"a": 0, "b": 1})
    )
```

**Stager Fixtures:**
```python
@pytest.fixture
def simple_stager():
    return Stager(scenes=[
        StartScene().scene(scene_id="start"),
        EndScene().scene(scene_id="end"),
    ])
```

**Game Fixtures:**
```python
@pytest.fixture
def mock_socketio():
    sio = Mock(spec=SocketIO)
    sio.emit = Mock()
    sio.start_background_task = Mock()
    return sio
```

## Coverage

**Requirements:** None enforced

**Recommended Target:**
- 80% for core logic (scenes, game management)
- 60% for server/socket handling
- 40% for UI/static scene generation

## Test Types Needed

**Unit Tests:**
- Scene builder pattern validation
- Stager navigation logic
- Action queue processing
- Configuration serialization

**Integration Tests:**
- End-to-end game flow
- Socket event handling
- Session persistence

**E2E Tests:**
- Framework: Playwright or Selenium (not currently configured)
- Scope: Full browser-based game testing

## Validation Patterns in Code

**Existing Assertions (could be test inspiration):**
```python
# From stager.py
assert isinstance(scenes[0], static_scene.StartScene)
assert isinstance(scenes[-1], static_scene.EndScene)

# From gym_scene.py
assert type(num_episodes) == int and num_episodes >= 1
assert location_representation in ["relative", "pixels"]

# From game_manager.py
assert isinstance(scene, gym_scene.GymScene)
```

## Getting Started with Testing

1. **Install dependencies:**
   ```bash
   pip install pytest pytest-cov pytest-mock
   ```

2. **Create initial structure:**
   ```bash
   mkdir -p tests/unit tests/integration
   touch tests/__init__.py tests/conftest.py
   ```

3. **Add to pyproject.toml:**
   ```toml
   [tool.pytest.ini_options]
   testpaths = ["tests"]
   python_files = ["test_*.py"]
   ```

4. **Create first test:**
   ```python
   # tests/unit/test_scene.py
   from interactive_gym.scenes.scene import Scene

   def test_scene_creation():
       scene = Scene()
       assert scene.status == SceneStatus.Inactive
   ```

5. **Run tests:**
   ```bash
   pytest -v
   ```

---

*Testing analysis: 2025-01-16*
