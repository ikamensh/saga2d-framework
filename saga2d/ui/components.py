"""Label, Button, KeyHints, Panel, Row, Column, ProgressBar.

Hotkeys are drawn as *keycaps*: small rounded key labels after a button's
text and in front of each hint in :class:`KeyHints`, styled by the theme's
``keycap_*`` settings.
"""

from __future__ import annotations

import math

from typing import TYPE_CHECKING, Any, Callable, Literal

from saga2d.input import normalize_combo
from saga2d.rendering._text import _Paragraph, _layout_paragraph
from saga2d.rendering.shapes import draw_box, rounded_rect
from saga2d.ui.base import Component
from saga2d.ui.layout import Layout, compute_anchor_position, compute_content_size, compute_flow_layout
from saga2d.ui.theme import Color, ResolvedStyle, Style, TextStyle, Theme, merge_styles
from saga2d.util.reactive import ReactiveValue

if TYPE_CHECKING:
    from saga2d.backends.base import Backend
    from saga2d.input import InputEvent

KEYCAP_PAD = 5
KEYCAP_RADIUS = 4
KEYCAP_GAP = 8  # between a button's text and its keycap
KEYCAP_LIFT = 2  # the darker slab showing under a keycap


def _normalize_shortcut(key: str) -> str:
    if not isinstance(key, str):
        raise TypeError("button shortcuts must be strings")
    prefix, separator, name = normalize_combo(key).rpartition("+")
    if not name:
        raise ValueError("button shortcuts need a nonempty key name")
    return prefix + separator + {"enter": "return", "esc": "escape"}.get(name, name)


def _draw_component_box(component: Component, resolved: ResolvedStyle) -> None:
    x, y, w, h = component.bounds
    draw_box(component._game.backend, x, y, w, h, resolved.background_color, border_color=resolved.border_color,
             border_width=resolved.border_width, radius=resolved.radius, order=component._order)


def keycap_size(backend: Backend, theme: Theme, key: str) -> tuple[int, int]:
    """``(width, height)`` of the keycap drawn for *key*."""
    tw, th = backend.measure_text(key, theme.keycap_font_size, theme.keycap_font or theme.font)
    h = th + 4
    return (max(tw + 2 * KEYCAP_PAD, h), h + KEYCAP_LIFT)


def draw_keycap(backend: Backend, theme: Theme, key: str, x: float, y: float, order: int) -> None:
    """Draw *key* as a keycap (a lifted cap over a dark slab) with its top-left at ``(x, y)``."""
    w, h = keycap_size(backend, theme, key)
    cap_h = h - KEYCAP_LIFT
    backend.draw_polygon(rounded_rect(x, y + KEYCAP_LIFT, w, cap_h, KEYCAP_RADIUS), (0, 0, 0, 110), order=order)
    backend.draw_polygon(rounded_rect(x, y, w, cap_h, KEYCAP_RADIUS), theme.keycap_color, order=order)
    backend.draw_text(key, x + w / 2, y + cap_h / 2, theme.keycap_font_size, theme.keycap_text_color,
                      font=theme.keycap_font or theme.font, anchor_x="center", anchor_y="center", order=order)


class Label(Component):
    """Text, optionally wrapped to an explicit width. *text* may be a string or a zero-argument
    callable re-evaluated every frame::

        Label(lambda: f"Gold {self.gold}", text_style="hud")

    Parameters:
        text_style: Named theme style or a :class:`TextStyle`.
        font_size / text_color / font: One-off overrides.
        wrap: Measure and wrap to ``width``; preferred height fits all lines.
        align: ``"left"`` (default), ``"center"`` or ``"right"`` inside an
               explicit ``width``.
    """

    def __init__(
        self,
        text: str | Callable[[], str] | None,
        *,
        text_style: str | TextStyle | None = None,
        font_size: int | None = None,
        text_color: Color | None = None,
        font: str | None = None,
        align: str = "left",
        wrap: bool = False,
        style: Style | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(style=merge_styles(Style(font=font, font_size=font_size, text_color=text_color), style), **kwargs)
        if wrap and (self._width is None or not math.isfinite(self._width) or self._width <= 0):
            raise ValueError("Wrapped labels require a positive finite width")
        self._wrap = wrap
        self._paragraph_key = None
        self._wrapped_paragraph = _Paragraph((), 0, 1.4)
        self._text_style = text_style
        self._align = align
        self._text_rv: ReactiveValue[str] = ReactiveValue(text if text is not None else "", default="", on_change=self._on_text_changed)

    @property
    def text(self) -> str:
        return self._text_rv.value

    @text.setter
    def text(self, value: str | None) -> None:
        self._text_rv.set(value if value is not None else "")

    def _on_text_changed(self, _old: str, _new: str) -> None:
        self.invalidate_layout()

    def _resolve(self) -> ResolvedStyle:
        theme = self._game.theme if self._game is not None else Theme()
        ts = self._text_style
        if isinstance(ts, str):
            ts = theme.get_text_style(ts)
        base = Style(font=ts.font, font_size=ts.font_size, text_color=ts.color) if ts is not None else None
        return theme.resolve_label_style(merge_styles(base, self.style))

    def _prepare_layout(self) -> None:
        super()._prepare_layout()
        if self._wrap:
            self._text_rv.refresh()
            self._paragraph(self._resolve())

    def _paragraph(self, resolved: ResolvedStyle) -> _Paragraph:
        backend = self._game.backend if self._game is not None else None
        key = (backend, backend.scale_factor if backend is not None else None,
               self.text, self._width, resolved.font_size, resolved.font)
        if key != self._paragraph_key:
            def measure(text):
                if backend is not None:
                    return backend.measure_text(text, resolved.font_size, resolved.font)
                return int(len(text) * resolved.font_size * 0.6), int(resolved.font_size * 1.2)
            self._wrapped_paragraph = _layout_paragraph(self.text, self._width, measure)
            self._paragraph_key = key
            self.invalidate_layout()
        return self._wrapped_paragraph

    def get_preferred_size(self) -> tuple[int, int]:
        self._text_rv.refresh()
        resolved = self._resolve()
        if self._wrap:
            w, h = self._width, math.ceil(self._paragraph(resolved).height)
        elif self._game is not None:
            w, h = self._game.backend.measure_text(self.text, resolved.font_size, resolved.font)
        else:
            w, h = int(len(self.text) * resolved.font_size * 0.6), int(resolved.font_size * 1.2)
        return (w if self._width is None else self._width, h if self._height is None else self._height)

    def on_draw(self) -> None:
        if self._game is None:
            return
        self._text_rv.refresh()
        if not self.text:
            return
        resolved = self._resolve()
        x, y, w, h = self.bounds
        if self._align == "center":
            anchor_x, tx = "center", x + w // 2
        elif self._align == "right":
            anchor_x, tx = "right", x + w
        else:
            anchor_x, tx = "left", x
        if self._wrap:
            paragraph = self._paragraph(resolved)
            top = y + (h - paragraph.height) / 2 if self._height is not None else y
            for index, line in enumerate(paragraph.lines):
                if line:
                    self._game.backend.draw_text(
                        line, tx, top + index * paragraph.line_height * paragraph.line_spacing,
                        resolved.font_size, resolved.text_color, font=resolved.font,
                        anchor_x=anchor_x, anchor_y="top", order=self._order,
                    )
            return
        self._game.backend.draw_text(
            self.text, tx, y + h // 2, resolved.font_size, resolved.text_color,
            font=resolved.font, anchor_x=anchor_x, anchor_y="center", order=self._order,
        )


class Button(Component):
    """Clickable rectangle with hover/press states.  *text* may be reactive
    like :class:`Label`.

    ``shortcut="E"`` draws a keycap and calls ``on_click`` on that key press.
    A tuple supplies aliases; its first entry is displayed. Keys are case
    insensitive; ``Enter``/``Return`` and ``Esc``/``Escape`` are equivalent.
    Modifier chords such as ``Ctrl+S`` match exactly: ``Shift+1`` cannot
    activate ``1``. Only the top scene's visible UI participates. Disabled
    buttons (or ancestors) consume a matching shortcut without activation;
    hidden or removed buttons have no shortcut. Two visible buttons claiming
    the same key raise ``ValueError`` before either callback runs.

    Normal UI event handlers have first refusal, then button shortcuts precede
    the camera and scene handlers. ``hotkey="Enter"`` instead draws a
    display-only hint for a contextual scene action. It does not bind input
    and cannot be combined with ``shortcut``. Use :attr:`Scene.controls` for
    actions without a button; a shortcut needs no separate scene binding.
    """

    def __init__(
        self,
        text: str | Callable[[], str],
        *,
        on_click: Callable[[], Any] | None = None,
        hotkey: str | None = None,
        shortcut: str | tuple[str, ...] | None = None,
        style: Style | None = None,
        **kwargs: Any,
    ) -> None:
        if hotkey is not None and shortcut is not None:
            raise ValueError("use hotkey for a display-only hint or shortcut for activation, not both")
        if shortcut is not None and not isinstance(shortcut, (str, tuple)):
            raise TypeError("shortcut must be a string, a tuple of strings, or None")
        if shortcut == ():
            raise ValueError("shortcut aliases cannot be empty")
        super().__init__(style=style, **kwargs)
        self._text_rv: ReactiveValue[str] = ReactiveValue(text, on_change=lambda _o, _n: self.invalidate_layout())
        shortcuts = (shortcut,) if isinstance(shortcut, str) else shortcut or ()
        self._hotkey = shortcuts[0] if shortcuts else hotkey
        self._shortcuts = tuple(_normalize_shortcut(key) for key in shortcuts)
        self.on_click = on_click
        self._state: Literal["normal", "hovered", "pressed"] = "normal"

    @property
    def text(self) -> str:
        return self._text_rv.value

    @text.setter
    def text(self, value: str) -> None:
        self._text_rv.set(value)

    @property
    def state(self) -> str:
        return self._state

    def _resolve(self, state: str = "normal") -> ResolvedStyle:
        theme = self._game.theme if self._game is not None else Theme()
        return theme.resolve_button_style(self.style, state)  # type: ignore[arg-type]

    def _content_size(self, resolved: ResolvedStyle) -> tuple[int, int, int]:
        """``(text width, keycap width, height)`` of the label and its keycap."""
        self._text_rv.refresh()
        if self._game is None:
            return int(len(self.text) * resolved.font_size * 0.6), 0, int(resolved.font_size * 1.2)
        backend, theme = self._game.backend, self._game.theme
        tw, th = backend.measure_text(self.text, resolved.font_size, resolved.font)
        kw, kh = keycap_size(backend, theme, self._hotkey) if self._hotkey else (0, 0)
        return tw, kw, max(th, kh)

    def get_preferred_size(self) -> tuple[int, int]:
        resolved = self._resolve()
        tw, kw, h = self._content_size(resolved)
        min_width = self._game.theme.button_min_width if self._game is not None else 120
        content = tw + (kw + KEYCAP_GAP if kw else 0)
        w = max(content + 2 * resolved.padding, min_width) if self._width is None else self._width
        return (w, h + 2 * resolved.padding if self._height is None else self._height)

    def on_event(self, event: InputEvent) -> bool:
        if event.type == "move":
            over = self.hit_test(event.x, event.y)
            if over and self._state == "normal":
                self._state = "hovered"
            elif not over and self._state == "hovered":
                self._state = "normal"
            return False  # siblings must see moves to un-hover
        if event.type == "click" and event.button == "left" and self.hit_test(event.x, event.y):
            self._state = "pressed"
            self._activate()
            return True
        if event.type == "release" and self._state == "pressed":
            self._state = "hovered" if self.hit_test(event.x, event.y) else "normal"
            return True
        return False

    def _activate(self) -> None:
        if self.on_click is not None:
            self.on_click()

    def on_draw(self) -> None:
        if self._game is None:
            return
        resolved = self._resolve("disabled" if not self.enabled else self._state)
        x, y, w, h = self.bounds
        backend, theme = self._game.backend, self._game.theme
        _draw_component_box(self, resolved)
        tw, kw, _ = self._content_size(resolved)
        content = tw + (kw + KEYCAP_GAP if kw else 0)
        left = x + (w - content) / 2
        backend.draw_text(self.text, left, y + h / 2, resolved.font_size, resolved.text_color,
                          font=resolved.font, anchor_x="left", anchor_y="center", order=self._order)
        if self._hotkey:
            _, kh = keycap_size(backend, theme, self._hotkey)
            draw_keycap(backend, theme, self._hotkey, left + tw + KEYCAP_GAP, y + (h - kh) / 2, self._order)


class Panel(Component):
    """Container with background, border and optional flow layout."""

    def __init__(
        self,
        *,
        layout: Layout = Layout.NONE,
        spacing: int = 0,
        children: list[Component] | None = None,
        style: Style | None = None,
        **kwargs: Any,
    ) -> None:
        if spacing < 0:
            raise ValueError(f"spacing cannot be negative, got {spacing}")
        super().__init__(style=style, **kwargs)
        self._layout = layout
        self._spacing = spacing
        for child in children or ():
            self.add(child)

    @property
    def layout(self) -> Layout:
        return self._layout

    @property
    def spacing(self) -> int:
        return self._spacing

    def _resolve(self) -> ResolvedStyle:
        theme = self._game.theme if self._game is not None else Theme()
        return theme.resolve_panel_style(self.style)

    def _visible_sizes(self) -> list[tuple[Component, tuple[int, int]]]:
        return [(c, c.get_preferred_size()) for c in self._children if c.visible]

    def get_preferred_size(self) -> tuple[int, int]:
        if self._width is not None and self._height is not None:
            return (self._width, self._height)
        padding = self._resolve().padding
        if self._layout is Layout.NONE:
            return (self._width or 100, self._height or 100)
        cw, ch = compute_content_size(self._layout, [s for _, s in self._visible_sizes()], self._spacing, padding)
        return (self._width if self._width is not None else cw, self._height if self._height is not None else ch)

    def compute_layout(self, x: int, y: int, w: int, h: int) -> None:
        own_w, own_h = self.get_preferred_size()
        if self._anchor is not None:
            self._computed_x, self._computed_y = compute_anchor_position(self._anchor, x, y, w, h, own_w, own_h, self._margin)
        else:
            self._computed_x, self._computed_y = x, y
        self._computed_w, self._computed_h = own_w, own_h
        self._layout_children()
        self._layout_dirty = False

    def _layout_children(self) -> None:
        if self._layout is Layout.NONE:
            super()._layout_children()
            return
        padding = self._resolve().padding
        visible = self._visible_sizes()
        positions = compute_flow_layout(
            self._layout, self._computed_x, self._computed_y, self._computed_w, self._computed_h,
            [s for _, s in visible], self._spacing, padding,
        )
        for (child, (cw, ch)), (cx, cy) in zip(visible, positions):
            child.compute_layout(cx, cy, cw, ch)

    def on_event(self, event: InputEvent) -> bool:
        """Clicks inside an opaque panel stop there instead of reaching the scene."""
        if event.type in ("click", "release") and self.hit_test(event.x, event.y):
            return self._resolve().background_color[3] > 0
        return False

    def on_draw(self) -> None:
        if self._game is None:
            return
        _draw_component_box(self, self._resolve())


_TRANSPARENT = Style(background_color=(0, 0, 0, 0), border_width=0, padding=0)


HintItems = list[tuple[str, str]]


class KeyHints(Component):
    """A row of “keycap action” pairs, e.g. ``KeyHints([("E", "end turn"), ("T", "tech")])``.
    *items* may be a zero-argument callable re-evaluated every frame."""

    def __init__(self, items: HintItems | Callable[[], HintItems], *, text_style: str | TextStyle = "caption",
                 gap: int = 6, spacing: int = 18, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._items_rv: ReactiveValue[HintItems] = ReactiveValue(items, default=[], on_change=lambda _o, _n: self.invalidate_layout())
        self._text_style = text_style
        self._gap = gap
        self._spacing = spacing

    @property
    def items(self) -> HintItems:
        self._items_rv.refresh()
        return self._items_rv.value

    def _style(self) -> TextStyle:
        ts = self._text_style
        return self._game.theme.get_text_style(ts) if isinstance(ts, str) else ts

    def _measure(self) -> list[tuple[str, str, tuple[int, int], int]]:
        """Per item: key, text, keycap size, text width."""
        backend, theme = self._game.backend, self._game.theme
        style = self._style()
        return [
            (key, text, keycap_size(backend, theme, key), backend.measure_text(text, style.font_size, style.font or theme.font)[0])
            for key, text in self.items
        ]

    def get_preferred_size(self) -> tuple[int, int]:
        if self._game is None:
            return (self._width or 0, self._height or 0)
        measured = self._measure()
        w = sum(kw + self._gap + tw for _, _, (kw, _), tw in measured) + self._spacing * max(0, len(measured) - 1)
        h = max((kh for _, _, (_, kh), _ in measured), default=0)
        return (w if self._width is None else self._width, h if self._height is None else self._height)

    def on_draw(self) -> None:
        if self._game is None:
            return
        backend, theme = self._game.backend, self._game.theme
        style = self._style()
        x, y, _w, h = self.bounds
        order = self._order
        for key, text, (kw, kh), tw in self._measure():
            draw_keycap(backend, theme, key, x, y + (h - kh) / 2, order)
            x += kw + self._gap
            backend.draw_text(text, x, y + h / 2, style.font_size, style.color, font=style.font or theme.font,
                              anchor_x="left", anchor_y="center", order=order)
            x += tw + self._spacing


class Row(Panel):
    """Transparent horizontal container: ``Row(Label(...), Label(...), spacing=8)``."""

    def __init__(self, *children: Component, spacing: int = 8, style: Style | None = None, **kwargs: Any) -> None:
        super().__init__(layout=Layout.HORIZONTAL, spacing=spacing, children=list(children), style=style or _TRANSPARENT, **kwargs)


class Column(Panel):
    """Transparent vertical container."""

    def __init__(self, *children: Component, spacing: int = 8, style: Style | None = None, **kwargs: Any) -> None:
        super().__init__(layout=Layout.VERTICAL, spacing=spacing, children=list(children), style=style or _TRANSPARENT, **kwargs)


class ProgressBar(Component):
    """Filled bar for ``value / max_value``; both may be reactive callables."""

    def __init__(
        self,
        value: float | Callable[[], float] = 0,
        max_value: float | Callable[[], float] = 100,
        *,
        width: int = 160,
        height: int = 12,
        bar_color: Color | None = None,
        bg_color: Color | None = None,
        rounded: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(width=width, height=height, **kwargs)
        self._value_rv: ReactiveValue[float] = ReactiveValue(value)
        self._max_rv: ReactiveValue[float] = ReactiveValue(max_value)
        self._bar_color = bar_color
        self._bg_color = bg_color
        self._rounded = rounded

    @property
    def value(self) -> float:
        self._value_rv.refresh()
        return self._value_rv.value

    @value.setter
    def value(self, v: float) -> None:
        self._value_rv.set(v)

    @property
    def max_value(self) -> float:
        self._max_rv.refresh()
        return self._max_rv.value

    @max_value.setter
    def max_value(self, v: float) -> None:
        self._max_rv.set(v)

    @property
    def fraction(self) -> float:
        mv = self.max_value
        return max(0.0, min(1.0, self.value / mv)) if mv > 0 else 0.0

    def on_draw(self) -> None:
        if self._game is None:
            return
        theme = self._game.theme
        bg = self._bg_color if self._bg_color is not None else theme.progressbar_bg_color
        bar = self._bar_color if self._bar_color is not None else theme.progressbar_color
        x, y, w, h = self.bounds
        self._draw_bar(x, y, w, h, bg)
        fill = int(w * self.fraction)
        if fill > 0:
            self._draw_bar(x, y, max(fill, h if self._rounded else 1), h, bar)

    def _draw_bar(self, x: int, y: int, w: int, h: int, color: Color) -> None:
        backend = self._game.backend
        order = self._order
        if not self._rounded or w <= h:
            backend.draw_rect(x, y, w, h, color, order=order)
            return
        r = h / 2
        backend.draw_rect(x + r, y, w - h, h, color, order=order)
        backend.draw_circle(x + r, y + r, r, color, order=order)
        backend.draw_circle(x + w - r, y + r, r, color, order=order)
