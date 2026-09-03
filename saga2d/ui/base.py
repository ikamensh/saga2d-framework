"""Base Component class and _UIRoot for the UI component tree.

Every UI widget inherits from :class:`Component`, which manages:

*   **Tree structure** — parent/children with ``add()`` / ``remove()``.
*   **Layout** — ``compute_layout()`` and ``get_preferred_size()`` for
    anchor-based and flow-based positioning.
*   **Hit testing** — ``hit_test(x, y)`` against computed screen-space bounds.
*   **Input dispatch** — ``handle_event(event)`` walks children front-to-back,
    then calls ``on_event()`` on self.
*   **Drawing** — ``draw()`` calls ``on_draw()`` then draws children.

:class:`_UIRoot` is an invisible root container that covers the full logical
screen.  It is created lazily via :attr:`Scene.ui` and serves as the
attachment point for all UI components within a scene.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from saga2d.ui.layout import Anchor
from saga2d.ui.theme import Style

if TYPE_CHECKING:
    from saga2d.game import Game
    from saga2d.input import InputEvent
    from saga2d.ui.drag_drop import DragManager


class Component:
    """Base class for all UI components.

    Manages a tree of children with layout computation, hit testing,
    input dispatch, and drawing.

    Parameters:
        width:       Explicit width in logical pixels, or ``None`` for
                     content-fit (determined by :meth:`get_preferred_size`).
        height:      Explicit height, or ``None`` for content-fit.
        anchor:      Positioning relative to parent rect.  ``None`` means
                     the parent's layout decides placement.
        margin:      Pixel margin inward from the anchor edge.
        visible:     Whether this component is drawn and receives input.
        enabled:     Whether this component receives input.  A disabled
                     component still draws (greyed out) but skips input.
        style:       Explicit :class:`Style` overrides, or ``None`` to
                     inherit everything from the theme.
        draggable:   If ``True`` this component can be dragged.  A left
                     click on it starts a drag session instead of firing
                     ``on_event`` / ``on_click``.
        drag_data:   Opaque payload passed from the drag source to the
                     drop target.  Game code defines the type.
        drop_accept: ``Callable[[Any], bool]`` — if not ``None``, this
                     component can receive drops.  Called with the dragged
                     data to decide accept (``True``) or reject (``False``).
        on_drop:     ``Callable[[Component, Any], Any]`` — fires when a
                     valid drop lands on this component.  Receives
                     ``(self, data)``.
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
        draggable: bool = False,
        drag_data: Any = None,
        drop_accept: Callable[[Any], bool] | None = None,
        on_drop: Callable[[Any, Any], Any] | None = None,
    ) -> None:
        if width is not None and width < 0:
            raise ValueError(f"width cannot be negative, got {width}")
        if height is not None and height < 0:
            raise ValueError(f"height cannot be negative, got {height}")
        if margin < 0:
            raise ValueError(f"margin cannot be negative, got {margin}")
        self._width = width
        self._height = height
        self._anchor = anchor
        self._margin = margin
        self.visible = visible
        self.enabled = enabled
        self.style = style

        # Drag-and-drop attributes (Stage 12).
        self.draggable = draggable
        self.drag_data = drag_data
        self.drop_accept = drop_accept
        self.on_drop = on_drop

        self._parent: Component | None = None
        self._children: list[Component] = []

        # Computed by layout pass — absolute logical screen coordinates.
        self._computed_x: int = 0
        self._computed_y: int = 0
        self._computed_w: int = 0
        self._computed_h: int = 0

        # Set when this component is added to a scene's UI tree.
        self._game: Game | None = None

        # Dirty flag — True when layout needs recomputing.
        self._layout_dirty: bool = True

    # ------------------------------------------------------------------
    # Tree management
    # ------------------------------------------------------------------

    def add(self, child: Component) -> None:
        """Add *child* to this component's children.

        Sets the child's parent reference and propagates the ``_game``
        reference so that all descendants can access the backend.
        """
        if child is self:
            raise ValueError("Cannot add component to itself")
        if child._parent is not None:
            child._parent.remove(child)
        child._parent = self
        self._children.append(child)
        self._propagate_game(child, self._game)
        self._mark_layout_dirty()

    def remove(self, child: Component) -> None:
        """Remove *child* from this component's children."""
        if child in self._children:
            self._children.remove(child)
            child._parent = None
            self._propagate_game(child, None)
            self._mark_layout_dirty()

    @property
    def parent(self) -> Component | None:
        """The parent component, or ``None`` if this is the root."""
        return self._parent

    @property
    def children(self) -> list[Component]:
        """A *copy* of the children list (for safe iteration)."""
        return list(self._children)

    def walk(self, *, include_self: bool = False):
        """Depth-first iterator over descendants.

        Yields each descendant :class:`Component` in the order a
        painter's-style draw would visit them. Useful for tests,
        debugging, and tooling that wants to see the whole tree
        without reaching into ``_children``::

            for label in scene.ui.walk():
                if isinstance(label, Label) and "HP" in label.text:
                    ...

        *include_self*: when ``True``, yields the receiver first.
        Default is ``False`` — game code calling
        ``scene.ui.walk()`` usually doesn't care about the invisible
        root itself.
        """
        if include_self:
            yield self
        for child in self._children:
            yield child
            yield from child.walk(include_self=False)

    def find(
        self,
        predicate: Callable[[Component], bool],
        *,
        include_self: bool = False,
    ) -> Component | None:
        """Return the first descendant satisfying *predicate*, or ``None``.

        Convenience shortcut for the common ``next((c for c in walk()
        if predicate(c)), None)`` pattern::

            hp_label = scene.ui.find(
                lambda c: isinstance(c, Label) and "HP" in c.text,
            )
        """
        for component in self.walk(include_self=include_self):
            if predicate(component):
                return component
        return None

    def find_all(
        self,
        predicate: Callable[[Component], bool],
        *,
        include_self: bool = False,
    ) -> list[Component]:
        """Return every descendant satisfying *predicate* as a list."""
        return [
            c for c in self.walk(include_self=include_self)
            if predicate(c)
        ]

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def get_preferred_size(self) -> tuple[int, int]:
        """Return the preferred ``(width, height)`` of this component.

        Components with explicit ``width``/``height`` return those values.
        Subclasses without explicit dimensions override this to measure
        their content (e.g. Label measures text, Panel measures children).

        The default returns ``(width or 0, height or 0)``.
        """
        return (self._width or 0, self._height or 0)

    def compute_layout(self, x: int, y: int, w: int, h: int) -> None:
        """Compute this component's layout within the given parent bounds.

        *x*, *y*, *w*, *h* describe the available rectangle from the
        parent.  This method sets ``_computed_x/y/w/h`` and recursively
        lays out children.

        If the component has an :attr:`_anchor`, it positions itself
        within ``(x, y, w, h)`` according to that anchor.  Otherwise it
        fills the given bounds (or uses its preferred size).
        """
        from saga2d.ui.layout import compute_anchor_position

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
            self._computed_w = own_w
            self._computed_h = own_h
        else:
            # No anchor — occupy the given bounds (or preferred size).
            self._computed_x = x
            self._computed_y = y
            self._computed_w = own_w if own_w > 0 else w
            self._computed_h = own_h if own_h > 0 else h

        # Lay out children within own bounds.
        self._layout_children()
        self._layout_dirty = False

    def _layout_children(self) -> None:
        """Lay out children within this component's computed bounds.

        The base implementation gives each child the full parent rect.
        Container subclasses (Panel) override this for flow layout.
        """
        for child in self._children:
            child.compute_layout(
                self._computed_x,
                self._computed_y,
                self._computed_w,
                self._computed_h,
            )

    # ------------------------------------------------------------------
    # Hit testing
    # ------------------------------------------------------------------

    def hit_test(self, x: int, y: int) -> bool:
        """Return ``True`` if logical coordinate ``(x, y)`` is within bounds.

        Uses the computed screen-space rectangle from the last layout
        pass.
        """
        return (
            self._computed_x <= x < self._computed_x + self._computed_w
            and self._computed_y <= y < self._computed_y + self._computed_h
        )

    # ------------------------------------------------------------------
    # Input dispatch
    # ------------------------------------------------------------------

    def handle_event(self, event: InputEvent) -> bool:
        """Dispatch *event* to children (front-to-back), then to self.

        Returns ``True`` if the event was consumed.

        *   Invisible or disabled components return ``False`` immediately.
        *   Children are iterated in reverse order so that the visually
            front-most child (drawn last) gets the event first.
        *   For ``draggable`` components, a left click that hits this
            component starts a drag session (takes precedence over
            :meth:`on_event` / ``on_click``).
        *   If no child consumes the event, :meth:`on_event` is called.
        """
        if not self.visible or not self.enabled:
            return False

        # Children in reverse order (front-most first).
        # Snapshot via list() so that child event handlers that add/remove
        # siblings don't corrupt the iterator (EC5 fix).
        for child in reversed(list(self._children)):
            if child.handle_event(event):
                return True

        # Drag-start check BEFORE on_event — drag takes precedence over
        # click for draggable components.
        if (
            self.draggable
            and event.type == "click"
            and event.button == "left"
            and self.hit_test(event.x, event.y)
        ):
            # Find the _UIRoot's DragManager to start the drag.
            if self._game is not None:
                top_scene = self._game._scene_stack.top()
                if top_scene is not None and top_scene._ui is not None:
                    dm = top_scene._ui.drag_manager
                    dm._start_drag(self, self.drag_data, event.x, event.y)
                    return True

        return self.on_event(event)

    def on_event(self, event: InputEvent) -> bool:
        """Handle an event on *this* component.

        Override in subclasses.  Return ``True`` to consume the event.
        The default implementation does not consume any events.
        """
        return False

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self) -> None:
        """Draw this component, then its children (painter's order).

        Invisible components are skipped entirely.
        """
        if not self.visible:
            return
        self.on_draw()
        # Snapshot via list() so that on_draw() callbacks that add/remove
        # siblings don't skip children or corrupt the iterator (EC4 fix).
        for child in list(self._children):
            child.draw()

    def on_draw(self) -> None:
        """Draw this component's own visuals.

        Override in subclasses.  The default does nothing (container-only
        components such as ``_UIRoot`` have no visuals of their own).
        """
        pass

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, dt: float) -> None:
        """Per-frame update hook.

        Called once per game tick with *dt* seconds since the last frame.
        Override in subclasses to drive animations, timers, or other
        time-dependent behaviour.

        The default does nothing.
        """
        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _mark_layout_dirty(self) -> None:
        """Signal that layout needs recomputation.

        Propagates upward to the root so that the next
        :meth:`_ensure_layout` call triggers a full re-layout.
        """
        self._layout_dirty = True
        if self._parent is not None:
            self._parent._mark_layout_dirty()

    def _ensure_layout(self) -> None:
        """Recompute layout if the dirty flag is set.

        Only the root should call this (before drawing or hit testing).
        """
        if self._layout_dirty:
            self.compute_layout(
                self._computed_x,
                self._computed_y,
                self._computed_w,
                self._computed_h,
            )

    @staticmethod
    def _propagate_game(component: Component, game: Game | None) -> None:
        """Recursively set ``_game`` on *component* and all descendants."""
        component._game = game
        for child in component._children:
            Component._propagate_game(child, game)


# ---------------------------------------------------------------------------
# _UIRoot — invisible root container for a scene's UI tree
# ---------------------------------------------------------------------------


class _UIRoot(Component):
    """Root component of a scene's UI tree.  Covers the full logical screen.

    Created lazily by :attr:`Scene.ui` on first access.  Game code never
    instantiates this directly — it just calls ``self.ui.add(panel)``.

    The root has no visuals; it only exists to:

    *   Provide screen-sized bounds for child layout.
    *   Propagate the ``_game`` reference to all descendants.
    *   Serve as the entry point for :meth:`handle_event` and
        :meth:`draw` during the game loop.
    *   Own the :class:`~saga2d.ui.drag_drop.DragManager` for
        drag-and-drop coordination (Stage 12).
    """

    def __init__(self, game: Game) -> None:
        w, h = game._resolution
        super().__init__(width=w, height=h)
        self._game = game
        # Pre-compute layout bounds to the full screen.
        self._computed_x = 0
        self._computed_y = 0
        self._computed_w = w
        self._computed_h = h

        # Drag-and-drop manager — created lazily on first access.
        self._drag_manager: DragManager | None = None

    @property
    def drag_manager(self) -> DragManager:
        """The :class:`~saga2d.ui.drag_drop.DragManager`, created lazily.

        Components access this to start drag sessions.  The DragManager
        intercepts events during an active drag and draws ghost overlays.
        """
        if self._drag_manager is None:
            from saga2d.ui.drag_drop import DragManager as _DM

            self._drag_manager = _DM(self)
        return self._drag_manager

    def add(self, child: Component) -> None:
        """Add a child and ensure it has the game reference."""
        super().add(child)
        # super().add already calls _propagate_game, but be defensive.
        Component._propagate_game(child, self._game)

    def get_preferred_size(self) -> tuple[int, int]:
        """The root always covers the full screen."""
        return (self._computed_w, self._computed_h)

    def handle_event(self, event: InputEvent) -> bool:
        """Dispatch input events, with drag-and-drop interception.

        If a drag session is active, the DragManager handles *all*
        events (ghost movement, drop, cancel).  Otherwise, normal
        child dispatch proceeds.
        """
        if self._drag_manager is not None and self._drag_manager.is_dragging:
            return self._drag_manager.handle_event(event)
        return super().handle_event(event)

    def draw(self) -> None:
        """Draw children, then draw the drag ghost overlay on top."""
        super().draw()
        # Draw ghost overlay after all children so it's always on top.
        if self._drag_manager is not None and self._drag_manager.is_dragging:
            self._drag_manager._draw_ghost()

    def _update_tree(self, dt: float) -> None:
        """Recursively call :meth:`update` on every component in the tree.

        Walks the tree depth-first (parent updated before children).
        Invisible components are skipped — they don't participate in
        per-frame updates.
        """
        self._update_recursive(self, dt)

    @staticmethod
    def _update_recursive(component: Component, dt: float) -> None:
        """Depth-first update walk."""
        if not component.visible:
            return
        component.update(dt)
        # Snapshot via list() so that update() callbacks that add/remove
        # siblings don't skip children or corrupt the iterator (EC3 fix).
        for child in list(component._children):
            _UIRoot._update_recursive(child, dt)
