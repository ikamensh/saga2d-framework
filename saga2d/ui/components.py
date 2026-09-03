"""Concrete UI components: Label, Button, and Panel.

These are the three building blocks for in-game menus and HUDs.

*   :class:`Label` — static text display.
*   :class:`Button` — clickable rectangle with hover / press states.
*   :class:`Panel` — container with optional flow layout and background.

All three inherit from :class:`~saga2d.ui.base.Component` and
access the backend through ``self._game._backend`` and the theme
through ``self._game.theme``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Literal

from saga2d.ui.base import Component
from saga2d.ui.layout import (
    Layout,
    compute_anchor_position,
    compute_content_size,
    compute_flow_layout,
)
from saga2d.ui.theme import ResolvedStyle, Style, TextStyle
from saga2d.util.reactive import ReactiveValue

if TYPE_CHECKING:
    from saga2d.input import InputEvent


# ---------------------------------------------------------------------------
# Border drawing helper
# ---------------------------------------------------------------------------


def _draw_border(
    backend: Any,
    x: int,
    y: int,
    width: int,
    height: int,
    border_color: tuple[int, int, int, int],
    border_width: int,
) -> None:
    """Draw a border as four thin rectangles inset within the given bounds.

    The border is drawn as four rectangles:
    - Top: from (x, y) with dimensions (width, border_width)
    - Bottom: from (x, y + height - border_width) with dimensions (width, border_width)
    - Left: from (x, y) with dimensions (border_width, height)
    - Right: from (x + width - border_width, y) with dimensions (border_width, height)

    Parameters:
        backend: The backend to draw with.
        x: Left edge of the component.
        y: Top edge of the component.
        width: Total width of the component.
        height: Total height of the component.
        border_color: RGBA color tuple for the border.
        border_width: Thickness of the border in pixels.
    """
    # Top border
    backend.draw_rect(x, y, width, border_width, border_color)
    # Bottom border
    backend.draw_rect(x, y + height - border_width, width, border_width, border_color)
    # Left border
    backend.draw_rect(x, y, border_width, height, border_color)
    # Right border
    backend.draw_rect(x + width - border_width, y, border_width, height, border_color)


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
    """Static or reactive text display.

    Draws a single line of text using the backend's ``draw_text()`` call.
    Sizes itself with a character-width heuristic when no explicit
    ``width``/``height`` is given.

    *text* may be a plain string **or a zero-argument callable returning
    a string**. A callable is re-evaluated on every frame before draw so
    the HUD can be declarative::

        panel.add(Label(lambda: f"HP {self.hp}/{self.max_hp}"))
        panel.add(Label(lambda: f"Coins {self.coins}"))

    — no manual ``label.text = "…"`` wiring after every state change.
    Assigning to :attr:`text` explicitly unbinds the callable.

    Parameters:
        text:       A string or ``Callable[[], str]``. ``None`` is
                    treated as the empty string.
        text_style: Named theme text style (``"title"``, ``"hud"``,
                    ``"sub"``, etc.) or a :class:`TextStyle` instance.
                    Mirrors :meth:`saga2d.Scene.draw_text`'s ``style=``.
                    Any of the convenience kwargs below override the
                    named style's value for this label.
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
        text: str | Callable[[], str] | None,
        *,
        text_style: str | TextStyle | None = None,
        font_size: int | None = None,
        text_color: tuple[int, int, int, int] | None = None,
        font: str | None = None,
        style: Style | None = None,
        **kwargs: Any,
    ) -> None:
        merged = _merge_label_style(style, font_size, text_color, font)
        super().__init__(style=merged, **kwargs)
        self._text_style: str | TextStyle | None = text_style
        # Reactive slot — callable evaluated each frame via refresh();
        # explicit .text = ... unbinds. on_change invalidates font cache
        # and layout so sizing re-computes when the string changes.
        self._text_rv: ReactiveValue[str] = ReactiveValue(
            text if text is not None else "",
            default="",
            on_change=self._on_text_changed,
        )
        self._font_handle: Any = None

    # -- Properties --------------------------------------------------------

    @property
    def text(self) -> str:
        """The currently displayed text.

        For a reactive label, returns the last evaluated value. Reading
        does not trigger a new evaluation; draw/layout do.
        """
        return self._text_rv.value

    @text.setter
    def text(self, value: str | None) -> None:
        # Assigning explicitly unbinds any reactive callable.
        self._text_rv.set(value if value is not None else "")

    def _on_text_changed(self, _old: str, _new: str) -> None:
        """Invalidate the cached font handle and mark layout dirty."""
        self._font_handle = None
        self._mark_layout_dirty()

    def _refresh_text(self) -> None:
        """Re-evaluate the reactive text callable, if any."""
        self._text_rv.refresh()

    @property
    def _text(self) -> str:
        """Internal accessor for the last-evaluated text (for tests)."""
        return self._text_rv.value

    # -- Layout ------------------------------------------------------------

    def get_preferred_size(self) -> tuple[int, int]:
        """Estimate text dimensions using a per-character width heuristic.

        Uses :func:`_estimate_text_width` which weights uppercase letters
        wider than lowercase.  Height is ``font_size × 1.4``.

        Explicit ``width``/``height`` override the heuristic. Reactive
        labels re-evaluate their text source here so layout tracks
        whatever the callable returned most recently.
        """
        self._refresh_text()
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
        if self._game is None:
            return
        self._refresh_text()
        if not self._text:
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
            anchor_x="left",
            anchor_y="top",
        )

    # -- Internal ----------------------------------------------------------

    def _resolved_text_style(self) -> TextStyle | None:
        """Return the label's :class:`TextStyle`, resolved from the theme
        when supplied as a string name. ``None`` when no text_style is set
        or when it is a string and the label is not yet attached to a game.
        """
        ts = self._text_style
        if ts is None:
            return None
        if isinstance(ts, TextStyle):
            return ts
        # String name — needs theme access.
        if self._game is None:
            return None
        return self._game.theme.get_text_style(ts)

    def _resolve_style(self) -> ResolvedStyle:
        """Merge text_style, explicit Style, and theme label defaults.

        Precedence (lowest → highest):
        1. Theme label defaults.
        2. ``text_style`` (resolved if a string name was passed).
        3. Explicit ``style`` / ``font_size`` / ``text_color`` / ``font``
           kwargs.
        """
        explicit = self.style
        text_style = self._resolved_text_style()

        if text_style is not None:
            # Layer text_style as a base Style; explicit kwargs win on top.
            base = Style(
                font=text_style.font,
                font_size=text_style.font_size,
                text_color=text_style.color,
            )
            if explicit is not None:
                base = Style(
                    font=explicit.font if explicit.font is not None else base.font,
                    font_size=(
                        explicit.font_size
                        if explicit.font_size is not None
                        else base.font_size
                    ),
                    text_color=(
                        explicit.text_color
                        if explicit.text_color is not None
                        else base.text_color
                    ),
                    background_color=explicit.background_color,
                    padding=explicit.padding,
                    border_color=explicit.border_color,
                    border_width=explicit.border_width,
                    hover_color=explicit.hover_color,
                    press_color=explicit.press_color,
                )
            effective = base
        else:
            effective = explicit

        if self._game is not None:
            return self._game.theme.resolve_label_style(effective)
        from saga2d.ui.theme import Theme

        return Theme().resolve_label_style(effective)


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
        if value is None:
            raise TypeError("Button text must be a string, got None")
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
            btn = getattr(event, "button", None)
            if btn is not None and btn != "left":
                return False
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
        """Draw background rectangle, border, then centered text."""
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

        # Hover outline (outer glow effect when hovered).  Skipped when
        # the caller explicitly requested a ghost (alpha-0) background —
        # a glow around an invisible button is a surprising phantom
        # outline. Only the *explicit* style signals intent; the
        # resolved hover-state bg is opaque by theme default.
        explicit = self.style
        explicit_bg = explicit.background_color if explicit is not None else None
        explicit_transparent = (
            explicit_bg is not None
            and len(explicit_bg) >= 4
            and explicit_bg[3] == 0
        )
        if self._state == "hovered" and not explicit_transparent:
            theme = self._game.theme
            _draw_border(
                self._game._backend,
                self._computed_x - 2,
                self._computed_y - 2,
                self._computed_w + 4,
                self._computed_h + 4,
                theme.button_hover_outline_color,
                theme.button_hover_outline_width,
            )

        # Border (on top of background, below text).
        if resolved.border_width > 0 and resolved.border_color is not None:
            _draw_border(
                self._game._backend,
                self._computed_x,
                self._computed_y,
                self._computed_w,
                self._computed_h,
                resolved.border_color,
                resolved.border_width,
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
        """Draw the panel's shadow, background rectangle, and border."""
        if self._game is None:
            return
        resolved = self._resolve_style()

        # Shadow (offset dark rectangle behind the panel).  Skipped when
        # the resolved background is fully transparent — a shadow cast by
        # nothing is a ghost rectangle that breaks transparent HUD rows.
        theme = self._game.theme
        shadow_offset = theme.panel_shadow_offset
        bg = resolved.background_color
        bg_visible = bg is not None and len(bg) >= 4 and bg[3] > 0
        if shadow_offset > 0 and bg_visible:
            self._game._backend.draw_rect(
                self._computed_x + shadow_offset,
                self._computed_y + shadow_offset,
                self._computed_w,
                self._computed_h,
                theme.panel_shadow_color,
            )

        # Background rect.
        if bg is not None:
            self._game._backend.draw_rect(
                self._computed_x,
                self._computed_y,
                self._computed_w,
                self._computed_h,
                bg,
            )

        # Border (on top of background, below children).
        if resolved.border_width > 0 and resolved.border_color is not None:
            _draw_border(
                self._game._backend,
                self._computed_x,
                self._computed_y,
                self._computed_w,
                self._computed_h,
                resolved.border_color,
                resolved.border_width,
            )

    # -- Internal ----------------------------------------------------------

    def _resolve_style(self) -> ResolvedStyle:
        """Merge explicit style with panel defaults from the theme."""
        if self._game is not None:
            return self._game.theme.resolve_panel_style(self.style)
        from saga2d.ui.theme import Theme

        return Theme().resolve_panel_style(self.style)


# ---------------------------------------------------------------------------
# Row / Column — transparent-container shortcuts
# ---------------------------------------------------------------------------


_TRANSPARENT_CONTAINER_STYLE = Style(
    background_color=(0, 0, 0, 0),
    border_width=0,
    padding=0,
)


class Row(Panel):
    """Transparent horizontal container. Declarative-HUD shortcut.

    Behaves like :class:`Panel` with ``layout=Layout.HORIZONTAL`` and a
    fully transparent style (no background, border, or padding). Takes
    children as positional arguments so the call site reads as naturally
    as possible::

        Row(
            Label(lambda: f"HP {self.hp}"),
            Label(lambda: f"Coins {self.coins}"),
            spacing=26, anchor=Anchor.BOTTOM_LEFT, margin=16,
        )

    Pass an explicit ``style=`` to re-enable background/border.
    """

    def __init__(
        self,
        *children: Component,
        spacing: int = 8,
        style: Style | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            layout=Layout.HORIZONTAL,
            spacing=spacing,
            children=list(children),
            style=style if style is not None else _TRANSPARENT_CONTAINER_STYLE,
            **kwargs,
        )


class Column(Panel):
    """Transparent vertical container. Mirror of :class:`Row`."""

    def __init__(
        self,
        *children: Component,
        spacing: int = 8,
        style: Style | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            layout=Layout.VERTICAL,
            spacing=spacing,
            children=list(children),
            style=style if style is not None else _TRANSPARENT_CONTAINER_STYLE,
            **kwargs,
        )
