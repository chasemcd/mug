# Participants & Data Collection

MUG tracks each participant by a **subject ID** in the URL, runs them through the [Stager](stager.md) scene-by-scene, and writes their data to a per-experiment folder on disk. This page covers the pieces you need to run a study end-to-end: how IDs are assigned, what's recorded automatically, where it lands on disk, and how to generate completion codes for panel platforms like Prolific or MTurk.

## The subject ID is the URL path

A participant's identity is the path component of the URL they land on — not a query parameter.

| URL a participant visits | Resulting subject ID |
|---|---|
| `https://your-server.com/` | Auto-generated UUID, 302-redirected to `/<uuid>` |
| `https://your-server.com/abc-123` | `abc-123` (verbatim) |
| `https://your-server.com/prolific_5f2e1a` | `prolific_5f2e1a` |

When a browser hits the root route, MUG generates a UUID and redirects:

```python
# mug/server/app.py
@app.route("/")
def index(*args):
    """If no subject ID provided, generate a UUID and re-route them."""
    subject_id = str(uuid.uuid4())
    return flask.redirect(flask.url_for("user_index", subject_id=subject_id))
```

If the participant visits `/<something>` directly, `<something>` is used as-is. That means panel platforms can construct the URL themselves and pass whatever identifier they like:

- **Prolific**: `https://your-server.com/{{%PROLIFIC_PID%}}`
- **MTurk**: `https://your-server.com/{{workerId}}` (via a redirect from the HIT page)
- **Custom links**: any URL-safe string works

!!! warning "Query parameters are not parsed"

    MUG does not read URL query parameters. `https://your-server.com/?prolific_pid=abc` will **not** set `abc` as the subject ID — it will generate a fresh UUID and discard the query string. If you need to carry extra metadata, put it in the path or stash it in `mugGlobals` (see below).

### Subject-ID guarantees

Several things happen automatically once a subject ID exists:

- **Duplicate-tab rejection.** If a participant already has an active socket connection and opens a second tab with the same ID, the second tab is rejected with a `duplicate_session` error. Each subject ID owns exactly one active session at a time.
- **Completion lockout.** When a participant reaches the end of their Stager, their ID is added to `PROCESSED_SUBJECT_NAMES`. Re-visiting the URL returns *"You have already completed the experiment with this ID!"* — participants cannot replay a completed session.
- **Session restoration.** If a participant disconnects mid-experiment, their `ParticipantSession` (which holds `stager_state`, `mug_globals`, and the last scene ID) persists on the server. When they re-open the same URL, MUG restores their stager at the scene they left off on and replays a `session_restored` event to the client.

!!! note "Session restoration restarts the current scene"

    Restoring a session brings the participant back to the **start** of the scene they were on, not to their exact position within it. `GymScene`s in particular are not resumed mid-episode — gameplay restarts from scratch for that scene. Any data streamed to disk before the disconnect (e.g. completed `_ep{N}.csv` files) is preserved, but the scene itself replays from its first episode.

## Participant lifecycle

The server tracks two layers of state per participant:

- A **`ParticipantSession`** dataclass holding long-lived context (subject ID, stager state, mug globals, socket ID, connection flag, timestamps).
- A **`ParticipantState`** enum for in-game lifecycle (`IDLE`, `IN_WAITROOM`, `IN_GAME`, `GAME_ENDED`), with validated transitions in `mug/server/participant_state.py`.

The flow from a fresh browser load through scene completion is:

1. **Browser GETs `/<subject_id>`.** The server creates a `ParticipantSession`, builds a fresh `Stager` instance, and returns `index.html` with the subject ID baked in.
2. **Client opens a socket and emits `register_subject`.** The server ties the socket ID to the subject, starts the stager, and activates the first scene.
3. **Scene activation writes metadata.** If the active scene has `should_export_metadata=True`, `{subject_id}_metadata.json` is written immediately.
4. **The participant interacts with the scene.** For `GymScene`s, the client streams `emit_episode_data` at each episode boundary and the server writes `{subject_id}_ep{N}.csv`.
5. **Client emits `advance_scene`.** The stager deactivates the current scene and activates the next one. Metadata for the new scene is exported, and the loop repeats from step 3.
6. **Terminal scene reached.** On `EndScene` or `CompletionCodeScene`, the final metadata (including the completion code, if any) is written and the subject ID is added to `PROCESSED_SUBJECT_NAMES`, preventing replays.

Concurrent participants are isolated by keying every server-side data structure on `subject_id`: `STAGERS[subject_id]`, `PARTICIPANT_SESSIONS[subject_id]`, `SUBJECTS[subject_id]` (a per-participant `threading.Lock`), and so on. Two participants can never collide with each other's scene state.

## What gets recorded automatically

MUG writes five kinds of files to disk. All are keyed by `subject_id` and namespaced by `experiment_id` and `scene_id`:

| File | Written when | Contents |
|---|---|---|
| `{subject_id}_metadata.json` | On scene activation, for scenes where `should_export_metadata=True` | Scene ID, scene type, timestamp, `element_ids`, form answers, `experiment_config`, any subclass-added fields (like `completion_code`) |
| `{subject_id}_ep{N}.csv` | At the end of every episode of a `GymScene` | Observations, actions, rewards, `terminateds`, `truncateds`, `episode_num`, timestep `t` — nested dicts flattened with dotted column names |
| `{subject_id}_globals.json` | Alongside every episode CSV | Latest snapshot of client-side `mugGlobals` (defaults to `{"subjectName": subject_id}`, plus whatever you've added) |
| `{subject_id}.csv` | Only if a scene sends its data in one post-hoc blob instead of streaming | Same shape as `_ep{N}.csv`, but full game. **In normal operation this file is never written** — episode streaming is preferred because end-of-scene uploads fail on large payloads |
| `{subject_id}_multiplayer_metrics.json` | On `emit_multiplayer_metrics` | P2P connection type/health, frame hashes, desync events, input delivery stats, rollback metrics |

### Episode streaming, not end-of-scene uploads

When a `GymScene` runs, every time an episode terminates, the client posts the buffered data via `emit_episode_data` and the server writes `{subject_id}_ep{N}.csv` immediately:

```python
# mug/server/app.py — simplified
@socketio.on("emit_episode_data")
def receive_episode_data(data):
    ...
    filename = f"data/{CONFIG.experiment_id}/{data['scene_id']}/{subject_id}_ep{episode_num}.csv"
    df.to_csv(filename, index=False)
```

This is deliberate. A long-running scene can generate hundreds of thousands of rows of observation data, and a single end-of-scene upload would frequently fail to transfer from the client back to the server. Per-episode streaming keeps each payload small and gives you partial results even if a participant drops mid-scene.

The end-of-scene handler (`emit_remote_game_data`) still exists, but it no-ops when it sees the data was already streamed:

```python
# Check if there's any data to save (may be empty if data was sent per-episode)
if not decoded_data or not decoded_data.get("t"):
    logger.info(f"No final data to save for scene {data.get('scene_id')} (data was sent per-episode)")
    return
```

### mugGlobals: extensible client-side state

`mugGlobals` is a dict that lives on the client across all scenes and is continuously synced to the server via `sync_globals` socket events. It's a good place for data that needs to survive scene transitions but doesn't fit neatly into a scene's built-in metadata — survey answers, condition assignments, panel IDs you read from `window.location`, and so on.

Anything written to `mugGlobals` ends up in `{subject_id}_globals.json` next to the episode CSVs. Every episode's save overwrites the file with the latest snapshot, so you always get the final value.

## Directory layout

All files land under `data/{experiment_id}/{scene_id}/{subject_id}*`. A typical Overcooked-style experiment with a start scene, tutorial, two gameplay scenes, a feedback scene, and a completion-code scene looks like this:

```
data/
└── overcooked_hai/
    ├── overcooked_start_scene/
    │   └── abc123_metadata.json
    ├── overcooked_tutorial/
    │   ├── abc123_metadata.json
    │   ├── abc123_ep0.csv
    │   └── abc123_globals.json
    ├── cramped_room_sp_0/
    │   ├── abc123_metadata.json
    │   ├── abc123_ep0.csv
    │   ├── abc123_ep1.csv
    │   ├── abc123_ep2.csv
    │   └── abc123_globals.json
    ├── cramped_room_ibc_0/
    │   ├── abc123_metadata.json
    │   ├── abc123_ep0.csv
    │   ├── abc123_ep1.csv
    │   └── abc123_globals.json
    ├── feedback_scene/
    │   └── abc123_metadata.json
    └── end_completion_code_scene/
        └── abc123_metadata.json
```

When `def123` finishes the same experiment, their files land next to `abc123`'s inside each scene's subdirectory — one folder per scene, one file per participant per data type.

## Configuring collection

Two knobs control data collection:

**Experiment-level**, on `ExperimentConfig`:

```python
config = (
    experiment_config.ExperimentConfig()
    .experiment(
        stager=stager.Stager(scenes=[...]),
        experiment_id="overcooked_hai",   # → data/overcooked_hai/...
        save_experiment_data=True,         # master switch, default True
    )
)
```

**Per-scene**, on any `Scene`:

```python
start_scene = (
    static_scene.StartScene()
    .scene(
        scene_id="overcooked_start_scene",
        should_export_metadata=True,      # write metadata JSON for this scene
    )
    .display(scene_header="Welcome", ...)
)
```

Scenes that capture form input (`TextBox`, `OptionBoxes`, `ScalesAndTextBox`, `CompletionCodeScene`) typically set `should_export_metadata=True` — without it, the participant's answers are collected in the browser but never persisted.

!!! note "Things that aren't configurable"

    - The output root is hardcoded to `data/` relative to the process's working directory. If you need files in a different location, run the server from a different CWD or `ln -s` the directory.
    - There is no per-scene "extra fields to capture" hook beyond what's serialized into `scene_metadata` automatically. To attach custom data to a scene, subclass the scene and extend its `scene_metadata` property, or write to `mugGlobals`.
    - Data is filesystem-only. There is no built-in database, S3, or cloud integration.

## Completion codes for Prolific, MTurk, and similar panels

Panel platforms usually require each participant to submit a unique code at the end of the task so the platform can reconcile who should be paid. MUG ships `CompletionCodeScene` for exactly this:

```python
from mug.scenes import static_scene

end_scene = (
    static_scene.CompletionCodeScene()
    .scene(
        scene_id="end_completion_code_scene",
        should_export_metadata=True,
    )
    .display(
        scene_header="Thanks for participating!",
        scene_body="Please copy your completion code and return to Prolific.",
    )
)
```

On scene build, it generates a fresh `uuid.uuid4()`, renders it in a styled HTML block for the participant to copy, and attaches it to the scene's metadata:

```python
# mug/scenes/static_scene.py
@property
def scene_metadata(self) -> dict:
    metadata = super().scene_metadata
    metadata["completion_code"] = self.completion_code
    return metadata
```

After the experiment runs, you can reconcile the panel's submitted codes against your actual participants by loading every `end_completion_code_scene/{subject_id}_metadata.json`:

```python
import glob, json
import pandas as pd

rows = []
for path in glob.glob("data/overcooked_hai/end_completion_code_scene/*_metadata.json"):
    meta = json.load(open(path))
    subject_id = path.split("/")[-1].removesuffix("_metadata.json")
    rows.append({"subject_id": subject_id, "completion_code": meta["completion_code"]})

codes = pd.DataFrame(rows)
# Left-join against Prolific's CSV export on "completion_code"
```

Any participant who submits a code that isn't in `codes.completion_code.values` didn't actually finish your experiment — reject or refund accordingly.

## Loading data back for analysis

MUG does not ship a loader module — the data is plain CSV and JSON, and the directory layout is designed so `glob` + `pandas` is enough. A minimal analysis starter:

```python
import glob, json
import pandas as pd

EXP = "data/overcooked_hai"

# 1. All episode data, tagged with scene and participant
ep_files = glob.glob(f"{EXP}/*/*_ep*.csv")
episodes = []
for path in ep_files:
    scene_id = path.split("/")[-2]
    fname = path.split("/")[-1]
    subject_id, ep_part = fname.rsplit("_ep", 1)
    episode_num = int(ep_part.removesuffix(".csv"))
    df = pd.read_csv(path)
    df["subject_id"] = subject_id
    df["scene_id"] = scene_id
    df["episode_num"] = episode_num
    episodes.append(df)
all_episodes = pd.concat(episodes, ignore_index=True)

# 2. All scene metadata (form answers, completion codes, timings)
meta_files = glob.glob(f"{EXP}/*/*_metadata.json")
metadata = []
for path in meta_files:
    scene_id = path.split("/")[-2]
    subject_id = path.split("/")[-1].removesuffix("_metadata.json")
    meta = json.load(open(path))
    metadata.append({"subject_id": subject_id, "scene_id": scene_id, **meta})
all_metadata = pd.DataFrame(metadata)
```

A few details worth knowing when you start slicing:

- Observation and action columns are **already flattened** with `flatten_dict` using dot notation. A nested obs like `{"player_0": {"position": [1, 2]}}` becomes columns like `player_0.position.0` and `player_0.position.1`. No need to `json.loads` anything on load.
- Each episode CSV is padded so all columns have equal length; timesteps that don't have a given key will be `None`/`NaN`.
- Scene metadata JSONs include the full `experiment_config` dict passed into `.scene()`, so condition assignments, layout IDs, and similar bookkeeping travel with the data.

## Related reading

- [Scenes](scenes.md) — how to build and configure the scenes whose data ends up on disk
- [Stager](stager.md) — how scenes are sequenced for each participant
- [Participant Exclusion](../participant-exclusion.md) — entry screening and mid-experiment ejection (separate from data collection)
