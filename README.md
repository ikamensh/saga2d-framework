# Saga2D

A small Python framework for 2D games, and **Tribes**, a Polytopia-style
strategy game built on it.

```bash
uv sync --extra dev
uv run python -m tribes            # title screen; --seed 7 jumps straight into a map
uv run python -m pytest tests -q   # headless suite, a few seconds
```

Set `SAGA2D_SILENT=1` to keep any pyglet-backed script or test off the
speakers (`SAGA2D_HEADLESS=1` implies it and also hides windows).

## Tribes in one screen

A 2.5D map of software-rendered low-poly blocks, units as game pieces on
a disc so their tile is never in doubt, procedural sound, a title screen
with map size, tribe count and the tribe to play (each starts with its own
tech), and animated combat. Capture villages, harvest resources inside
your borders to level cities up, pick a reward at every new level
(workshop, explorer, walls, border growth, population, park or stars),
walk onto ruins for treasure, knowledge, settlers or a map, research
techs, train units, take every enemy city — or lead on score when the
round limit falls. Everything has a hotkey, and the UI shows them as
keycaps (text is Nunito, SIL OFL, bundled with saga2d):

| Key | Action | Key | Action |
|-----|--------|-----|--------|
| Click / Enter | act at the cursor: select, move, attack, harvest, capture | Arrows | move the cursor |
| Tab / Shift+Tab | next / previous unit with actions left | WASD, right-drag | pan |
| E | end turn (twice if units can still act) | Wheel, + / - | zoom |
| T | research | C | capture village or city |
| 1-5 | train in the selected city | H | hold (idle units heal) |
| F5 / F9 | save / load | Esc | cancel, then pause menu (settings, back to title) |
| Home | jump to your capital | F1 | help |
| 1 / 2 | pick a city's level reward | Tab (new game) | choose the tribe to play |

The game is `tribes/`: `model.py` holds every rule (pure Python, no
rendering), `mapgen.py` builds connected maps, `ai.py` plays the other
tribes, `textures.py` pre-renders the isometric blocks and props with
`saga2d.render3d` (a tiny Pillow software renderer with a configurable camera),
`view.py` lays the map out and keeps sprites in step with the model,
`effects.py` holds the transient animations, `sound.py` synthesises every
effect and the ambient loop with numpy (cached under `~/.tribes`), and
`scene.py` plus `title.py` are the saga2d scenes that turn input into
model calls.

## The framework

Saga2D renders sprites and simple shapes on the GPU through pyglet, lays
out a small UI toolkit, and runs a scene stack. Game code never touches
the backend.

```python
from saga2d import Anchor, Camera, Game, Label, RenderLayer, Scene, Sprite


class World(Scene):
    background_color = (18, 20, 30, 255)
    controls = {"e": "end_turn", ("tab", "n"): "next_unit", "ctrl+s": "save"}

    def on_enter(self):
        self.camera = Camera(self.game.resolution, zoom=1.0)
        self.hero = self.add_sprite(Sprite("hero", position=(320, 240), size=(64, 64)))
        self.ui.add(Label(lambda: f"Gold {self.gold}", text_style="hud", anchor=Anchor.TOP_LEFT, margin=12))

    def draw(self):
        self.draw_rect(0, 0, 64, 64, (255, 255, 255, 60), space="world", layer=RenderLayer.OBJECTS)

    def end_turn(self): ...
    def next_unit(self, event): ...   # handlers may take the InputEvent
    def save(self): ...


Game("My Game", resolution=(1280, 800)).run(World())
```

What you get:

* **Two coordinate spaces.** `"world"` is transformed by the scene's
  `Camera` (pan, zoom, shake) on the GPU; `"screen"` is for UI.  Sprites
  default to world space; `draw_rect`, `draw_circle`, `draw_line`,
  `draw_polygon`, `draw_text` and `draw_image` take `space=`.
* **Sprites with a logical size.**  `Sprite("name", size=(64, 64))` draws
  any texture at that size, so procedural textures rendered at the
  display's pixel density stay crisp on HiDPI screens.
* **Declarative input.**  `controls` maps keys and chords to methods;
  `bind_key` does the same at runtime; `game.input.is_pressed` polls held
  keys.  Mouse events carry `world_x`/`world_y`.
* **A scene stack** with transparent overlays, deferred push/pop, and
  per-scene ownership of sprites, timers and particle emitters.
* **UI**: `Label` (reactive: pass a lambda), `Button` (its `hotkey` is
  drawn as a keycap), `KeyHints`, `Panel`, `Row`, `Column`, `ProgressBar`,
  anchors, flow layout, and a `Theme` with named text styles, corner radii
  and keycap colours.  Text is measured by the backend, so layout fits.
* **Actions** (`Sequence`, `Parallel`, `MoveTo`, `Delay`, `Do`, `FadeOut`,
  `Remove`, `Repeat`, `PlayAnim`), tweens, timers, particle emitters, frame
  animation, audio (sounds and looping music), JSON save slots.
* **A mock backend** that records every draw call for headless tests, and
  `saga2d.testing.render_scene` for offscreen screenshots you can look at.
* **Audio** with `master`/`music`/`sfx` channels, pitch variation, mute,
  and a silent driver for tests.

See [DESIGN.md](DESIGN.md) for the architecture and the reasoning behind
the cuts.
