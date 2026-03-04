# Saga2D

Python framework for 2D sprite-based games. You write game logic, not engine plumbing.

## Quick Start

```bash
pip install -e .
```

```python
from saga2d import Game, Scene, Button, Label, Panel, Layout, Anchor


class MenuScene(Scene):
    def on_enter(self) -> None:
        self.ui.add(Panel(
            layout=Layout.VERTICAL,
            spacing=20,
            anchor=Anchor.CENTER,
            children=[
                Label("My Game", font_size=48),
                Button("Play", on_click=lambda: self.game.pop()),
            ],
        ))


game = Game("My Game", resolution=(960, 540))
game.run(MenuScene())
```

> **Headless / CI:** Pass `backend="mock"` to `Game(...)` to run without a display
> server. The mock backend stubs out all rendering and audio, making it suitable for
> automated tests and continuous integration environments.

## Core Features

| Feature | Description |
|---------|-------------|
| **Scene stack** | Push/pop scenes. Each scene has `on_enter`, `on_exit`, `on_reveal` hooks. |
| **Sprites** | Position, animate, layer. Actions: `Sequence`, `Parallel`, `MoveTo`, `FadeIn`, etc. |
| **Camera** | Follow, scroll, pan, bounds. `camera.shake()` for screen shake. |
| **UI** | `Button`, `Label`, `Panel`, `List`, `ProgressBar`, `DataTable`. Layout and anchoring. |
| **Theme** | Global style defaults. `game.theme` or per-component `Style`. |
| **Audio** | Channels (master, music, sfx, ui). `play_music`, `crossfade_music`, sound pools. |
| **Input** | Action mapping (bind keys to actions). `handle_input(event)` in scenes. |
| **Save/load** | `game.save(slot)`, `game.load(slot)`. JSON-based, slot metadata. |
| **Tweening** | `tween(obj, "x", 0, 100, 1.0)` for property interpolation. |
| **Drag-and-drop** | `DragManager` for draggable UI. |

See `tutorials/tower_defense/` for a complete tutorial. `DESIGN.md` for requirements, `BACKEND.md` for implementation details.

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
