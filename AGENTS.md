# Saga2D — the framework

A small Python framework for 2D games: scenes, GPU rendering through pyglet, a
UI toolkit, input, audio, saves and settings, LAN and online matches, a room
server, a PyInstaller recipe, and a mock backend that makes all of it testable
without a window. Read `DESIGN.md` before changing the framework.

Part of the Saga stack (`~/saga/`, see `../AGENTS.md`). Games pin a PyPI engine
release; changes here are isolated until a game deliberately upgrades. After
changing public behaviour, explicitly install this checkout in the affected
game's environment and run its suite with `uv run --no-sync pytest -q`, then
restore its released engine. See [releases](docs/releases.md) for the commands,
version policy and package verification. `__version__` in `saga2d/__init__.py`
is the single version source. Commit stable release increments. Saga2D is
AI-owned: agents have standing authorization to publish verified engine
releases to PyPI and push engine commits and release tags, following the
release guide. Game publishing and hosted deployments remain separate.
Procedural asset generation (sound synthesis, the software 3D renderer) lives
in `../sagaforge`; the framework does not depend on it.

## Commands

```bash
uv sync --extra dev
uv run pytest -q                                   # headless suite (mock backend)
uv run python tools/demo_match_room.py --serve     # a two-seat counter room; then run it twice more to play
uv run python -m saga2d.server --games saga2d.testing.online:GAMES   # the room server with the test game
uv run python tools/verify_frame_pacing.py         # real-backend checks; see each tool's docstring
```

## Layout

- `saga2d/game.py` — game loop (`tick`), subsystems, scene stack glue.
- `saga2d/scene.py` — `Scene` hooks, `controls`, draw helpers, ownership.
- `saga2d/backends/pyglet_backend.py` — GPU backend: view matrices per space,
  triangle soup for shapes, cached labels, texture atlas. `mock_backend.py`
  records every call for tests.
- `saga2d/rendering/`, `saga2d/ui/`, `saga2d/util/` — camera, layers, sprites,
  particles; components, layout math, theme, minimap; collision, reactive
  values, timers, tweens.
- `saga2d/effects.py`, `fonts.py`, `hexgrid.py`, `animation.py`, `actions.py`,
  `audio.py`, `assets.py`, `save.py`, `settings.py`, `release.py` — pieces the
  games share.
- `saga2d/network.py`, `online.py`, `multiplayer_ui.py` — LAN host/client, the
  online client and the shared match menu and lobby.
- `saga2d/server/` — the authoritative room server. Games register a
  `GameSpec` table (`<game>.multiplayer:ONLINE`); `python -m saga2d.server
  --games ...` hosts any set of them.
- `saga2d/packaging/` — build, verify and install standalone games (each game
  has a ten-line `tools/package.py` describing itself as a `GamePackage`).
- `saga2d/testing/` — `render_scene`, text-overlap checks, `cpu_budget`,
  `native_frames.tick`, the pytest fixtures plugin and `online` (the counter
  test game plus helpers that drive a real server process).
- `tools/` — demos and real-backend verification scripts; `docs/framework-*.md`
  are small runnable cookbooks.

## Rules

- Framework additions need a concrete game need; two games needing the same
  thing is the strongest case. Features exist because a game needed them in
  that exact form. Delete rather than deprecate.
- Clear exceptions over silent fallbacks.
- Game code imports from `saga2d`, never from `saga2d.backends`.
- Visual changes must be looked at. Mock tests prove logic, not pixels. After
  any change to rendering, the pyglet backend or UI components, render a real
  frame and open the PNG:

  ```python
  from saga2d.testing import render_scene

  def setup(game):
      game.push(MyScene())

  render_scene(setup, resolution=(1280, 800), tick_count=3).save("/tmp/check.png")
  ```

  Real input goes through pyglet's dispatch on the hidden window:
  `game.backend.window.dispatch_event("on_key_press", key.TAB, 0)`. pyglet
  handlers must return `True` or ESC closes the window. The display must be
  awake for pyglet to open windows (a `get_default_screen` IndexError means it
  is asleep; `caffeinate -u` wakes it).
- Tests: `Game("t", backend="mock")`, `game.tick(dt)`, `backend.inject_key(...)`,
  `backend.inject_click(x, y)`; assert on `backend.texts/rects/sprites`. The
  `game` and `backend` fixtures come from `saga2d.testing.fixtures`. Tests
  exercise public behaviour; no mocking of internals; a regression test for
  every bug found.
- Run at most one expensive local test or verification job at a time; native
  loops use `saga2d.testing.native_frames.tick(game)` (30 FPS cap).
- Commit each working increment.
