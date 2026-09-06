# Screen drawing layers

Put a group of immediate draw calls above earlier screen content:

```python
def draw(self):
    self.draw_text("Health 12/20", 100, 100)
    with self.screen_layer(1):
        self.draw_rect(90, 70, 150, 45, (20, 30, 40, 255))
        self.draw_text("Recovered +8", 100, 100)
```

The rectangle covers the earlier text. Without a higher layer, text draws
above shapes at the same order, even when the rectangle is drawn afterward.
The scope also applies when those calls live inside a game's own drawing
helpers. It covers `draw_rect`, `draw_circle`, `draw_line`, `draw_polygon`,
`draw_image`, `draw_text` and `draw_paragraph`.

Layers are integers from 0 to 999; zero is the default. Higher layers cover
lower layers regardless of call order. Within a layer, text stays above
images and images above shapes. Nested scopes select an absolute layer and
restore the prior layer on exit, including exceptions. Booleans, fractional
values and out-of-range values raise `ValueError`.

The scene's UI tree draws above all its immediate screen layers. Children
and later siblings cover earlier components, matching which control receives
mouse input. Every part of the next scene draws above the scene below it.
Use a transparent overlay `Scene` for menus and dialogs that should own input;
a drawing scope has no effect on input or scene lifetimes.

World-space calls keep their existing `RenderLayer` and camera behavior,
including inside a screen-layer scope. Retained `Sprite` order is unchanged.

The independent example is interactive and also has a bounded native check:

```sh
python tools/demo_screen_layers.py
python tools/demo_screen_layers.py --verify --output /tmp/saga2d-screen-layers
```

The check verifies that old text and images cannot leak through an opaque
panel, later UI siblings cover earlier labels, clicks reach the visible
control, and a modal covers and isolates everything below it. It saves PNGs
for visual inspection. Shardbound's damage pills and Tribes' floating labels
motivate the scope; Warband's minimap frame motivated the private order
spacing retained inside each component.
