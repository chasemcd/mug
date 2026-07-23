# Operate your study from the command line

*For study authors and operators. One command, `mug`, publishes a study, deploys
it, exports its data, replays a run, and drains a batch of background work. Each
verb reaches the runtime the same way a participant's browser does -- through the
one command spine -- so the command line is never a second, different path into
your study.*

> Status: **the command line is built.** `mug publish`, `mug deploy`, `mug
> export`, `mug replay`, and `mug simulate` run today. `mug stop` reports a known
> gap (see below). The tool adds no dependency of its own and holds no study
> logic; it wires your study to the runtime.

---

## Where it runs against

Every verb opens the same store your deployment opens:

- Set `MUG_PG_DSN` and the command line runs against your Postgres study, exactly
  as the deployed server does.
- Leave it unset and it runs against an in-memory store -- handy for a quick local
  try, but it keeps nothing between runs.

You never pass a database handle; the tool resolves it from the environment.

---

## The verbs

```text
mug publish  ENVELOPE          publish a compiled study version
mug deploy   ENVELOPE          deploy a published study version
mug export   OUT               export the whole dataset to a folder
mug replay   OUT --interaction I --stream S ...   assemble a run's replay bundle
mug simulate --handler M:F     drain the durable job queue
mug stop                       (not yet available -- see the gap below)
```

### Publish and deploy

Your study toolchain compiles a study into one prepared command -- a *command
envelope*, the same bytes a client posts to the server. You hand that file to the
command line and it drives it through the runtime:

```bash
mug publish ./build/publish.json
# publish: accepted (created) -- positions {'stream_...': 1}
```

```bash
mug deploy ./build/deploy.json
# deploy: accepted (created) -- positions {'stream_...': 1}
```

The command line reports the durable receipt the runtime returned: whether the
command was accepted, and where it landed. A publish that is not a release
candidate, or a deploy whose bindings do not satisfy the requirement, comes back
rejected with a reason and changes nothing.

### Export

When your study has run, pull the whole dataset down:

```bash
mug export ./data
# export: wrote 3 bundle(s) [events, trajectories, preferences] to data
```

You get one newline-delimited-JSON file per kind of data you collected, plus a
`manifest.json` that names each file, its lineage, and its row schema. The export
reads the working tree's git commit and records it, so every file states the code
state that produced it. When the store holds exactly one published version, the
command line finds it for you; when it holds several, pass
`--study-version FILE`. Add `--kind events` (repeatable) to export only some
kinds.

The export is safe to share: every row is a canonical event that points at its
data by a digest, never a raw form answer, observation, or secret.

### Replay

Assemble a replay bundle for one recorded run:

```bash
mug replay ./out --interaction interaction_… --stream stream_…
# replay: assembled 4 event(s) from 1 stream(s) to out
```

The bundle names every artifact by digest and writes its manifest to the folder,
so a reviewer can validate the recorded run byte for byte.

### Simulate

Drain a batch of durable background work -- for example, running episodes for a
simulated study. The work itself is your study's, so you name the handler that
does it as `module:function`, and the command line imports and drives it over the
durable queue:

```bash
mug simulate --handler my_study.jobs:run_one --workers 4
# simulate: drained 12 job(s)
```

A restart rediscovers queued work from the store, so a simulate that stops halfway
picks up where it left off. The command line composes the fenced job runner and
the worker pool; you provide only the handler.

---

## The one gap: `mug stop`

`mug stop` is **not available yet**. The platform models a deployment as an
append-only chain of immutable revisions; it has no stop or teardown command. To
change what is served, deploy a new revision. The command line reports this
plainly rather than pretend a stop happened:

```bash
mug stop
# error: mug stop is not available: the platform has no stop command yet ...
```

When the platform grows a stop command, the verb wires to it.

---

## Under the hood (you do not write this)

For completeness: `mug publish` and `mug deploy` call the exact
`dispatch_command` path the HTTP server calls -- one route table, one context
mint, one handler -- so a command from the command line and a command from a
client reach a family the same way. `mug export`, `mug replay`, and `mug simulate`
call the same export, replay, and job runtimes the platform calls. There is no
second code path, so the command line can never drift from the server. This
section is here only so you know why the two always agree.
