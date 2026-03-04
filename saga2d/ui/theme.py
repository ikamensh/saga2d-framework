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
        text_color: Color = (220, 225, 240, 255),
        # Panel defaults
        panel_background_color: Color = (32, 38, 54, 230),
        panel_padding: int = 16,
        panel_border_color: Color | None = (80, 80, 110, 180),
        panel_border_width: int = 1,
        # Button defaults
        button_background_color: Color = (45, 55, 85, 255),
        button_hover_color: Color = (65, 80, 120, 255),
        button_press_color: Color = (35, 45, 75, 255),
        button_disabled_color: Color = (30, 35, 45, 255),
        button_text_color: Color = (240, 240, 240, 255),
        button_disabled_text_color: Color = (100, 100, 110, 200),
        button_padding: int = 12,
        button_font_size: int = 24,
        button_min_width: int = 200,
        # Label defaults
        label_text_color: Color = (220, 225, 240, 255),
        # ProgressBar defaults
        progressbar_color: Color = (60, 180, 60, 255),
        progressbar_bg_color: Color = (40, 40, 40, 200),
        # List / Grid / DataTable defaults
        selected_color: Color = (60, 60, 100, 255),
        # Tooltip defaults
        tooltip_background_color: Color = (20, 20, 20, 230),
        tooltip_text_color: Color = (230, 230, 230, 255),
        tooltip_font_size: int = 18,
        tooltip_padding: int = 6,
        # TabGroup defaults
        tab_active_color: Color = (70, 70, 100, 255),
        tab_inactive_color: Color = (45, 45, 60, 200),
        tab_text_color: Color = (220, 220, 220, 255),
        tab_font_size: int = 20,
        tab_padding: int = 10,
        # DataTable defaults
        datatable_header_bg_color: Color = (55, 55, 75, 255),
        datatable_header_text_color: Color = (240, 240, 240, 255),
        datatable_row_bg_color: Color = (35, 35, 45, 200),
        datatable_alt_row_bg_color: Color = (42, 42, 55, 200),
        # Drag-and-drop defaults
        drop_accept_color: Color = (0, 180, 0, 80),
        drop_reject_color: Color = (180, 0, 0, 80),
        ghost_opacity: float = 0.5,
    ) -> None:
        self._font = font
        self._font_size = font_size
        self._text_color = text_color
        self._panel_background_color = panel_background_color
        self._panel_padding = panel_padding
        self._panel_border_color = panel_border_color
        self._panel_border_width = panel_border_width
        self._button_background_color = button_background_color
        self._button_hover_color = button_hover_color
        self._button_press_color = button_press_color
        self._button_disabled_color = button_disabled_color
        self._button_text_color = button_text_color
        self._button_disabled_text_color = button_disabled_text_color
        self._button_padding = button_padding
        self._button_font_size = button_font_size
        self._button_min_width = button_min_width
        self._label_text_color = label_text_color
        self._progressbar_color = progressbar_color
        self._progressbar_bg_color = progressbar_bg_color
        self._selected_color = selected_color
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
    def progressbar_color(self) -> Color:
        return self._progressbar_color

    @property
    def progressbar_bg_color(self) -> Color:
        return self._progressbar_bg_color

    @property
    def selected_color(self) -> Color:
        return self._selected_color

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
