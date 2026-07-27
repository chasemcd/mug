# Deployment topology: what may run in more than one process

| Field | Value |
| --- | --- |
| Status | Current as of 2026-07-26 |
| Applies to | The native runtime (`mug/`), not the legacy runtime |
| Pinned by | `tests/unit/gateway/test_gateway_topology.py` |

A study runs on one process by default, and that is the shape everything here has
been tested in. This note says what changes when a deployment runs several, because
the answer is not the same for every part: some parts are safe as they are, one part
is safe only once a secret is shared, and two parts do not work across processes at
all.

Read it before adding a second replica. Nothing below is a limit of the design; the
parts that do not replicate simply have not been given the shared state they would
need, and each says what that state would be.

## The three variables a multi-process deployment sets

| Variable | What it shares | What breaks without it |
| --- | --- | --- |
| `MUG_PG_DSN` | The ledger, the aggregates, the artifacts | Every process keeps its own in-memory store, so nothing is shared at all |
| `MUG_GATEWAY_SECRET` | The seed of the content-addressed command identifiers | A client retry that lands on another process is refused with `command.idempotency_conflict` instead of replaying |
| `MUG_RETURN_LINK_KEY` | The key that signs a return link | A returning participant whose reconnection lands on another process cannot resume |

All three take one long random value shared by every process. The first two are the
ones a deployment forgets; the third was already documented with the return links.

### Why the gateway secret is not optional

A command's identity is content-addressed: the gateway derives the command, receipt,
error, and event identifiers from the client's idempotency key and the payload, so an
identical retry re-mints identical identifiers and the store replays it rather than
committing twice. The derivation is seeded with a per-gateway secret, which keeps a
derived public handle unguessable.

That secret defaults to a fresh one per process. With two processes and two secrets,
one retried envelope derives two different command identities, and the store then
sees one idempotency key carrying two different contents -- which it refuses. The
retry fails, and the fault is the deployment's rather than the client's.

`tests/unit/gateway/test_gateway_topology.py` pins both directions: with a shared
secret the second process's commit replays the first receipt and the aggregate stays
at revision 1; without one the second commit raises `command.idempotency_conflict`.

The producer epoch is deliberately **not** shared. Each process draws its own, so two
processes never claim positions in one sequence they cannot coordinate.

## What replicates safely today

- **The command spine and the HTTP edge.** Every write goes through the store's own
  transaction, revision guard, and fencing. Two processes committing to one aggregate
  resolve through the revision guard exactly as two workers do.
- **Durable jobs and workers.** N worker processes over one store are safe by
  construction: a claim installs a strictly greater fencing generation on the job's
  stream, so a worker whose lease was taken over cannot commit its result, and the
  queue each process holds is only an index, rebuilt from the store at start. A worker
  that goes away mid-flight is taken over by another once its lease expires -- across
  processes, not only within one (`mug/workers.py`).
- **Admission.** Each process bounds itself. `/readyz` answers 503 once a process is
  at its session bound, which is what tells a load balancer to stop adding to it. The
  bound is therefore per replica, and the deployment's capacity is the sum.
- **Telemetry.** Each process keeps its own counters and renders its own `/metrics`.
  A scraper aggregates across replicas; nothing needs to be shared.
- **Form and game activities that touch only one participant.** A visit's state is in
  the store, and a reconnection resumes it from there.

## Peer-to-peer across processes

Two runtimes used to rendezvous participants with each other **in process memory**,
so two participants on two replicas never met. They now share a waiting room.

`MUG_NODE_ID` names this process. With it set, `mug/interactions/rendezvous.py` puts
the waiting list and the room registry in the shared store: a match is made from
everyone who is waiting rather than from everyone this process happens to hold, and
the store's own revision check is the fence, so a group is claimed by exactly one
process however many are polling. `mug/interactions/bus.py` carries a message from
one process to another, over the shared store by default and over a broker if the
deployment supplies one (`NodeBus` is two methods wide).

**The process that claims a group runs it, and every other process relays.** The
claiming process hosts the mesh engines, or holds the room core the browsers signal
through. A process that holds another member's socket keeps no state about the run:
it passes what its participant did to the owner and writes back what the owner
sends. So there is one authority per room and no agreement to reach.

- **Peer-to-peer matchmaking.** `NodeMeshMatchmaker` (`mug/participant.py`) is the
  cross-process mount; `MeshMatchmaker` and `PooledMeshMatchmaker` are unchanged and
  are what a single process still uses. A remote seat's held action and its frames
  each cross the bus once.
- **The browser peer-to-peer coordinator.** `P2PCoordinator` takes a `node`. The
  browsers still talk to each other directly once they are connected, so only the
  negotiation crosses: the assignment, the signals, the readiness reports, the
  completion claims, the capture, and the ICE redemption. An ICE grant is redeemed
  on the process that issued it, because it is one-use and bound to one room.

**What it costs.** Every message the store-backed bus carries is a durable write.
That is honest for browser signalling, which is a few dozen messages per room, and
it is slow for a stepped game, which is one hop per input change and one per frame
per remote seat. A deployment that runs `mesh_game` across processes should pass a
broker-backed `NodeBus`; the shipped one is the floor, not the ceiling.

**What still does not replicate.** A ticket names the process that holds its socket,
and a process that dies leaves its tickets behind. They expire (five minutes), so a
dead node's participants fall out of the waiting room rather than poisoning it, but
a room whose **owner** dies mid-run is not taken over by another process: its members
are aborted and re-pooled, exactly as they are when a peer disconnects. Taking over a
live room would need the room core's state in the store, which it is not.

Two smaller ones in the same family:

- **The demo's launch ticket** (`app.state.launch_ticket`) is provisioned per process,
  so each replica exposes a different one. A real study provisions tickets through
  `mug/launch.py` against the shared store instead.
- **The agent game's collected replay bundles** (`app.state.replay_bundles`) are an
  in-process list for a watcher to read. The bundles themselves are in the artifact
  store; only the convenience list is local.

## The recommended shapes

1. **One process.** Everything works. Leave `MUG_NODE_ID` unset: matching stays in
   memory and no bus message is ever written. This is what a single study should run
   unless it has a reason not to.
2. **One realtime process, N worker processes.** Set `MUG_PG_DSN`,
   `MUG_RETURN_LINK_KEY`, and `MUG_GATEWAY_SECRET`. The workers drain the durable
   queue over the shared store and the realtime process keeps the sessions.
3. **N realtime processes.** Set those three and give each process a distinct
   `MUG_NODE_ID` -- the pod name serves. Two participants on two replicas are then
   matched with each other. A study with a stepped `mesh_game` should pass a
   broker-backed `NodeBus` as well, because the store-backed one writes a record per
   frame.

## What an operator watches

| Endpoint | Answers | Read by |
| --- | --- | --- |
| `/healthz` | Is the process alive? | A supervisor deciding whether to restart |
| `/readyz` | Should this process be sent more participants? | A load balancer; 503 once at the session bound |
| `/metrics` | Prometheus text: commands by outcome and category, open sessions, refusals by category | A scraper |

None of the three is authenticated, and none should be reachable from outside the
deployment: the readiness numbers say how loaded a study is. The series are labelled
by command, outcome, and error category only -- never by a participant or a
principal -- so a scrape cannot leak who was in the study.

## What is still open

- Taking over a live room whose owning process died. Its members are aborted and
  re-pooled today, which is correct and not graceful.
- The store-backed bus writes one durable record per message, which bounds how fast a
  stepped game can run across processes.
- `/readyz` reports capacity, not store reachability. A process whose database has
  gone away still answers ready until a command fails. A store probe would need a
  cheap round trip the `Store` protocol does not have yet.
- No process draining on shutdown: a replaced replica drops its live sessions, and
  each participant reconnects and resumes from their cursor. That is correct but not
  graceful.
