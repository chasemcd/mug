# Multiplayer State Synchronization API

## Overview

For deterministic multiplayer synchronization in MUG, environments **must** implement state serialization methods that allow perfect state reconstruction across clients.

This is required for:
- Detecting and correcting desyncs between players
- Recovering from network issues
- Ensuring all players see the same game state

---

## Required Methods

All environments used in multiplayer Pyodide games must implement these two methods:

### `get_state() -> dict`

Returns a complete, JSON-serializable representation of the environment state.

**Signature:**
```python
def get_state(self) -> dict:
    """
    Returns the complete environment state as a JSON-serializable dictionary.

    Returns:
        dict: State dictionary containing all information needed to perfectly
              reconstruct the environment state.

    Raises:
        NotImplementedError: If environment doesn't support state sync
    """
```

**Requirements:**
- ✅ Must return a `dict`
- ✅ Must be JSON-serializable (only primitive types: `int`, `float`, `str`, `bool`, `list`, `dict`, `None`)
- ✅ Must be deterministic (same state → same dict)
- ✅ Must be complete (captures ALL state affecting gameplay)
- ✅ Should be reasonably compact

**Example:**
```python
def get_state(self) -> dict:
    return {
        'agents': {
            0: {
                'position': [2, 3],
                'orientation': 'north',
                'holding': 'onion',
                'has_interacted': False,
            },
            1: {
                'position': [4, 1],
                'orientation': 'east',
                'holding': None,
                'has_interacted': True,
            },
        },
        'objects': [
            {'type': 'onion', 'position': [1, 1]},
            {'type': 'pot', 'position': [3, 2], 'contents': ['onion', 'onion'], 'cook_time': 5},
        ],
        'time_remaining': 120,
        'score': 15,
        'delivery_count': 3,
    }
```

---

### `set_state(state: dict) -> None`

Restores the environment to the exact state provided.

**Signature:**
```python
def set_state(self, state: dict) -> None:
    """
    Restores the environment to the exact state provided.

    Args:
        state: Dictionary previously returned by get_state()

    Raises:
        ValueError: If state is invalid or incompatible
    """
```

**Requirements:**
- ✅ Must accept the dict returned by `get_state()`
- ✅ Must fully restore the environment to that exact state
- ✅ After calling `set_state(s)`, calling `get_state()` should return `s`
- ✅ Should validate the state dict and raise clear errors if invalid

**Example:**
```python
def set_state(self, state: dict) -> None:
    # Validate state structure
    if 'agents' not in state or 'objects' not in state:
        raise ValueError("Invalid state dict: missing required keys")

    # Restore agents
    for agent_id, agent_state in state['agents'].items():
        self.agents[int(agent_id)].position = agent_state['position']
        self.agents[int(agent_id)].orientation = agent_state['orientation']
        self.agents[int(agent_id)].holding = agent_state['holding']
        self.agents[int(agent_id)].has_interacted = agent_state['has_interacted']

    # Restore objects
    self.objects.clear()
    for obj_data in state['objects']:
        self.objects.append(self._create_object(obj_data))

    # Restore game state
    self.time_remaining = state['time_remaining']
    self.score = state['score']
    self.delivery_count = state['delivery_count']
```

---

## What to Include in State

### ✅ Must Include

- **Agent state**: positions, orientations, velocities, health, etc.
- **Agent inventories**: held items, equipment
- **Agent status**: buffs, debuffs, cooldowns
- **Object states**: positions, properties, contents
- **World state**: if mutable (terrain modifications, doors, etc.)
- **Game state**: score, time, objectives, counters
- **Internal variables**: anything that affects the next `step()`

### ❌ Don't Include

- **Cached computations**: Can be recomputed on demand
- **Observation buffers**: Recompute from state
- **Rendering state**: Recompute from state
- **History/logs**: Not needed for state reconstruction
- **Action buffers**: Not part of environment state

### 🤔 Guidelines

Ask yourself: *"If I restore this state, will the environment behave identically?"*

If the answer is no, you're missing something in the state.

---

## Testing Your Implementation

### Basic Round-Trip Test

```python
import json

# Get initial state
state1 = env.get_state()

# Verify it's JSON-serializable
json_str = json.dumps(state1)
state1_copy = json.loads(json_str)

# Take some actions
env.step({0: 1, 1: 2})
env.step({0: 3, 1: 1})

# Restore to initial state
env.set_state(state1)

# Get state again - should match
state2 = env.get_state()

# Compare
assert state1 == state2, "State round-trip failed!"
print("✓ State round-trip test passed")
```

### Determinism Test

```python
# Start from same state in two environments
env1 = YourEnv()
env2 = YourEnv()

state = env1.get_state()
env2.set_state(state)

# Take same actions in both
actions = [{0: 1, 1: 2}, {0: 3, 1: 1}, {0: 2, 1: 3}]

for action in actions:
    obs1, reward1, done1, info1 = env1.step(action)
    obs2, reward2, done2, info2 = env2.step(action)

    assert env1.get_state() == env2.get_state(), "Environments diverged!"

print("✓ Determinism test passed")
```

---

## Error Handling

Provide clear error messages:

```python
def get_state(self) -> dict:
    try:
        state = {
            'agents': self._serialize_agents(),
            'objects': self._serialize_objects(),
            # ...
        }
        return state
    except Exception as e:
        raise RuntimeError(f"Failed to serialize environment state: {e}")

def set_state(self, state: dict) -> None:
    # Validate
    required_keys = ['agents', 'objects', 'time_remaining', 'score']
    missing_keys = [k for k in required_keys if k not in state]

    if missing_keys:
        raise ValueError(
            f"Invalid state dict: missing required keys: {missing_keys}"
        )

    try:
        # Restore state
        self._restore_agents(state['agents'])
        self._restore_objects(state['objects'])
        # ...
    except Exception as e:
        raise RuntimeError(f"Failed to restore environment state: {e}")
```

---

## Client-Side Validation

When a multiplayer game starts, MUG will automatically validate that your environment implements these methods:

```javascript
// Automatic validation on game start
[MultiplayerPyodide] Validating environment state sync API...
[MultiplayerPyodide] ✓ Environment OvercookedEnv supports state synchronization
```

If methods are missing, you'll see a clear error:

```
❌ Multiplayer State Sync API Error
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Environment: OvercookedEnv (overcooked_env)

Missing required methods: get_state(), set_state()

For multiplayer synchronization, environments must implement:

  def get_state(self) -> dict:
      """Return JSON-serializable state dict"""
      return {...}  # Complete environment state

  def set_state(self, state: dict) -> None:
      """Restore environment from state dict"""
      # Restore all environment variables from state

See documentation: docs/multiplayer_state_sync_api.md
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Implementation Checklist

- [ ] Implement `get_state()` returning JSON-serializable dict
- [ ] Implement `set_state()` accepting dict from `get_state()`
- [ ] Test round-trip: `set_state(get_state())` is identity
- [ ] Test determinism: same state + actions → same state
- [ ] Test JSON serialization: `json.dumps(get_state())` works
- [ ] Add validation and error handling
- [ ] Document what's included in your state dict
- [ ] Test with actual multiplayer game

---

## Examples

### Minimal Example

```python
class SimpleGridWorld:
    def __init__(self):
        self.agent_pos = [0, 0]
        self.goal_pos = [5, 5]
        self.steps = 0

    def get_state(self) -> dict:
        return {
            'agent_pos': self.agent_pos.copy(),
            'goal_pos': self.goal_pos.copy(),
            'steps': self.steps,
        }

    def set_state(self, state: dict) -> None:
        self.agent_pos = state['agent_pos'].copy()
        self.goal_pos = state['goal_pos'].copy()
        self.steps = state['steps']
```

### Complex Example (Multi-Agent)

```python
class OvercookedEnv:
    def get_state(self) -> dict:
        return {
            'agents': {
                agent_id: {
                    'position': agent.position.tolist(),
                    'orientation': agent.orientation,
                    'held_object': agent.held_object.to_dict() if agent.held_object else None,
                }
                for agent_id, agent in self.agents.items()
            },
            'world': {
                'counters': [
                    {
                        'position': c.position.tolist(),
                        'item': c.item.to_dict() if c.item else None,
                    }
                    for c in self.world.counters
                ],
                'pots': [
                    {
                        'position': p.position.tolist(),
                        'contents': [item.to_dict() for item in p.contents],
                        'cooking_time': p.cooking_time,
                    }
                    for p in self.world.pots
                ],
            },
            'game': {
                'time_remaining': self.time_remaining,
                'score': self.score,
                'orders': [order.to_dict() for order in self.orders],
            },
        }

    def set_state(self, state: dict) -> None:
        # Restore agents
        for agent_id, agent_state in state['agents'].items():
            self.agents[agent_id].position = np.array(agent_state['position'])
            self.agents[agent_id].orientation = agent_state['orientation']
            self.agents[agent_id].held_object = (
                Object.from_dict(agent_state['held_object'])
                if agent_state['held_object'] else None
            )

        # Restore world state
        self.world.counters = [
            Counter.from_dict(c) for c in state['world']['counters']
        ]
        self.world.pots = [
            Pot.from_dict(p) for p in state['world']['pots']
        ]

        # Restore game state
        self.time_remaining = state['game']['time_remaining']
        self.score = state['game']['score']
        self.orders = [Order.from_dict(o) for o in state['game']['orders']]
```

---

## FAQ

**Q: Why not use pickle?**

A: Pickle has issues:
- Not portable across Python versions
- Not human-readable for debugging
- Can fail with complex objects
- Security concerns
- Harder to validate

JSON-serializable dicts are safer, more portable, and easier to debug.

**Q: What if my state contains NumPy arrays?**

A: Convert to lists:
```python
state = {
    'position': self.position.tolist(),  # Convert numpy array to list
}
```

**Q: What about nested objects?**

A: Implement `to_dict()` and `from_dict()` methods:
```python
class Item:
    def to_dict(self) -> dict:
        return {'type': self.type, 'amount': self.amount}

    @classmethod
    def from_dict(cls, data: dict):
        return cls(type=data['type'], amount=data['amount'])
```

**Q: How often is state sync used?**

A: Only when desyncs are detected (every 300 frames by default, ~10 seconds). If your implementation is deterministic, state sync rarely happens.

**Q: What if `get_state()` is expensive?**

A: Optimize it! State sync is infrequent, but should complete in <100ms. Cache expensive computations if needed.

---

## Support

If you have questions about implementing these methods for your environment:

1. Check the examples above
2. Look at reference implementations in MUG
3. Open an issue: https://github.com/anthropics/interactive-gym/issues
4. Join discussions: https://github.com/anthropics/interactive-gym/discussions

---

**Last updated:** 2025-10-12
