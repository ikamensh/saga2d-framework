"""Component — base class of the UI tree; _UIRoot — a scene's root.

A component owns children, computes its layout inside the rectangle its
parent offers, hit-tests against that rectangle, dispatches input to its
front-most child first, and draws itself before its children.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Callable, Iterator

from saga2d.ui.layout import Anchor, compute_anchor_position
from saga2d.ui.theme import Style

if TYPE_CHECKING:
    from saga2d.game import Game
    from saga2d.input import InputEvent
    from saga2d.scene import Scene


# Components may use order + 1 for a frame above an image (Warband Minimap).
_COMPONENT_ORDER_STRIDE = 4


class Component:
    """Parameters:
        width / height: Explicit size, or ``None`` to fit content.
        anchor:  Placement inside the parent rect; ``None`` lets the
                 parent's flow layout decide.
        margin:  Inset from the anchored edge(s); an int or ``(x, y)``.
        visible: Hidden components neither draw nor receive input.
        enabled: Disabled components draw greyed and ignore input.
        focusable: Participate in an opted-in scene's keyboard navigation.
        blocks_pointer: Consume otherwise unhandled clicks inside this control,
                        including when disabled. Motion and wheel events still pass.
        tooltip: Hover explanation, optionally a zero-argument callable. Disabled
                 controls still explain themselves; children inherit a parent's tip.
                 Tips wrap inside the viewport; text too tall to fit ends in an
                 ellipsis. Only the top scene's front-most hovered tree participates.
        style:   :class:`Style` overrides.
    """

    def __init__(
        self,
        *,
        width: int | None = None,
        height: int | None = None,
        anchor: Anchor | None = None,
        margin: int | tuple[int, int] = 0,
        visible: bool = True,
        enabled: bool = True,
        focusable: bool = False,
        blocks_pointer: bool = False,
        tooltip: str | Callable[[], str] | None = None,
        style: Style | None = None,
    ) -> None:
        mx, my = (margin, margin) if isinstance(margin, int) else margin
        if (width is not None and width < 0) or (height is not None and height < 0) or mx < 0 or my < 0:
            raise ValueError(f"width, height and margin must be >= 0, got {width}, {height}, {margin}")
        self._width = width
        self._height = height
        self._anchor = anchor
        self._margin = (mx, my)
        self._visible = visible
        self._enabled = enabled
        self.focusable = focusable
        self.blocks_pointer = blocks_pointer
        self.tooltip = tooltip
        self.style = style
        self._parent: Component | None = None
        self._children: list[Component] = []
        self._computed_x = 0
        self._computed_y = 0
        self._computed_w = 0
        self._computed_h = 0
        self._game: Game | None = None
        self._layout_dirty = True
        self._paint_index = 0

    @property
    def visible(self) -> bool:
        return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        value = bool(value)
        if value != self._visible:
            self._visible = value
            if not value:
                self._forget_interaction()
            self.invalidate_layout()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = bool(value)
        if not self._enabled:
            self._forget_interaction()

    def _forget_interaction(self) -> None:
        root = self._ui_root()
        if root is not None:
            descendants = set(self.walk(include_self=True))
            if root._focused in descendants:
                root._focused = None
            if root._captured in descendants:
                root._cancel_pointer()

    # -- Tree ------------------------------------------------------------------

    def add(self, child: Component) -> Component:
        if child is self:
            raise ValueError("Cannot add a component to itself")
        if child._parent is not None:
            child._parent.remove(child)
        child._parent = self
        self._children.append(child)
        self._propagate_game(child, self._game)
        self.invalidate_layout()
        return child

    def remove(self, child: Component) -> None:
        if child in self._children:
            child._forget_interaction()
            self._children.remove(child)
            child._parent = None
            self._propagate_game(child, None)
            self.invalidate_layout()

    def clear(self) -> None:
        for child in list(self._children):
            self.remove(child)

    @property
    def parent(self) -> Component | None:
        return self._parent

    @property
    def children(self) -> list[Component]:
        return list(self._children)

    def walk(self, *, include_self: bool = False) -> Iterator[Component]:
        if include_self:
            yield self
        for child in self._children:
            yield from child.walk(include_self=True)

    def find(self, predicate: Callable[[Component], bool]) -> Component | None:
        return next((c for c in self.walk() if predicate(c)), None)

    def find_all(self, predicate: Callable[[Component], bool]) -> list[Component]:
        return [c for c in self.walk() if predicate(c)]

    # -- Layout ----------------------------------------------------------------

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        """``(x, y, w, h)`` from the last layout pass."""
        return (self._computed_x, self._computed_y, self._computed_w, self._computed_h)

    def get_preferred_size(self) -> tuple[int, int]:
        return (self._width or 0, self._height or 0)

    def compute_layout(self, x: int, y: int, w: int, h: int) -> None:
        own_w, own_h = self.get_preferred_size()
        if self._anchor is not None:
            self._computed_x, self._computed_y = compute_anchor_position(self._anchor, x, y, w, h, own_w, own_h, self._margin)
            self._computed_w, self._computed_h = own_w, own_h
        else:
            self._computed_x, self._computed_y = x, y
            self._computed_w = own_w if own_w > 0 else w
            self._computed_h = own_h if own_h > 0 else h
        self._layout_children()
        self._layout_dirty = False

    def _layout_children(self) -> None:
        for child in self._children:
            child.compute_layout(self._computed_x, self._computed_y, self._computed_w, self._computed_h)

    def invalidate_layout(self) -> None:
        self._layout_dirty = True
        if self._parent is not None:
            self._parent.invalidate_layout()

    def _prepare_layout(self) -> None:
        """Refresh derived measurements before input or drawing uses the layout."""
        for child in self._children:
            if child.visible:
                child._prepare_layout()

    def _ensure_layout(self) -> None:
        self._prepare_layout()
        if self._layout_dirty:
            self.compute_layout(self._computed_x, self._computed_y, self._computed_w, self._computed_h)

    # -- Input -----------------------------------------------------------------

    def _ui_root(self) -> _UIRoot | None:
        root = self
        while root.parent is not None:
            root = root.parent
        return root if isinstance(root, _UIRoot) else None

    def _available(self) -> bool:
        component: Component | None = self
        while component is not None:
            if not component.visible or not component.enabled:
                return False
            component = component.parent
        root = self._ui_root()
        return root is not None and root._scene.game is root._game and root._scene._ui is root

    @property
    def focused(self) -> bool:
        """Whether this control owns keyboard focus in its scene."""
        root = self._ui_root()
        return root is not None and root.focused is self

    @property
    def hovered(self) -> bool:
        """Whether this control or a descendant is the front-most pointer owner."""
        root = self._ui_root()
        if root is None or self._game.scene is not root._scene or self._game.mouse_position is None:
            return False
        target = root.pointer_target(*self._game.mouse_position)
        while target is not None:
            if target is self:
                return True
            target = target.parent
        return False

    def activate(self) -> bool:
        """Activate an attached, visible, enabled control; return whether it was available."""
        if not self._available():
            return False
        self.on_activate()
        return True

    def on_activate(self) -> None:
        """Override for a custom focusable control's Enter/Space action."""
        pass

    @property
    def has_pointer_capture(self) -> bool:
        root = self._ui_root()
        return root is not None and root._captured is self

    def capture_pointer(self) -> None:
        """Own subsequent motion/drag/release, including outside this control's bounds."""
        root = self._ui_root()
        if root is None or not self._available() or self._game.scene is not root._scene:
            raise ValueError("Pointer capture requires an available control in the active scene")
        if root._captured is not self:
            root._cancel_pointer()
            root._captured = self

    def release_pointer(self) -> None:
        root = self._ui_root()
        if root is not None and root._captured is self:
            root._captured = None

    def on_pointer_cancel(self) -> None:
        """Capture ended without a release: hidden/disabled, removed, covered or unfocused."""
        pass

    def hit_test(self, x: float, y: float) -> bool:
        return (
            self._computed_x <= x < self._computed_x + self._computed_w
            and self._computed_y <= y < self._computed_y + self._computed_h
        )

    def handle_event(self, event: InputEvent) -> bool:
        """Front-most child first, then :meth:`on_event`.  True = consumed."""
        if not self.visible:
            return False
        if not self.enabled:
            return event.type == "click" and self.pointer_target(event.x, event.y) is not None
        for child in reversed(list(self._children)):
            if child.handle_event(event):
                return True
        return self.on_event(event) or (event.type == "click" and self.blocks_pointer and self.hit_test(event.x, event.y))

    def pointer_target(self, x: float, y: float) -> Component | None:
        """Front-most visible pointer owner at a point; disabled controls still own their area."""
        if not self.visible:
            return None
        for child in reversed(self._children):
            target = child.pointer_target(x, y)
            if target is not None:
                return target
        return self if self.blocks_pointer and self.hit_test(x, y) else None

    def on_event(self, event: InputEvent) -> bool:
        return False

    def _tooltip_text(self) -> str | None:
        return self.tooltip() if callable(self.tooltip) else self.tooltip

    def _at_pointer(self, x: float, y: float) -> Component | None:
        """Front-most visible paint target, regardless of enabled state."""
        if not self.visible:
            return None
        for child in reversed(self._children):
            target = child._at_pointer(x, y)
            if target is not None:
                return target
        return self if self.hit_test(x, y) else None

    # -- Drawing / update --------------------------------------------------------

    def draw(self) -> None:
        if not self.visible:
            return
        self.on_draw()
        for child in list(self._children):
            child.draw()

    def on_draw(self) -> None:
        pass

    def update(self, dt: float) -> None:
        pass

    # -- Internals -------------------------------------------------------------

    @property
    def _order(self) -> int:
        """Tree paint order above the owning scene's immediate screen layers."""
        from saga2d.scene import UI_ORDER_BASE, UI_ORDER_STRIDE, _SCREEN_LAYER_COUNT

        root = self
        while root._parent is not None:
            root = root._parent
        scene = getattr(root, "_scene", None)
        return (UI_ORDER_BASE + (scene._level if scene is not None else 0) * UI_ORDER_STRIDE
                + _SCREEN_LAYER_COUNT + self._paint_index * _COMPONENT_ORDER_STRIDE)

    @staticmethod
    def _propagate_game(component: Component, game: Game | None) -> None:
        component._game = game
        for child in component._children:
            Component._propagate_game(child, game)


class _UIRoot(Component):
    """Invisible full-screen root of a scene's UI tree."""

    def __init__(self, scene: Scene) -> None:
        w, h = scene.game.resolution
        super().__init__(width=w, height=h)
        self._game = scene.game
        self._scene = scene
        self._computed_w, self._computed_h = w, h
        self._focused: Component | None = None
        self._navigation: str | None = None
        self._activation_keys: tuple[str, ...] = ()
        self._captured: Component | None = None

    def _cancel_pointer(self) -> None:
        captured, self._captured = self._captured, None
        if captured is not None:
            captured.on_pointer_cancel()

    def enable_focus(self, *, navigation: str = "tab", activate: tuple[str, ...] = ("return", "space")) -> None:
        """Opt into focus, leaving gameplay keys untouched in other scenes.

        ``tab`` cycles with Tab/Shift+Tab; ``vertical`` also uses Up/Down;
        ``spatial`` uses arrows to select a nearby control in that direction.
        ``manual`` lets the scene call focus_next/focus_direction itself.
        ``activate`` names exact key combinations; use ``()`` for custom actions.
        """
        from saga2d.ui.components import _normalize_shortcut

        if navigation not in ("tab", "vertical", "spatial", "manual"):
            raise ValueError(f"Unknown focus navigation {navigation!r}")
        if not isinstance(activate, tuple):
            raise TypeError("focus activation keys must be a tuple")
        activation_keys = tuple(_normalize_shortcut(key) for key in activate)
        self._navigation = navigation
        self._activation_keys = activation_keys

    @property
    def focused(self) -> Component | None:
        """The live focus owner, or None after removal, hiding or disabling."""
        if self._focused is not None and not self._can_focus(self._focused):
            self._focused = None
        return self._focused

    def _can_focus(self, component: Component) -> bool:
        return component.focusable and component._ui_root() is self and component._available()

    def focus(self, component: Component | None) -> None:
        """Select an available focusable descendant, or clear focus with None."""
        if component is not None and not self._can_focus(component):
            raise ValueError("Focus requires a visible, enabled, focusable control in this UI tree")
        self._focused = component

    def _focus_candidates(self, candidates: Iterable[Component] | None) -> list[Component]:
        return list(dict.fromkeys(component for component in (self.walk() if candidates is None else candidates)
                                  if self._can_focus(component)))

    def focus_next(self, *, reverse: bool = False, candidates: Iterable[Component] | None = None) -> Component | None:
        """Cycle live controls in tree order, or a game-supplied candidate order."""
        items = self._focus_candidates(candidates)
        if not items:
            self.focus(None)
        elif self.focused in items:
            self.focus(items[(items.index(self.focused) + (-1 if reverse else 1)) % len(items)])
        else:
            self.focus(items[-1 if reverse else 0])
        return self.focused

    def focus_direction(self, direction: str, *, candidates: Iterable[Component] | None = None) -> Component | None:
        """Focus the nearest well-aligned control within a 60-degree forward cone."""
        directions = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}
        if direction not in directions:
            raise ValueError(f"Unknown focus direction {direction!r}")
        self._ensure_layout()
        items = self._focus_candidates(candidates)
        current = self.focused
        if current is None:
            return self.focus_next(candidates=items)
        dx, dy = directions[direction]
        x, y, w, h = current.bounds
        choices = []
        for index, component in enumerate(items):
            cx, cy, cw, ch = component.bounds
            vx, vy = cx + cw / 2 - (x + w / 2), cy + ch / 2 - (y + h / 2)
            distance2, forward = vx * vx + vy * vy, vx * dx + vy * dy
            if distance2 > 0 and forward > 0 and forward * forward >= distance2 * .25:
                choices.append((distance2 / forward, index, component))
        if choices:
            self.focus(min(choices, key=lambda item: item[:2])[2])
        return self.focused

    def _handle_focus(self, event: InputEvent) -> bool:
        if self._navigation is None or event.type != "key_press":
            return False
        combo = event.combo
        if self._navigation != "manual" and combo in ("tab", "shift+tab"):
            return self.focus_next(reverse=combo == "shift+tab") is not None
        if self._navigation == "vertical" and combo in ("up", "down"):
            return self.focus_next(reverse=combo == "up") is not None
        if self._navigation == "spatial" and combo in ("up", "down", "left", "right"):
            return self.focus_direction(combo) is not None
        if combo in self._activation_keys and self.focused is not None:
            return self.focused.activate()
        return False

    def get_preferred_size(self) -> tuple[int, int]:
        return (self._computed_w, self._computed_h)

    def draw(self) -> None:
        from saga2d.scene import UI_ORDER_STRIDE, _SCREEN_LAYER_COUNT

        # Preorder matches draw() and the reverse sibling order used by input.
        # Reassign every frame so hiding, removal and reparenting leave no stale order.
        for index, component in enumerate(self.walk(include_self=True)):
            if _SCREEN_LAYER_COUNT + (index + 2) * _COMPONENT_ORDER_STRIDE > UI_ORDER_STRIDE:
                raise ValueError("UI tree exceeds the scene's draw-order capacity")
            component._paint_index = index
        super().draw()
        self._draw_tooltip()

    def _draw_tooltip(self) -> None:
        # Resolve against the current tree on every draw. No stored target can
        # survive removal, reparenting, hidden ancestry or a covering scene.
        if self._game.scene is not self._scene or self._game._mouse is None:
            return
        mx, my = self._game._mouse
        target = self._at_pointer(mx, my)
        text = None
        while target is not None:
            text = target._tooltip_text()
            if text is not None:
                break
            target = target.parent
        if not text:
            return
        from saga2d.rendering._text import _layout_paragraph
        from saga2d.rendering.shapes import draw_box
        from saga2d.scene import UI_ORDER_BASE, UI_ORDER_STRIDE

        backend, theme = self._game.backend, self._game.theme
        style = theme.get_text_style("body")
        font = style.font or theme.font
        padding, margin = 8, 6
        width = min(320, self._game.width - 2 * (padding + margin))
        measure = lambda line: backend.measure_text(line, style.font_size, font)
        line_height = measure("Mg")[1]
        step = line_height * 1.2
        available = self._game.height - 2 * (padding + margin)
        limit = max(1, int((available - line_height) // step) + 1)
        paragraph = _layout_paragraph(text, width, measure, line_spacing=1.2, max_lines=limit)
        lines = paragraph.lines
        w = max(measure(line)[0] for line in lines) + 2 * padding
        h = paragraph.height + 2 * padding
        x = max(margin, min(mx + 12, self._game.width - w - margin))
        y = my + 18 if my + 18 + h + margin <= self._game.height else my - h - 12
        y = max(margin, min(y, self._game.height - h - margin))
        order = UI_ORDER_BASE + (self._scene._level + 1) * UI_ORDER_STRIDE - _COMPONENT_ORDER_STRIDE
        draw_box(backend, x, y, w, h, (*theme.panel_background_color[:3], 255),
                 border_color=theme.panel_border_color, border_width=1, radius=4, order=order)
        for index, line in enumerate(lines):
            backend.draw_text(line, x + padding, y + padding + index * step, style.font_size,
                              style.color, font=font, anchor_y="top", order=order)

    def handle_event(self, event: InputEvent) -> bool:
        """Let normal UI consume first, then resolve live button shortcuts."""
        if self._captured is not None and event.is_mouse:
            if event.type in ("move", "drag", "release"):
                captured = self._captured
                try:
                    captured.on_event(event)
                finally:
                    if event.type == "release" and self._captured is captured:
                        self._captured = None
                return True
            if event.type == "click":
                self._cancel_pointer()
        if self._navigation is not None and event.type == "click":
            target = self.pointer_target(event.x, event.y)
            while target is not None:
                if self._can_focus(target):
                    self.focus(target)
                    break
                target = target.parent
        if super().handle_event(event):
            return True
        if event.type != "key_press":
            return False
        from saga2d.ui.components import Button

        matches = []
        for component in self.walk():
            if not isinstance(component, Button) or event.combo not in component._shortcuts:
                continue
            ancestor: Component | None = component
            enabled = True
            while ancestor is not None:
                if not ancestor.visible:
                    break
                enabled = enabled and ancestor.enabled
                ancestor = ancestor.parent
            else:
                # A visible disabled control reserves its key, so a scene's
                # fallback cannot bypass the disabled state.
                matches.append((component, enabled))
        if len(matches) > 1:
            names = ", ".join(repr(button.text) for button, _ in matches)
            raise ValueError(f"duplicate button shortcut {event.combo!r}: {names}")
        if matches:
            button, enabled = matches[0]
            if enabled:
                button.activate()
            return True
        return self._handle_focus(event)

    def _update_tree(self, dt: float) -> None:
        for component in list(self.walk(include_self=True)):
            if component.visible:
                component.update(dt)
