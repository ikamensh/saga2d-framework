# Measure before attaching UI

`Scene.measure(component) -> (width, height)` measures an unattached tree using
the scene's current theme, fonts and display scale. It uses the same preferred
size as ordinary UI layout. It does not attach, draw, update or register input
for that tree. Reactive labels evaluate their current text when measured.

```python
card = Column(Label(description, width=330, wrap=True), Button("Accept"))
width, height = self.measure(card)
self.ui.add(Column(card, anchor=Anchor.TOP_LEFT,
                   margin=(35, round(self.game.height - 105 - height))))
```

Call it from an entered Scene, with a tree whose root has no parent. An already
owned tree raises `ValueError`; use that tree's `get_preferred_size()` directly.
Measurement does not cache the result for the caller: measure again when
changing its text, theme or display size. Framework font/wrapping caches still
avoid repeated glyph work. A failing reactive callback propagates its exception
and releases the temporary measurement context, so callers can correct their
content and retry normally.

Shardbound's save and rival screens previously attached temporary Columns just
to acquire font measurements, cleared them, then rebuilt the visible tree.
They now measure complete blocks directly. The game retains its content,
available-space budget, whole-entry paging and shortcut choices. A general
strategy-screen or pagination framework would add unrelated policy here.

The independent example has no game imports or assets:

```bash
uv run python tools/demo_ui_measurement.py
uv run python tools/demo_ui_measurement.py --verify
```

P shows a prospective job card, T changes its description, F changes its font,
and A accepts only a visible job. The card grows upwards from the controls.
Native verification checks twelve layouts across three window sizes, exact
measured/rendered dimensions, both font/content choices, keyboard and mouse,
and the absence of hidden action activation. Public integration tests also
cover tree ownership, theme/reactive changes and callback failure cleanup.
