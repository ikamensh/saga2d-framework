### proudly vibe coded with [kodo](https://github.com/ikamensh/kodo), claude code and cursor 

# Saga2D

Python framework for 2D sprite-based games. You write game logic, not engine plumbing.

## Quick Start

```bash
pip install -e .
```

A scene is a class. State is attributes. Controls are a dict. HUD reads from
state reactively — no manual `label.text = …` after every mutation:

```python
from saga2d import (
    Anchor, Game, Label, ProgressBar, Row, Scene, TextStyle, Theme,
)


class GameScene(Scene):
    background_color = (18, 14, 28, 255)
    controls = {
        ("right", "d"):        "gain_coin",
        ("left", "a"):         "take_damage",
        ("confirm", "space"):  "reset",
    }

    def __init__(self):
        super().__init__()
        self.hp = 10
        self.coins = 0

    def gain_coin(self):    self.coins += 1
    def take_damage(self):  self.hp = max(0, self.hp - 1)
    def reset(self):        self.hp, self.coins = 10, 0

    def on_enter(self):
        self.ui.add(Label("My Game", text_style="title",
                          anchor=Anchor.TOP_LEFT, margin=20))
        self.ui.add(Row(
            Label(lambda: f"HP {self.hp}/10", text_style="hud"),
            ProgressBar(value=lambda: self.hp, max_value=10,
                        width=120, height=12),
            Label(lambda: f"Coins {self.coins}", text_style="hud"),
            spacing=16,
            anchor=Anchor.BOTTOM_LEFT, margin=16,
        ))


game = Game("My Game", resolution=(800, 600),
            theme=Theme(text_styles={"title": TextStyle(28, (255, 215, 100, 255)),
                                     "hud":   TextStyle(18, (245, 245, 250, 255))}))
game.run(GameScene())
```

Everything in this scene is declarative:

* **State** — plain Python attributes. No observable machinery, no decorators.
* **Controls** — a class-level dict. Method names are validated at class-def
  time; typos raise `AttributeError` at import, not on the first keypress.
* **HUD** — `Label(lambda: …)` and `ProgressBar(value=lambda: …)` re-evaluate
  each frame. Mutate `self.hp` anywhere and the HUD updates with zero wiring.
* **Layout** — `Row(...)` / `Column(...)` are transparent containers, no
  `Panel(style=HUD_BG, layout=…, children=[…])` scaffolding.
* **Typography** — `text_style="hud"` looks up one centrally-defined
  `TextStyle`. Change the theme once, every HUD label restyles.

> **Headless / CI:** Pass `backend="mock"` to `Game(...)` to run without a
> display server. Saga2D's own test suite has ~700 mock-backend tests.

## Examples

Three complete examples ship under `examples/`, each under 150 lines:

* **`ring_of_pain/`** — roguelike node ring. Player rotates around 8 nodes
  (enemies, treasure, heart, shop, portal), attacks or collects per node.
  Demonstrates `ring_positions` + `ring_budget`, sub-labels on every node,
  reactive HP bar, declarative controls.
* **`dial_menu/`** — 6-option radial selector with gold highlight on the
  current option. Demonstrates `Selector` state helper, `ring_positions`
  at a different count, theme with three text styles.
* **`tictactoe/`** — 3x3 grid with arrow-key cursor, win/draw detection,
  Shift+R shortcut to open with X in centre. Demonstrates `grid_positions`,
  Scene.controls with modifier-aware event handlers, `draw_rect` borders.

Each example has its own test file under `tests/examples/` exercising the
game's rules through the mock backend.

## Core Features

| Feature | Description |
|---------|-------------|
| **Scene stack** | Push/pop scenes. `on_enter`, `on_exit`, `on_reveal`, `update`, `draw` hooks. |
| **Declarative controls** | `class MyScene(Scene): controls = {"right": "step"}` — tuple-aliased keys, validated at import, optional event arg. |
| **Reactive HUD** | `Label(text=lambda: …)` and `ProgressBar(value=lambda: …)` re-evaluate every frame. |
| **Layout primitives** | `ring_positions`, `grid_positions`, `line_positions`, `ring_budget` — pure-math helpers for procedural layout. |
| **Selector** | `Selector[T]` wraps choose-one-of-N state (options, index, next/prev/set_index, replace). |
| **Theme text styles** | `Theme(text_styles={"title": TextStyle(28, gold), …})` — centrally-named text appearance. |
| **Row / Column** | Transparent horizontal / vertical containers — no background, no border, no padding. HUD one-liners. |
| **Sprites & actions** | Position, animate, layer. `Sequence`, `Parallel`, `MoveTo`, `FadeIn`, composable. |
| **Camera** | Follow, scroll, pan, bounds, shake. |
| **Audio** | Channels, crossfade, sound pools. |
| **Input** | Action mapping + modifier booleans (shift / ctrl / alt / meta) on every event. |
| **Save/load** | `game.save(slot)`, `game.load(slot)`. JSON-based, slot metadata. |
| **Tweening** | `tween(obj, "x", 0, 100, 1.0)` for property interpolation. |
| **Drag-and-drop** | `DragManager` for draggable UI. |

New to saga2d? Start with **[`tutorials/declarative/tutorial.md`](tutorials/declarative/tutorial.md)**
— a 5-step walk-through that builds a tiny guess-the-number game from
scratch, introducing one declarative API per step. Each snippet in the
tutorial is mirrored by a test in `tests/examples/test_tutorial_snippets.py`
so it can't drift.

See `DESIGN.md` for requirements, `BACKEND.md` for implementation details, and
`keras.dev` for a round-by-round log of how the declarative APIs evolved.

---

## Existing Python Game Frameworks

A survey of what exists, what each provides, and what's missing. This is why Saga2D
needs to exist.

### Low-level backends (what frameworks build on)

**[pygame / pygame-ce](https://github.com/pygame-community/pygame-ce)** — SDL2 wrapper. Window, 2D software rendering, event queue, audio
mixer. ~8.6k stars, actively maintained (pygame-ce is the more active community fork).
Gives you a surface to blit pixels onto. Everything else is your problem.

**[pyglet](https://github.com/pyglet/pyglet)** — Pure Python, OpenGL-based. Sprite batching, text rendering, audio playback.
~2k stars, actively maintained (v2.1+). Our chosen first backend — GPU-accelerated,
no binary dependencies, readable stack traces.

### Higher-level frameworks

**[Arcade](https://github.com/pythonarcade/arcade)** (~1.8k stars, active, v3.3) — The most feature-complete living project.
Built on pyglet. Has GPU sprite batching, a GUI system with layout and anchoring,
Camera2D, and tiled map loading. Solid for what it covers. But:
- "Scene" is a sprite list organizer, not a state machine — no push/pop scene stack
- No theming system for UI
- No audio channels, crossfade, or sound pools
- No input action mapping (raw key events only)
- No tweening or composable action sequences
- No drag-and-drop, no save/load system
- Hardcoded to pyglet — cannot swap backends
- **[arcade-curtains](https://github.com/maarten-dp/arcade-curtains)** (~30 stars) is a community plugin adding scene transitions and
  sprite animation to Arcade — evidence that users want exactly what's missing

**[Cocos2d Python](https://github.com/los-cocos/cocos)** (los-cocos, ~700 stars, **abandoned ~2020**) — The historical
ancestor of what Saga2D wants to be. Had the right architecture:
- Director singleton with push/pop scene stack
- Scene/Layer system for state management
- **Actions system** — composable sprite operations: `Sequence(MoveTo(...), FadeIn(...),
  CallFunc(attack), Delay(0.5))`. Run in sequence, parallel, loop, chain. This is the
  best idea in any Python game framework. Proven and dead.
- Built on pyglet, never became backend-agnostic
- Never built UI components, audio management, asset system, or theming
- Saga2D's composable Actions are directly inspired by this

**[Ursina](https://github.com/pokepetter/ursina)** (~2.5k stars, active) — "Unity for Python." Entity-based, has decent UI
widgets, a `Draggable` component, built-in `animate()` with easing curves. But:
- 3D-first (built on Panda3D) — 2D is not the focus
- No scene stack, no theming, no audio channels
- Heavy dependency (pulls in entire Panda3D C++ engine)

**[Pygame Zero](https://github.com/lordmauve/pgzero)** (pgzero, ~4.5k stars) — Zero-boilerplate game programming. No
`pygame.init()`, no event loop, just `draw()` and `update()` functions. Brilliant
for education. But intentionally minimal — no scenes, no UI, no camera, no tweening.
Not a framework, a teaching tool.

### UI-only libraries

**[pygame-gui](https://github.com/MyreMylar/pygame_gui)** (~700 stars, active) — Best game UI in the Python ecosystem. JSON theme
files, anchoring, solid widget set (buttons, text entry, dropdowns, progress bars,
panels, tooltips, windows). But:
- UI only — no scenes, sprites, audio, or camera
- Hardcoded to pygame surfaces

**[ThorPy](https://github.com/YannThoworkin/thorpy)** (~100 stars, active) — Simpler alternative to pygame-gui. Buttons, sliders,
checkboxes. Less feature-complete, pygame-only.

### Utility libraries

**[PyTweening](https://github.com/asweigart/pytweening)** — Pure easing functions (ease_in, ease_out, bounce, elastic). Just math,
no tween manager, no integration with any framework.

**[python-statemachine](https://github.com/fgmacedo/python-statemachine)** (~800 stars), **[transitions](https://github.com/pytransitions/transitions)** (~5.5k stars) — General-purpose
FSM libraries. Not game-specific, no rendering or update loop integration.

---

## Gap Analysis

What Saga2D provides that no existing Python framework does:

| Feature | Saga2D | [Arcade](https://github.com/pythonarcade/arcade) | [Cocos2d](https://github.com/los-cocos/cocos) | [Ursina](https://github.com/pokepetter/ursina) | [pygame-gui](https://github.com/MyreMylar/pygame_gui) |
|---|---|---|---|---|---|
| Scene stack (push/pop) | **yes** | — | **yes** (dead) | — | — |
| UI components + layout | **yes** | **yes** | — | **yes** | **yes** |
| Data-driven theming | **yes** | — | — | — | **yes** |
| Sprite animation + callbacks | **yes** | partial | **yes** (dead) | partial | — |
| Composable actions (Sequence/Parallel) | **yes** | — | **yes** (dead) | — | — |
| Camera/scrolling | **yes** | **yes** | partial | **yes** | — |
| Audio channels/crossfade/sound pools | **yes** | — | — | — | — |
| Asset loading by name | **yes** | — | — | — | — |
| Input action mapping | **yes** | — | — | — | — |
| Drag-and-drop | **yes** | — | — | **yes** | — |
| Tweening | **yes** | — | **yes** (dead) | **yes** | — |
| Save/load system | **yes** | — | — | — | — |
| Backend-agnostic protocol | **yes** | — | — | — | — |

No existing project combines all of these. The "complete 2D framework" niche that
exists in other ecosystems (Love2D for Lua, MonoGame for C#, Phaser for JavaScript)
is empty in Python.

The closest historical attempt — Cocos2d Python — had the right architecture
(scene stack, composable actions) but was abandoned before it grew UI, audio, or
asset management. Saga2D picks up where it left off, with a broader scope and
backend-agnostic design.
