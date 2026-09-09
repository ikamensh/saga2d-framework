# Saga2D

A small Python framework for 2D games where the developer writes game logic,
not engine plumbing. It renders sprites and simple shapes on the GPU through
pyglet, lays out a small UI toolkit, runs a scene stack, hosts online matches
and packages standalone builds. Game code never touches the backend.

Three games prove it, each in its own repository beside this one:
[Tribes](../tribes) (turn-based, Polytopia-style), [Warband](../warband)
(real-time strategy) and [Shardbound](../shardbound) (an Eador-inspired
campaign). Procedural assets — sound synthesis and a software low-poly renderer —
live in [sagaforge](../sagaforge); the hosted server and website in
[saga-online](../saga-online).

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
* **Measured paragraphs.** `Scene.draw_paragraph(text, x, y, width)` wraps
  against the actual font and returns the height for subsequent layout.
* **Hex boards.** `HexGrid` supplies centers, corners, picking, neighbours,
  weighted movement ranges and shortest paths; the game supplies terrain
  costs. See the [cookbook](docs/framework-hexgrid.md).
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
  See [wrapped labels](docs/framework-wrapped-label.md),
  [measuring a tree](docs/framework-ui-measurement.md) and
  [button shortcuts](docs/framework-button-shortcuts.md).
* **Actions**, tweens, timers, particle emitters, frame animation, transient
  effects, audio with `master`/`music`/`sfx` channels and a silent driver,
  JSON save slots and persisted settings.
* **Multiplayer.** `MatchHost`/`MatchClient` for LAN, `OnlineClient` and the
  shared `MatchMenu`/`MatchLobby` for hosted rooms, and `saga2d.server`, the
  authoritative room server any game registers with through a `GameSpec`.
  Follow the [counter-room tutorial](docs/framework-match-menu.md) and the
  [transport notes](docs/multiplayer.md).
* **Packaging.** `saga2d.packaging` builds, verifies and installs standalone
  games with PyInstaller from a ten-line `tools/package.py`.
* **Testing.** A mock backend that records every draw call, `render_scene`
  for offscreen screenshots you can look at, a CPU budget for long checks,
  paced native frames, and a counter test game for the server.

See [DESIGN.md](DESIGN.md) for the architecture and the reasoning behind the cuts.
