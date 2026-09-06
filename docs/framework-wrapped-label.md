# Wrapped labels in a flow

Give a description its allotted width and let the next control follow it:

```python
from saga2d import Anchor, Button, Column, Label, Scene

class Orders(Scene):
    def on_enter(self):
        self.objective = "Gather the army at the northern gate before advancing toward the enemy."
        self.ui.add(Column(
            Label(lambda: self.objective, width=300, wrap=True, text_style="body"),
            Button("Continue", on_click=self.game.pop),
            spacing=12, anchor=Anchor.CENTER,
        ))
```

`wrap=True` requires a positive finite explicit `width`. The label measures
its actual resolved font and reports the height of all its lines, rounded up
to a logical pixel. `Column`, `Row` and flow-layout `Panel` use that size.
Changing the reactive text, named theme style, font or display scale refreshes
the measurement before the existing input/draw layout passes. A following
button therefore draws and responds at its new position in the same frame.
Covered scenes also refresh visible text even while their updates are paused.

Wrapping shares `Scene.draw_paragraph`'s word measurement: explicit newlines
and blank lines remain, other whitespace collapses, and an overlong word
splits between characters. Lines use 1.4 times the measured font height, with
no trailing gap. Empty text consumes zero height. If even one character cannot
fit the width, drawing raises `ValueError` instead of silently overflowing.

`align="left"`, `"center"` and `"right"` apply to every line inside the given
width. Normally the block begins at the label's top. Supplying `height` keeps
that caller-owned size and vertically centers the text block; it does not clip
text or shrink its font. Games still choose a width and maximum content that
fit their screen, or provide their own paging. Existing `Label` calls keep
single-line behavior unless they explicitly opt in.

The implementation shares one private paragraph layout helper with immediate
Scene text and adds one private preparation hook at existing UI layout
boundaries. Games do not implement a new lifecycle, measure line breaks,
subscribe to theme changes, or move the next button themselves.

This addresses two concrete callers: Shardbound's reward/equipment descriptions
currently need manual row heights and button positions; Warband's width-390
tutorial objective can exceed its existing single-line Label. This increment
changes neither game's caller nor the Warband worktree.

Run the independent example:

```sh
python tools/demo_wrapped_label.py
python tools/demo_wrapped_label.py --verify --output /tmp/saga2d-wrapped-label
python -m pytest tests/framework/test_wrapped_label.py tests/framework/test_text.py -q
```

The native check uses real keyboard/mouse events, inspects glyph pixels within
the allotted column, clicks the moved button, changes text and font, redraws a
paused scene under an overlay, and repeats at a smaller window size. It writes
screenshots and a compact report. Public integration tests additionally cover
font changes followed by a click within one input batch, blank/empty text,
long tokens, alignment and unchanged single-line rendering. The extracted
`Scene.draw_paragraph` renderer was also compared against actual prior source
`3923255` with three fonts, authored blank lines and a long token: the native
1800×1200 frames matched pixel for pixel.

Checkpoint `25cda6a` passed 888 full tests (239 framework tests), 60 Tribes AI
games and 20 Tribes random-input runs. Twenty Shardbound scene runs exercised
10,003 random input activations, with source hashes unchanged. The native
example passed nine keyboard/mouse activations and three confirmations after
reflow; its initial description grew from 192 to 368 logical pixels with the
larger font. Inspected captures and reports are retained in
[the evidence directory](evidence/framework-wrapped-label-2026-09-06/), including
[checks and source hashes](evidence/framework-wrapped-label-2026-09-06/checks.json),
[scene fuzz](evidence/framework-wrapped-label-2026-09-06/eador-ui-fuzz.json),
[native results](evidence/framework-wrapped-label-2026-09-06/verification.json),
and [prior-renderer comparison](evidence/framework-wrapped-label-2026-09-06/paragraph-comparison.json).

After merging relic-content main `9d52700`, integration checkpoint `c2bbb2c`
passes all 894 tests. Its framework implementation is unchanged from `25cda6a`.
