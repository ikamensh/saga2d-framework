"""Theme, Style and TextStyle — colours, fonts and paddings for UI."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

Color = tuple[int, int, int, int]


@dataclass
class Style:
    """Per-component overrides; ``None`` fields inherit from the theme."""

    font: str | None = None
    font_size: int | None = None
    text_color: Color | None = None
    background_color: Color | None = None
    padding: int | None = None
    border_color: Color | None = None
    border_width: int | None = None
    hover_color: Color | None = None
    press_color: Color | None = None
    radius: int | None = None


@dataclass(frozen=True)
class TextStyle:
    """A named text role (``"title"``, ``"hud"``…) used by labels and ``draw_text``."""

    font_size: int
    color: Color
    font: str | None = None


@dataclass(frozen=True)
class ResolvedStyle:
    font: str
    font_size: int
    text_color: Color
    background_color: Color
    padding: int
    border_color: Color | None
    border_width: int
    hover_color: Color
    press_color: Color
    radius: int


_DEFAULT_TEXT_STYLES: dict[str, TextStyle] = {
    "title": TextStyle(28, (255, 220, 80, 255)),
    "heading": TextStyle(22, (248, 250, 252, 255)),
    "hud": TextStyle(18, (248, 250, 252, 255)),
    "body": TextStyle(16, (226, 232, 240, 255)),
    "sub": TextStyle(13, (210, 210, 225, 230)),
    "caption": TextStyle(12, (155, 155, 170, 255)),
    "floating": TextStyle(18, (255, 255, 255, 255)),  # damage numbers and other saga2d.effects.FloatingText
    "banner": TextStyle(40, (255, 255, 255, 255)),  # saga2d.effects.Banner
    "banner_sub": TextStyle(17, (255, 255, 255, 255)),
}


def _pick[T](explicit: T | None, default: T) -> T:
    return explicit if explicit is not None else default


class Theme:
    def __init__(
        self,
        *,
        font: str = "sans-serif",
        font_size: int = 18,
        text_color: Color = (248, 250, 252, 255),
        panel_background_color: Color = (30, 41, 59, 255),
        panel_padding: int = 16,
        panel_border_color: Color | None = (71, 85, 105, 255),
        panel_border_width: int = 2,
        panel_radius: int = 0,
        button_background_color: Color = (51, 65, 85, 255),
        button_hover_color: Color = (71, 85, 105, 255),
        button_press_color: Color = (56, 189, 248, 255),
        button_disabled_color: Color = (30, 41, 59, 255),
        button_text_color: Color = (248, 250, 252, 255),
        button_disabled_text_color: Color = (100, 116, 139, 200),
        button_padding: int = 10,
        button_font_size: int = 18,
        button_min_width: int = 120,
        button_radius: int = 0,
        keycap_color: Color = (255, 255, 255, 36),
        keycap_text_color: Color = (236, 240, 250, 255),
        keycap_font: str | None = None,
        keycap_font_size: int = 12,
        progressbar_color: Color = (56, 189, 248, 255),
        progressbar_bg_color: Color = (15, 23, 42, 220),
        text_styles: dict[str, TextStyle] | None = None,
    ) -> None:
        """Keycaps are the small rounded key labels buttons and :class:`KeyHints`
        draw for hotkeys; ``keycap_font`` defaults to the theme font."""
        self.font = font
        self.font_size = font_size
        self.text_color = text_color
        self.panel_background_color = panel_background_color
        self.panel_padding = panel_padding
        self.panel_border_color = panel_border_color
        self.panel_border_width = panel_border_width
        self.panel_radius = panel_radius
        self.button_background_color = button_background_color
        self.button_hover_color = button_hover_color
        self.button_press_color = button_press_color
        self.button_disabled_color = button_disabled_color
        self.button_text_color = button_text_color
        self.button_disabled_text_color = button_disabled_text_color
        self.button_padding = button_padding
        self.button_font_size = button_font_size
        self.button_min_width = button_min_width
        self.button_radius = button_radius
        self.keycap_color = keycap_color
        self.keycap_text_color = keycap_text_color
        self.keycap_font = keycap_font
        self.keycap_font_size = keycap_font_size
        self.progressbar_color = progressbar_color
        self.progressbar_bg_color = progressbar_bg_color
        self._text_styles = dict(_DEFAULT_TEXT_STYLES)
        if text_styles:
            self._text_styles.update(text_styles)

    def get_text_style(self, name: str) -> TextStyle:
        try:
            return self._text_styles[name]
        except KeyError:
            raise KeyError(f"Unknown text style {name!r}. Registered: {', '.join(sorted(self._text_styles))}") from None

    def set_text_style(self, name: str, style: TextStyle) -> None:
        self._text_styles[name] = style

    def resolve_label_style(self, explicit: Style | None) -> ResolvedStyle:
        e = explicit or Style()
        return ResolvedStyle(
            font=_pick(e.font, self.font), font_size=_pick(e.font_size, self.font_size),
            text_color=_pick(e.text_color, self.text_color), background_color=_pick(e.background_color, (0, 0, 0, 0)),
            padding=_pick(e.padding, 0), border_color=e.border_color, border_width=_pick(e.border_width, 0),
            hover_color=_pick(e.hover_color, self.button_hover_color), press_color=_pick(e.press_color, self.button_press_color),
            radius=_pick(e.radius, 0),
        )

    def resolve_button_style(self, explicit: Style | None, state: Literal["normal", "hovered", "pressed", "disabled"] = "normal") -> ResolvedStyle:
        e = explicit or Style()
        if state == "disabled":
            bg, text = _pick(e.background_color, self.button_disabled_color), _pick(e.text_color, self.button_disabled_text_color)
        elif state == "hovered":
            bg, text = _pick(e.hover_color, self.button_hover_color), _pick(e.text_color, self.button_text_color)
        elif state == "pressed":
            bg, text = _pick(e.press_color, self.button_press_color), _pick(e.text_color, self.button_text_color)
        else:
            bg, text = _pick(e.background_color, self.button_background_color), _pick(e.text_color, self.button_text_color)
        return ResolvedStyle(
            font=_pick(e.font, self.font), font_size=_pick(e.font_size, self.button_font_size), text_color=text,
            background_color=bg, padding=_pick(e.padding, self.button_padding),
            border_color=_pick(e.border_color, self.panel_border_color), border_width=_pick(e.border_width, self.panel_border_width),
            hover_color=_pick(e.hover_color, self.button_hover_color), press_color=_pick(e.press_color, self.button_press_color),
            radius=_pick(e.radius, self.button_radius),
        )

    def resolve_panel_style(self, explicit: Style | None) -> ResolvedStyle:
        e = explicit or Style()
        return ResolvedStyle(
            font=_pick(e.font, self.font), font_size=_pick(e.font_size, self.font_size), text_color=_pick(e.text_color, self.text_color),
            background_color=_pick(e.background_color, self.panel_background_color), padding=_pick(e.padding, self.panel_padding),
            border_color=_pick(e.border_color, self.panel_border_color), border_width=_pick(e.border_width, self.panel_border_width),
            hover_color=_pick(e.hover_color, self.button_hover_color), press_color=_pick(e.press_color, self.button_press_color),
            radius=_pick(e.radius, self.panel_radius),
        )


def merge_styles(base: Style | None, override: Style | None) -> Style | None:
    """Fields set on *override* win over *base*."""
    if base is None:
        return override
    if override is None:
        return base
    changes = {k: v for k, v in vars(override).items() if v is not None}
    return replace(base, **changes)
