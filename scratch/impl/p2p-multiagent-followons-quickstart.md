# P2P and multi-agent follow-ons

*For a study author who runs multiplayer or multi-agent games. The peer-to-peer
mesh already ran a real-time parallel game across peers. These follow-ons extend
that same spine: a turn-based multi-agent game over the mesh, a real wire between
peers and the signalling bootstrap that opens it, a bot that plays across the
mesh, a diverged peer that repairs itself, a server-hosted game that seats bots
beside people, and many games forming at once. Every one is runtime over the
frozen records -- no new schema, no vendor SDK, no socket in your code.*

> Status: **runtime built; server mounts built.** The P2P and multi-agent
> modules, `DataChannelLink`, and the transport-neutral bootstrap in
> `mug/game/signalling.py` and `mug/game/signal_relay.py` are proven in-process.
> `ServerGameSpec` and `PooledMeshMatchmaker` are mounted on the websocket path as
> `server_game` and `concurrent_mesh`. The authenticated browser P2P **transport**
> is mounted as `browser_p2p` (see section 7). Browser P2P **gameplay** is not
> done: the transport hands over open data channels, and no browser executor yet
> plays a game over them.

---

## 1. A turn-based multi-agent game over the mesh

The mesh already ran a *parallel* multi-agent env (every agent acts each frame). For
a *turn-based* env (one agent acts per turn), wrap it in `AecReplica` instead of
`MultiAgentReplica`. It presents the same three-callable seam the peer engine reads,
so nothing else changes:

```python
from mug.game.multiagent import AecReplica

replica = AecReplica(
    make_my_aec_env,                 # duck-types the PettingZoo AEC API
    actor_agents={actor_id: agent_id, ...},
    seed=seed,
)
# replica.step / replica.snapshot / replica.restore feed a PeerEngine, as before.
```

One mesh frame is one turn of the selected agent. The snapshot covers the
environment and both global generators, so a rollback replay is exact.

---

## 2. A real wire between peers

The server-hosted mesh relays every packet in one process. To move each peer engine
to its own process (or the browser) over a real data channel, drive it with a
`PeerNode` over a `PeerLink`:

```python
from mug.game.wire import PeerNode

node = PeerNode(engine=my_engine, actor_id=actor_id, links=links, action=held_action)
node.start()
await node.tick()          # each frame: drain, submit, advance, gossip
...
node.finalize()            # once node.ready_to_finalize()
```

A `PeerLink` is any duplex channel with `send` / `recv` of one json-able message --
a WebRTC data channel in production. The codec (`encode_input` / `decode` …) turns
each engine packet into a message and back. Now the round trip is real, so the
engine predicts and rolls back on its own, exactly as it was built to.

---

## 3. A bot that plays across the mesh

A bot seat has no human and no engine. Exactly one peer -- the highest eligible peer,
which the `P2PBotAuthority` record names -- produces the bot's action and broadcasts
it; every other peer applies it. That single source keeps the bot deterministic
across the mesh. Bind it with a `BotSeat`:

```python
from mug.game.bot_authority import BotSeat

bot = BotSeat(bot_actor_id=bot_id, authority_actor_id=authority_id, controller=policy)

if bot.holds_authority(my_actor_id):     # only the authority peer decides
    packet = engine.submit_for(bot_id, bot.decide(observation))
    broadcast(packet)                    # every other peer receives it over the mesh
```

---

## 4. A diverged peer that repairs itself

If a replica draws from state a snapshot does not cover, its trajectory splits and
the mesh records the frames `disputed`. Repair transfers a snapshot from a trusted
peer to the diverged one, which re-derives forward and reconverges:

```python
from mug.game.desync_repair import resync_peer

if diverged.disputed_frames():
    resync_peer(diverged=diverged, authority=trusted, target_frame=diverged.disputed_frames()[0])
    # keep advancing the diverged engine; it re-derives the agreed trajectory.
```

---

## 5. A server-hosted game that seats bots beside people

Not every game is peer-to-peer. For a server-authoritative game with one
authoritative environment, use `ServerSeatSession` -- the server counterpart of the
mesh session. It seats a bot controller beside a human input over the one seat seam,
steps one shared timeline, and reports one summary per seat:

```python
from mug.game.server_session import ServerSeat, ServerSeatSession

session = ServerSeatSession(
    seats=[
        ServerSeat("seat-1", human_actor, "player_0", human_input, kind="human"),
        ServerSeat("seat-2", bot_actor, "player_1", bot_policy, kind="bot"),
    ],
    env=my_multiseat_env,
    channel_key="server-game",
    interaction_id=interaction_id, episode_id=episode_id, now=clock,
)
episode = await session.run()            # one authoritative timeline, per-seat summaries
```

---

## 6. Many games forming at once

The single formation service forms one mesh at a time. `MeshFormationPool` forms
every group that can form in one sweep, across games:

```python
from mug.interactions.pool import GroupConfig, MeshFormationPool

pool = MeshFormationPool(new_id=mint, now=clock, study_version=version)
pool.register(GroupConfig("overcooked", "p2p-overcooked", 2, strategy))
pool.register(GroupConfig("racer", "p2p-racer", 3, strategy))
for enrollment in waiting:
    pool.submit(group_key=enrollment.game, enrollment_id=enrollment.id, visit_id=enrollment.visit)

formed = pool.poll_all()    # every mesh that can form this sweep, across both games
```

---

## 7. An authenticated browser mesh

For browsers that will hold the peer connections themselves, mount the browser
P2P transport. The server forms the room, relays the signals, holds the start
barrier, and reconciles the capture; the browsers hold the data channels:

```python
from mug.app import build_demo_app
from mug.participant_p2p_types import BrowserP2PConfig

app = build_demo_app(
    browser_p2p=BrowserP2PConfig(
        channel_key="p2p-browser",
        size=2,
        verify_capture=my_verifier,   # payload -> VerifiedCapture
    ),
    require_launch=True,              # the mount needs a durable enrollment
)
```

Each browser is told only its own room handle, its own peer handle, the other
peers with their offer roles, and a one-use ICE grant. It is never told a
principal, actor, membership, lease, or secret, and it cannot name its own source
on a signal: the server stamps that.

To supply TURN, pass an `IceServerConfig` with a `TurnSecret`. The secret stays in
the server process; the browser redeems its grant at the configured same-origin
path and gets a short-lived credential with `Cache-Control: no-store`.

**What this does not do yet:** it hands your executor open data channels. Running
a deterministic game over them in the browser is the next piece of work.

---

## Runtime adapters and current application mounts

The transport-neutral adapters and current server mounts are built. None needed
a record change:

- **A WebRTC data channel behind the wire seam.** `mug.game.wire.DataChannelLink`
  adapts an `aiortc` (or browser-bridged) `RTCDataChannel` to the `PeerLink` seam, so
  a `PeerNode` drives a real peer process. The adapter duck-types the channel, so no
  vendor SDK is imported:

  ```python
  from mug.game.wire import DataChannelLink, PeerNode

  link = DataChannelLink(rtc_data_channel)   # any channel with send + on(event, ...)
  node = PeerNode(engine=engine, actor_id=actor_id, links={peer: link}, action=held)
  ```

- **A signalling bootstrap before the data channel.**
  `mug.game.signalling.establish_data_channel` exchanges the offer, answer, and
  trickled ICE through an injected pairwise signal channel, then returns the open
  `DataChannelLink`. `open_peer_links` does this concurrently for a full mesh.
  `mug.game.signal_relay.SignalRelay` supplies the frozen-room in-process relay
  used by the proof.

- **A server-hosted game on the websocket path.** Pass a `ServerGameSpec` to
  `build_demo_app(server_game=...)` (or `build_app_from_env`): the participant plays
  one seat, the study's `ServerBotSeat` bots play the rest of one authoritative env,
  and the run is captured on the visit exactly as any other game.

- **Concurrent peer rooms on the websocket path.** Pass `concurrent_mesh=True` beside
  a `mesh_game` to mount `MeshFormationPool`: many rooms of that game form and run at
  once, rather than one mesh at a time.

- **The authenticated browser P2P transport on the websocket path.** Pass a
  `BrowserP2PConfig` to `build_demo_app(browser_p2p=...)`, as section 7 shows. It
  mounts the room core, the signalling relay, the start barrier, capture
  reconciliation, and the one-use ICE endpoint.

The transport vertical is complete and mounted: authenticated routing, lease and
membership-generation fencing, and short-lived ICE/TURN provisioning are built and
covered. What remains for browser P2P *gameplay* is the browser executor that
consumes the data-channel handoff, plus a real STUN/TURN deployment. Until that
lands, `mesh_game` remains the server-hosted `MeshSession` path.
