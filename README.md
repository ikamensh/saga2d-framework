# Saga2D

A small Python framework for 2D games, exercised by three games built on
it: **Tribes**, a Polytopia-style turn-based strategy game; **Warband**, a
Warcraft 2-style real-time strategy game; and **Shardbound**, a compact
Eador-inspired campaign with a province map and separate tactical battles.

```bash
uv sync --extra dev
uv run python -m tribes            # title screen; --seed 7 jumps straight into a map
uv run python -m warband           # title screen; --seed 3 starts a match directly
uv run python -m eador             # Shardbound; --seed 7 --hero Wizard skips the title
uv run python -m pytest tests -q   # headless suite, a few seconds
```

Set `SAGA2D_SILENT=1` to keep any pyglet-backed script or test off the
speakers (`SAGA2D_HEADLESS=1` implies it and also hides windows).

## Shardbound

Choose one of four heroes, develop a stronghold, explore guarded ruins,
recruit an army, and take Duskspire before the rival reaches Westwatch.
The 19-province campaign carries wounds, casualties and experience between
hex battles. Movement highlights, exact attack previews, two spells,
optional automatic rounds and saves during battle keep the tactics usable.
Heroes choose between two class disciplines as they level; six adventure
types award relics with combat and economy effects. Manual slots, rolling
autosaves and explicit backup recovery preserve battles and pending choices.

The [player guide](eador/README.md) includes a tested opening and controls.
The [reference research](docs/eador-research.md) records the source material,
scope and deliberate simplifications. This is one complete shard with
original art, not the commercial game's content catalogue or astral campaign.
The [Early Access criteria](docs/early-access-criteria.md) define the larger
release goal; [progress and remaining gaps](docs/early-access-progress.md)
are tracked explicitly. The current build is a development milestone.

```bash
uv run python tools/fuzz_eador.py       # seeded rule and scene-input checks
uv run python tools/verify_eador.py     # real input + PNGs in /tmp/shardbound
```

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
| T | research wheel (Tab / arrows, Enter) | C | capture village or city |
| 1-7 | train in the selected city | H | hold (idle units heal) |
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

## Warband in one screen

A top-down map of meadows, woods and lakes under a soft fog of war; a base
in each corner with a gold mine and a wood beside it.  Peasants mine gold
and fell trees, build farms for supply, a barracks for footmen, archers and
knights, and guard towers; the AI does the same and attacks in growing
waves.  Raze every enemy building and hunt down what is left.  Selection
by click or drag box, right-click does the sensible thing (move, harvest,
attack, resume building), a context command card with keycaps, control
groups, a minimap that pans and orders, alerts, save/load, and a march
under it all.

| Key | Action | Key | Action |
|-----|--------|-----|--------|
| Drag / click | select | Right click | move · harvest · attack · rally point |
| Shift | add to selection / queue orders | A | attack-move |
| S / H | stop / hold | B then F B H T | build farm · barracks · town hall · tower |
| P / F / A / K | train peasant · footman · archer · knight | Ctrl+1-9 / 1-9 | assign / recall a group |
| Tab / . | next idle peasant / soldier | Space | jump to the last alert |
| Arrows, edges, middle-drag | scroll | Wheel, + / − | zoom |
| F3 / F5 / F9 | pause / save / load | Esc, F1, F10 | cancel · help · menu |

The game is `warband/`: `model.py` is a 20 Hz fixed-step simulation with
orders, harvesting, construction, supply, towers, fog and elimination;
`path.py` is A*; `mapgen.py` lays out and connects the bases; `ai.py` runs
each computer player; `textures.py` paints the ground and renders every
prop and unit through `saga2d.render3d`'s front camera; `view.py` keeps
sprites in step with the model and draws the fog and minimap as dynamic
images; `sound.py` synthesises the effects and the march; `scene.py` and
`title.py` are the saga2d scenes.

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
* **Measured paragraphs.** `Scene.draw_paragraph(text, x, y, width)` wraps
  against the actual font and returns the height for subsequent layout.
* **Hex boards.** `HexGrid(cells, size=..., origin=...)` supplies centers,
  corners, picking, neighbors, weighted movement ranges and shortest paths.
  The game supplies terrain costs and occupied cells. See the
  [small runnable cookbook](docs/framework-hexgrid.md).
* **Sprites with a logical size.**  `Sprite("name", size=(64, 64))` draws
  any texture at that size, so procedural textures rendered at the
  display's pixel density stay crisp on HiDPI screens.
* **Declarative input.**  `controls` maps keys and chords to methods;
  `bind_key` does the same at runtime; `game.input.is_pressed` polls held
  keys.  Mouse events carry `world_x`/`world_y` and the modifier keys.
* **A scene stack** with transparent overlays, deferred push/pop, and
  per-scene ownership of sprites, timers and particle emitters.
* **UI**: `Label` (reactive: pass a lambda), `Button` (its `hotkey` is
  drawn as a keycap), `KeyHints`, `Panel`, `Row`, `Column`, `ProgressBar`,
  anchors, flow layout, and a `Theme` with named text styles, corner radii
  and keycap colours.  Text is measured by the backend, so layout fits.
* **Actions** (`Sequence`, `Parallel`, `MoveTo`, `Delay`, `Do`, `FadeOut`,
  `Remove`, `Repeat`, `PlayAnim`), tweens, timers, particle emitters, frame
  animation, audio (sounds and looping music), JSON save slots.
* **Shared by both games**: `saga2d.render3d` (a Pillow low-poly renderer
  with a configurable camera), `saga2d.effects` (floating text, pulses,
  bursts, hit reactions, banners, toasts), `saga2d.synth` (procedural sound
  with a WAV cache and a bank), `saga2d.fonts` (bundled Nunito), dynamic
  images (`assets.update_image` for fog of war and minimaps), and a
  `Minimap` component.
* **A mock backend** that records every draw call for headless tests, and
  `saga2d.testing.render_scene` for offscreen screenshots you can look at.
* **Audio** with `master`/`music`/`sfx` channels, pitch variation, mute,
  and a silent driver for tests.

See [DESIGN.md](DESIGN.md) for the architecture and the reasoning behind
the cuts.
