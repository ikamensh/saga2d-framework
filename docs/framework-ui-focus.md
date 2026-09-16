# Focus and pointer ownership

Scenes opt into keyboard focus so gameplay Tab/arrows keep their existing meaning:

```python
class Menu(Scene):
    def on_enter(self):
        self.ui.enable_focus(navigation="vertical", activate=("return",))
        self.ui.add(Column(Button("Continue", on_click=self.continue_game),
                           Button("Quit", on_click=self.game.quit)))
```

Tab/Shift+Tab traverse visible, enabled focusable controls. `vertical` also uses
Up/Down; `spatial` uses arrows and control centers; `manual` lets the game call
`ui.focus_next(reverse=False, candidates=None)` and
`ui.focus_direction("left", candidates=None)` with its own candidate policy.
`ui.focus(control)` selects a control, `ui.focus(None)` clears it, and
`ui.focused` returns the live owner. Focus remains with its scene under a modal
and is discarded on hiding, disabling or removing its owner or an ancestor.
Explicit Button shortcuts precede focus navigation/activation. The default
activation keys are Enter and Space; choose an empty tuple for custom actions.

Buttons are focusable by default. Custom controls can inherit Button and replace
`on_draw`, retaining pointer/keyboard behavior and reading `focused`/`hovered`.
For non-button focus targets, use `Component(focusable=True)` and `on_activate`.
`activate()` refuses hidden, disabled or detached controls. A focusable settings
row can contain `Button(..., focusable=False)` children: clicking a child focuses
the nearest available focusable ancestor before its callback runs.

`blocks_pointer=True` makes a component own clicks inside its rectangle, even
when disabled. It does not swallow motion, wheel or drag events automatically.
`ui.pointer_target(x, y)` finds the frontmost visible pointer owner, or None;
HUD hover and placement ghosts can use this instead of scanning child bounds.
Buttons and Minimap opt in; decorative labels and containers do not. Mark the
whole HUD panel when its empty area should also block world clicks. Bounds use
the current layout, like `hit_test`; disabled ancestry prevents activation.
`game.mouse_position` reports the latest logical pointer coordinates.

A drag control calls `capture_pointer()` after accepting a press. The root sends
motion, drag and release to it, including outside its rectangle, then releases
capture on mouse release. `release_pointer()` ends it explicitly. Removal,
hiding, disabling, scene cover and window focus loss cancel capture and call
`on_pointer_cancel()`. `has_pointer_capture` is the source of truth; there is no
need to maintain a second dragging flag. Minimap uses this same mechanism.

The games retain their choice of eligible research nodes, settings adjustments,
card artwork and gameplay shortcuts. These interfaces do not add clipping,
scrolling or text-entry widgets.

Run the independent native journey and inspect its three captures:

```bash
uv run python tools/verify_ui_focus.py --output /tmp/saga2d-ui-focus
```

It exercises a custom card and an ordinary button, disabled HUD occlusion,
dragging outside a control, modal capture cancellation and queued-key isolation.
