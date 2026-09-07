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
order; sprites with `y_sort=True` add their bottom edge inside the band,
in steps of `Y_SORT_STEP` (eight units).  Every distinct order is a batch
group in pyglet and a moving sprite migrates between groups as its order
changes, so a step of one pixel made a 150-unit battle spend most of its
frame re-sorting groups; eight is invisible on 32-unit tiles and cheap.  The backend also
uploads a view matrix only when consecutive groups need different ones.
Three more things keep a 150-unit battle under 16 ms: pyglet's per-call GL
error checking is off (`saga2d/__init__.py` sets `debug_gl` before
`pyglet.gl` loads; a frame makes thousands of GL calls), `draw_image`
reuses a pool of pyglet sprites in call order instead of allocating one
per call per frame (a HUD draws the same portraits every frame), and a
sprite's appearance setters only reach the backend when the value
changed (views set `visible`/`opacity` every frame for every unit).
`saga2d.testing.assert_no_text_overlap(game, top_scene_only=True)` fails a
mock-backed frame in which one text is drawn over another, using the same
`measure_text` numbers the layout used; a game sweeps every screen through
it at the window sizes players have (`tests/warband/test_layout.py`), which
is how a tagline landing on a menu button and a codex column running into
the next were caught.  On a Mac the pyglet backend reports Control+click
as the right button, the platform's secondary click, so games need no
trackpad special case of their own.
`saga2d.testing.FrameTimer` measures the frame breakdown (wrap the phases,
time frames, print the report; `tools/perf_warband.py` is its use); time
frames with it before claiming numbers, and never under a profiler or
`tracemalloc`, which slow tight Python loops several times over and shift
the blame.  `ParticleEmitter.burst` and `continuous` return the emitter,
so a view builds and starts one in a single expression.
Screen-space UI is ordered by the scene's position in the stack (with a
stride of four orders per level), so an overlay always draws above the
scene beneath it.  Text at an order draws above shapes and images at the
same order, images above shapes; shapes at one order draw in call order.
The spare orders inside a level let a component put a shape over an image
it drew (the minimap's viewport frame).

`with scene.screen_layer(1):` groups immediate screen drawing above the
default layer zero. The scope applies through game drawing helpers and
paragraphs, restores after nesting or failure, and does not change world
`RenderLayer` or retained sprites. Local layers are bounded to 0–999 so they
cannot escape their scene. Controls draw above all local layers; children and
later UI siblings paint above earlier ones, matching mouse dispatch. A modal
scene remains above all content below it and owns its input independently.

Shardbound's stationary damage pill and Tribes' floating text/toast panels
need shapes to cover earlier text. Warband's committed Minimap needs a frame
above its image. The private scene stride builds on that Warband change;
each UI component keeps four suborders, preserving its frame-at-`order + 1`
composition while keeping later siblings above it. There is no popup manager
or tactical effect in the framework. See the [screen layer example](docs/framework-screen-layers.md).

## Window display

`Game.set_fullscreen(bool)` adopts the committed Warband interface. Together
with `set_window_size((width, height))` and the read-only `fullscreen` and
`window_size` properties, it gives Warband, Shardbound and Tribes one small
display seam. Games choose their presets, shortcuts and persistence policy.
There is no second window manager or framework settings screen.

Window size changes and OS border dragging retain the logical resolution,
camera coordinates and UI layout. Selecting a size leaves fullscreen;
toggling fullscreen restores the last actual windowed size. The native window
is now resizable. Getters report actual backend state, including OS size
constraints, rather than the last request. The mock exposes the same behavior
and `inject_resize` for OS-resize journeys.

The Pyglet adapter contains the native details: desktop fullscreen, Cocoa
content-point/backing-pixel normalization, projection refresh after context
recreation, and clipping all drawing to the letterboxed canvas. A native
reproduction showed the unnormalized toggle doubling a Retina window's size;
image assertions caught stale fullscreen projection and drawing in the bars.
The independent [display example](docs/framework-display.md) checks native
UI and world picking, retained sprites, screenshots and actual size restoration.
This is physical presentation of one canvas, not logical resizing or a text
scaling implementation.

## Retained sprites, immediate shapes

`Sprite` is retained: the backend keeps a GPU sprite and is only told
about changes.  `draw_rect` / `draw_circle` / `draw_line` /
`draw_polygon` / `draw_text` / `draw_image` are immediate: re-issued
every frame from `Scene.draw()` or a UI component.  The pyglet backend
batches all immediate shapes at one order into a single triangle list
and caches text labels across frames keyed by their content, so a HUD
with dozens of labels and a few hundred highlight rectangles renders in
a couple of milliseconds.

Text measurement caches physical glyph dimensions at the rounded raster size;
logical dimensions are calculated using the current viewport scale at return.
Caching the already-divided result would conflate different logical font sizes
after a resize. The independent `tools/verify_text_measurement.py` regression
compares warm and fresh windows, including exact wrapped-flow pixels and native
clicks in both directions.

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

`Game.run(scene, fps=60)` sleeps for the unused part of each frame instead of
spinning. Inactive or hidden windows are limited to 15 FPS; a lower chosen cap
also applies there. Focus and show/hide notifications use the existing backend
event queue, including minimization and restoration. Rendering and VSync time
count toward the interval, and slow frames do not create catch-up bursts.
Elapsed time continues to drive animation and timers at either rate.
`tick(dt)` still advances exactly one unpaced frame for embedding and deterministic
tests; those callers own their pacing. No game has to write a sleep loop.
See the independent [frame-pacing example](docs/framework-frame-pacing.md).

`Game.close()` owns final scene/resource cleanup and backend shutdown for
callers that drive explicit ticks. `run()` and `render_scene()` use the same
operation; ordinary launchers need no additional call. Scene cleanup failures
still propagate after the backend is closed. `quit()` only requests loop exit,
so an input callback does not tear resources out from under its current frame.
Independent display, wrapping and measurement checks previously duplicated
private teardown and backend-close calls, sometimes missing window cleanup.
The [two-session example](docs/framework-game-lifetime.md) demonstrates the
single public operation without a new lifecycle manager or game policy.

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

`Label(text, width=300, wrap=True)` opts into measured multiline text whose
preferred height participates in ordinary flow layout. Shardbound's reward
card descriptions and Warband's width-390 tutorial objective need the next
control to follow the complete text, including after reactive text or font
changes. Immediate paragraphs and retained labels share one private layout
helper. A private preparation hook runs at existing input/draw layout
boundaries, including visible paused scenes; games acquire no new lifecycle
or manual invalidation requirement. Default single-line Labels stay unchanged.
Width and maximum screen content remain the game's choice. See the independent
[wrapped-label example](docs/framework-wrapped-label.md).

`Scene.measure(component)` returns an unattached tree's preferred size using
the scene's current theme, font metrics and viewport scale. It removes the
temporary attach/measure/remove sequence needed by Shardbound's complete save
rows and rival force layout. It neither parents the tree nor registers input;
the measurement context is released even when content evaluation raises.
Already owned trees are rejected instead of being borrowed from another scene.
Games still choose widths, content budgets, pagination and placement. The
independent [preview example](docs/framework-ui-measurement.md) positions a
variable-height card before adding it to the UI.

For a key that activates the button itself, `Button(shortcut="E", on_click=...)`
owns both its keycap and activation. It uses the current visible UI tree,
respects enabled ancestors, and needs no scene binding or cleanup when removed.
Exact modifier matching and duplicate-key errors prevent accidental actions.
`hotkey` stays a display-only hint for contextual scene commands; specifying
both is an error. Shardbound's paged relics/save rows, Tribes' recruitment keys,
and Warband's command-card routing exposed the same duplicated binding and
disabled-state checks. The [shortcut example](docs/framework-button-shortcuts.md)
demonstrates the primitive independently of those games.

## Persistent preferences

`Settings` persists a game's preferences independently of campaign saves.
Warband's committed mapping/defaults interface is shared through
`game.settings(defaults, validator=...)` and `game.data_dir`. Tribes' volume
options, Warband's display/audio preferences and Shardbound's accessibility
settings need the same file lifecycle, while their ranges, enums and runtime
effects remain game code. Known keys retain their JSON kind; a game validator
can reject its own invalid values without declaring an options schema.

Loading errors are explicit on `settings.error`; defaults remain usable in
memory so the game can present recovery. Ordinary save refuses damaged data.
Reset stays in memory until save, which retains the displaced file's exact
bytes under a unique recovery name. Save slots and settings share only private
durable file staging/replacement in `_fileio.py`; each owns its validation and
backup policy. See [the settings guide](docs/framework-settings.md) and the
independent `tools/demo_settings.py` example.

## Audio ownership

`saga2d.synth` provides pure sample composition and WAV export. Tribes and
Warband had the same tone/noise/envelope/mix code; Shardbound needs original
assets generated before packaging. Tribes now imports those helpers while
retaining its compositions and cache. Shardbound will use the same functions
at build time and ordinary `game.audio` playback at runtime. These functions
need no Game or resource lifetime. The framework does not choose cue names,
music transitions or caching policy. See the independent
[synthesis example](docs/framework-synth.md).

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
`inject_scroll`, `inject_drag`). Tests drive `game.tick(dt)` and assert
on model state and recorded draws. Focused checks run without a GPU; the full
suite also includes longer campaign and content journeys.

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
* `synth` — `tone`, `noise`, `thump`, `mix`, `level`, `pan` and
  `write_wav`: pure synthesis shared by every game.  Each game owns its bank
  (which names it renders to WAV, the version marker, playback through its
  `AudioManager`): Tribes' D-major bank in `tribes/sound.py`, Warband's
  A-minor `SynthBank` in `warband/sound.py`.  The two banks are alike; if a
  third game wants one, that is the moment to lift it back into saga2d.
* `fonts` — Nunito in three weights, one family per weight because pyglet
  cannot pick a weight out of a variable font.
* `settings` — a JSON preferences file with defaults that keeps working
  when the file is corrupt; `Game.settings(defaults)` puts it in the game's
  `data_dir` next to the saves.  Save slots may be names as well as numbers
  (`"autosave"`, `"quick"`), carry a `summary` from `Scene.get_save_summary`
  for save browsers, and `list_slots` reports a corrupt file instead of
  raising, so a browser can say so.  `Game.set_fullscreen` toggles the
  window; `Toast(top=)` keeps notices clear of a game's own strips.

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

`eador/` is an Eador-inspired game with linked shard campaigns: a province economy and
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

## Multiplayer transport

`MatchHost` and `MatchClient` provide a two-seat host/join session. Nonblocking
TCP, bounded length-prefixed JSON messages, version/room checks, connection
health, command rejection and snapshot delivery belong to Saga2D. Polling is
explicit, so tests use actual loopback sockets without a window or threads.
The host assigns seats and never trusts a player id supplied by the guest.

The game supplies `apply(player, command)` and `snapshot(player)`, raises
`CommandError` for an expected invalid order, and publishes after autonomous
simulation. Unexpected implementation errors propagate. Optional revision
checks reject orders based on obsolete turn state. A guest can reconnect with
the same room token; the host sends its current snapshot. Games pause whenever
the session is not ready and own the session lifetime alongside their scene.

Commands, snapshot schemas, fog, turns, simulation clocks, AI, faction ownership
and victory remain in each game. The transport does not call arbitrary model
methods, deserialize Python objects, or prescribe lockstep to an RTS.

A session also exposed a concrete scene-lifetime distinction: `on_exit` runs
when an overlay covers a scene, so it cannot close a match connection.
`Scene.on_close` runs on permanent removal or failed entry, before detaching
and releasing owned rendering resources. All three network scenes use it;
the existing scene-owned timer keeps network traffic moving under menus.

`MatchMenu` and `MatchLobby` share address/code entry and the handoff into a
game-supplied scene. `tribes.multiplayer` validates alternating faction orders;
`warband.multiplayer` runs a host-owned fixed-step clock and sends numbered
feedback events; `eador.multiplayer` serializes both partners' orders into one
shared campaign and refreshes its map/battle/progression screens. These adapters
reuse each game's existing model and views. See [multiplayer](docs/multiplayer.md)
for launch instructions, supported modes and transport limits.

`OnlineClient` implements the same polled session interface for both players
against a dedicated server. One asynchronous worker owns DNS, TLS, WebSocket
I/O and reconnects; `poll()` delivers state on the game thread. Private seat
credentials permit automatic recovery without replaying uncertain commands.
Online room-code entry is the default and explicit LAN keeps the original
transport. The shared menu accepts JSON creation options so an online creator
never constructs a local authoritative model.

The deployable `online_server` package composes the existing game matches.
Its room loop owns player identity, admission, revisions, bounded input and
private reconnect credentials. Independent writers coalesce queued snapshots;
a slow connection cannot stall another match. Only Warband advances at 20 Hz,
and publishes at 10 Hz while both seats are connected. The catalog validates
bounded map options and restores each game's JSON state. A private SQLite
store retains room checkpoints across process restarts and expires disconnected
rooms. This deployment package imports the games; Saga2D itself still has no
game rules. See [online play](docs/online-multiplayer.md).
