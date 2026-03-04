# EasyGame Engine — Design Document

## Vision

A Python framework where the developer writes **game logic**, not engine plumbing.

Target: 2D games with sprites, animations, and UI-heavy screens. The framework handles
everything that is common across games: rendering sprites in layers, animating them,
playing sounds, composing UI screens, managing scenes, and loading assets. The developer
writes what makes their game unique.

Reference games that should be **buildable** with this framework (not that the framework
contains their specific mechanics): Heroes of Might and Magic 2, Disciples, Warcraft 2,
Baldur's Gate. These span turn-based strategy, real-time strategy, and party-based RPG —
the common denominator across all of them defines what belongs in the framework.

### What belongs in the framework vs. the game

**The test:** If Baldur's Gate, Heroes 2, AND Warcraft 2 all need it in essentially the
same way, it's framework. If only one genre needs it, or the games need fundamentally
different versions of it, it's game code that builds on framework primitives.

| Framework (common to all)             | Game code (uses framework primitives)       |
|---------------------------------------|---------------------------------------------|
| Sprites with animation                | Tile maps (strategy) vs. free-scroll (RPG)  |
| Render layers, y-sorting              | Fog of war rules                            |
| UI components, layout, theming        | Campaign progression                        |
| Scene stack                           | Pathfinding strategy (A* vs navmesh)        |
| Asset loading (images, sounds, fonts) | Building placement                          |
| Input action mapping                  | Control groups                              |
| Audio channels, music, crossfade      | Combat systems, AI                          |
| Camera / viewport                     | Save state schema (what to persist)         |
| Tweening, timers                      | Inventory / equipment logic                 |
| Color/palette swaps                   | Tech trees, resource systems                |
| Drag-and-drop in UI                   | Game speed rules                            |
| Cursor management                     | Entity-specific state machines              |

### Principles

1. **No boilerplate.** A game with a title screen and a menu is < 20 lines.
2. **Good defaults, optional overrides.** Fullscreen, centered UI, standard settings
   screen — all automatic. Everything can be customized, nothing must be.
3. **Progressive disclosure.** Simple things are one line. Complex things are possible
   but not required upfront.
4. **Backend-agnostic.** The public API never exposes backend types. The first backend
   can be swapped or replaced without changing game code.
5. **AI-art friendly.** Assets are PNGs, sprite sheets, and WAV/OGG files. No proprietary
   formats, no toolchain dependencies.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│  Game Code (user writes this)                   │
├─────────────────────────────────────────────────┤
│  Utilities                                      │
│    Timers, Tweening, State Machine              │
├─────────────────────────────────────────────────┤
│  Sprites & Animation                            │
│    Sprite, AnimationDef, Render Layers, Camera  │
├─────────────────────────────────────────────────┤
│  UI Components                                  │
│    Panel, Button, Label, List, Grid, TextBox    │
├─────────────────────────────────────────────────┤
│  Core                                           │
│    Game, Scene, SceneStack, Assets, Input, Audio│
├─────────────────────────────────────────────────┤
│  Backend (hidden)                               │
│    GPU-accelerated renderer (see BACKEND.md)    │
└─────────────────────────────────────────────────┘
```

Each layer depends only on layers below it. Game code can reach into any layer.

Note: there is no "TileMap" or "World" layer. Tile grids, hex grids, free-scrolling
backgrounds — these are game-level constructs built on the framework's sprites, camera,
and rendering. The framework provides the rendering and interaction primitives; the game
decides its world model.

---

## Backend

### Motivation

The framework must not leak backend types into the public API. This allows swapping
renderers without changing game code, and keeps the user-facing API clean and focused
on game concepts.

### Responsibilities

- Window creation and fullscreen management
- Surface/texture creation, blitting, scaling
- Event polling (keyboard, mouse, window)
- Audio device initialization and playback
- Font loading and text rendering to surface
- Frame timing (clock, delta time)

### Design

A `Backend` protocol defines all operations the framework needs from the rendering/audio
layer. The backend is selected once at `Game` creation and never referenced directly by
game code. See `BACKEND.md` for implementation details and backend choice rationale.

```python
# User never sees this. The Game object owns the backend.
class Backend(Protocol):
    # Lifecycle
    def create_window(self, width: int, height: int, fullscreen: bool) -> None: ...
    def begin_frame(self) -> None: ...
    def end_frame(self) -> None: ...       # submit batched draws + present

    # Rendering
    def load_image(self, path: Path) -> ImageHandle: ...
    def draw_image(self, handle: ImageHandle, x: int, y: int, ...) -> None: ...
    def draw_text(self, text: str, font: FontHandle, x: int, y: int, ...) -> None: ...

    # Audio
    def load_sound(self, path: Path) -> SoundHandle: ...
    def play_sound(self, handle: SoundHandle) -> None: ...

    # Input
    def poll_events(self) -> list[Event]: ...
```

`ImageHandle`, `SoundHandle`, `FontHandle` are opaque types — the framework passes them
around but never inspects their internals. This is how backend independence works.

The `begin_frame` / `end_frame` pattern allows GPU backends to batch all draw calls
and submit them in a single GPU operation, while CPU backends can draw immediately.
Same interface, radically different performance characteristics.

---

## Core

### Game

The top-level object. Created once. Owns the backend, the scene stack, the asset
manager, and the audio system.

```python
game = Game(
    title="My Game",
    # Everything below is optional with good defaults
    background="parchment.png",    # default background for all scenes
    resolution=(1920, 1080),       # logical coordinate space
    fullscreen=True,               # default: True
    backend="pyglet",              # default backend
)
game.run(start_scene=MainMenu())
```

**Logical resolution is a coordinate system, not a render target.** The game thinks in
a fixed coordinate space (e.g. 1920x1080) for positioning, layout, and anchoring. But
rendering happens at the display's native physical resolution. This distinction matters:

- **Text** is rasterized at native pixel density — always sharp, even on retina displays.
  A "font size 16" in logical coordinates becomes 32pt on a 2x display.
- **UI elements** (panels, borders, progress bars) are drawn at native resolution.
- **Sprites** are drawn at their actual pixel size. The asset manager supports resolution
  variants (`knight.png` for 1x, `knight@2x.png` for retina) and selects automatically.
  Pixel art uses nearest-neighbor scaling (crispy pixels). Painted/AI art uses linear
  filtering (smooth scaling).

The coordinate system ensures layout code works identically on every monitor. The
native-resolution rendering ensures everything looks sharp. These are separate concerns
— the framework handles both.

The `Game` object also auto-provides:
- A **Settings scene** (accessible via ESC or a standard key) with volume and
  keybinding options. The developer does not build this.
- Graceful quit handling.

### Scene & SceneStack

A Scene is a self-contained game state: title screen, world map, battle, inventory,
dialogue. The SceneStack manages what's active.

```python
class Scene:
    def on_enter(self) -> None: ...          # called when scene becomes active
    def on_exit(self) -> None: ...           # called when scene is removed/covered
    def on_reveal(self) -> None: ...         # called when scene above it is popped
    def update(self, dt: float) -> None: ... # called every frame
    def draw(self, ctx: DrawContext) -> None: ...
    def handle_input(self, event: InputEvent) -> bool: ...  # return True = consumed
```

SceneStack operations:
- `push(scene)` — new scene on top (e.g. open inventory over world map)
- `pop()` — return to previous scene
- `replace(scene)` — swap current scene (e.g. main menu → game)
- `clear_and_push(scene)` — start fresh (e.g. return to title)

**Motivation:** The push/pop model is essential for modal UI. In Heroes 2, clicking a
town pushes the town screen; closing it pops back to the adventure map. In Baldur's
Gate, opening the inventory pushes it over the game world. In Warcraft 2, opening the
menu pushes a pause overlay. Without a scene stack, developers manually track "which
screen am I on" with flags — a common source of bugs.

Scenes below the top of the stack can optionally still be drawn (transparent overlay)
and optionally still receive update ticks (background animation continues). This is
controlled by two scene properties: `transparent: bool` and `pause_below: bool`.

### Assets

Convention-based asset loading. Drop files in a known directory structure:

```
assets/
  images/
    backgrounds/
    sprites/
    ui/
  sounds/
  music/
  fonts/
```

Load by name, not path:

```python
# Loads assets/images/sprites/knight.png (or knight/ directory with frames)
sprite_img = game.assets.image("sprites/knight")

# Loads assets/sounds/sword_hit.wav
game.assets.sound("sword_hit")
```

The asset manager handles:
- Caching (load once, return same handle)
- Sprite sheet slicing (via companion .json or naming convention: `knight_walk_01.png`)
- Resolution variants: loads `knight@2x.png` on retina displays if available,
  falls back to `knight.png` with upscaling
- Scaling mode per asset: `nearest` for pixel art (crispy), `linear` for painted/AI art
  (smooth). Default is `linear`; pixel art games set `nearest` globally in Game config.
- Missing asset errors with clear messages

**Motivation:** Typical game library tutorials start with manual image load calls and path
construction. This is noise. A convention-based loader eliminates it and makes the
project structure predictable. The companion JSON for sprite sheets is compatible with
tools like Aseprite and TexturePacker, and with AI-generated sprite sheets that follow
a grid layout. Resolution variant support means the same game code runs sharp on both
a 1080p monitor and a 5K retina display.

### Input

Input is mapped to **actions**, not raw keys. The engine provides a default mapping
and the settings screen lets players rebind.

```python
# Engine provides standard actions:
#   "confirm", "cancel", "menu", "up", "down", "left", "right",
#   "scroll_up", "scroll_down"
# Game defines custom actions:
game.input.bind("attack", Key.A)
game.input.bind("build", Key.B)

# In scene:
def handle_input(self, event: InputEvent) -> bool:
    if event.action == "confirm":
        self.select_current()
        return True
```

Mouse input is separate: `click(pos, button)`, `hover(pos)`, `drag(start, end)`,
`scroll(direction)`. UI components consume mouse events before the scene sees them
(standard event bubbling).

**Motivation:** Raw key handling scatters `if event.key == K_RETURN` checks everywhere
and makes rebinding impossible. Action mapping is standard in engines (Unity, Godot)
because it decouples intent from physical input.

### Audio

```python
game.audio.play_sound("sword_hit")            # fire and forget
game.audio.play_music("battle_theme")          # loops by default
game.audio.crossfade_music("victory", 1.0)     # crossfade over 1 second
game.audio.set_volume(channel="music", level=0.7)
```

Channels: `master`, `music`, `sfx`, `ui`. Volumes multiply down (master * channel).

Sound pools — playing a random sound from a set without immediate repeats:

```python
game.audio.register_pool("knight_ack", ["knight_ack_01", "knight_ack_02", "knight_ack_03"])
game.audio.play_pool("knight_ack")         # random from pool, no immediate repeat
```

**Motivation:** Low-level audio libraries require manual channel management and have no
crossfade. These are universal needs. The channel model matches what players expect in
settings. Sound pools are needed by every game that has more than one voice clip per
character — it's a small feature that eliminates scattered `random.choice()` calls.

---

## UI Components

### Motivation

Every game has menus, dialogs, inventory screens, and HUD elements. Building these from
raw draw calls is the #1 source of boilerplate in game libraries. The framework provides
composable UI components with a layout system, so the developer describes *what* they
want, not *where every pixel goes*.

### Layout Model

UI components are positioned using **anchoring** and **flow layout**, not absolute
pixel coordinates.

**Anchoring:** Place a component relative to its parent or the screen.
```python
# Centered on screen
Panel(anchor=Anchor.CENTER, width=400, height=300)

# Bottom-right corner with margin
Panel(anchor=Anchor.BOTTOM_RIGHT, margin=10)

# Top bar spanning full width
Panel(anchor=Anchor.TOP, width="100%", height=48)
```

**Flow layout:** Children inside a container are arranged automatically.
```python
panel = Panel(anchor=Anchor.CENTER, width=400, layout=Layout.VERTICAL, spacing=12)
panel.add(Label("Choose your class:"))
panel.add(Button("Warrior", on_click=pick_warrior))
panel.add(Button("Mage", on_click=pick_mage))
panel.add(Button("Rogue", on_click=pick_rogue))
```

**Motivation:** Absolute positioning breaks on different resolutions and requires manual
arithmetic for centering. Anchoring solves 90% of game UI layout (HUD corners, centered
menus, side panels). Flow layout handles the rest (lists of buttons, inventory grids).
This is not a full CSS box model — intentionally simpler, because game UI is simpler.

### Standard Components

| Component     | Purpose                         | Example Use                         |
|---------------|--------------------------------|-------------------------------------|
| `Label`       | Static text, styled            | "Gold: 500", dialogue text          |
| `Button`      | Clickable, hover/press states  | Menu items, action buttons          |
| `Panel`       | Container with background      | Inventory window, dialog box        |
| `ImageBox`    | Display an image               | Character portrait, item icon       |
| `List`        | Scrollable list of items       | Save game list, unit roster         |
| `Grid`        | Grid of cells                  | Inventory grid, spell book          |
| `ProgressBar` | Filled bar                     | Health, mana, build progress        |
| `TextBox`     | Multi-line styled text         | Dialogue, event log, story text     |
| `Tooltip`     | Hover popup                    | Item description, unit stats        |
| `TabGroup`    | Tabbed container               | Different inventory categories      |
| `DataTable`   | Rows + columns with headers    | Stats overview, comparison table    |

All components support:
- `visible: bool` — show/hide without removing
- `enabled: bool` — grayed out, non-interactive
- `style: Style` — background image/color, border, font, text color, padding
- `on_click`, `on_hover`, `on_focus` callbacks
- Transition animations (fade in/out, slide) via built-in presets

### Drag-and-Drop

UI-level drag-and-drop is a framework concern because every game with an inventory,
equipment screen, or slot-based management needs it (Baldur's Gate paper doll, Heroes 2
army slots, Warcraft 2 is the exception but even it has build queues).

```python
# Any component can be a drag source
slot = ImageBox(icon, draggable=True, drag_data=item)

# Any container can be a drop target
inventory_grid = Grid(
    columns=4, rows=3,
    drop_accept=lambda data: isinstance(data, Item),
    on_drop=lambda cell, data: equip_item(cell.index, data),
)
```

Visual feedback: dragged item follows cursor as semi-transparent ghost.
Drop targets highlight (green=valid, red=invalid) when a dragged item hovers.

**Motivation:** Drag-and-drop between slots requires coordinated mouse tracking, ghost
rendering, hit testing, and validation. It's the same mechanics whether you're dragging
a sword to an equipment slot (Baldur's Gate), a creature stack between army slots
(Heroes 2), or items in a trade window. One implementation covers all cases.

### Theming

A `Theme` defines default styles for all components. The game sets one theme; individual
components can override.

```python
game.theme = Theme(
    font="medieval",
    panel_background="ui/panel_bg.png",
    button_background="ui/button.png",
    button_hover="ui/button_hover.png",
    text_color=(220, 200, 160),
    # ...
)
```

**Motivation:** Games have a visual identity. Setting it once and having every button,
panel, and label inherit it eliminates per-component styling. Heroes 2's UI is all
the same stone/parchment style. Baldur's Gate is all the same leather/paper style.
One theme definition covers it.

### Convenience Screens

Pre-built scene templates for extremely common patterns:

```python
# Message screen (story text, "press any key to continue")
game.push(MessageScreen("The kingdom has fallen. Only you can restore it."))

# Choice screen
game.push(ChoiceScreen(
    "The road forks. Which path do you take?",
    choices=["Through the forest", "Along the river", "Into the caves"],
    on_choice=handle_path_choice,
))

# Confirmation dialog
game.push(ConfirmDialog("Are you sure you want to retreat?", on_confirm=retreat))

# Sequential messages (end-of-turn reports, story sequences)
game.show_sequence([
    MessageScreen("Week 2 begins."),
    MessageScreen("Your mines produce +500 gold."),
], on_complete=start_next_turn)
```

**Motivation:** These patterns appear in every game. A message screen with "press any
key" should never take more than one line. Sequential popups (Heroes 2 end-of-week,
Baldur's Gate story events) are chains of the same primitive.

### Text Effects

```python
# Typewriter reveal (mission briefings, story text, dialogue)
textbox = TextBox(text="The kingdom has fallen...", typewriter_speed=30)  # chars/sec

# Auto-scrolling text
textbox = TextBox(text=long_text, auto_scroll_speed=2)  # lines/sec
```

**Motivation:** Typewriter text reveal appears in Warcraft 2 briefings, Baldur's Gate
dialogue, and countless RPGs. It's a rendering feature, not game logic.

### Persistent HUD Layer

The `Game` object owns an optional HUD layer that renders above all scenes but below
modal overlays (dialogs, tooltips).

```python
hud = game.hud
hud.add(Panel(anchor=Anchor.TOP, width="100%", height=32))  # resource bar area
hud.visible = True

# Scenes can suppress the HUD
class MainMenu(Scene):
    show_hud = False
```

**Motivation:** Every reference game has persistent UI (resource bar, minimap, portraits)
that survives scene transitions. The HUD is a container of standard UI components with
special render ordering — not game-specific logic, just a framework-level render slot
between the scene stack and modal overlays.

---

## Sprites & Animation

### Sprite

A `Sprite` is the visual representation of something on screen. It has a position,
a current image, and optionally an active animation. Sprites are the universal building
block — a unit, a tree, a projectile, a spell effect, a background element, an animated
tile — all are sprites.

```python
knight = Sprite(
    image="sprites/knight_idle",
    position=(400, 300),               # pixel position in world space
    anchor=SpriteAnchor.BOTTOM_CENTER, # where the position point is on the image
    layer=RenderLayer.UNITS,           # rendering order category
)
```

**Motivation for pixel position (not tile position):** The framework doesn't know about
tiles. Sprites have positions in a continuous 2D world. A strategy game maps tile coords
to pixel coords; an RPG like Baldur's Gate uses pixel coords directly. This keeps the
Sprite generic.

**Motivation for `SpriteAnchor.BOTTOM_CENTER`:** Sprites in top-down games are taller
than their footprint. The "foot" of the sprite sits at its position. Bottom-center
anchoring means the position is where the sprite's feet are. This is universal across
the reference games.

### AnimationDef

An animation definition is a **reusable template** — it defines what frames to play,
how fast, and whether it loops. It does not belong to any specific sprite.

```python
walk_right = AnimationDef(
    frames=["knight_walk_01", "knight_walk_02", "knight_walk_03", "knight_walk_04"],
    frame_duration=0.15,          # seconds per frame
    loop=True,
)

attack_right = AnimationDef(
    frames=["knight_atk_01", "knight_atk_02", "knight_atk_03"],
    frame_duration=0.1,
    loop=False,                   # play once
)

death = AnimationDef(
    frames=["knight_death_01", "knight_death_02", "knight_death_03"],
    frame_duration=0.2,
    loop=False,
)
```

**Motivation for separating definition from playback:** In Warcraft 2, every footman
shares the same walk animation definition but each has independent playback state
(different frame, different timing). In Baldur's Gate, every skeleton uses the same
death animation. AnimationDef is the template; the sprite holds playback state. This
also makes it easy for AI art: produce a sprite sheet, define frame names and timing,
done.

### Playing Animations

```python
knight.play(walk_right)                         # start animation
knight.play(attack_right, on_complete=do_damage) # callback when done
knight.play(death, on_complete=lambda: knight.remove())  # die and remove
knight.queue(idle)                              # play after current finishes
```

The animation player:
- Tracks current frame and elapsed time
- Advances frames on `update(dt)`
- Fires `on_complete` when a non-looping animation finishes
- Supports `queue()` to chain animations: walk → attack → idle

### Compound Animations (Tweening + Frame Animation)

Many game actions combine **movement and frame animation**. A unit walking needs both
a position tween (smooth pixel movement) and a walk animation (frame cycling). The
framework composes these:

```python
# Move while playing walk animation
knight.play(walk_right)
knight.move_to(target_pixel_pos, speed=200, on_arrive=lambda: knight.play(idle))

# Projectile: create, move, remove on arrival
arrow = Sprite("sprites/arrow", position=archer_pos)
arrow.move_to(target_pos, speed=500, on_arrive=lambda: [
    arrow.remove(),
    target.play(hit_reaction),
])
```

**Motivation:** This is the core of what makes 2D games feel alive. Units walk. Arrows
fly. Spells have travel time. Baldur's Gate characters walk across the screen. Warcraft 2
catapults lob projectiles. Heroes 2 creatures charge in battle. Without engine support
for "animate + move simultaneously," every developer reimplements lerp+timer logic.

### Composable Actions

The callback style above works well for simple cases (walk, then idle). But game sequences
get complex: a battle turn in Heroes 2 is "attacker walks forward, plays attack animation,
wait 0.3s, defender plays hit reaction, damage number floats up, attacker walks back."
Nested callbacks become unreadable. The framework provides a composable Actions system
for orchestrating multi-step sequences.

**Inspired by:** Cocos2d Python's Actions system, the best part of a now-dead framework.

```python
from saga2d.actions import Sequence, Parallel, Delay, Do, PlayAnim, MoveTo, FadeOut, Remove

# Battle attack sequence — flat and readable
knight.do(Sequence(
    Parallel(PlayAnim(walk), MoveTo((500, 400), speed=200)),  # walk + move together
    PlayAnim(attack),
    Delay(0.3),
    Do(lambda: target.do(Sequence(  # trigger on target
        PlayAnim(hit),
        PlayAnim(death),
        FadeOut(0.5),
        Remove(),
    ))),
    Parallel(PlayAnim(walk), MoveTo((100, 400), speed=200)),  # walk back
    PlayAnim(idle),
))

# Projectile with trail particles
arrow = Sprite("sprites/arrow", position=archer_pos)
arrow.do(Sequence(
    MoveTo(target_pos, speed=500),
    Do(lambda: ParticleEmitter(image="sprites/spark", position=target_pos, count=15).burst()),
    Do(lambda: target.do(PlayAnim(hit))),
    Remove(),
))
```

**Building blocks:**

| Action | What it does |
|---|---|
| `Sequence(a, b, c)` | Run actions one after another |
| `Parallel(a, b)` | Run actions simultaneously, finish when all done |
| `PlayAnim(anim_def)` | Play a frame animation, finish when it completes (or never for loops) |
| `MoveTo(pos, speed)` | Tween position, finish on arrival |
| `Delay(seconds)` | Wait |
| `Do(callable)` | Call a function, finish immediately |
| `FadeOut(duration)` | Tween opacity to 0 |
| `FadeIn(duration)` | Tween opacity to 1 |
| `Remove()` | Remove the sprite |
| `Repeat(action, times)` | Repeat an action N times (or forever) |

Actions compose: `Parallel` inside `Sequence`, `Sequence` inside `Repeat`, etc.
Any sprite has `.do(action)` to start an action and `.stop_actions()` to cancel.

**Relationship to callbacks:** Actions are built on the same primitives — tweens,
animation playback, and timers. The simple callback style (`play(anim, on_complete=...)`,
`move_to(pos, on_arrive=...)`) still exists for one-step cases. Actions are for when
you need to compose a multi-step sequence without callback nesting.

**Motivation:** Cocos2d Python proved this pattern works. Every game hits the wall where
callback nesting becomes unmanageable — battle sequences, cutscenes, spell effects,
multi-step UI animations. Composable actions make these flat, readable, and reorderable.
The pattern is well-known in game engines (Unity Coroutines, Godot Tweeners, Cocos2d
Actions) but missing from every living Python framework.

### Render Layers

Fixed rendering order, back to front:

```
BACKGROUND    — background images, terrain
OBJECTS       — trees, buildings, environmental objects
UNITS         — living units, characters, NPCs
EFFECTS       — spell effects, projectiles, explosions
UI_WORLD      — health bars above units, selection circles, name labels
(UI layer is drawn separately by the UI system, always on top)
```

Within each layer, sprites are sorted by y-position (higher y = further down screen =
drawn later = appears in front). This gives correct visual overlap for top-down views.

**Motivation:** This order is universal in 2D games. Baldur's Gate draws backgrounds,
then objects, then characters, then spell effects. Warcraft 2 draws terrain, then
buildings, then units, then projectiles. Making it fixed eliminates "why is my sprite
behind the tree" bugs. If a game needs additional layers, the set can be extended.

### Particle Emitter

A particle emitter spawns many short-lived sprites with randomized properties. This is
how spell effects, explosions, weather, and ambient effects work in 2D games.

```python
emitter = ParticleEmitter(
    image="sprites/spark",              # small image (or list for variety)
    position=(500, 300),                # spawn point
    count=30,                           # how many to spawn
    speed=(50, 200),                    # random speed range (pixels/sec)
    direction=(0, 360),                 # random angle range (degrees)
    lifetime=(0.3, 0.8),               # random lifetime range (seconds)
    fade_out=True,                      # fade opacity over lifetime
)
```

A particle is just a lightweight sprite with velocity and a death timer. The emitter
manages the pool — spawning, updating, and removing dead particles each frame.

**Motivation:** Particles are sprites. There's no separate rendering path, no GPU
compute, no special system — just a managed collection of short-lived sprites with
randomized motion. At our target scale (tens to low hundreds of particles for a spell
effect), this performs fine. Warcraft 2's blizzard spell, Heroes 2's lightning bolt,
Baldur's Gate's fireball — all achievable with this.

Emitter modes:
- `burst(count)` — spawn all at once (explosion, impact)
- `continuous(rate)` — spawn N per second (fire, smoke, rain)
- `stop()` — stop spawning, let existing particles die naturally

### Color Swaps (Team Colors / Palette Variants)

Sprites can define color regions that get replaced at load time.

```python
knight = Sprite(
    image="sprites/knight_idle",
    color_swap=ColorSwap(
        source_colors=[(255, 0, 0), (200, 0, 0), (150, 0, 0)],
        target_colors=[(0, 0, 255), (0, 0, 200), (0, 0, 150)],
    ),
)

# Or using named palettes:
knight = Sprite(image="sprites/knight_idle", team_palette="blue")
```

The color swap creates a cached recolored surface — one-time cost, not per-frame.

**Motivation:** Warcraft 2 uses palette swaps for team colors. Heroes 2 uses them for
factions. Baldur's Gate uses tint variations for different armor types. Without this,
artists must create separate sprite sheets per color variant, multiplying asset count.
This is a rendering concern, not game logic.

---

## Camera & Viewport

### Motivation

Every reference game has a world larger than the screen. Baldur's Gate scrolls over
pre-rendered backgrounds. Warcraft 2 scrolls over tile maps. Heroes 2 scrolls over an
adventure map. The camera defines what portion of the world is visible.

The camera is deliberately **not** tied to a tile map. It operates in pixel/world
coordinates. A tile-based game converts tile positions to pixel positions; the camera
doesn't care.

### Design

```python
camera = Camera(
    viewport_size=(1920, 1080),    # matches logical resolution
    world_bounds=(4096, 4096),     # total world size in pixels (optional, for clamping)
)

camera.center_on(x=2000, y=1500)   # center view on world position
camera.follow(sprite)               # follow a sprite each frame
camera.scroll(dx=5, dy=0)           # manual scroll (arrow keys, edge scroll)
camera.enable_edge_scroll(speed=8, margin=20)  # scroll when mouse near screen edge
```

The camera provides coordinate conversion:

```python
world_pos = camera.screen_to_world(mouse_x, mouse_y)
screen_pos = camera.world_to_screen(sprite.x, sprite.y)
```

**Motivation for coordinate conversion:** When the player clicks the screen, the game
needs to know what world position was clicked. When drawing a sprite, the renderer needs
to know where on screen it goes. These conversions are pure math but easy to get wrong,
especially with scrolling and zoom.

The zoom level is fixed at creation (changeable in settings with reload). Dynamic zoom
is not supported in v1 — it complicates the rendering pipeline and is not needed for
the target games.

---

## Utilities

### Timers & Delays

```python
game.after(2.0, show_next_dialogue)         # call after 2 seconds
game.every(1.0, regenerate_mana)            # call every 1 second
timer_id = game.after(5.0, timeout)
game.cancel(timer_id)                       # cancel a timer
```

**Motivation:** Turn-based games need delays for animations ("show attack, wait 0.5s,
show damage"). Real-time games need periodic updates. Baldur's Gate auto-pauses after
events. Raw `time.time()` tracking is noise that every game reimplements.

### Tweening

Smooth interpolation of any numeric property over time.

```python
tween(sprite, "x", from_val=100, to_val=300, duration=0.5, ease=Ease.EASE_OUT)
tween(panel, "opacity", from_val=0, to_val=1, duration=0.3)  # fade in
```

Standard easing functions: linear, ease_in, ease_out, ease_in_out.

**Motivation:** Tweening is how things move smoothly — sprites walking, UI panels
sliding in, fade transitions. Every game needs it. It's math, not game logic.

### State Machine

Simple finite state machine for entity behavior.

```python
unit_fsm = StateMachine(
    states=["idle", "walking", "attacking", "dead"],
    initial="idle",
    transitions={
        "idle": {"move": "walking", "attack": "attacking", "die": "dead"},
        "walking": {"arrive": "idle", "attack": "attacking", "die": "dead"},
        "attacking": {"done": "idle", "die": "dead"},
    },
    on_enter={
        "idle": lambda: sprite.play(idle_anim),
        "walking": lambda: sprite.play(walk_anim),
        "dead": lambda: sprite.play(death_anim, on_complete=sprite.remove),
    },
)
```

**Motivation:** FSMs are universal in games: Warcraft 2 units, Baldur's Gate character
states, Heroes 2 battle phases. The engine provides the state machine mechanism; the
game defines the states and transitions. Without a helper, developers write nested
if/elif chains.

### Cursor

```python
game.cursor.set("default")
game.cursor.set("attack")       # custom cursor image from assets
game.cursor.set("move")
game.cursor.set("forbidden")
```

**Motivation:** All three reference games change the cursor based on context. Custom
cursors are a rendering feature that the framework manages.

---

## Game Loop

### Loop

```
while running:
    dt = clock.tick(target_fps)
    events = backend.poll_events()

    # Input phase
    for event in events:
        if hud.handle(event): continue     # HUD eats event
        if ui.handle(event): continue      # scene UI eats event
        scene_stack.top().handle_input(event)

    # Update phase
    scene_stack.top().update(dt)           # game logic
    tween_system.update(dt)                # position/property tweens
    animation_system.update(dt)            # sprite frame advances
    timer_system.update(dt)                # fire scheduled callbacks

    # Draw phase
    scene_stack.draw(ctx)                  # scenes draw back to front
    hud.draw(ctx)                          # HUD above scenes
    modal_overlay.draw(ctx)                # tooltips, dialogs on top

    backend.flip()
```

**Turn-based optimization:** If a scene declares `real_time = False`, the update/draw
cycle only runs when input is received or an animation/tween is in progress. Zero CPU
usage while waiting for the player — important for laptops.

**Target FPS:** Configurable per-scene. 30fps default, sufficient for all target games.

---

## Save/Load

### Motivation

Save/load is universal — every game longer than one session needs it. The framework
provides the plumbing (file I/O, slot management, UI). The game defines **what** to
persist via a simple protocol.

### Design

```python
class Scene:
    def get_save_state(self) -> dict:
        """Override: return serializable state."""
        return {"units": [...], "turn": self.turn, "map_data": ...}

    def load_save_state(self, state: dict) -> None:
        """Override: restore from saved state."""
        ...

# Framework handles:
game.save(slot=1)                          # serializes to file
game.load(slot=1)                          # deserializes and restores
game.push(SaveLoadScreen())                # standard UI with slots
```

The framework manages save file storage, timestamps, slot listing, and the UI. The
game decides what goes in the dict. Format: JSON with schema version for forward compat.

**Why this is framework, not game:** The file I/O, versioning, slot management UI, and
autosave hooks are identical across games. Only the state dict contents vary.

---

## Standard Game Flow Example

```python
from saga2d import Game, Scene, MessageScreen, ChoiceScreen
from saga2d.ui import Panel, Label, Button, Anchor, Layout, Style


class MainMenu(Scene):
    show_hud = False

    def on_enter(self):
        panel = Panel(anchor=Anchor.CENTER, layout=Layout.VERTICAL, spacing=16)
        panel.add(Label("Chronicles of the Realm", style=Style(font_size=48)))
        panel.add(Button("New Game", on_click=self.new_game))
        panel.add(Button("Load Game", on_click=lambda: self.game.push(SaveLoadScreen())))
        panel.add(Button("Settings", on_click=lambda: self.game.push_settings()))
        panel.add(Button("Quit", on_click=self.game.quit))
        self.ui.add(panel)

    def new_game(self):
        self.game.push(MessageScreen(
            "The Dark Lord has returned...",
            on_dismiss=lambda: self.game.replace(WorldMapScene()),
        ))


game = Game("Chronicles of the Realm", background="parchment.png")
game.run(MainMenu())
```

---

## File / Project Structure

```
easygame/
    __init__.py              # public API re-exports
    game.py                  # Game class, game loop
    scene.py                 # Scene, SceneStack
    assets.py                # AssetManager
    audio.py                 # Audio system, sound pools
    input.py                 # InputManager, action mapping
    cursor.py                # Cursor management
    save.py                  # Save/Load system

    ui/
        __init__.py
        component.py         # Base Component class
        components.py        # Label, Button, Panel, ImageBox, List, Grid, etc.
        layout.py            # Anchor, Layout, positioning math
        theme.py             # Theme, Style
        drag_drop.py         # Drag-and-drop system
        hud.py               # Persistent HUD layer
        screens.py           # MessageScreen, ChoiceScreen, ConfirmDialog, SaveLoadScreen

    rendering/
        __init__.py
        sprite.py            # Sprite class
        animation.py         # AnimationDef, AnimationPlayer
        particles.py         # ParticleEmitter
        camera.py            # Camera, viewport, edge scroll
        layers.py            # RenderLayer, layer sorting
        color_swap.py        # ColorSwap, palette utilities

    actions.py               # Sequence, Parallel, Delay, Do, PlayAnim, MoveTo, etc.

    util/
        __init__.py
        tween.py             # Tween system, easing functions
        timer.py             # Timer, scheduled callbacks
        fsm.py               # StateMachine

    backends/
        __init__.py
        base.py              # Backend protocol
        pyglet_backend.py    # Pyglet implementation (see BACKEND.md)
```

---

## What the framework explicitly does NOT include

These are game-level concerns, built from the framework primitives above:

- **Tile maps / hex grids** — A tile map is sprites arranged on a grid with coordinate
  math. The game defines its world topology; the framework renders sprites wherever the
  game puts them. (A tile map helper library could exist as a separate optional package.)
- **Pathfinding** — A* on a rect grid, A* on a hex grid, and navmesh pathfinding are
  fundamentally different. The game picks what fits. (Could be a separate package.)
- **Fog of war** — Rendering approach (overlay sprites with alpha) uses framework
  primitives. The visibility rules are game logic.
- **Campaign system** — A campaign is a sequence of scenes with some persisted state
  between them. The scene stack + save system provide all the primitives needed.
- **Building placement** — A ghost sprite following the cursor with color tinting is
  a sprite + cursor + input handling. Game code composes these.
- **Selection manager / control groups** — Game-level input handling. A list of selected
  entities is just a list; control groups are just 10 lists bound to keys.
- **Entity model** — The framework has Sprite (visual) but no Entity (game object).
  Whether your game object has health, inventory, faction, or spell slots is entirely
  game-defined. The game attaches a Sprite to whatever object model it uses.
- **Combat, AI, tech trees, resource systems** — Pure game logic.
- **3D rendering, physics, networking, level editor, scripting language** — Out of scope.
- **Dynamic zoom** — Complicates rendering pipeline. Not needed for target games.
- **Skeletal animation** — Frame-by-frame sprites only.

---

## Design Decisions Log

### Why no Entity base class in the framework

Earlier drafts included an `Entity` with `tile_pos`, `move_to()`, and lifecycle events.
This was removed because:
- It assumes tile-based positioning (Baldur's Gate uses free movement)
- It couples the visual (Sprite) to game logic (position, events)
- Games have wildly different entity needs (units vs buildings vs items vs terrain objects)
- The framework's job is rendering. A Sprite is a visual. The game owns its objects.

If you need an entity, make one:
```python
class Entity:
    def __init__(self, sprite, x, y):
        self.sprite = sprite
        self.x, self.y = x, y
        self.sprite.position = (x, y)
```

### Why no tile map in the framework

A tile map is a data structure (2D grid) + rendering logic (draw terrain sprites at grid
positions) + coordinate conversion (tile ↔ pixel). The rendering and coordinate parts
use framework sprites and camera. The data structure is game-defined because:
- Heroes 2 uses hex, Warcraft 2 uses rect, Baldur's Gate uses neither
- Occupancy, fog of war, and passability rules differ per game
- Tile maps are well-served by a separate optional library on top of the framework

### Why drag-and-drop IS in the framework

Drag-and-drop could be argued as game UI logic, but:
- It requires deep integration with the input system (mouse tracking, event interception)
- It requires framework-level rendering (ghost image following cursor above all UI)
- Every game with inventory or slot management needs it identically
- Getting it wrong (z-order bugs, dropped events) is painful

### Why sound pools ARE in the framework

Sound pools (random selection from a set) could be a 5-line game helper, but:
- It integrates with the audio channel system (respect volume, don't overlap)
- The "no immediate repeat" logic is subtle to get right
- Every game with voice responses needs this identically
- It's a natural extension of `play_sound`, not a separate system

### Why camera IS in the framework but tile map is NOT

The camera is pure math: viewport offset, clamping, coordinate conversion, edge scroll.
It works identically whether the world is tiles, pre-rendered backgrounds, or
procedurally generated terrain. A tile map embeds game-specific decisions (grid type,
tile data, occupancy). Camera = universal rendering concern. Tile map = game world model.
