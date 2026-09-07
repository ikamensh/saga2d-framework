# A small multiplayer consumer

The three reference games need the same room entry, waiting screen and transfer
of a connection into their own game scene. `MatchMenu` and `MatchLobby` own that
UI and handoff; `OnlineClient` owns asynchronous WebSocket I/O. The game owns
commands, authoritative rules and the JSON shown by each seat.

[`tools/demo_match_room.py`](../tools/demo_match_room.py) is an independent
consumer. Its complete rule is “Add one increments the sender's counter.”
It imports no reference game or production server catalog, and adds no framework
interface. A small in-memory authority in the same file makes the Online path
executable without the hosted service.

## Run the complete example locally

From the repository root, start three terminals:

```sh
# Terminal 1: one ephemeral room, bound only to IPv4 loopback.
uv run python tools/demo_match_room.py --serve --port 8766

# Terminal 2: choose Create room. The room code is counter.
uv run python tools/demo_match_room.py --port 8766

# Terminal 3: type counter in the menu and choose Join room.
uv run python tools/demo_match_room.py --port 8766
```

Click **Add one** or press **Space**. Each seat changes only its own count.
Open **Help** with **H**, then add from the other window: the covered scene still
receives state. **Esc** closes Help; **Esc** in the counter quits that client.
Quit both windows and stop the server with Ctrl+C when finished.

For the direct client/lobby construction path, replace the third command with:

```sh
uv run python tools/demo_match_room.py --port 8766 --join counter
```

The launcher explicitly sets `SAGA2D_SERVER_URL=ws://127.0.0.1:8766` from
`--port` for the shared menu. `--join` passes that URL directly to
`OnlineClient`. It also uses a separate temporary data directory per window,
so a previous game's saved endpoint or private seat cannot affect the demo.
The menu's existing **LAN** option remains available and has its usual direct
LAN/VPN behavior; the commands above exercise **Online over loopback**.

The windows use `Game.run(..., fps=30)`, which drops to at most 15 FPS when
unfocused. The authority waits for WebSocket messages; it has no simulation or
busy polling loop. This is a learning server: one room, no persistence, no
public deployment or production admission controls. Restart it to reset the
counters. Private seat credentials support reconnecting within the server's
lifetime; the launcher's temporary files disappear when that client exits.

## The factory interfaces

```python
MatchMenu(title, game_id, create_match, create_scene, *, create_options=None)
```

| Caller-supplied function | When it runs and what it returns |
| --- | --- |
| `create_match()` | LAN host only. Returns an authority with `apply(player, command)` and `snapshot(player)`. The transport assigns `player`; command data never chooses its seat. |
| `create_scene(session, match)` | Once the session is ready. Returns the caller's `Scene`. `match` is the local authority for a LAN host, and `None` for a LAN guest or either Online seat. |
| `create_options()` | Online creation only. Returns JSON options understood by that server's game catalog. Defaults to an empty dictionary. It does not construct local authority. |

`apply` commits a validated command or raises `CommandError` for an expected
invalid order. `snapshot` returns fresh JSON data suitable for that player.
The counter's snapshot is `{"counts": [0, 0], "you": player}`. Its scene renders
the received snapshot and submits `{"action": "add"}`; it never increments a
local copy optimistically.

Direct construction uses a **one-argument** lobby factory:

```python
session = OnlineClient("counter-demo-v1", endpoint="ws://127.0.0.1:8766",
                       room="counter")
lobby = MatchLobby(session, lambda connection: CounterScene(connection, None))
```

`OnlineClient(game_id, *, endpoint=None, room=None, options=None,
resume_token=None)` creates when `room` is absent, joins when it is supplied,
and resumes a private seat when both `room` and `resume_token` are supplied.
An omitted endpoint reads `SAGA2D_SERVER_URL`, then the hosted default.
`MatchMenu` uses that environment configuration for create/join; its saved-room
rejoin uses the recorded endpoint. Use explicit endpoints and isolated data for
local checks. Plain `ws://` is accepted only for loopback; other hosts need TLS.

## State and lifetime ownership

`MatchLobby` owns the session while waiting. It calls `poll()` and displays
errors or the room code. When `ready` becomes true, `state` is available and the
lobby invokes the scene factory, clears the previous scene stack and transfers
ownership. Canceling before that handoff closes the session.

The returned scene now owns the session. Poll on the game thread, submit JSON
commands, and close in `on_close`. A scene-owned timer such as
`self.every(1 / 30, self.poll)` keeps networking active under a help overlay;
`update` alone pauses while covered. Do not close in `on_exit`, which also runs
on cover. `on_close` runs for permanent removal and failed scene entry. The
example's timer is canceled automatically when that scene is removed.

`ready` requires both partners. Controls pause when it is false. Optional
`submit(command, revision=session.revision)` rejects a stale decision rather
than applying it to a changed state. Expected `CommandError` becomes visible
feedback; unexpected errors propagate. `OnlineClient.close()` requests worker
shutdown; a disconnected order is never automatically replayed. Ordinary
`Game.run()` closes the game on exit; callers driving explicit ticks must call
`Game.close()` in `finally`.

## Bounded verification

```sh
uv run python -m pytest tests/framework/test_match_room_demo.py -q
```

The integration test starts only the demo authority on an OS-assigned loopback
port, creates through actual menu input, joins a second real WebSocket client,
checks both counters, continues receiving under Help and closes the owning Game.
It uses one mock window, sleeps between bounded polling steps, and terminates
the server in `finally`. It does not prove internet deployment, audio, native
rendering or behavior of any reference game's multiplayer adapter.

A separate [retained macOS native journey](evidence/framework-match-menu/README.md)
uses actual menu clicks and keyboard input, verifies a peer update while Help
covers the counter, and records complete cleanup. Representative reviewed frames
and source hashes are retained with the precise local-only scope.
