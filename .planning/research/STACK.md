# Technology Stack: Deterministic State Hashing for P2P Sync Validation

**Project:** Interactive Gym P2P Multiplayer - v1.1 Sync Validation
**Researched:** 2026-01-20
**Confidence:** MEDIUM-HIGH (Core approach verified against existing codebase and official documentation)

## Executive Summary

The existing codebase already implements state hashing using Python's `hashlib.md5()` with `json.dumps(state, sort_keys=True)` executed in Pyodide. This approach is fundamentally sound and should be retained. This research focuses on hardening the implementation for production-quality desync detection.

**Key finding:** The current implementation is correct in principle but has potential edge cases around floating-point serialization and hash algorithm availability. The recommended stack builds on what exists while addressing these gaps.

---

## Current Implementation Analysis

### What Already Works

The codebase at `pyodide_multiplayer_game.js` implements state hashing:

```python
# Current approach (lines 1916-1925 in pyodide_multiplayer_game.js)
import json
import hashlib

_env_state_for_hash = env.get_state()
_json_str = json.dumps(_env_state_for_hash, sort_keys=True)
_hash = hashlib.md5(_json_str.encode()).hexdigest()[:16]
```

This is executed via `pyodide.runPythonAsync()` and returns a 16-character hex hash.

**Strengths of current approach:**
- Uses `sort_keys=True` for deterministic key ordering (correct)
- Environment's `get_state()` returns primitive-only dicts (correct)
- Hash computed in Python ensures consistency with any server-side validation
- 16-char truncated MD5 is sufficient for desync detection (not cryptographic)

### Identified Gaps

| Gap | Risk | Mitigation |
|-----|------|------------|
| `hashlib` may need explicit loading in Pyodide | Hashing silently fails | Pre-load hashlib package |
| Floating-point representation edge cases | Hash mismatch on identical states | Normalize floats before serialization |
| No fallback if `get_state()` not implemented | Runtime error | Already handled via `stateSyncSupported` flag |
| Hash computation is async Python call | Performance overhead | Consider caching strategy |

---

## Recommended Stack

### Serialization Layer

| Component | Choice | Confidence | Rationale |
|-----------|--------|------------|-----------|
| **Object Serialization** | `json.dumps(state, sort_keys=True)` (Python) | HIGH | Already in use, deterministic with `sort_keys=True` |
| **Float Normalization** | Round to fixed precision before hashing | MEDIUM | Prevents platform-specific float repr differences |
| **Encoding** | UTF-8 via `.encode()` | HIGH | Standard, deterministic |

**Why NOT to change serialization:**
- **msgpack**: Would require additional package loading in Pyodide and coordination with JavaScript side
- **CBOR**: Same concerns as msgpack, no benefit for this use case
- **Custom binary format**: Unnecessary complexity

### Hashing Layer

| Component | Choice | Confidence | Rationale |
|-----------|--------|------------|-----------|
| **Primary Hash** | SHA-256 via Python `hashlib` | HIGH | More reliably available in Pyodide than MD5 |
| **Hash Truncation** | First 16 characters (64 bits) | HIGH | Sufficient for desync detection, reduces message size |
| **Fallback Hash** | Keep MD5 as fallback | MEDIUM | Backwards compatibility |

**Why SHA-256 over MD5:**
- SHA-256 is guaranteed available in Python's hashlib without OpenSSL (via HACL* fallback in Python 3.12+)
- MD5 may require loading the `hashlib` package explicitly in Pyodide for OpenSSL algorithms
- Performance difference negligible for small state objects (< 10KB)

**Why NOT xxHash/other fast hashes:**
- Would require loading additional Python packages in Pyodide
- State objects are small (typically < 5KB), cryptographic hash overhead is negligible
- Cross-platform consistency is more important than raw speed

### JavaScript Side (if needed)

If JavaScript-side hashing is ever needed (currently not required):

| Component | Choice | Confidence | Rationale |
|-----------|--------|------------|-----------|
| **Deterministic JSON** | `json-stringify-deterministic` or `safe-stable-stringify` | HIGH | Handles key ordering correctly |
| **Hashing** | Web Crypto API `crypto.subtle.digest('SHA-256', ...)` | HIGH | Native browser API, optimal performance |
| **Alternative** | `hash-wasm` xxHash64 | MEDIUM | For high-frequency hashing if performance becomes issue |

---

## Implementation Details

### Pre-loading hashlib in Pyodide

**Problem:** OpenSSL-dependent hash algorithms (including MD5) may not be available until `hashlib` package is explicitly loaded.

**Solution:** Add to Pyodide initialization:

```javascript
// During Pyodide setup, before game starts
await pyodide.loadPackage('hashlib');
```

**Verification:** After loading, verify availability:

```python
import hashlib
print(f"MD5 available: {hasattr(hashlib, 'md5')}")
print(f"SHA256 available: {hasattr(hashlib, 'sha256')}")
```

### Float Normalization Strategy

**Problem:** Floating-point representation can vary between platforms. `repr(0.1)` might produce different string lengths on different Python builds.

**Solution:** Normalize floats to fixed precision before serialization:

```python
import json
import hashlib

def normalize_for_hash(obj):
    """Recursively normalize an object for deterministic hashing.

    Rounds floats to 10 decimal places to avoid platform-specific
    representation differences while preserving sufficient precision
    for game state comparison.
    """
    if isinstance(obj, float):
        # Round to 10 decimal places, then truncate trailing zeros
        return round(obj, 10)
    elif isinstance(obj, dict):
        return {k: normalize_for_hash(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [normalize_for_hash(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(normalize_for_hash(item) for item in obj)
    else:
        return obj

def compute_state_hash(state):
    """Compute deterministic hash of game state."""
    normalized = normalize_for_hash(state)
    json_str = json.dumps(normalized, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(json_str.encode()).hexdigest()[:16]
```

**Why 10 decimal places:**
- Sufficient for game physics (sub-pixel precision)
- Avoids accumulating floating-point noise across platforms
- Matches typical game coordinate systems

### Optimized Hash Computation

For production, the hash computation can be inlined to reduce Python call overhead:

```javascript
async computeQuickStateHash() {
    if (!this.stateSyncSupported) return null;

    const hashResult = await this.pyodide.runPythonAsync(`
import json
import hashlib

def _normalize(obj):
    if isinstance(obj, float):
        return round(obj, 10)
    elif isinstance(obj, dict):
        return {k: _normalize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_normalize(item) for item in obj]
    return obj

_state = env.get_state()
_normalized = _normalize(_state)
_json = json.dumps(_normalized, sort_keys=True, separators=(',', ':'))
hashlib.sha256(_json.encode()).hexdigest()[:16]
    `);
    return hashResult;
}
```

### Compact JSON Serialization

Use `separators=(',', ':')` to remove whitespace from JSON output:

```python
# Default (with whitespace)
json.dumps({'a': 1, 'b': 2})  # '{"a": 1, "b": 2}' (18 bytes)

# Compact (no whitespace)
json.dumps({'a': 1, 'b': 2}, separators=(',', ':'))  # '{"a":1,"b":2}' (13 bytes)
```

This reduces serialization time and ensures consistent output across platforms.

---

## Environment Requirements

### get_state() Contract

Environments must implement `get_state()` returning a JSON-serializable dict with:

| Type | Allowed | Notes |
|------|---------|-------|
| `dict` | Yes | Must have string keys |
| `list` | Yes | Ordered |
| `str` | Yes | UTF-8 encodable |
| `int` | Yes | No size limit in JSON |
| `float` | Yes | Will be normalized |
| `bool` | Yes | Serializes as `true`/`false` |
| `None` | Yes | Serializes as `null` |
| `numpy.ndarray` | **No** | Must convert to list |
| `numpy.int64` etc | **No** | Must convert to Python int/float |
| Custom objects | **No** | Must convert to primitives |

**Example compliant implementation** (from `slimevb_env.py`):

```python
def get_state(self) -> dict[str, int | float | str]:
    return {
        "t": self.t,
        "ball_x": self.game.ball.x,
        "ball_y": self.game.ball.y,
        "ball_vx": self.game.ball.vx,
        "ball_vy": self.game.ball.vy,
        # ... all primitive types
    }
```

---

## What NOT to Use

| Technology | Why Avoid |
|------------|-----------|
| `JSON.stringify()` in JavaScript | Not deterministic for object key order |
| `pickle` | Platform-dependent, not JSON-compatible |
| `numpy.save()`/`.tobytes()` | Platform-dependent byte order |
| `hash()` Python builtin | Randomized per-process (PYTHONHASHSEED) |
| CRC32 | Insufficient collision resistance for state comparison |
| Raw object identity (`id()`) | Memory address, not content-based |

---

## Performance Considerations

### Hash Computation Overhead

| State Size | JSON Serialize | SHA-256 Hash | Total | Notes |
|------------|---------------|--------------|-------|-------|
| 1 KB | ~0.1 ms | ~0.1 ms | ~0.2 ms | Typical small game |
| 5 KB | ~0.3 ms | ~0.2 ms | ~0.5 ms | Complex game state |
| 20 KB | ~1 ms | ~0.5 ms | ~1.5 ms | Large state (consider optimization) |

At 30 FPS with hash every 30 frames (1 Hz sync):
- Overhead: 0.5 ms per second = 0.05% of frame budget
- Acceptable for desync detection

### When to Optimize

If hash computation becomes a bottleneck (> 2ms):

1. **Reduce sync frequency**: Hash every 60 frames instead of 30
2. **Partial state hashing**: Hash only critical state fields
3. **Incremental hashing**: Track changed fields, hash only deltas
4. **Move to JavaScript**: Use Web Crypto API (native speed)

---

## Integration with Existing Code

### Required Changes

1. **Pre-load hashlib** in Pyodide initialization
2. **Add float normalization** to hash computation
3. **Switch to SHA-256** for better Pyodide compatibility
4. **Add compact JSON separators** for consistency

### Backwards Compatibility

The hash algorithm change (MD5 to SHA-256) means:
- Old and new clients will compute different hashes for same state
- Clients must agree on hash algorithm at connection time
- Recommend version field in P2P handshake

### Configuration

```python
# Suggested configuration additions
class SyncValidationConfig:
    hash_algorithm: str = 'sha256'  # 'sha256' or 'md5'
    hash_truncate_length: int = 16  # characters
    float_precision: int = 10       # decimal places
    sync_interval_frames: int = 30  # frames between hash broadcasts
```

---

## Sources

### HIGH Confidence (Official Documentation)

- [Pyodide Python compatibility](https://pyodide.org/en/stable/usage/wasm-constraints.html) - hashlib constraints
- [Python hashlib documentation](https://docs.python.org/3/library/hashlib.html) - Algorithm availability
- [Python json documentation](https://docs.python.org/3/library/json.html) - `sort_keys` behavior
- [MDN SubtleCrypto.digest()](https://developer.mozilla.org/en-US/docs/Web/API/SubtleCrypto/digest) - Web Crypto API

### MEDIUM Confidence (Technical Analysis)

- [Exploring SHA-256 Performance on the Browser](https://medium.com/@ronantech/exploring-sha-256-performance-on-the-browser-browser-apis-javascript-libraries-wasm-webgpu-9d9e8e681c81) - Browser hashing performance
- [Floating Point Determinism (Gaffer On Games)](https://gafferongames.com/post/floating_point_determinism/) - Cross-platform float challenges
- [Preparing your game for deterministic netcode](https://yal.cc/preparing-your-game-for-deterministic-netcode/) - Desync detection patterns

### LOW Confidence (Community Sources)

- [json-stringify-deterministic npm](https://www.npmjs.com/package/json-stringify-deterministic) - JavaScript deterministic JSON
- [safe-stable-stringify GitHub](https://github.com/BridgeAR/safe-stable-stringify) - Alternative JS JSON library
- [hash-wasm GitHub](https://github.com/Daninet/hash-wasm) - Fast WASM hashing (if needed)
- [xxhash-wasm npm](https://www.npmjs.com/package/xxhash-wasm) - Fast non-cryptographic hash (if needed)

---

## Open Questions

1. **Pyodide hashlib version**: Verify actual algorithm availability in the Pyodide version used by the project
2. **Float precision requirements**: Validate 10 decimal places is sufficient for all environment types
3. **Large state handling**: Profile hash computation for environments with larger state dicts (> 20KB)
4. **Hash algorithm negotiation**: Design protocol for clients to agree on hash algorithm during P2P handshake

---

*Stack research for sync validation: 2026-01-20*
