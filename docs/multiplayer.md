# LAN multiplayer and game integration

## Online identity and rated play

An online account is a random public `player_id` plus a strong random private
`player_token`. The token is a bearer credential: the game persists it per
endpoint, the server only ever stores its hash, and it never appears in room
states, rosters or HTTP answers. The display name is not the identity — two
players may share one. Names trim to at most 32 printable characters with no
control characters; anything else is a clear refusal. `resume_token` stays the
separate private room-seat credential. Every create and join assigns an
identity, including clients from before identities existed.

`OnlineClient(..., player_token='', player_name='Commander', rated=False)`
sends `rated` on create; joins and resumes inherit the room's flag. A rated
create on an old server fails clearly instead of falling back to casual, as
does a join with player options the server does not understand.

A game opts into ratings with three `GameSpec` hooks: `result(match)` naming
the winning seat or `None` while undecided (no hook, no rated rooms),
`rated(match)` for eligibility, and `forfeit(match, seat)` recording an
abandonment. Rated rooms need a supported, eligible, non-campaign match with
2–4 seats, and one account cannot hold two of its seats. Only completed
authoritative matches rate: all participants start at 1500, the winner takes
32·(1−E) normalised over each loser while losers tie, games/wins/losses
tally, and each match UUID records exactly one receipt. `configure_player`
applies a joining seat's private options (a race choice) before the seat is
claimed; resume never reconfigures.

A rated seat absent past `--rated-grace` (default 60 seconds, positive and
finite) forfeits through the game's hook once the match has begun — the lobby
never starts that clock, and an empty room stays paused. Reconnecting in time
keeps the seat with no defeat. The welcome carries the configured grace, so
menus read `OnlineClient.rated_grace` (`None` before the welcome or on old
servers) instead of guessing it.

Anyone may read `GET /status` (counts plus per-game rated support, never room
codes, tokens or identities), `GET /ratings?game=id&limit=20` (public
profiles, best first, limit 1–100) and `GET /players/{id}?game=id` as JSON;
`/healthz` stays plain `ok`.

For internet play, use the default **Online** mode described in
[the online multiplayer guide](../../tribes/docs/online-multiplayer.md). The following describes
the explicit **LAN** mode.

Each title has **M / Multiplayer** (Shardbound calls it **Co-op**). Choose **LAN**, then
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

Tribes shows final multiplayer scores without entering them on its solo high-score
board. Start another room from the title to play again.

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
schema. `warband/online/authority.py` owns grouped RTS orders, the authoritative clock
and event delivery. `eador/multiplayer.py` owns shared campaign/tactical commands
and the transition between map, battle, rewards and campaign progression.
Existing models and scenes remain the source of game rules and presentation.
None of those concepts belong in the transport.

## Observers

A match can be watched without playing it, over LAN and through the room
server. Watching is an explicit role, not a seat: a watcher says `observe`
(a distinct handshake type, never `hello` with a flag), holds no seat
(`player` is None), carries no seat credential (no resume token, no account
token, no identity), and can never submit — `submit` raises CommandError
locally, and a raw order over a watcher wire is refused without touching the
match. Otherwise a watcher looks like any session: `state`, `revision`,
`ready`, `error`, `poll` and `close` work the same way.

```python
watcher = MatchClient('warband-v1', host.address, token=code, observer=True)
watcher = OnlineClient('warband-v1', endpoint=url, room=code, observer=True)
```

A game opts in with one hook: `observer_snapshot(match)` on `GameSpec`, or
`observer_snapshot()` on `MatchHost`. That hook is the watcher's whole world —
watchers never see a seat snapshot or a checkpoint. A game without the hook
refuses watchers clearly (`This match does not support observing`), and
everything else plays on unchanged. At most eight watchers fit one room or
host; seats never compete for those slots.

Watchers may arrive before the first player, while the match runs, or after it
is decided; they see states once the room is ready, and watching the same code
again reconnects the same way. They change nothing: they occupy and satisfy no
seat, never appear in `present`, `seats` or `players` (those count playing
seats only; `observer_count` carries the watching tally), mint no account,
alter no rating, settle no result, block no readiness, pause nothing on
leaving, and extend no retention — an emptied room still expires under watching
eyes. Seats learn watcher arrivals and departures at the same revision, from
their last published state, so the tally stays live even in a paused room
that never publishes again. A suspended campaign detaches its watchers with
an explicit refusal; watching again restores the room. A watcher welcome
carries public room data only, while states may carry
the public roster and the rated receipt. A broken observer hook ends watching,
loudly in the server log, while the seats play on. A watcher handshake that
never completes is dropped after ten seconds no matter how much it pings, so
squatters cannot hold the guest seat hostage.

An old host rejects the unknown `observe` type without claiming its guest
seat, so watching an unupgraded host ends in a clear refusal. The other way
round, a new watcher requires an explicit observer welcome followed by
observer-flagged states and refuses anything shaped like a seat claim instead
of downgrading silently. Old clients ignore the added `observer_count` key on
seat states.

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
