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
maintained.  The test for a new feature is: does Tribes, or an equally
concrete game, need it in exactly this form?

## Layers

```
Game code            tribes/, eador/  — models, AI, art, scenes
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
Screen-space UI is ordered by the scene's position in the stack, so an
overlay always draws above the scene beneath it.  Text at an order draws
above shapes at the same order; shapes at one order draw in call order.

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
draw call regardless of image.

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
already computed from the scene's camera.

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
`draw_keycap`, so the game's hint strip and its buttons agree.

For a key that activates the button itself, `Button(shortcut="E", on_click=...)`
owns both its keycap and activation. It uses the current visible UI tree,
respects enabled ancestors, and needs no scene binding or cleanup when removed.
Exact modifier matching and duplicate-key errors prevent accidental actions.
`hotkey` stays a display-only hint for contextual scene commands; specifying
both is an error. Shardbound's paged relics/save rows, Tribes' recruitment keys,
and Warband's command-card routing exposed the same duplicated binding and
disabled-state checks. The [shortcut example](docs/framework-button-shortcuts.md)
demonstrates the primitive independently of those games.

## Audio ownership

`AudioManager` keeps independent master/music/SFX levels. Changing a level or
muting updates sounds already playing as well as future sounds, preserving
each effect's local gain. The backend owns native effect and music players;
the manager stores opaque playback IDs and gains, pruning ended IDs when it
next plays or adjusts effects. Natural completion releases native resources
and removes the player from the backend on the next event poll. Game teardown
stops all effects and its own music; backend shutdown releases any remaining
players, including music started by another manager.

Tribes' sound bank and Warband's synth bank use their own AudioManagers, while
Shardbound needs live volume and mute settings. A global backend SFX gain would
couple independent banks. Per-manager playback IDs solve that without adding
an audio graph, a settings policy, or new game-facing methods. Mock recordings
keep the original `sounds_played` history and expose current `sounds_playing`
separately. `tools/verify_audio.py` checks native sustained playback, natural
completion and shutdown, using the silent driver by default.

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

Early Access work keeps a second persistence boundary explicit:
`SaveManager` validates the generic file envelope, stages durable atomic
writes and retains one previous file. `load_backup(slot)` opens that
previous file only when requested; it never silently replaces current data.
Both games benefit from safe file I/O without sharing a campaign schema.
`eador.persistence.CampaignSaves` owns three manual slots, three rolling
autosaves, schema compatibility and the saved-state descriptions shown in
Shardbound's browser. Sites, skills, relics and unresolved choices stay in
`eador.content` and its model. These are game rules rather than generic
framework quest, equipment or progression systems.

Scene reliability is likewise shared: an input batch stops applying old
events after a scene transition is requested, and failed scene startup
releases acquired resources without calling an exit hook on a partially
initialized scene. Game startup and teardown preserve the original failure
while releasing the window and singleton. Independent integration tests
exercise these guarantees without either game's models.

The framework owns geometry and presentation mechanics. It has no province,
economy, hero, army, spell, turn, combat, faction or victory abstraction.
Both rule modules run without a window, and only import Saga2D's pure
`HexGrid` utility. The [cookbook](docs/framework-hexgrid.md) demonstrates that
primitive without importing either reference game. The
[research and scope](docs/eador-research.md) explains which Eador systems
this compact implementation preserves and simplifies.
