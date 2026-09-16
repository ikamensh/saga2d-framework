# Saga2D

A small Python framework for 2D games where the developer writes game logic,
not engine plumbing. It renders sprites and simple shapes on the GPU through
pyglet, lays out a small UI toolkit, runs a scene stack, hosts online matches
and packages standalone builds. Game code never touches the backend.

Three games prove it, each in its own repository:
[Tribes](https://github.com/ikamensh/tribes) (turn-based, Polytopia-style), [Warband](https://github.com/ikamensh/warband)
(real-time strategy) and [Shardbound](https://github.com/ikamensh/shardbound) (an Eador-inspired
campaign). Procedural assets — sound synthesis and a software low-poly renderer —
live in [sagaforge](https://github.com/ikamensh/sagaforge); the hosted server and website in
[saga-online](https://github.com/ikamensh/saga-online).

## Install

Requires Python 3.12 or newer. Pin the engine in a game so engine development
cannot change that game's build:

```bash
uv add 'saga2d==0.3.0'
# or: python -m pip install 'saga2d==0.3.0'
```

Commit the game's `pyproject.toml` and lockfile. Upgrade the pin deliberately,
then run that game's tests before committing the upgrade. See the
[release guide](https://github.com/ikamensh/saga2d-framework/blob/main/docs/releases.md)
for compatibility policy, publishing and testing a local engine checkout.

## Develop the engine

```bash
uv sync --extra dev
uv run pytest -q          # headless suite on the mock backend
```

Set `SAGA2D_SILENT=1` to keep any pyglet-backed script off the speakers
(`SAGA2D_HEADLESS=1` implies it and also hides windows).

## A complete game

This example needs no image or sound files:

```python
from saga2d import Anchor, Button, Column, Game, Label, Scene


class World(Scene):
    background_color = (18, 20, 30, 255)
    controls = {"escape": "close"}

    def on_enter(self):
        self.gold = 0
        self.ui.add(Column(
            Label(lambda: f"Gold: {self.gold}", text_style="heading"),
            Button("Collect a coin", shortcut="Space", on_click=self.collect, width=220),
            Label("Esc closes the window.", text_style="caption"),
            spacing=16, anchor=Anchor.TOP_LEFT, margin=24,
        ))

    def draw(self):
        self.draw_circle(360, 220, 32, (230, 190, 90, 255))

    def collect(self):
        self.gold += 1

    def close(self):
        self.game.quit()


Game("My Game", resolution=(640, 400)).run(World())
```

## What you get

* **Two coordinate spaces.** `"world"` is transformed by the scene's `Camera`
  (pan, zoom, shake) on the GPU; `"screen"` is for UI. Sprites default to
  world space; `draw_rect`, `draw_circle`, `draw_line`, `draw_polygon`,
  `draw_text` and `draw_image` take `space=`.
* **Measured text.** `Scene.layout_text(text, width)` returns wrapped lines and
  height; `Scene.draw_paragraph` draws the same layout. Both accept `max_lines`,
  and `Scene.fit_text` fits a single line with ellipsis. See the
  [text layout cookbook](docs/framework-text-layout.md).
* **Hex boards.** `HexGrid` supplies centers, corners, picking, neighbours,
  weighted movement ranges and shortest paths; the game supplies terrain
  costs. See the [cookbook](https://github.com/ikamensh/saga2d-framework/blob/main/docs/framework-hexgrid.md).
* **Sprites with a logical size.** `Sprite("name", size=(64, 64))` draws any
  texture at that size, so procedural textures rendered at the display's
  pixel density stay crisp on HiDPI screens.
* **Declarative input.** `controls` maps keys and chords to methods;
  `bind_key` does the same at runtime; mouse events carry world coordinates
  and modifier keys.
* **A scene stack** with transparent overlays, deferred push/pop, and
  per-scene ownership of sprites, timers and particle emitters.
* **UI**: reactive `Label`, `Button` with keycap shortcuts, `KeyHints`,
  `Panel`, `Row`, `Column`, `ProgressBar`, `Minimap`, anchors, flow layout,
  wrapped text and a `Theme`. Text is measured by the backend, so layout fits.
  See [wrapped labels](https://github.com/ikamensh/saga2d-framework/blob/main/docs/framework-wrapped-label.md),
  [measuring a tree](https://github.com/ikamensh/saga2d-framework/blob/main/docs/framework-ui-measurement.md) and
  [button shortcuts](https://github.com/ikamensh/saga2d-framework/blob/main/docs/framework-button-shortcuts.md).
  Opt-in keyboard focus, custom activation and pointer capture work across the
  same tree; `blocks_pointer=True` keeps HUD clicks out of the world. See
  [focus and pointer handling](docs/framework-ui-focus.md).
* **Actions**, tweens, timers, particle emitters, frame animation, transient
  effects, audio with `master`/`music`/`sfx` channels and a silent driver,
  JSON save slots and persisted settings.
* **Multiplayer.** `MatchHost`/`MatchClient` for LAN, `OnlineClient` and the
  shared `MatchMenu`/`MatchLobby` for hosted rooms, and `saga2d.server`, the
  authoritative room server any game registers with through a `GameSpec`.
  Follow the [counter-room tutorial](https://github.com/ikamensh/saga2d-framework/blob/main/docs/framework-match-menu.md) and the
  [transport notes](https://github.com/ikamensh/saga2d-framework/blob/main/docs/multiplayer.md).
* **Packaging.** `saga2d.packaging` builds, verifies and installs standalone
  games with PyInstaller from a ten-line `tools/package.py`.
* **Testing.** A mock backend that records every draw call, `render_scene`
  for offscreen screenshots you can look at, a CPU budget for long checks,
  paced native frames, and a counter test game for the server.

See [DESIGN.md](https://github.com/ikamensh/saga2d-framework/blob/main/DESIGN.md) for the architecture and the reasoning behind the cuts.
[The September 2026 engine review](docs/engine-review-2026-09.md) prioritizes
game extractions and proposed improvements beyond the current genres.
