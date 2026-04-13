# Installation

When building experiments, always install MUG with the server option:

```bash
pip install multi-user-gymnasium[server]
```


!!! note

    The base installation (`pip install multi-user-gymnasium`) without `[server]` only installs the minimal core dependencies (`gymnasium` and `numpy`). This minimal version is automatically installed by Pyodide in the participant's browser when running client-side experiments. **As an experiment developer, you should always use the `[server]` option.**


## Development Installation

To contribute to MUG or modify the source code, clone the repository and install in editable mode:

```bash
git clone https://github.com/chasemcd/mug.git
cd mug
pip install -e .
```

For development with server dependencies:

```bash
pip install -e ".[server]"
```



### Important: Eventlet Monkey Patching

All experiment files must include eventlet monkey patching at the very top, before any other imports:

```python
from __future__ import annotations

import eventlet

eventlet.monkey_patch()

# Now import MUG and other modules
from mug.server import app
from mug.scenes import stager, static_scene, gym_scene
# ... rest of your imports
```

This monkey patching must occur before importing any other modules to ensure proper asynchronous networking behavior. Without it, your experiments may not work correctly.
