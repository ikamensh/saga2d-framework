"""Component — base class of the UI tree; _UIRoot — a scene's root.

A component owns children, computes its layout inside the rectangle its
parent offers, hit-tests against that rectangle, dispatches input to its
front-most child first, and draws itself before its children.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Iterator

from saga2d.ui.layout import Anchor, compute_anchor_position
from saga2d.ui.theme import Style

if TYPE_CHECKING:
    from saga2d.game import Game
    from saga2d.input import InputEvent
    from saga2d.scene import Scene


class Component:
    """Parameters:
        width / height: Explicit size, or ``None`` to fit content.
        anchor:  Placement inside the parent rect; ``None`` lets the
                 parent's flow layout decide.
        margin:  Inset from the anchored edge(s).
        visible: Hidden components neither draw nor receive input.
        enabled: Disabled components draw greyed and ignore input.
        style:   :class:`Style` overrides.
    """

    def __init__(
        self,
        *,
        width: int | None = None,
        height: int | None = None,
        anchor: Anchor | None = None,
        margin: int = 0,
        visible: bool = True,
        enabled: bool = True,
        style: Style | None = None,
    ) -> None:
        if (width is not None and width < 0) or (height is not None and height < 0) or margin < 0:
            raise ValueError(f"width, height and margin must be >= 0, got {width}, {height}, {margin}")
        self._width = width
        self._height = height
        self._anchor = anchor
        self._margin = margin
        self.visible = visible
        self.enabled = enabled
        self.style = style
        self._parent: Component | None = None
        self._children: list[Component] = []
        self._computed_x = 0
        self._computed_y = 0
        self._computed_w = 0
        self._computed_h = 0
        self._game: Game | None = None
        self._layout_dirty = True

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

    def _ensure_layout(self) -> None:
        if self._layout_dirty:
            self.compute_layout(self._computed_x, self._computed_y, self._computed_w, self._computed_h)

    # -- Input -----------------------------------------------------------------

    def hit_test(self, x: float, y: float) -> bool:
        return (
            self._computed_x <= x < self._computed_x + self._computed_w
            and self._computed_y <= y < self._computed_y + self._computed_h
        )

    def handle_event(self, event: InputEvent) -> bool:
        """Front-most child first, then :meth:`on_event`.  True = consumed."""
        if not self.visible or not self.enabled:
            return False
        for child in reversed(list(self._children)):
            if child.handle_event(event):
                return True
        return self.on_event(event)

    def on_event(self, event: InputEvent) -> bool:
        return False

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
        """Screen-space draw order: the owning scene's level in the stack."""
        from saga2d.scene import UI_ORDER_BASE

        root = self
        while root._parent is not None:
            root = root._parent
        scene = getattr(root, "_scene", None)
        return UI_ORDER_BASE + (scene._level if scene is not None else 0)

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

    def get_preferred_size(self) -> tuple[int, int]:
        return (self._computed_w, self._computed_h)

    def _update_tree(self, dt: float) -> None:
        for component in list(self.walk(include_self=True)):
            if component.visible:
                component.update(dt)
