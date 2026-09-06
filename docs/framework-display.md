# One logical canvas, different windows

A game declares its logical canvas once. Window resizing scales that canvas
and adds letterbox bars; it leaves scene, camera and UI coordinates intact.

```python
from saga2d import Game, Scene

class Play(Scene):
    controls = {'f11': 'toggle_fullscreen', '1': 'small_window'}

    def toggle_fullscreen(self):
        self.game.set_fullscreen(not self.game.fullscreen)

    def small_window(self):
        self.game.set_window_size((960, 600))

Game('My game', resolution=(1280, 800)).run(Play())
```

| Interface | Behavior |
|---|---|
| `game.fullscreen` | Actual current fullscreen state; read-only |
| `game.window_size` | Actual native content width/height; read-only |
| `game.set_fullscreen(True)` | Enter fullscreen at the current desktop size |
| `game.set_fullscreen(False)` | Restore the last actual windowed size |
| `game.set_window_size((w, h))` | Leave fullscreen if needed, then select this windowed size |

`game.resolution`, `width` and `height` continue to describe the fixed logical
canvas. Window sizes exclude title bars/borders and the additional backing
pixels of a Retina surface. On the verified Retina host, a `960 × 600` window
has a `1920 × 1200` framebuffer; both render the same `1280 × 800` game canvas.
The backend handles native coordinate conversion. Game input still receives
logical screen coordinates and camera-transformed world coordinates.

The native window is now resizable, so dragging its OS border also works.
Toggling fullscreen after an OS resize restores that actual size. The OS may
constrain requests; read `window_size` to show the applied result. Calling
`set_fullscreen` with the current state is harmless and does not replace the
remembered windowed size. Fullscreen does not request a different monitor
resolution. Drawing is clipped to the logical canvas; letterbox bars retain
the scene background color.

Size requests require a pair of positive integers (JSON lists are also
accepted). Floats, booleans used as dimensions, zero and malformed pairs raise
`ValueError` before changing the display. Fullscreen requires a boolean.
`SAGA2D_HEADLESS=1` keeps startup windowed/hidden and rejects runtime fullscreen
with `RuntimeError`, preserving the existing headless policy.

Games own available presets, keyboard bindings and Apply/Cancel/persistence
policy. A saved windowed size can be applied first, followed by the saved
fullscreen flag. `Settings` is already the independent persistence primitive;
display methods never read or write files. This does not implement logical
canvas resizing, text scaling, reduced motion, monitor selection or a settings
screen.

## Native example and verification

```bash
uv run python tools/demo_display.py
uv run python tools/demo_display.py --verify --out /tmp/saga2d-display
```

The example uses a fixed canvas, four corner buttons, a zoomed world target
and a retained sprite. F11 toggles fullscreen; 1/2/3 select window sizes; Esc
quits. The bounded verification mode drives real Pyglet keys/clicks, performs
a native OS resize outside Game, toggles fullscreen, selects a size while
fullscreen, and starts a fresh Game directly in fullscreen. It asserts actual
restoration, logical UI/world picking and pixels at all canvas edges, inside
the sprite and in the letterbox bars, then saves screenshots and a JSON report.
An awake graphical desktop is required. Mock tests cover the public interface
and invalid inputs; `backend.inject_resize(w, h)` simulates an OS resize while
ordinary mock clicks remain logical coordinates.

The native path was verified on macOS arm64 with Pyglet 2.1.13 and a 2× backing
scale. Windows/Linux and multiple-monitor behavior still require native host
verification. Screenshot checks prove the fixed-canvas mechanism, not that a
game's existing text is comfortable at every chosen size.

The implementation reuses Pyglet's
[window operations](https://docs.pyglet.org/en/latest/modules/window.html#pyglet.window.Window.set_fullscreen).
Pyglet requires a resizable window for defined `set_size` behavior. The adapter
also accounts for the pinned Cocoa implementation's differing getter/setter
units and refreshes the projection after fullscreen recreates the context.

A display preview can snapshot `game.windowed_size` and `game.fullscreen`,
then restore with `set_window_size(saved_size)` and `set_fullscreen(saved_mode)`.
`windowed_size` reports the actual OS windowed size, or the remembered restoration
size while fullscreen. It avoids mistaking the desktop dimensions for the player's
previous window when cancelling a fullscreen preview.
