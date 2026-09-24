# Frame telemetry

`Game.run()` keeps how the game actually ran on the player's machine, beside
its saves, with nothing for the game to set up:

```text
<data_dir>/telemetry/20260924-153901-4242-001.jsonl
```

The first line of each file says what ran: the game, the engine version, the
frozen build's version and commit (`null` from a checkout), Python, the
platform, the CPU count, the canvas and the FPS cap. Then one line per window
of five seconds:

```json
{"kind":"window","t":1210.0,"s":5.0,"scene":"GameScene","fg":true,"frames":142,"fps":28.4,
 "frame_ms":[33.4,61.2,88.0,120.3],"work_ms":[30.1,58.9,86.2,118.0],
 "update_ms":24.3,"draw_ms":6.1,"present_ms":1.2,"hitches":9,
 "worst":{"frame":120.3,"update":104.9,"draw":13.1,"present":2.3},
 "cpu":0.97,"gc_full":0,"phases":{"ai":14.2,"sim":8.8,"view":2.1},
 "window":[2560,1440],"fullscreen":true,
 "context":{"run":"6ede8f53-…","map":"144x108","seats":12,"tick":16240,"units":402}}
```

- `frame_ms` is p50, p95, p99 and max of the interval from one frame's start
  to the next: what the player sees. `work_ms` is the same for update plus
  draw without presenting: the CPU's share, and the headroom under the cap.
- `update_ms`, `draw_ms` and `present_ms` are means per frame. `present` is
  the buffer swap, which waits for VSync or the GPU.
- `hitches` counts frames of 50 ms or more; `worst` splits the longest.
- `cpu` is process CPU seconds per wall second (audio threads included);
  `gc_full` counts full garbage collections.
- `phases` are blocks the game timed, as means per frame:

  ```python
  with self.game.telemetry.phase("ai"):
      for brain in self.brains:
          brain.think(world)
  ```

- `context` is what the scenes say about themselves. Each scene on the stack
  is asked once per window, bottom first, so an overlay's keys win:

  ```python
  def telemetry_context(self):
      return {"map": f"{w}x{h}", "tick": self.world.tick, "units": len(self.world.units)}
  ```

A window closes after five seconds, or early when the top scene or the
window's focus changes, so each line holds one scene in one state. `"fg":
false` lines are frames behind another application, capped at 15 FPS.

## What it keeps

A file that reaches 4 MiB continues as the next part of the same session,
headed again by the first line. Whenever a part opens, the oldest files are
deleted until the directory holds at most 16 MiB; the file being written is
never deleted. A long evening of play is a few hundred KB. Change the limits
through `game.telemetry.file_limit`, `total_limit` and `window` before `run()`.

Only `run()` records: a test or tool that drives `tick(dt)` owns its clock
and writes nothing, and the mock backend has no frames worth keeping.
`SAGA2D_TELEMETRY=0`, or `game.telemetry.enabled = False` before `run()`,
turns it off. Nothing leaves the machine.

## Reading it

```sh
uv run python -m saga2d.telemetry ~/.warband          # the last five sessions
uv run python -m saga2d.telemetry ~/.warband --last 20 --worst 5
```

Each session gets its minutes in the foreground by scene, the median and 5th
percentile frame rate weighted by time, the share of time under 30 FPS, the
hitch count and the slowest windows with their context. The rows are plain
JSON lines for anything else: `saga2d.telemetry.read(directory)` returns the
sessions.

The game need: Warband's replays hold the start and every order, not frames,
so whether a 12-seat match on a 144×108 map was playable could only be
reconstructed by re-running it. A window's context names the run and the
tick, so a slow stretch can be found again in that run's replay.
