# Saga2D — Design

## Scope

Saga2D does the part of a 2D game that is the same in every 2D game:
put images and shapes on the screen in a defined order, move a camera
over them, lay out a HUD, route input, and run a stack of scenes.  The
game owns its world model, rules, AI and art.

The framework used to promise much more (drag-and-drop, palette swaps, a
settings screen, sound pools, a HUD layer that survives scene changes,
snapshot tooling, thirteen UI widgets).  Each of those was either vague
enough that no game exercised it or specific enough that the one game
that needed it would rather own it.  They were deleted rather than
maintained.  The test for a new feature is: does Tribes or Warband, or an
equally concrete game, need it in exactly this form?  A piece both games
need in the same form is the strongest case, and that is how the renderer,
the effects, the sound synth, the font and the minimap got in.

## Layers

```
Game code            tribes/, warband/, eador/  — models, AI, art, scenes
Shared game pieces   render3d, effects, synth, fonts, hexgrid, ui.Minimap
Scene toolkit        Scene, SceneStack, Camera, Sprite, actions, particles, UI
Backend protocol     saga2d/backends/base.py
Backends             pyglet (GPU)   mock (records calls)
```

Game code imports from `saga2d` only.  The backend is chosen by name in
`Game(...)`; nothing above it knows which one is running.

## Coordinates and draw order

Framework coordinates are y-down with the origin at the top-left.  There
are two spaces:

* **screen** — logical pixels of the window (`Game(resolution=...)`).
  UI lives here.
* **world** — the same units, transformed by the active scene's
  `Camera`: `screen = (world - camera.offset) * camera.zoom`.

The pyglet backend applies the camera as a view matrix on a render group,
so scrolling and zooming cost nothing per sprite.  Text is rasterised at
physical pixel size and positioned in physical pixels, so it stays sharp
on HiDPI displays at every zoom.  `Camera.zoom_toward` eases towards a
target about a fixed screen point; scroll events carry fractional wheel
lines (trackpads send many small ones), so a scene scales the target by
a per-line factor instead of stepping per event.

Every draw call carries an integer `order`; lower draws first.  World
content draws before screen content.  Inside the world, `RenderLayer`
bands (`BACKGROUND < OBJECTS < UNITS < EFFECTS < UI_WORLD`) set the
order; sprites with `y_sort=True` add their bottom edge inside the band.
Screen-space UI is ordered by the scene's position in the stack (with a
stride of four orders per level), so an overlay always draws above the
scene beneath it.  Text at an order draws above shapes and images at the
same order, images above shapes; shapes at one order draw in call order.
The spare orders inside a level let a component put a shape over an image
it drew (the minimap's viewport frame).

## Retained sprites, immediate shapes

`Sprite` is retained: the backend keeps a GPU sprite and is only told
about changes.  `draw_rect` / `draw_circle` / `draw_line` /
`draw_polygon` / `draw_text` / `draw_image` are immediate: re-issued
every frame from `Scene.draw()` or a UI component.  The pyglet backend
batches all immediate shapes at one order into a single triangle list
and caches text labels across frames keyed by their content, so a HUD
with dozens of labels and a few hundred highlight rectangles renders in
a couple of milliseconds.

Textures are packed into one atlas, so sprites at the same order share a
draw call regardless of image.  An image registered from PIL can be
redrawn in place (`assets.update_image`); every sprite showing it changes
with it, which is how Warband draws fog of war — one pixel per tile,
stretched over the map, bilinear filtering supplying the soft edges — and
its minimap.

## Frame

`Game.tick(dt)`:

1. Poll backend events; a window close sets `running = False`.
2. Dispatch each input event to the top scene: UI tree, then camera key
   scroll, then `controls` / `bind_key` handlers, then `handle_input`,
   then `pop_on_cancel`.
3. `update(dt)` on the top scene (and the scenes below it while
   `pause_below` is false), then the UI tree.
4. Actions, particles, timers, tweens, frame animation.
5. Camera update; the backend receives the camera offset and zoom.
6. Clear with the base scene's `background_color`; draw every visible
   scene bottom-up (`draw()` then its UI).

Scene-stack operations requested during steps 2–3 are queued and applied
after the phase, so a scene never mutates the stack under itself.

## Scenes own their resources

`Scene.add_sprite`, `add_emitter`, `after`, `every` register resources
the scene owns; they are released when the scene leaves the stack, and
survive while it is covered by an overlay.  Everything else (module-level
`_current_game`, the tween manager) is process-global so game code can
write `Sprite(...)` without threading a game object through every call.

## Input

Keys are plain lowercase names (`"a"`, `"space"`, `"escape"`, `"f5"`).
`Scene.controls` maps a key, a tuple of aliases, or a chord like
`"ctrl+s"` to a method name; the mapping is validated when the class is
defined.  A handler with a required positional parameter receives the
`InputEvent`, one without is called bare.  Chords are tried before the
bare key.  Mouse events reach `handle_input` with `world_x`/`world_y`
already computed from the scene's camera, and with the modifier keys held
(shift-click adds to a selection, ctrl-drag differs from a drag).

## UI

Components form a tree under `Scene.ui`.  Each computes a preferred size
(labels ask the backend to measure text), is placed by an `Anchor`
inside its parent or by a `Panel`'s flow layout, hit-tests its rectangle,
and draws itself before its children.  `Label` and `ProgressBar` accept
callables and re-evaluate them every frame, which removes the usual
"update the label after every state change" plumbing.  `Theme` holds the
colours, paddings, corner radii and named `TextStyle`s; a `TextStyle`
names a font family, and a weight is simply another family (a bundled
"Nunito SemiBold" file), which is the one mechanism every backend has.
Hotkeys are drawn as keycaps: `Button(hotkey="E")` and `KeyHints` share
`draw_keycap`, so the game's hint strip and its buttons agree.  `Minimap`
draws a game-supplied image with the camera's viewport framed over it and
turns clicks and drags into world coordinates.

## Testing

The mock backend records every call (`backend.sprites`, `rects`,
`texts`, `camera`, ...) and injects input (`inject_key`, `inject_click`,
`inject_scroll`, `inject_drag`).  Tests drive `game.tick(dt)` and assert
on model state and recorded draws; the whole suite runs headless in well
under a second.

Mock tests prove logic, not pixels.  `saga2d.testing.render_scene`
renders through the real pyglet backend into a hidden window and returns
a PIL image — look at it before shipping a visual change.  Real event
dispatch can be exercised the same way with `window.dispatch_event`.
Sound never reaches the speakers from tests or verification scripts:
the mock backend only records `play_sound` calls, and the pyglet backend
selects pyglet's silent audio driver when `SAGA2D_SILENT=1` (or
`SAGA2D_HEADLESS=1`) is set, still running the real load/play/stop path.

## Pieces two games share

* `render3d` — a Pillow software renderer for low-poly meshes: boxes,
  pyramids, cones, cylinders, spheres, gable roofs, flat and camera-facing
  faces; one directional light, back-to-front sorting, supersampled
  rasterisation.  A `Projection` says where the camera stands:
  `Projection.dimetric()` is Tribes' isometric view, `Projection.front()`
  Warband's 3/4 view with square tile footprints, so a 3×3 building covers
  3×3 tiles and still shows lit walls.  Both games pre-render tiles, props,
  buildings and units with it at the display's pixel density.
* `effects` — `Effect`/`Effects` and the transient animations every game
  wants: floating text, pulses, particle bursts, hit flashes with knockback,
  dissolves, a turn banner and a toast.  They draw through the scene's
  helpers and the theme's text styles, so they look like the game they run in.
* `synth` — `tone`, `noise`, `thump`, `mix`, `level`, `pan` and a
  `SynthBank` that renders a game's generators to WAV once (versioned) and
  plays them through an `AudioManager`.  Tribes' D-major bank and Warband's
  A-minor bank are each a page of generators.
* `fonts` — Nunito in three weights, one family per weight because pyglet
  cannot pick a weight out of a variable font.

## Warband as the second reference game

`warband/model.py` is a 20 Hz fixed-step simulation: units with a queue of
orders (move, attack-move, attack, harvest, deposit, build, hold), gold
mining and tree felling, construction with a builder hidden inside the
site, training queues and rally points, supply from farms, towers that
shoot on their own, damage rolls, an under-attack alert per cooldown, fog
of war as per-player visible and explored grids, elimination and JSON
saves.  `path.py` is bounded A* that walks up to unreachable goals, which
is exactly what approaching a building or a tree needs.  The scene
accumulates frame time and steps the world in whole `SIM_DT`s, running the
AI brains between steps, so the game is deterministic for a seed
regardless of frame rate.  Two movement deadlocks the fuzz found — head-on
collisions the symmetric separation push could never resolve, and paths
made stale by a building placed across them — are why walking units
sidestep to their right and re-plan when their next tile is no longer
adjacent or passable.  `tools/fuzz_warband.py` plays AI-vs-AI games with
world invariants and a stall check, and feeds the scene random input.

## Tribes as the reference game

`tribes/model.py` is the game: tiles, cities, units, tribes and every
rule (movement with terrain and zone of control, the Polytopia combat
formula, capture, harvest and city growth, research, turn order, healing,
elimination, score, JSON serialisation).  It has no saga2d imports, so
the AI and the tests use it directly.  `tribes/view.py` lays the grid out
isometrically and reconciles sprites with the model; `tribes/textures.py`
pre-renders the low-poly blocks and props with `saga2d.render3d`; `tribes/effects.py`
holds transient animations; `tribes/sound.py` synthesises audio;
`tribes/scene.py` and `tribes/title.py` turn input into model calls.

## Shardbound and the abstraction test

`eador/` is an Eador-inspired single-shard game: a province economy and
hero army feed into separate tactical battles, then receive casualties,
experience and rewards. `model.py` owns campaign rules and serialization;
`battle.py` owns tactical rules, exact damage previews and enemy decisions;
`scene.py` translates input and presents the campaign, battle and overlays;
`art.py` draws original miniatures using ordinary Scene primitives.

Building a second type of strategy game justified two small additions:

* `HexGrid` combines axial geometry, picking, neighbors and weighted search.
  A finite set of cells defines either a province map or a battlefield.
  Callers supply blockers and the cost of entering cells. The same search
  powers movement ranges and routes without knowing armies or terrain.
* `Scene.draw_paragraph` measures the actual font, wraps words to a pixel
  width, preserves paragraph breaks and returns the consumed height.
  Guide text and recruitment descriptions exposed the need: character-count
  wrapping overflowed their panels in real screenshots.

Everything else uses existing scenes, buttons, input dispatch, draw helpers
and save slots. Results are transparent scenes, so they cover underlying
text and route input correctly without custom render orders. Campaign saves
include a pending battle; applying its result clears it exactly once.

The framework owns geometry and presentation mechanics. It has no province,
economy, hero, army, spell, turn, combat, faction or victory abstraction.
Both rule modules run without a window, and only import Saga2D's pure
`HexGrid` utility. The [cookbook](docs/framework-hexgrid.md) demonstrates that
primitive without importing either reference game. The
[research and scope](docs/eador-research.md) explains which Eador systems
this compact implementation preserves and simplifies.
