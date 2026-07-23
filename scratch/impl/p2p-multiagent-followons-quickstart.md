# P2P and multi-agent follow-ons: the five things you can now do

*For a study author who runs multiplayer or multi-agent games. The peer-to-peer
mesh already ran a real-time parallel game across peers. These five follow-ons
extend that same spine: a turn-based multi-agent game over the mesh, a real wire
between peers, a bot that plays across the mesh, a diverged peer that repairs
itself, a server-hosted game that seats bots beside people, and many games forming
at once. Every one is runtime over the frozen records -- no new schema, no vendor
SDK, no socket in your code.*

> Status: **built.** `mug/game/multiagent.py` (`AecReplica`), `mug/game/wire.py`,
> `mug/game/bot_authority.py`, `mug/game/desync_repair.py`,
> `mug/game/server_session.py`, and `mug/interactions/pool.py` are live, each proven
> in-process.

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

## What stays for production wiring

The runtime for all five is done and proven. Two production-wiring steps remain, and
neither needs a record change: a concrete `aiortc` (or browser) `PeerLink` adapter
behind the wire tier's seam, and mounting `ServerSeatSession` and
`MeshFormationPool` on the participant websocket path beside the existing
`MeshMatchmaker`.
