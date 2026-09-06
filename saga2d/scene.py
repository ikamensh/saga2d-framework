"""Scene — one self-contained game state (title screen, world map, dialog).

Subclasses override the lifecycle hooks they need.  Declarative input
lives in :attr:`Scene.controls`; sprites, timers and emitters registered
through the scene are released automatically when it leaves the stack.
"""

from __future__ import annotations

import inspect
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Callable, Iterator

from saga2d.input import normalize_combo
from saga2d.rendering._text import _layout_paragraph, _validate_paragraph_size
from saga2d.rendering.layers import RenderLayer, world_order
from saga2d.rendering.shapes import draw_box

if TYPE_CHECKING:
    from saga2d.backends.base import Color, Space
    from saga2d.game import Game
    from saga2d.input import InputEvent
    from saga2d.rendering.camera import Camera
    from saga2d.rendering.particles import ParticleEmitter
    from saga2d.rendering.sprite import Sprite
    from saga2d.ui.base import Component, _UIRoot
    from saga2d.ui.theme import TextStyle

#: Screen-space immediate draws of scene-stack level ``k`` use order
#: ``UI_ORDER_BASE + k * UI_ORDER_STRIDE``. Local drawing and the UI tree
#: occupy separate ranges inside that scene, so overlays stay above both.
UI_ORDER_BASE = 1_000_000
UI_ORDER_STRIDE = 1_000_000
_SCREEN_LAYER_COUNT = 1000


def _call_with_optional_event(cb: Callable[..., Any], event: Any) -> None:
    """Call ``cb(event)`` if *cb* has a required positional parameter, else ``cb()``.

    So ``def end_turn(self)`` and ``lambda t=tech: buy(t)`` run bare, while
    ``def next_unit(self, event)`` receives the :class:`InputEvent`.
    """
    try:
        params = inspect.signature(cb).parameters.values()
    except (ValueError, TypeError):
        cb()
        return
    positional = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    if any(p.kind in positional and p.default is inspect.Parameter.empty for p in params):
        cb(event)
    else:
        cb()


class Scene:
    """Lifecycle hooks (all no-ops by default):

    * ``on_enter`` — became the top scene (after push/replace).
    * ``on_exit``  — removed, or covered by a pushed scene.
    * ``on_reveal`` — the scene above was popped.
    * ``update(dt)`` — every frame while active (and while covered, if the
      scene above sets ``pause_below = False``).
    * ``draw()`` — every frame while visible; use the ``draw_*`` helpers.
    * ``handle_input(event)`` — return ``True`` to consume.

    If ``on_enter`` fails, owned resources are released and the scene is
    detached without calling ``on_exit`` on the partially initialized scene.

    Class attributes:
        transparent:      Draw the scene below this one too.
        pause_below:      Stop updating the scene below.
        pop_on_cancel:    Escape pops this scene when nothing else consumed it.
        background_color: Clear colour when this scene is the visible base.
        controls:         ``{"key" | ("k1", "k2"): "method_name"}`` — dispatched
                          on key press; chords like ``"ctrl+s"`` work.  A method
                          with a required positional parameter receives the
                          :class:`InputEvent`; one without is called bare.
    """

    transparent: bool = False
    pause_below: bool = True
    pop_on_cancel: bool = False
    background_color: Color | None = None
    controls: dict[str | tuple[str, ...], str] = {}
    _flat_controls: dict[str, str] = {}

    game: Game
    camera: Camera | None = None
    _ui: _UIRoot | None = None
    _level: int = 0

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        flat: dict[str, str] = {}
        missing: list[str] = []
        for keys, method_name in cls.controls.items():
            for key in (keys if isinstance(keys, tuple) else (keys,)):
                flat[normalize_combo(key)] = method_name
            if not callable(getattr(cls, method_name, None)):
                missing.append(method_name)
        if missing:
            raise AttributeError(f"{cls.__name__}.controls references missing methods: {', '.join(sorted(set(missing)))}")
        cls._flat_controls = flat

    def __new__(cls, *args: Any, **kwargs: Any) -> Scene:
        # Set up ownership registries here so subclasses need not call super().__init__().
        self = super().__new__(cls)
        self._owned_sprites: set[Sprite] = set()
        self._owned_timers: set[int] = set()
        self._owned_emitters: set[ParticleEmitter] = set()
        self._key_handlers: dict[str, Callable[..., Any]] = {}
        self._screen_draw_layer = 0
        return self

    # -- Lifecycle hooks -------------------------------------------------------

    def on_enter(self) -> None:
        pass

    def on_exit(self) -> None:
        pass

    def on_reveal(self) -> None:
        pass

    def update(self, dt: float) -> None:
        pass

    def draw(self) -> None:
        pass

    def handle_input(self, event: InputEvent) -> bool:
        return False

    # -- Ownership -------------------------------------------------------------

    def add_sprite(self, sprite: Sprite) -> Sprite:
        """Own *sprite*: it is removed when this scene leaves the stack."""
        if not sprite.is_removed:
            self._owned_sprites.add(sprite)
            sprite._owning_scene = self
        return sprite

    def remove_sprite(self, sprite: Sprite) -> None:
        self._owned_sprites.discard(sprite)
        sprite.remove()

    def add_emitter(self, emitter: ParticleEmitter) -> ParticleEmitter:
        self._owned_emitters.add(emitter)
        return emitter

    def after(self, delay: float, callback: Callable[[], Any]) -> int:
        """One-shot timer cancelled automatically when the scene leaves the stack."""
        timer_id = self.game.after(delay, callback)
        self._owned_timers.add(timer_id)
        return timer_id

    def every(self, interval: float, callback: Callable[[], Any]) -> int:
        timer_id = self.game.every(interval, callback)
        self._owned_timers.add(timer_id)
        return timer_id

    def cancel_timer(self, timer_id: int) -> None:
        self._owned_timers.discard(timer_id)
        self.game.cancel(timer_id)

    def _release_resources(self) -> None:
        """Release ownership after removal or failed entry, then detach the scene."""
        try:
            for sprite in list(self._owned_sprites):
                sprite.remove()
            self._owned_sprites.clear()
            for emitter in list(self._owned_emitters):
                emitter.remove()
            self._owned_emitters.clear()
            for timer_id in self._owned_timers:
                self.game.cancel(timer_id)
            self._owned_timers.clear()
            if self.camera is not None:
                self.camera._cancel_pan()
        finally:
            self._ui = None
            self.game = None  # type: ignore[assignment]

    # -- Input -----------------------------------------------------------------

    def bind_key(self, key: str, callback: Callable[..., Any]) -> None:
        """Runtime key binding; overrides :attr:`controls` for the same key."""
        self._key_handlers[normalize_combo(key)] = callback

    def bind_keys(self, keys: list[str] | tuple[str, ...], callback: Callable[..., Any]) -> None:
        for key in keys:
            self.bind_key(key, callback)

    def unbind_key(self, key: str) -> None:
        self._key_handlers.pop(normalize_combo(key), None)

    def _dispatch_key(self, event: InputEvent) -> bool:
        if event.type != "key_press" or event.key is None:
            return False
        for name in (event.combo, event.key):
            cb = self._key_handlers.get(name)
            if cb is not None:
                _call_with_optional_event(cb, event)
                return True
            method_name = self._flat_controls.get(name)
            if method_name is not None:
                _call_with_optional_event(getattr(self, method_name), event)
                return True
        return False

    # -- Drawing helpers -------------------------------------------------------

    @contextmanager
    def screen_layer(self, layer: int) -> Iterator[None]:
        """Draw screen content on a local layer (0–999; default 0).

        Higher layers cover lower shapes, images and text regardless of call
        order. Within one layer, text stays above images, and images above
        shapes. The scene's UI tree is above all these layers; the next scene
        is above both. Use an overlay Scene when a panel must also own input.

        The scope applies to every immediate ``draw_*`` helper, including
        calls made by your own drawing functions. Nested scopes choose an
        absolute layer and restore the previous one, even after an exception.
        World-space drawing and retained sprites are unaffected.
        """
        if isinstance(layer, bool) or not isinstance(layer, int) or not 0 <= layer < _SCREEN_LAYER_COUNT:
            raise ValueError("Screen layer must be an integer from 0 to 999")
        previous = self._screen_draw_layer
        self._screen_draw_layer = layer
        try:
            yield
        finally:
            self._screen_draw_layer = previous

    def _order(self, space: Space, layer: RenderLayer, y: float) -> int:
        if space == "world":
            return world_order(layer, y)
        return UI_ORDER_BASE + self._level * UI_ORDER_STRIDE + self._screen_draw_layer

    def draw_rect(
        self, x: float, y: float, width: float, height: float, color: Color, *,
        space: Space = "screen", layer: RenderLayer = RenderLayer.UI_WORLD,
        border_color: Color | None = None, border_width: float = 0, radius: float = 0,
    ) -> None:
        """Filled rectangle from top-left ``(x, y)``, optionally with rounded
        corners and a border drawn just inside its edge.  *layer* orders
        world-space draws."""
        order = self._order(space, layer, y + height)
        draw_box(self.game.backend, x, y, width, height, color, border_color=border_color, border_width=border_width,
                 radius=radius, space=space, order=order)

    def draw_circle(
        self, x: float, y: float, radius: float, color: Color, *,
        space: Space = "screen", layer: RenderLayer = RenderLayer.UI_WORLD,
    ) -> None:
        self.game.backend.draw_circle(x, y, radius, color, space=space, order=self._order(space, layer, y + radius))

    def draw_line(
        self, x1: float, y1: float, x2: float, y2: float, color: Color, width: float = 1.0, *,
        space: Space = "screen", layer: RenderLayer = RenderLayer.UI_WORLD,
    ) -> None:
        self.game.backend.draw_line(x1, y1, x2, y2, color, width, space=space, order=self._order(space, layer, max(y1, y2)))

    def draw_polygon(
        self, points: list[tuple[float, float]], color: Color, *,
        space: Space = "screen", layer: RenderLayer = RenderLayer.UI_WORLD,
    ) -> None:
        bottom = max(p[1] for p in points) if points else 0.0
        self.game.backend.draw_polygon(points, color, space=space, order=self._order(space, layer, bottom))

    def draw_image(
        self, image: str, x: float, y: float, width: float, height: float, *,
        opacity: float = 1.0, space: Space = "screen", layer: RenderLayer = RenderLayer.UI_WORLD,
    ) -> None:
        handle = self.game.assets.image(image)
        self.game.backend.draw_image(handle, x, y, width, height, opacity=opacity, space=space, order=self._order(space, layer, y + height))

    def draw_text(
        self, text: str, x: float, y: float, *,
        style: str | TextStyle | None = None, font_size: int | None = None, color: Color | None = None,
        font: str | None = None, anchor_x: str = "left", anchor_y: str = "baseline",
        space: Space = "screen", layer: RenderLayer = RenderLayer.UI_WORLD,
    ) -> None:
        """Text with a named theme style (``"title"``, ``"hud"``…) or explicit size/colour."""
        font_size, color, font = self._resolve_text_style(style, font_size, color, font)
        self.game.backend.draw_text(
            text, x, y, font_size, color, font=font, anchor_x=anchor_x, anchor_y=anchor_y,
            space=space, order=self._order(space, layer, y),
        )

    def _resolve_text_style(
        self, style: str | TextStyle | None, font_size: int | None,
        color: Color | None, font: str | None,
    ) -> tuple[int, Color, str | None]:
        theme = self.game.theme
        if style is not None:
            text_style = theme.get_text_style(style) if isinstance(style, str) else style
            font_size = font_size if font_size is not None else text_style.font_size
            color = color if color is not None else text_style.color
            font = font if font is not None else text_style.font
        else:
            font_size = font_size if font_size is not None else theme.font_size
            color = color if color is not None else theme.text_color
            font = font if font is not None else theme.font
        return font_size, color, font

    def draw_paragraph(
        self, text: str, x: float, y: float, width: float, *,
        style: str | TextStyle | None = None, font_size: int | None = None,
        color: Color | None = None, font: str | None = None, line_spacing: float = 1.4,
        space: Space = "screen", layer: RenderLayer = RenderLayer.UI_WORLD,
    ) -> float:
        """Draw measured, word-wrapped text from top-left and return its height.

        ``line_spacing`` multiplies the backend-measured font height. The
        returned height reaches the bottom of the final line, with no trailing
        gap, so callers can position subsequent content below the paragraph.
        Style and explicit font options work exactly as in :meth:`draw_text`.

        Explicit newlines, including blank lines, are preserved; other
        whitespace collapses to single spaces. Overlong words split between
        characters. Width and spacing must be positive and finite; a width
        too small for one character raises ``ValueError`` before drawing.
        Empty text consumes no height.
        """
        _validate_paragraph_size(width, line_spacing)
        if not text:
            return 0.0
        font_size, color, font = self._resolve_text_style(style, font_size, color, font)
        paragraph = _layout_paragraph(text, width,
                                      lambda value: self.game.backend.measure_text(value, font_size, font), line_spacing)
        for index, line in enumerate(paragraph.lines):
            if line:
                self.draw_text(line, x, y + index * paragraph.line_height * line_spacing, style=style,
                               font_size=font_size, color=color, font=font, anchor_y="top", space=space, layer=layer)
        return paragraph.height

    # -- Save / load -----------------------------------------------------------

    def get_save_state(self) -> dict[str, Any]:
        return {}

    def load_save_state(self, state: dict[str, Any]) -> None:
        pass

    # -- UI --------------------------------------------------------------------

    def measure(self, component: Component) -> tuple[int, int]:
        """Return an unattached UI tree's preferred size in this scene's game.

        Uses the current theme, fonts and display scale without parenting,
        drawing or activating the tree. Already attached trees are rejected;
        ask those components for their ``get_preferred_size()`` directly.
        """
        if component.parent is not None or component._game is not None:
            raise ValueError('Scene.measure requires an unattached UI tree')
        component._propagate_game(component, self.game)
        try:
            return component.get_preferred_size()
        finally:
            component._propagate_game(component, None)

    @property
    def ui(self) -> _UIRoot:
        """Root of this scene's UI tree (created on first access)."""
        if self._ui is None:
            from saga2d.ui.base import _UIRoot

            self._ui = _UIRoot(self)
        return self._ui
