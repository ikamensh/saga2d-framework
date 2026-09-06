# Closing an explicitly driven game

`Game.run(scene)` owns the loop and closes the game when it stops. An embedder
or a verification tool that drives `Game.tick(dt)` instead owns that lifetime:

```python
from saga2d import Game, Scene

game = Game('Embedded example', backend='mock')
try:
    game.push(Scene())
    game.tick(1 / 60)
finally:
    game.close()
```

`game.close()` immediately releases scenes, sprites, timers and audio, closes
the backend window, and allows another Game to be created. An exit-hook error
still propagates, after resource cleanup and backend shutdown have been
attempted. Call it from the owner after stepping has finished, rather than
from an input or update callback. Within callbacks, `game.quit()` requests
that the loop stop; it does not release resources underneath the current frame.

There is no new clock or scene lifecycle to configure. Explicit ticks retain
their supplied timestep and remain unpaced. `Game.run()` retains its original
exception if shutdown also fails. `saga2d.testing.render_scene()` also owns and
closes its temporary game, including when scene cleanup raises.

The caller problem was repeated private `_teardown()` / `backend.quit()` pairs
in independent display, wrapping and measurement examples. Some callers omitted
backend shutdown; others skipped it if scene cleanup raised. The existing
`quit()` only stops the loop, and the screenshot helper cannot serve callers
that need to retain a session across several explicit inputs. One public close
operation owns this sequence without exposing backend details or introducing
a separate lifecycle manager. Ordinary games still need only `run()`.

Run the independent two-session example:

```sh
uv run python tools/demo_game_close.py
uv run python tools/demo_game_close.py --backend pyglet
```

The first command uses the mock backend. The optional native check opens two
hidden windows sequentially, advances three frames in each at a 30 FPS cap,
then checks that each backend has closed before creating the next. Neither
path imports a game or requires assets. The public integration regression
additionally checks that a failing scene exit still closes the backend and
permits the next session.
