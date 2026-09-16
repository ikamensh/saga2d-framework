# Measured layout and fitting

`Scene.layout_text` uses the same font metrics and wrapping as immediate
paragraphs and retained labels. It returns an immutable `TextLayout` before
anything is drawn, so a log can place its newest entry at the bottom or a
preview can measure its height first:

```python
layout = scene.layout_text(message, 280, style="body", line_spacing=1.2)
top = bottom - layout.height
for index, line in enumerate(layout.lines):
    scene.draw_text(line, left, top + index * layout.line_height * layout.line_spacing,
                    style="body", anchor_y="top")
```

`lines` includes explicit blank lines. `height` reaches the bottom of the last
line without a trailing gap. Empty text has no lines and zero height. Other
whitespace collapses to single spaces; overlong words split between characters.
Measure again after changing the text, style, font size or window scale.

For card descriptions, pass `max_lines` to layout, immediate drawing or a
wrapped label. The last line gets a measured ellipsis when text is omitted;
`TextLayout.truncated` tells a custom view whether that happened.

```python
scene.draw_paragraph(description, 30, 80, 280, style="body", max_lines=3)
scene.ui.add(Label(description, width=280, wrap=True, max_lines=3))
```

For a single-line name, `fit_text` keeps the longest prefix that fits alongside
an ellipsis, including partial words. It returns the original text unchanged
when it fits. Use the same style to draw the result:

```python
name = scene.fit_text(character_name, card_width - 20, style="title")
scene.draw_text(name, card_left + 10, card_top + 10, style="title", anchor_y="top")
```

Widths and line spacing must be positive and finite. `max_lines` must be a
positive integer and requires `wrap=True` on a Label. An impossible character
fit or an ellipsis wider than its box raises `ValueError`; the engine never
silently emits overflowing text. `fit_text` rejects newlines; use layout for
multiline content. Default paragraphs and labels retain their previous behavior.

Ninefold uses this for measured card names and bottom-aligned logs. Absolution
uses bounded descriptions. Content selection, positioning, scrolling and log
retention remain game decisions.

Run the independent native check and inspect its two images:

```bash
caffeinate -u
uv run python tools/verify_text_layout.py
```

It verifies measured sizes, wrapping, blank lines, long tokens, truncation and
single-line fitting with bundled fonts, then compares immediate paragraphs
against retained labels pixel for pixel before and after a window resize.
