# Icons and hover explanations

An image belongs in ordinary layout; a button can use one without losing its
name, shortcut or disabled behavior:

```python
from saga2d import Button, Image, Label, Row

self.ui.add(Row(
    Image('icons/gold', width=24, height=24),
    Label(lambda: str(wallet.gold)),
    tooltip=lambda: f'Gold available: {wallet.gold}',
))
self.ui.add(Button('Save progress', icon='icons/save', show_text=False,
                   shortcut='F5', on_click=save))
```

Image names use the normal asset cache. Their aspect ratio is preserved inside
the requested box; widgets do not acquire separate image handles. An icon-only
button defaults to its complete, possibly reactive name as its tooltip. Supply
`tooltip=` when it needs a more useful explanation, such as why saving is
unavailable. `show_text=True` displays the image alongside the label.

A parent's tooltip applies when hovering either its icon or value. Disabled
controls and disabled ancestors retain explanations. The front-most visible
component controls hover; another scene suppresses the covered scene's tips.
Removing or hiding the component removes its explanation without cleanup code.
Tips use `theme.get_text_style('body')`, wrap within the viewport and mark with
an ellipsis if the complete explanation is too tall to fit.

The framework does not choose icon meanings, hide primary actions, or add a
keyboard focus system. Games retain their existing shortcuts and guides.
Shardbound uses original game-owned symbols for resources and utilities, and
keeps contextual actions, costs and consequences in text.

Run the independent example:

```bash
uv run python tools/demo_icon_controls.py
uv run python tools/demo_icon_controls.py --verify --output /tmp/icon-controls
uv run python -m pytest tests/framework/test_ui_icons.py -q
```

The bounded native verification checks actual click and shortcut activation,
disabled input, shared hover, modal suppression, reactive names and closing the
game. It saves four screenshots and uses the shared 30 FPS verifier cap.
