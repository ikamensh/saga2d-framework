"""Concrete UI components: Label, Button, and Panel.

These are the three building blocks for in-game menus and HUDs.

*   :class:`Label` — static text display.
*   :class:`Button` — clickable rectangle with hover / press states.
*   :class:`Panel` — container with optional flow layout and background.

All three inherit from :class:`~saga2d.ui.component.Component` and
access the backend through ``self._game._backend`` and the theme
through ``self._game.theme``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Literal

from saga2d.ui.component import Component
from saga2d.ui.layout import (
    Layout,
    compute_anchor_position,
    compute_content_size,
    compute_flow_layout,
)
from saga2d.ui.theme import ResolvedStyle, Style

if TYPE_CHECKING:
    from saga2d.input import InputEvent


# ---------------------------------------------------------------------------
# Text size heuristic
# ---------------------------------------------------------------------------


def _estimate_text_width(text: str, font_size: int) -> int:
    """Estimate rendered text width using a per-character heuristic.

    Uppercase letters and digits are wider than lowercase, so each
    character is weighted individually:

    *   Uppercase letters: ``font_size × 0.95``
    *   Lowercase letters: ``font_size × 0.65``
    *   Digits: ``font_size × 0.65``
    *   Spaces: ``font_size × 0.40``
    *   Other punctuation: ``font_size × 0.50``

    The sum is a rough but usable estimate for layout purposes.
    These weights are tuned for common serif/sans-serif fonts and
    intentionally overestimate slightly — it's better to have a
    bit of extra space than to clip text.
    """
    total = 0.0
    for ch in text:
        if ch == " ":
            total += font_size * 0.40
        elif ch.isupper():
            total += font_size * 0.95
        elif ch.islower():
            total += font_size * 0.65
        elif ch.isdigit():
            total += font_size * 0.65
        else:
            total += font_size * 0.50
    return int(total)


# ---------------------------------------------------------------------------
# Label
# ---------------------------------------------------------------------------


def _merge_label_style(
    style: Style | None,
    font_size: int | None,
    text_color: tuple[int, int, int, int] | None,
    font: str | None,
) -> Style | None:
    """Merge convenience kwargs with explicit Style. Explicit style wins for overlapping fields."""
    base = style or Style()
    if font_size is None and text_color is None and font is None:
        return style
    return Style(
        font=base.font if base.font is not None else font,
        font_size=base.font_size if base.font_size is not None else font_size,
        text_color=base.text_color if base.text_color is not None else text_color,
        background_color=base.background_color,
        padding=base.padding,
        border_color=base.border_color,
        border_width=base.border_width,
        hover_color=base.hover_color,
        press_color=base.press_color,
    )


class Label(Component):
    """Static text display.

    Draws a single line of text using the backend's ``draw_text()`` call.
    Sizes itself with a character-width heuristic when no explicit
    ``width``/``height`` is given.

    Parameters:
        text:       The text string to display.
        font_size:  Convenience override for font size (avoids wrapping in Style).
        text_color: Convenience override for text color, e.g. ``(255, 255, 255, 255)``.
        font:       Convenience override for font family.
        style:      Explicit :class:`Style` overrides. When both style and
                    convenience kwargs are provided, explicit style wins for
                    overlapping fields.
        **kwargs:   Forwarded to :class:`Component` (``width``, ``height``,
                    ``anchor``, ``margin``, ``visible``, ``enabled``).
    """

    def __init__(
        self,
        text: str | None,
        *,
        font_size: int | None = None,
        text_color: tuple[int, int, int, int] | None = None,
        font: str | None = None,
        style: Style | None = None,
        **kwargs: Any,
    ) -> None:
        merged = _merge_label_style(style, font_size, text_color, font)
        super().__init__(style=merged, **kwargs)
        self._text = text if text is not None else ""
        self._font_handle: Any = None

    # -- Properties --------------------------------------------------------

    @property
    def text(self) -> str:
        """The displayed text."""
        return self._text

    @text.setter
    def text(self, value: str | None) -> None:
        new_text = value if value is not None else ""
        if new_text != self._text:
            self._text = new_text
            self._font_handle = None  # invalidate cached font
            self._mark_layout_dirty()

    # -- Layout ------------------------------------------------------------

    def get_preferred_size(self) -> tuple[int, int]:
        """Estimate text dimensions using a per-character width heuristic.

        Uses :func:`_estimate_text_width` which weights uppercase letters
        wider than lowercase.  Height is ``font_size × 1.4``.

        Explicit ``width``/``height`` override the heuristic.
        """
        resolved = self._resolve_style()
        font_size = resolved.font_size
        w = (
            _estimate_text_width(self._text, font_size)
            if self._width is None
            else self._width
        )
        h = int(font_size * 1.4) if self._height is None else self._height
        return (w, h)

    # -- Drawing -----------------------------------------------------------

    def on_draw(self) -> None:
        """Draw the text at the computed position."""
        if self._game is None or not self._text:
            return
        resolved = self._resolve_style()
        if self._font_handle is None:
            self._font_handle = self._game._backend.load_font(resolved.font)
        self._game._backend.draw_text(
            self._text,
            self._computed_x,
            self._computed_y,
            resolved.font_size,
            resolved.text_color,
            font=self._font_handle,
        )

    # -- Internal ----------------------------------------------------------

    def _resolve_style(self) -> ResolvedStyle:
        """Merge explicit style with label defaults from the theme."""
        if self._game is not None:
            return self._game.theme.resolve_label_style(self.style)
        # Fallback when not yet attached to a game tree.
        from saga2d.ui.theme import Theme

        return Theme().resolve_label_style(self.style)


# ---------------------------------------------------------------------------
# Button
# ---------------------------------------------------------------------------


class Button(Component):
    """Clickable button with hover / press visual states.

    Draws a background rectangle (color depends on state) with centered
    text on top.  Fires ``on_click`` on mouse press within bounds.

    State machine::

        normal  → mouse enters  → hovered
        hovered → mouse leaves  → normal
        hovered → click         → pressed (fires on_click)
        pressed → release       → hovered (if over) or normal

    Parameters:
        text:     Button label text.
        on_click: Callback fired when the button is clicked.  May be
                  ``None`` (useful for buttons whose callback is set
                  later).
        style:    Explicit :class:`Style` overrides.
        **kwargs: Forwarded to :class:`Component`.
    """

    def __init__(
        self,
        text: str,
        *,
        on_click: Callable[[], Any] | None = None,
        style: Style | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(style=style, **kwargs)
        self._text = text
        self._on_click = on_click
        self._state: Literal["normal", "hovered", "pressed"] = "normal"
        self._font_handle: Any = None

    # -- Properties --------------------------------------------------------

    @property
    def text(self) -> str:
        """The button label text."""
        return self._text

    @text.setter
    def text(self, value: str) -> None:
        if value != self._text:
            self._text = value
            self._font_handle = None
            self._mark_layout_dirty()

    @property
    def on_click(self) -> Callable[[], Any] | None:
        """The click callback."""
        return self._on_click

    @on_click.setter
    def on_click(self, value: Callable[[], Any] | None) -> None:
        self._on_click = value

    @property
    def state(self) -> str:
        """Current visual state: ``"normal"``, ``"hovered"``, or ``"pressed"``."""
        return self._state

    # -- Layout ------------------------------------------------------------

    def get_preferred_size(self) -> tuple[int, int]:
        """Button size: text dimensions + padding, respecting min_width.

        Uses :func:`_estimate_text_width` (same heuristic as
        :class:`Label`), then adds padding on all sides and enforces
        the theme's minimum button width.
        """
        resolved = self._resolve_style("normal")
        font_size = resolved.font_size
        text_w = _estimate_text_width(self._text, font_size)
        text_h = int(font_size * 1.4)
        padding = resolved.padding

        # Get min_width from theme.
        if self._game is not None:
            min_width = self._game.theme.button_min_width
        else:
            min_width = 200  # default

        w = max(text_w + padding * 2, min_width) if self._width is None else self._width
        h = (text_h + padding * 2) if self._height is None else self._height
        return (w, h)

    # -- Input handling ----------------------------------------------------

    def on_event(self, event: InputEvent) -> bool:
        """Handle mouse events for hover / press state transitions.

        *   ``move``: update hover state.  Never consumed — all siblings
            must see every move so they can un-hover when the mouse
            leaves.  This prevents two adjacent buttons from both being
            stuck in "hovered" state.
        *   ``click``: set pressed and fire ``on_click``.  Consumed.
        *   ``release``: return to hovered/normal.  Consumed.
        """
        if not self.enabled:
            return False

        if event.type == "move":
            is_over = self.hit_test(event.x, event.y)
            if is_over and self._state == "normal":
                self._state = "hovered"
            elif not is_over and self._state == "hovered":
                self._state = "normal"
            return False  # never consume moves — siblings need them

        if event.type == "click":
            if self.hit_test(event.x, event.y):
                self._state = "pressed"
                if self._on_click is not None:
                    self._on_click()
                return True

        if event.type == "release":
            if self._state == "pressed":
                self._state = "hovered" if self.hit_test(event.x, event.y) else "normal"
                return True

        return False

    # -- Drawing -----------------------------------------------------------

    def on_draw(self) -> None:
        """Draw background rectangle then centered text."""
        if self._game is None:
            return
        state: Literal["normal", "hovered", "pressed", "disabled"] = (
            "disabled" if not self.enabled else self._state
        )
        resolved = self._resolve_style(state)

        # Background rect.
        self._game._backend.draw_rect(
            self._computed_x,
            self._computed_y,
            self._computed_w,
            self._computed_h,
            resolved.background_color,
        )

        # Centered text.
        if self._font_handle is None:
            self._font_handle = self._game._backend.load_font(resolved.font)
        text_x = self._computed_x + self._computed_w // 2
        text_y = self._computed_y + self._computed_h // 2
        self._game._backend.draw_text(
            self._text,
            text_x,
            text_y,
            resolved.font_size,
            resolved.text_color,
            font=self._font_handle,
            anchor_x="center",
            anchor_y="center",
        )

    # -- Internal ----------------------------------------------------------

    def _resolve_style(
        self,
        state: Literal["normal", "hovered", "pressed", "disabled"] = "normal",
    ) -> ResolvedStyle:
        """Merge explicit style with button defaults, considering state."""
        if self._game is not None:
            return self._game.theme.resolve_button_style(self.style, state)
        from saga2d.ui.theme import Theme

        return Theme().resolve_button_style(self.style, state)


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


class Panel(Component):
    """Container component with optional background and flow layout.

    A Panel can arrange its children using :attr:`Layout.VERTICAL` or
    :attr:`Layout.HORIZONTAL` flow, or :attr:`Layout.NONE` for free
    anchor-based positioning within the panel.

    When no explicit ``width``/``height`` is given, the Panel sizes
    itself to fit its children (content-fit).

    Parameters:
        layout:   How children are arranged.
        spacing:  Gap in pixels between adjacent children (flow layouts).
        children: Optional list of children to add immediately.
        style:    Explicit :class:`Style` overrides.
        **kwargs: Forwarded to :class:`Component` (``width``, ``height``,
                  ``anchor``, ``margin``, ``visible``, ``enabled``).
    """

    def __init__(
        self,
        *,
        layout: Layout = Layout.NONE,
        spacing: int | None = 0,
        children: list[Component] | None = None,
        style: Style | None = None,
        **kwargs: Any,
    ) -> None:
        if spacing is None:
            spacing = 0
        if spacing < 0:
            raise ValueError(f"spacing cannot be negative, got {spacing}")
        super().__init__(style=style, **kwargs)
        self._layout = layout
        self._spacing = spacing
        if children:
            for child in children:
                self.add(child)

    # -- Properties --------------------------------------------------------

    @property
    def layout(self) -> Layout:
        """The layout strategy for children."""
        return self._layout

    @property
    def spacing(self) -> int:
        """Gap between children in flow layouts."""
        return self._spacing

    # -- Layout ------------------------------------------------------------

    def get_preferred_size(self) -> tuple[int, int]:
        """Panel size: explicit dimensions, or content-fit from children.

        Content-fit uses :func:`compute_content_size` to measure children
        and add padding/spacing.  For ``Layout.NONE`` without explicit
        dimensions, falls back to ``(100, 100)``.
        """
        if self._width is not None and self._height is not None:
            return (self._width, self._height)

        resolved = self._resolve_style()
        padding = resolved.padding

        if self._layout in (Layout.VERTICAL, Layout.HORIZONTAL):
            children_sizes = [c.get_preferred_size() for c in self._children]
            content_w, content_h = compute_content_size(
                self._layout,
                children_sizes,
                self._spacing,
                padding,
            )
            w = self._width if self._width is not None else content_w
            h = self._height if self._height is not None else content_h
            return (w, h)

        # Layout.NONE: use explicit size or fallback.
        return (self._width or 100, self._height or 100)

    def compute_layout(self, x: int, y: int, w: int, h: int) -> None:
        """Position self within parent bounds, then lay out children.

        For flow layouts (VERTICAL / HORIZONTAL), children are positioned
        using :func:`compute_flow_layout`.  For ``Layout.NONE``, each
        child lays itself out within the panel's bounds using its own
        anchor.
        """
        own_w, own_h = self.get_preferred_size()

        if self._anchor is not None:
            ax, ay = compute_anchor_position(
                self._anchor,
                x,
                y,
                w,
                h,
                own_w,
                own_h,
                self._margin,
            )
            self._computed_x = ax
            self._computed_y = ay
        else:
            self._computed_x = x
            self._computed_y = y
        self._computed_w = own_w
        self._computed_h = own_h

        # Lay out children.
        self._layout_children()
        self._layout_dirty = False

    def _layout_children(self) -> None:
        """Lay out children according to the panel's layout strategy."""
        if self._layout in (Layout.VERTICAL, Layout.HORIZONTAL):
            resolved = self._resolve_style()
            padding = resolved.padding
            children_sizes = [c.get_preferred_size() for c in self._children]
            positions = compute_flow_layout(
                self._layout,
                self._computed_x,
                self._computed_y,
                self._computed_w,
                self._computed_h,
                children_sizes,
                self._spacing,
                padding,
            )
            for child, (cx, cy), (cw, ch) in zip(
                self._children,
                positions,
                children_sizes,
            ):
                child.compute_layout(cx, cy, cw, ch)
        else:
            # Layout.NONE: each child gets the full panel bounds.
            for child in self._children:
                child.compute_layout(
                    self._computed_x,
                    self._computed_y,
                    self._computed_w,
                    self._computed_h,
                )

    # -- Drawing -----------------------------------------------------------

    def on_draw(self) -> None:
        """Draw the panel's background rectangle."""
        if self._game is None:
            return
        resolved = self._resolve_style()
        bg = resolved.background_color
        if bg is not None:
            self._game._backend.draw_rect(
                self._computed_x,
                self._computed_y,
                self._computed_w,
                self._computed_h,
                bg,
            )

    # -- Internal ----------------------------------------------------------

    def _resolve_style(self) -> ResolvedStyle:
        """Merge explicit style with panel defaults from the theme."""
        if self._game is not None:
            return self._game.theme.resolve_panel_style(self.style)
        from saga2d.ui.theme import Theme

        return Theme().resolve_panel_style(self.style)
