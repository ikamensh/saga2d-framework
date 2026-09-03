"""Label, Button, Panel, Row, Column, ProgressBar."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Literal

from saga2d.ui.base import Component
from saga2d.ui.layout import Layout, compute_anchor_position, compute_content_size, compute_flow_layout
from saga2d.ui.theme import Color, ResolvedStyle, Style, TextStyle, Theme, merge_styles
from saga2d.util.reactive import ReactiveValue

if TYPE_CHECKING:
    from saga2d.input import InputEvent


def _draw_border(component: Component, color: Color, width: int) -> None:
    x, y, w, h = component.bounds
    backend = component._game.backend
    order = component._order
    backend.draw_rect(x, y, w, width, color, order=order)
    backend.draw_rect(x, y + h - width, w, width, color, order=order)
    backend.draw_rect(x, y, width, h, color, order=order)
    backend.draw_rect(x + w - width, y, width, h, color, order=order)


class Label(Component):
    """Single line of text.  *text* may be a string or a zero-argument
    callable re-evaluated every frame::

        Label(lambda: f"Gold {self.gold}", text_style="hud")

    Parameters:
        text_style: Named theme style or a :class:`TextStyle`.
        font_size / text_color / font: One-off overrides.
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
        style: Style | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(style=merge_styles(Style(font=font, font_size=font_size, text_color=text_color), style), **kwargs)
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

    def get_preferred_size(self) -> tuple[int, int]:
        self._text_rv.refresh()
        resolved = self._resolve()
        if self._game is not None:
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
        self._game.backend.draw_text(
            self.text, tx, y + h // 2, resolved.font_size, resolved.text_color,
            font=resolved.font, anchor_x=anchor_x, anchor_y="center", order=self._order,
        )


class Button(Component):
    """Clickable rectangle with hover/press states.  *text* may be reactive
    like :class:`Label`; *hotkey* is shown after the text (e.g. ``"[E]"``)."""

    def __init__(
        self,
        text: str | Callable[[], str],
        *,
        on_click: Callable[[], Any] | None = None,
        hotkey: str | None = None,
        style: Style | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(style=style, **kwargs)
        self._text_rv: ReactiveValue[str] = ReactiveValue(text, on_change=lambda _o, _n: self.invalidate_layout())
        self._hotkey = hotkey
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

    def _label(self) -> str:
        self._text_rv.refresh()
        return f"{self.text}  {self._hotkey}" if self._hotkey else self.text

    def _resolve(self, state: str = "normal") -> ResolvedStyle:
        theme = self._game.theme if self._game is not None else Theme()
        return theme.resolve_button_style(self.style, state)  # type: ignore[arg-type]

    def get_preferred_size(self) -> tuple[int, int]:
        resolved = self._resolve()
        label = self._label()
        if self._game is not None:
            tw, th = self._game.backend.measure_text(label, resolved.font_size, resolved.font)
            min_width = self._game.theme.button_min_width
        else:
            tw, th, min_width = int(len(label) * resolved.font_size * 0.6), int(resolved.font_size * 1.2), 120
        w = max(tw + 2 * resolved.padding, min_width) if self._width is None else self._width
        h = th + 2 * resolved.padding if self._height is None else self._height
        return (w, h)

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
            if self.on_click is not None:
                self.on_click()
            return True
        if event.type == "release" and self._state == "pressed":
            self._state = "hovered" if self.hit_test(event.x, event.y) else "normal"
            return True
        return False

    def on_draw(self) -> None:
        if self._game is None:
            return
        resolved = self._resolve("disabled" if not self.enabled else self._state)
        x, y, w, h = self.bounds
        backend = self._game.backend
        backend.draw_rect(x, y, w, h, resolved.background_color, order=self._order)
        if resolved.border_width > 0 and resolved.border_color is not None:
            _draw_border(self, resolved.border_color, resolved.border_width)
        backend.draw_text(
            self._label(), x + w // 2, y + h // 2, resolved.font_size, resolved.text_color,
            font=resolved.font, anchor_x="center", anchor_y="center", order=self._order,
        )


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

    def on_draw(self) -> None:
        if self._game is None:
            return
        resolved = self._resolve()
        x, y, w, h = self.bounds
        if resolved.background_color[3] > 0:
            self._game.backend.draw_rect(x, y, w, h, resolved.background_color, order=self._order)
        if resolved.border_width > 0 and resolved.border_color is not None:
            _draw_border(self, resolved.border_color, resolved.border_width)


_TRANSPARENT = Style(background_color=(0, 0, 0, 0), border_width=0, padding=0)


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
