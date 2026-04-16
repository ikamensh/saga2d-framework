"""Style and Theme for UI theming.

Style holds optional overrides; None means "inherit from theme".
Theme provides defaults per component type and resolve methods that merge
explicit Style overrides with those defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# RGBA tuple: (r, g, b, a), 0-255 per channel
Color = tuple[int, int, int, int]


@dataclass
class Style:
    """Visual style for a UI component.

    All fields are optional — None means "inherit from theme".
    """

    font: str | None = None
    font_size: int | None = None
    text_color: Color | None = None
    background_color: Color | None = None
    padding: int | None = None
    border_color: Color | None = None
    border_width: int | None = None
    hover_color: Color | None = None
    press_color: Color | None = None


@dataclass(frozen=True)
class TextStyle:
    """Named text style used by :meth:`saga2d.Scene.draw_text`.

    Captures the "look" of a text role (title, HUD, caption) so scenes
    refer to it by name (``style="title"``) instead of hand-picking
    ``font_size`` and ``color`` at every call site. One theme change
    then restyles every scene.
    """

    font_size: int
    color: Color
    font: str | None = None


# ---- Default text styles -------------------------------------------------
# Tuned for typical 800×600 to 1920×1080 logical viewports.
_DEFAULT_TEXT_STYLES: dict[str, TextStyle] = {
    "title":    TextStyle(font_size=28, color=(255, 220, 80, 255)),       # gold
    "heading":  TextStyle(font_size=22, color=(248, 250, 252, 255)),      # near-white
    "hud":      TextStyle(font_size=18, color=(248, 250, 252, 255)),      # near-white
    "body":     TextStyle(font_size=16, color=(226, 232, 240, 255)),      # slate 200
    "sub":      TextStyle(font_size=13, color=(210, 210, 225, 230)),      # muted slate
    "caption":  TextStyle(font_size=12, color=(155, 155, 170, 255)),      # dim
}


@dataclass
class ResolvedStyle:
    """Fully resolved style — all fields have concrete values after merging."""

    font: str
    font_size: int
    text_color: Color
    background_color: Color
    padding: int
    border_color: Color | None
    border_width: int
    hover_color: Color
    press_color: Color


def _pick[T](explicit: T | None, default: T) -> T:
    """Use explicit value if not None, else default."""
    return explicit if explicit is not None else default


class Theme:
    """Default styles for each component type.

    Components inherit from theme unless overridden by explicit Style.
    """

    def __init__(
        self,
        *,
        font: str = "serif",
        font_size: int = 24,
        text_color: Color = (248, 250, 252, 255),  # Slate 50
        # Panel defaults
        panel_background_color: Color = (30, 41, 59, 255),  # Slate 800
        panel_padding: int = 16,
        panel_border_color: Color | None = (71, 85, 105, 255),  # Slate 600
        panel_border_width: int = 2,
        # Shadow offset for Panel (pixels right/down)
        panel_shadow_offset: int = 4,
        panel_shadow_color: Color = (0, 0, 0, 120),
        # Button defaults
        button_background_color: Color = (51, 65, 85, 255),  # Slate 700
        button_hover_color: Color = (71, 85, 105, 255),  # Slate 600
        button_press_color: Color = (56, 189, 248, 255),  # Sky 400 (accent)
        button_disabled_color: Color = (30, 41, 59, 255),  # Slate 800
        button_text_color: Color = (248, 250, 252, 255),  # Slate 50
        button_disabled_text_color: Color = (100, 116, 139, 200),  # Slate 500
        button_hover_outline_color: Color = (100, 181, 246, 200),  # Light blue glow
        button_hover_outline_width: int = 3,
        button_padding: int = 12,
        button_font_size: int = 24,
        button_min_width: int = 200,
        # Label defaults
        label_text_color: Color = (248, 250, 252, 255),  # Slate 50
        # ProgressBar defaults
        progressbar_color: Color = (56, 189, 248, 255),  # Sky 400 (accent)
        progressbar_bg_color: Color = (15, 23, 42, 220),  # Slate 900
        # List / Grid / DataTable defaults
        selected_color: Color = (56, 189, 248, 80),  # Sky 400 translucent
        list_alt_row_bg_color: Color = (30, 41, 59, 120),  # Slate 800
        grid_cell_bg_color: Color = (40, 48, 68, 180),  # Slate 700 translucent
        # Tooltip defaults
        tooltip_background_color: Color = (15, 23, 42, 240),  # Slate 900
        tooltip_text_color: Color = (248, 250, 252, 255),  # Slate 50
        tooltip_font_size: int = 18,
        tooltip_padding: int = 6,
        # TabGroup defaults
        tab_active_color: Color = (51, 65, 85, 255),  # Slate 700
        tab_inactive_color: Color = (30, 41, 59, 220),  # Slate 800
        tab_text_color: Color = (248, 250, 252, 255),  # Slate 50
        tab_font_size: int = 20,
        tab_padding: int = 10,
        # DataTable defaults
        datatable_header_bg_color: Color = (51, 65, 85, 255),  # Slate 700
        datatable_header_text_color: Color = (248, 250, 252, 255),  # Slate 50
        datatable_row_bg_color: Color = (30, 41, 59, 180),  # Slate 800
        datatable_alt_row_bg_color: Color = (15, 23, 42, 180),  # Slate 900
        # Drag-and-drop defaults
        drop_accept_color: Color = (0, 180, 0, 80),
        drop_reject_color: Color = (180, 0, 0, 80),
        ghost_opacity: float = 0.5,
        # Named text styles for Scene.draw_text(style=…)
        text_styles: dict[str, TextStyle] | None = None,
    ) -> None:
        self._font = font
        self._font_size = font_size
        self._text_color = text_color
        self._panel_background_color = panel_background_color
        self._panel_padding = panel_padding
        self._panel_border_color = panel_border_color
        self._panel_border_width = panel_border_width
        self._panel_shadow_offset = panel_shadow_offset
        self._panel_shadow_color = panel_shadow_color
        self._button_background_color = button_background_color
        self._button_hover_color = button_hover_color
        self._button_press_color = button_press_color
        self._button_disabled_color = button_disabled_color
        self._button_text_color = button_text_color
        self._button_disabled_text_color = button_disabled_text_color
        self._button_hover_outline_color = button_hover_outline_color
        self._button_hover_outline_width = button_hover_outline_width
        self._button_padding = button_padding
        self._button_font_size = button_font_size
        self._button_min_width = button_min_width
        self._label_text_color = label_text_color
        self._progressbar_color = progressbar_color
        self._progressbar_bg_color = progressbar_bg_color
        self._selected_color = selected_color
        self._list_alt_row_bg_color = list_alt_row_bg_color
        self._grid_cell_bg_color = grid_cell_bg_color
        self._tooltip_background_color = tooltip_background_color
        self._tooltip_text_color = tooltip_text_color
        self._tooltip_font_size = tooltip_font_size
        self._tooltip_padding = tooltip_padding
        self._tab_active_color = tab_active_color
        self._tab_inactive_color = tab_inactive_color
        self._tab_text_color = tab_text_color
        self._tab_font_size = tab_font_size
        self._tab_padding = tab_padding
        self._datatable_header_bg_color = datatable_header_bg_color
        self._datatable_header_text_color = datatable_header_text_color
        self._datatable_row_bg_color = datatable_row_bg_color
        self._datatable_alt_row_bg_color = datatable_alt_row_bg_color
        self._drop_accept_color = drop_accept_color
        self._drop_reject_color = drop_reject_color
        self._ghost_opacity = ghost_opacity
        # Caller-provided styles override/extend the defaults.
        self._text_styles: dict[str, TextStyle] = dict(_DEFAULT_TEXT_STYLES)
        if text_styles:
            self._text_styles.update(text_styles)

    def resolve_label_style(self, explicit: Style | None) -> ResolvedStyle:
        """Merge explicit style with label defaults from theme."""
        e = explicit or Style()
        return ResolvedStyle(
            font=_pick(e.font, self._font),
            font_size=_pick(e.font_size, self._font_size),
            text_color=_pick(e.text_color, self._label_text_color),
            background_color=(0, 0, 0, 0),  # Labels have no background
            padding=_pick(e.padding, 0),
            border_color=e.border_color,
            border_width=_pick(e.border_width, 0),
            hover_color=_pick(e.hover_color, self._button_hover_color),
            press_color=_pick(e.press_color, self._button_press_color),
        )

    def resolve_button_style(
        self,
        explicit: Style | None,
        state: Literal["normal", "hovered", "pressed", "disabled"] = "normal",
    ) -> ResolvedStyle:
        """Merge explicit style with button defaults, considering state."""
        e = explicit or Style()
        if state == "disabled":
            bg = _pick(e.background_color, self._button_disabled_color)
            text = _pick(e.text_color, self._button_disabled_text_color)
        elif state == "hovered":
            bg = _pick(e.hover_color, self._button_hover_color)
            text = _pick(e.text_color, self._button_text_color)
        elif state == "pressed":
            bg = _pick(e.press_color, self._button_press_color)
            text = _pick(e.text_color, self._button_text_color)
        else:
            bg = _pick(e.background_color, self._button_background_color)
            text = _pick(e.text_color, self._button_text_color)
        return ResolvedStyle(
            font=_pick(e.font, self._font),
            font_size=_pick(e.font_size, self._button_font_size),
            text_color=text,
            background_color=bg,
            padding=_pick(e.padding, self._button_padding),
            border_color=_pick(e.border_color, self._panel_border_color),
            border_width=_pick(e.border_width, self._panel_border_width),
            hover_color=_pick(e.hover_color, self._button_hover_color),
            press_color=_pick(e.press_color, self._button_press_color),
        )

    def resolve_panel_style(self, explicit: Style | None) -> ResolvedStyle:
        """Merge explicit style with panel defaults."""
        e = explicit or Style()
        return ResolvedStyle(
            font=_pick(e.font, self._font),
            font_size=_pick(e.font_size, self._font_size),
            text_color=_pick(e.text_color, self._text_color),
            background_color=_pick(e.background_color, self._panel_background_color),
            padding=_pick(e.padding, self._panel_padding),
            border_color=_pick(e.border_color, self._panel_border_color),
            border_width=_pick(e.border_width, self._panel_border_width),
            hover_color=_pick(e.hover_color, self._button_hover_color),
            press_color=_pick(e.press_color, self._button_press_color),
        )

    @property
    def button_min_width(self) -> int:
        return self._button_min_width

    @property
    def button_hover_outline_color(self) -> Color:
        """Outer-glow colour drawn around hovered buttons."""
        return self._button_hover_outline_color

    @property
    def button_hover_outline_width(self) -> int:
        """Border thickness (px) of the hover outline glow."""
        return self._button_hover_outline_width

    @property
    def progressbar_color(self) -> Color:
        return self._progressbar_color

    @property
    def progressbar_bg_color(self) -> Color:
        return self._progressbar_bg_color

    @property
    def selected_color(self) -> Color:
        return self._selected_color

    @property
    def list_alt_row_bg_color(self) -> Color:
        """Alternating row background color for List widget."""
        return self._list_alt_row_bg_color

    @property
    def grid_cell_bg_color(self) -> Color:
        """Background color for Grid cells."""
        return self._grid_cell_bg_color

    def resolve_list_style(self, explicit: Style | None) -> ResolvedStyle:
        """Merge explicit style with List defaults from theme.

        Lists use the panel background colour and default font/text settings.
        """
        e = explicit or Style()
        return ResolvedStyle(
            font=_pick(e.font, self._font),
            font_size=_pick(e.font_size, self._font_size),
            text_color=_pick(e.text_color, self._text_color),
            background_color=_pick(e.background_color, self._panel_background_color),
            padding=_pick(e.padding, 4),
            border_color=_pick(e.border_color, self._panel_border_color),
            border_width=_pick(e.border_width, self._panel_border_width),
            hover_color=_pick(e.hover_color, self._button_hover_color),
            press_color=_pick(e.press_color, self._button_press_color),
        )

    def resolve_grid_style(self, explicit: Style | None) -> ResolvedStyle:
        """Merge explicit style with Grid defaults from theme.

        Grids use the panel background colour and a small padding.
        The ``selected_color`` property provides the cell highlight.
        """
        e = explicit or Style()
        return ResolvedStyle(
            font=_pick(e.font, self._font),
            font_size=_pick(e.font_size, self._font_size),
            text_color=_pick(e.text_color, self._text_color),
            background_color=_pick(e.background_color, self._panel_background_color),
            padding=_pick(e.padding, 4),
            border_color=_pick(e.border_color, self._panel_border_color),
            border_width=_pick(e.border_width, self._panel_border_width),
            hover_color=_pick(e.hover_color, self._button_hover_color),
            press_color=_pick(e.press_color, self._button_press_color),
        )

    def resolve_tooltip_style(self, explicit: Style | None) -> ResolvedStyle:
        """Merge explicit style with Tooltip defaults from theme.

        Tooltips use a dark background, light text, smaller font, and
        compact padding.
        """
        e = explicit or Style()
        return ResolvedStyle(
            font=_pick(e.font, self._font),
            font_size=_pick(e.font_size, self._tooltip_font_size),
            text_color=_pick(e.text_color, self._tooltip_text_color),
            background_color=_pick(
                e.background_color,
                self._tooltip_background_color,
            ),
            padding=_pick(e.padding, self._tooltip_padding),
            border_color=_pick(e.border_color, self._panel_border_color),
            border_width=_pick(e.border_width, 0),
            hover_color=_pick(e.hover_color, self._button_hover_color),
            press_color=_pick(e.press_color, self._button_press_color),
        )

    def resolve_tabgroup_style(self, explicit: Style | None) -> ResolvedStyle:
        """Merge explicit style with TabGroup defaults from theme.

        TabGroups use the panel background for the content area.  Tab
        header colours are accessed via dedicated properties.
        """
        e = explicit or Style()
        return ResolvedStyle(
            font=_pick(e.font, self._font),
            font_size=_pick(e.font_size, self._tab_font_size),
            text_color=_pick(e.text_color, self._tab_text_color),
            background_color=_pick(
                e.background_color,
                self._panel_background_color,
            ),
            padding=_pick(e.padding, self._tab_padding),
            border_color=_pick(e.border_color, self._panel_border_color),
            border_width=_pick(e.border_width, 0),
            hover_color=_pick(e.hover_color, self._button_hover_color),
            press_color=_pick(e.press_color, self._button_press_color),
        )

    @property
    def tab_active_color(self) -> Color:
        """Background colour for the active tab header."""
        return self._tab_active_color

    @property
    def tab_inactive_color(self) -> Color:
        """Background colour for inactive tab headers."""
        return self._tab_inactive_color

    def resolve_datatable_style(self, explicit: Style | None) -> ResolvedStyle:
        """Merge explicit style with DataTable defaults from theme.

        DataTables use the panel background for the overall container.
        Header and row colours are accessed via dedicated properties.
        """
        e = explicit or Style()
        return ResolvedStyle(
            font=_pick(e.font, self._font),
            font_size=_pick(e.font_size, self._font_size),
            text_color=_pick(e.text_color, self._text_color),
            background_color=_pick(
                e.background_color,
                self._panel_background_color,
            ),
            padding=_pick(e.padding, 6),
            border_color=_pick(e.border_color, self._panel_border_color),
            border_width=_pick(e.border_width, 0),
            hover_color=_pick(e.hover_color, self._button_hover_color),
            press_color=_pick(e.press_color, self._button_press_color),
        )

    @property
    def datatable_header_bg_color(self) -> Color:
        """Background colour for the DataTable header row."""
        return self._datatable_header_bg_color

    @property
    def datatable_header_text_color(self) -> Color:
        """Text colour for the DataTable header row."""
        return self._datatable_header_text_color

    @property
    def datatable_row_bg_color(self) -> Color:
        """Background colour for even data rows."""
        return self._datatable_row_bg_color

    @property
    def datatable_alt_row_bg_color(self) -> Color:
        """Background colour for odd data rows (alternating)."""
        return self._datatable_alt_row_bg_color

    @property
    def drop_accept_color(self) -> Color:
        """Overlay colour for valid drop targets (green)."""
        return self._drop_accept_color

    @property
    def drop_reject_color(self) -> Color:
        """Overlay colour for invalid drop targets (red)."""
        return self._drop_reject_color

    @property
    def ghost_opacity(self) -> float:
        """Opacity for the drag ghost overlay (0.0–1.0)."""
        return self._ghost_opacity

    @property
    def default_font(self) -> str:
        """Theme-level default font name."""
        return self._font

    @property
    def default_font_size(self) -> int:
        """Theme-level default font size for untagged text."""
        return self._font_size

    @property
    def default_text_color(self) -> Color:
        """Theme-level default text colour for untagged text."""
        return self._text_color

    def get_text_style(self, name: str) -> TextStyle:
        """Return the :class:`TextStyle` registered under *name*.

        Names ``title`` / ``heading`` / ``hud`` / ``body`` / ``sub`` /
        ``caption`` come pre-registered (see ``_DEFAULT_TEXT_STYLES``).
        Pass ``text_styles={...}`` to the :class:`Theme` constructor to
        add or override.
        """
        try:
            return self._text_styles[name]
        except KeyError as e:
            known = ", ".join(sorted(self._text_styles))
            raise KeyError(
                f"Unknown text style {name!r}. Registered: {known}"
            ) from e

    def set_text_style(self, name: str, style: TextStyle) -> None:
        """Register or replace the style under *name* after construction."""
        self._text_styles[name] = style

    @property
    def panel_shadow_offset(self) -> int:
        """Shadow offset in pixels (right and down) for Panel."""
        return self._panel_shadow_offset

    @property
    def panel_shadow_color(self) -> Color:
        """Shadow colour for Panel."""
        return self._panel_shadow_color
