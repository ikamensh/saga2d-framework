# Multiplayer in the three games

Each title has **M / Multiplayer** (Shardbound calls it **Co-op**). Choose
**Host room** on one computer. On the other, enter the host's LAN or private-VPN
address, the displayed port and room code, then choose **Join room**. Click a
field to replace it, use Tab to move between fields, and Backspace to edit.
Both computers need the same game version. Two processes on one computer can
use `127.0.0.1`.

| Game | Mode | Authority |
| --- | --- | --- |
| Tribes | Two competitive human tribes; normal turn order, fog and victory rules | Host validates the active faction and every command |
| Warband | Two competitive human factions; simultaneous RTS orders | Host alone advances the 20 Hz simulation; clients receive snapshots at about 10 Hz |
| Shardbound | Two partners share one realm, hero, army and campaign decisions | Host serializes both partners' campaign and tactical commands |

Shardbound's title Co-op action starts a linked campaign with the selected hero,
seed and difficulty. The command line also supports a standalone co-op shard.
Both partners can move units, use abilities, build, recruit, make reward and
retinue choices, and end a round/turn. If two orders were made from the same
old state, the host accepts the first and asks the other player to try again.
Accepted campaign changes refresh both screens; catalog and tactical selection
are retained where applicable.

## Command-line launch

```bash
# Host; the room code is printed and displayed in the lobby.
uv run python -m tribes --host --seed 7
uv run python -m warband --host --seed 3
uv run python -m eador --host --campaign --seed 7

# Guest; replace the address and code with the host's values.
uv run python -m tribes --join 192.168.1.20 --room CODE
uv run python -m warband --join 192.168.1.20 --room CODE
uv run python -m eador --join 192.168.1.20 --room CODE
```

`--port 7788` chooses a different TCP port; use the same value on both sides.
`--room mycode` chooses the host's code. Seed/world options are chosen by the
host; the guest always receives the host's existing world. Network matches
have exactly two human seats.

A disconnected guest can return to the title and join the same address, port
and code while the host remains open. The host pauses while disconnected and
sends the current state on reconnection. Menus do not disconnect either player;
Warband continues running while a menu is open. Closing the host ends the room.

This is direct play for trusted LAN/VPN peers. There is no matchmaking, relay,
NAT traversal, host migration, encrypted transport or ranked anti-cheat. Normal
fog is enforced by the game views; snapshots currently include the complete
simulation, so modified clients can inspect hidden information. Network matches
resume from the live host; offline saves are not a multiplayer session format.

## Framework versus games

Saga2D owns two small modules:

- `network.py`: nonblocking TCP, bounded JSON framing, version/room handshake,
  assigned seats, ordered delivery, optional revision checks, rejection messages,
  disconnect detection, reconnection and authoritative snapshot publication.
- `multiplayer_ui.py`: address/code entry, host/join lobby, shared CLI flags and
  transfer into a game-supplied match scene. The title backdrop is released when
  a match starts. `Scene.on_close` closes the connection only when its scene is
  removed, including failed startup; covering the scene leaves it connected.

A host supplies `apply(player, command)` and `snapshot(player)`. A guest submits
JSON commands and reads snapshots. The framework does not dispatch arbitrary
model methods. Each game has an explicit list of permitted orders and validates
ownership, argument shapes and its existing rules. Invalid commands leave the
whole authoritative state unchanged. Unexpected implementation errors propagate.

`tribes/multiplayer.py` owns faction/turn permissions and the Tribes command
schema. `warband/multiplayer.py` owns grouped RTS orders, the authoritative clock
and event delivery. `eador/multiplayer.py` owns shared campaign/tactical commands
and the transition between map, battle, rewards and campaign progression.
Existing models and scenes remain the source of game rules and presentation.
None of those concepts belong in the transport.

## Reproducing verification

```bash
uv run python -m pytest tests/framework/test_network.py tests/test_multiplayer_games.py -q
SAGA2D_SILENT=1 uv run python tools/verify_multiplayer.py /tmp/multiplayer
```

The socket tests use actual loopback connections. The native verifier runs a
separate host process, opens the real title and join form, enters the room using
pyglet key events, and issues game orders through native input. It compares
accepted state and captures all three games. Jobs run sequentially; native
frames are paced at 30 FPS and host polling yields between iterations.
