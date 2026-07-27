"""Tandem: a two-player grid game for the browser peer-to-peer mode.

This is study code, not platform code. It supplies the whole environment as the
``source_bundle`` the platform ships to every browser, so the peers each step an
identical replica in Pyodide and agree over their own data channels.

The bundle is deliberately dependency-free: it imports only the standard library,
so a browser installs no wheel and the runtime is ready as soon as Pyodide boots.
It defines the two names the platform drives: ``make_replica(peer_actor_ids,
seed)`` and ``draw(replica)``.

Two properties make the game usable as peer-to-peer evidence:

- it is **deterministic from its seed alone**. The token positions come from a
  small generator the replica holds itself, so a snapshot covers it and a rollback
  replay reproduces the exact state the confirmed inputs imply.
- it **reacts to both seats every frame**, so a wrong prediction changes the
  observation. A game where one seat's input rarely mattered would hide a
  rollback defect rather than expose it.

The study that runs it is ``examples/tandem/study.py``:
``uvicorn examples.tandem.study:app``.
"""

from __future__ import annotations

from mug.game.browser_mesh import BrowserMeshSpec

# The Python every browser runs in Pyodide. The platform ships it verbatim.
_SOURCE_BUNDLE = '''
GRID = 9
STAY, UP, DOWN, LEFT, RIGHT = 0, 1, 2, 3, 4
_MOVES = {
    STAY: (0, 0),
    UP: (0, -1),
    DOWN: (0, 1),
    LEFT: (-1, 0),
    RIGHT: (1, 0),
}


class Tandem:
    """Two players share one grid and race for the token that keeps moving."""

    def __init__(self, peer_actor_ids, seed):
        self.peers = tuple(sorted(peer_actor_ids))
        # The whole generator is one integer, so a snapshot covers it exactly.
        self.rng = (seed * 2654435761 + 12345) % 2147483647 or 1
        self.frame = 0
        corners = [(0, 0), (GRID - 1, GRID - 1), (GRID - 1, 0), (0, GRID - 1)]
        self.players = {
            peer: corners[index % len(corners)]
            for index, peer in enumerate(self.peers)
        }
        self.scores = {peer: 0 for peer in self.peers}
        self.token = self._place()

    def _next(self):
        """Advance the generator and return its next value."""
        self.rng = (self.rng * 48271) % 2147483647
        return self.rng

    def _place(self):
        """Place the token on a free square."""
        for _ in range(64):
            spot = (self._next() % GRID, self._next() % GRID)
            if spot not in self.players.values():
                return spot
        return (GRID // 2, GRID // 2)

    def step(self, actions):
        """Move every player, award the token, and report the frame."""
        self.frame += 1
        for peer in self.peers:
            dx, dy = _MOVES.get(actions[peer] % 5, (0, 0))
            x, y = self.players[peer]
            self.players[peer] = (
                min(GRID - 1, max(0, x + dx)),
                min(GRID - 1, max(0, y + dy)),
            )
        rewards = {peer: 0.0 for peer in self.peers}
        # A tie is resolved by the frozen peer order, so every replica agrees.
        for peer in self.peers:
            if self.players[peer] == self.token:
                self.scores[peer] += 1
                rewards[peer] = 1.0
                self.token = self._place()
                break
        return (self.observation(), rewards, False, False, None)

    def observation(self):
        """Return the json-able state the mesh hashes and the client draws."""
        return {
            "frame": self.frame,
            "players": {peer: list(self.players[peer]) for peer in self.peers},
            "scores": {peer: self.scores[peer] for peer in self.peers},
            "token": list(self.token),
        }

    def snapshot(self):
        """Return the whole replica state, including the generator."""
        return (
            self.rng,
            self.frame,
            dict(self.players),
            dict(self.scores),
            self.token,
        )

    def restore(self, snapshot):
        """Restore the whole replica state from a snapshot."""
        rng, frame, players, scores, token = snapshot
        self.rng = rng
        self.frame = frame
        self.players = dict(players)
        self.scores = dict(scores)
        self.token = token


def make_replica(peer_actor_ids, seed):
    """Build one deterministic replica for the frozen peer set and shared seed."""
    return Tandem(peer_actor_ids, seed)


_COLORS = ["#2d6cdf", "#df6c2d", "#2ddf6c", "#df2d6c"]


def draw(replica):
    """Return the surface commands for the replica's current state."""
    cell = 1.0 / GRID
    commands = [
        {
            "op": "rect",
            "id": "board",
            "relative": True,
            "color": "#f2f2f2",
            "x": 0.0,
            "y": 0.0,
            "width": 1.0,
            "height": 1.0,
        }
    ]
    token_x, token_y = replica.token
    commands.append(
        {
            "op": "circle",
            "id": "token",
            "relative": True,
            "color": "#d4af37",
            "x": (token_x + 0.5) * cell,
            "y": (token_y + 0.5) * cell,
            "radius": cell * 0.3,
        }
    )
    for index, peer in enumerate(replica.peers):
        x, y = replica.players[peer]
        commands.append(
            {
                "op": "rect",
                "id": "player-" + str(index),
                "relative": True,
                "color": _COLORS[index % len(_COLORS)],
                "x": x * cell + cell * 0.15,
                "y": y * cell + cell * 0.15,
                "width": cell * 0.7,
                "height": cell * 0.7,
            }
        )
    return commands
'''


def tandem_mesh_spec() -> BrowserMeshSpec:
    """Return the browser peer-to-peer specification for the Tandem demo."""
    return BrowserMeshSpec(
        channel_key="tandem",
        source_bundle=_SOURCE_BUNDLE,
        requires=(),
        action_bindings={
            "ArrowUp": 1,
            "ArrowDown": 2,
            "ArrowLeft": 3,
            "ArrowRight": 4,
        },
        default_action=0,
        fps=15,
        max_steps=120,
        input_delay=2,
        snapshot_interval=5,
    )


__all__ = ["tandem_mesh_spec"]
