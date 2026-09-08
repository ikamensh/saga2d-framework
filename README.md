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
uv run python -m pytest tests -q   # headless integration suite
```

Set `SAGA2D_SILENT=1` to keep any pyglet-backed script or test off the
speakers (`SAGA2D_HEADLESS=1` implies it and also hides windows).

## Shardbound

Choose one of four heroes, develop a stronghold, explore guarded ruins,
recruit an army, and take Duskspire before the rival reaches Westwatch.
The 19-province campaign carries wounds, casualties and experience between
hex battles. Movement highlights, exact attack and ability previews,
optional automatic rounds and saves during battle keep the tactics usable.
Heroes choose between two class disciplines as they level. Ten recruitable
roles, twelve relics, and authored hold, escape and rout adventures provide
different tactical plans. Manual slots, rolling
autosaves and explicit backup recovery preserve battles and pending choices.

The [player guide](eador/README.md) includes a tested opening and controls.
The [reference research](docs/eador-research.md) records the source material,
scope and deliberate simplifications. The game now offers a three-shard
linked campaign with challenge choices, a traveling retinue and one recovery
expedition, alongside quick standalone shards. Its original content and
bounded progression are described in the [linked journey](docs/eador-linked-ui.md).
Accessible, Standard and Challenge select saved realm rules; the
[difficulty comparison](docs/eador-difficulty-candidate.md) records their
current limits. Difficulty and seed can be chosen on the title or command line.
The [Early Access criteria](docs/early-access-criteria.md) define the larger
release goal; [progress and remaining gaps](docs/early-access-progress.md)
are tracked explicitly. The current build is a development milestone.

```bash
uv run python tools/fuzz_eador.py       # seeded checks, default CPU allowance: 25% of one core
uv run python tools/verify_eador.py     # real input + PNGs in /tmp/shardbound
```

Both fuzz drivers and the economy, difficulty, crystal-demand, world, linked
campaign, discipline, army-plan, resource-breakpoint and tactical
control/role/relic/extraction/Causeway/Aerie/Relief audit CLIs target
**25% of one CPU core** by sleeping between short work blocks. Choose
`--cpu-percent 100` explicitly for an unrestricted stress run.
The allowance is cooperative: one atomic model command may exceed the roughly
50 ms work block, and several simultaneous processes add their CPU use together.
Run heavy checks one at a time on a shared laptop.
Hero equipment, Pin, save and result verification also pace their campaign preparation at this allowance;
`--cpu-percent` controls that work independently of its native frame cap.
The older Relief prototype applies the same allowance to its paid preparation,
orders and searches; `--trials` and `--world-seeds` select small search samples.

Economy, difficulty and crystal-demand audits accept `--heroes`, `--themes` and
`--plans` to select a small comparison. Their existing matrix sizes are preserved;
use `--seeds 1` with those filters for a quick probe.
The resource-breakpoint audit accepts `--theme`, `--difficulty` and `--plan`;
select all three to run one observed/baseline campaign pair.

Normal play uses `game.run(scene, fps=60)`, sleeping between frames and reducing
unfocused or hidden windows to **15 FPS**. A game can choose `fps=30` for a lower
active frame rate.

Shardbound's `PlayerInput` verification driver caps native rendering at **30
FPS**, including screenshot settling loops. Standalone native verification
scripts use `tools.native_frames.tick(game)` for the same cap. Both retain
`dt=1 / 60` simulation steps, so these checks can take longer without changing
saved results. Direct mock/model tests remain unpaced. A frame cap limits
rendering frequency, while the fuzzer allowance limits CPU work; neither is a
battery-life measurement.

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

Finished games show a score breakdown, victory and early-finish bonuses, and
local high scores (**L** from the title or results). Armyless computer opponents
concede when they cannot rebuild. See [scoring and surrender](docs/tribes-scores.md)
for the rules and local storage details.

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

A top-down map of meadows, woods and lakes under a soft fog of war, in
summer, winter or wasteland; a base for each of two to four players with a
gold mine and a wood beside it.  Peasants mine gold and fell trees; farms
feed the army; a barracks, lumber mill, blacksmith, stables, workshop and
church open seven units and nine upgrades; guard towers hold the line.
Three AI difficulties expand, upgrade, raid and attack in growing waves.
Raze every enemy building and hunt down what is left.  Selection by click
or drag box, right-click does the sensible thing (move, harvest, attack,
resume building), a context command card with keycaps, control groups,
patrol, camera bookmarks, a minimap that pans and orders, alerts, three
save slots with an autosave, persisted settings, a tutorial strip, a
codex, and two marches under it all.

| Key | Action | Key | Action |
|-----|--------|-----|--------|
| Drag / click | select | Right click | move · harvest · attack · rally point |
| Shift | add to selection / queue orders | A / P | attack-move / patrol |
| S / H | stop / hold | B then F B H T M K S W C | build farm · barracks · hall · tower · mill · smith · stables · workshop · church |
| R | repair a damaged building (peasants) | Mac trackpad | two-finger click or Ctrl+click is the right-click; Cmd-click selects a type |
| Letters on the card | train and research in the selected building | Ctrl+1-9 / 1-9 | assign / recall a group |
| Tab / . | next idle peasant / soldier | Space | jump to the last alert |
| Arrows, edges, middle-drag | scroll | Wheel, + / − | zoom |
| F3 / F5 / F9 | pause / quicksave / quickload | Esc, F1, F2, F10 | cancel · help · codex · menu |

The game is `warband/`: `model.py` is a 20 Hz fixed-step simulation with
orders, harvesting, construction, supply, upgrades, towers, fog and
elimination; `path.py` is A*; `mapgen.py` lays out and connects the bases
and audits fairness; `ai.py` runs each computer player from a profile per
difficulty; `textures.py` paints the ground and renders every prop and unit
through `saga2d.render3d`'s front camera; `view.py` keeps sprites in step
with the model and draws the fog, the minimap and the moving water;
`sound.py` synthesises the effects and the marches; `scene.py`, `title.py`
and `tutorial.py` are the saga2d scenes.  The tools: `fuzz_warband.py`
(AI matches with invariants, monkey input), `verify_warband.py` (real
pyglet events with frames to look at), `ai_report.py` (difficulties against
a scripted opening and against each other), `map_report.py` (fairness over
seeds), `perf_warband.py` (frame times of a 150-unit battle),
`soak_warband.py` (whole matches on the real backend) and
`build_warband.py` (versioned standalone builds and Windows installers) and
`verify_warband_package.py` (installed/extracted executable checks). See the
[Mac and Windows play-together guide](docs/warband-play-together.md),
[Windows build guide](docs/windows-warband.md) and
[remote AI guide](docs/warband-remote-ai.md).

## The framework

Saga2D renders sprites and simple shapes on the GPU through pyglet, lays
out a small UI toolkit, and runs a scene stack. Game code never touches
the backend.

This complete example needs no image or sound files:

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
* **UI**: `Label` (reactive: pass a lambda), `Button` (its optional
  `shortcut` owns keyboard input and the visible keycap), `KeyHints`, `Panel`, `Row`, `Column`, `ProgressBar`,
  anchors, flow layout, and a `Theme` with named text styles, corner radii
  and keycap colours.  Text is measured by the backend, so layout fits.
  `Label(text, width=300, wrap=True)` also sizes multiline descriptions and
  moves following controls when text or fonts change. See the independent
  [wrapped-label example](docs/framework-wrapped-label.md).
  `Scene.measure(component)` sizes an unattached tree before choosing where it
  belongs, using the same theme and fonts; see the independent
  [preview example](docs/framework-ui-measurement.md).
  Use `hotkey` for a display-only contextual hint; see
  [button shortcuts](docs/framework-button-shortcuts.md).
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
  `Game.run()` closes automatically; callers driving `tick()` finish with
  `game.close()`. See the [two-session example](docs/framework-game-lifetime.md).
* **Audio** with `master`/`music`/`sfx` channels, pitch variation, mute,
  and a silent driver for tests.

See [DESIGN.md](DESIGN.md) for the architecture and the reasoning behind
the cuts.

## Multiplayer

All three games offer **Online** room creation and code-based joining from **M**
on the title: competitive Tribes and Warband, shared-campaign Shardbound co-op.
The Scaleway server runs the match; players need no router setup. Direct LAN
remains an explicit mode. See [online play and reconnection](docs/online-multiplayer.md)
and [the LAN transport and game interfaces](docs/multiplayer.md).

For a small independent consumer, follow the
[counter-room tutorial](docs/framework-match-menu.md): two counters use the
shared menu, lobby and OnlineClient against a local server. It shows command
ownership, connection handoff, polling under Help and cleanup without importing
a reference game.
