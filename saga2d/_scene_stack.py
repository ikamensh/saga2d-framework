"""SceneStack — push/pop/replace/clear_and_push scene stack manager.

Extracted from ``scene.py`` to keep that file focused on the Scene
base class. Operations requested during ``update()`` or
``handle_input()`` are queued and flushed after those phases complete.
"""

from __future__ import annotations

import collections
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from saga2d.game import Game
    from saga2d.scene import Scene

_logger = logging.getLogger(__name__)

# Safety cap to prevent infinite pending-op loops (e.g. on_enter that
# always pushes another scene). The cap is well above any realistic
# depth; hitting it signals a bug and we log + drop the remainder.
_MAX_FLUSH_ITERATIONS = 1000


class SceneStack:
    """Manages a stack of scenes with deferred push/pop/replace/clear_and_push.

    Operations requested during update() or handle_input() are queued and
    flushed after those phases complete. This avoids modifying the stack
    mid-iteration (e.g. scene receiving on_exit during its own update).
    """

    def __init__(self, game: Game) -> None:
        self._game: Game = game
        self._stack: list[Scene] = []
        self._pending_ops: collections.deque[tuple[str] | tuple[str, Scene]] = (
            collections.deque()
        )
        self._in_tick: bool = False
        self._flushing: bool = False
        self._in_on_exit: bool = False

    def top(self) -> Scene | None:
        """Return the top scene, or None if stack is empty."""
        return self._stack[-1] if self._stack else None

    def get_base_scene(self) -> Scene | None:
        """Return the lowest visible scene (opaque or bottom of transparent chain).

        Used to determine which scene's background_color to apply when clearing.
        """
        if not self._stack:
            return None
        start = len(self._stack) - 1
        while start > 0 and self._stack[start].transparent:
            start -= 1
        return self._stack[start]

    def _should_defer(self) -> bool:
        """True when stack mutations must be queued instead of applied."""
        return self._in_tick or self._flushing or self._in_on_exit

    def push(self, scene: Scene) -> None:
        """Push scene on top. Current top gets on_exit, new scene gets on_enter."""
        if scene is None:
            raise ValueError("push() requires a Scene instance, got None")
        if self._should_defer():
            self._pending_ops.append(("push", scene))
            return
        self._apply_push(scene)
        self._flush_after_direct_op()

    def pop(self) -> None:
        """Pop top scene. Top gets on_exit, new top (if any) gets on_reveal."""
        if self._should_defer():
            self._pending_ops.append(("pop",))
            return
        self._apply_pop()
        self._flush_after_direct_op()

    def replace(self, scene: Scene) -> None:
        """Replace top scene. Old gets on_exit, new gets on_enter. No on_reveal.

        The old scene is popped before the new one is pushed. If the new
        scene's on_enter raises, rollback only pops the failed scene; the
        old scene is not restored.
        """
        if scene is None:
            raise ValueError("replace() requires a Scene instance, got None")
        if self._should_defer():
            self._pending_ops.append(("replace", scene))
            return
        self._apply_replace(scene)
        self._flush_after_direct_op()

    def clear_and_push(self, scene: Scene) -> None:
        """Clear stack, push scene. All cleared scenes get on_exit."""
        if scene is None:
            raise ValueError("clear_and_push() requires a Scene instance, got None")
        if self._should_defer():
            self._pending_ops.append(("clear_and_push", scene))
            return
        self._apply_clear_and_push(scene)
        self._flush_after_direct_op()

    def begin_tick(self) -> None:
        """Mark start of tick. Operations will be deferred until flush."""
        self._in_tick = True

    def _drain_pending(self) -> None:
        """Apply queued ops until the queue is empty or the safety cap hits."""
        iterations = 0
        while self._pending_ops and iterations < _MAX_FLUSH_ITERATIONS:
            iterations += 1
            op = self._pending_ops.popleft()
            kind = op[0]
            if kind == "pop":
                self._apply_pop()
            elif kind == "push":
                self._apply_push(op[1])  # type: ignore[misc]
            elif kind == "replace":
                self._apply_replace(op[1])  # type: ignore[misc]
            elif kind == "clear_and_push":
                self._apply_clear_and_push(op[1])  # type: ignore[misc]
        if iterations >= _MAX_FLUSH_ITERATIONS and self._pending_ops:
            _logger.warning(
                "SceneStack: deferred ops cap (%d) reached; %d ops discarded",
                _MAX_FLUSH_ITERATIONS,
                len(self._pending_ops),
            )
            self._pending_ops.clear()

    def _flush_after_direct_op(self) -> None:
        """Flush deferred ops that accumulated during a direct (non-tick)
        scene operation.

        Lifecycle hooks like ``on_exit`` and ``on_reveal`` set
        ``_in_on_exit`` which defers operations.  When the direct
        ``push``/``pop``/``replace``/``clear_and_push`` call returns,
        those deferred ops need to be flushed immediately.

        No-op when already inside a tick or another flush.
        """
        if self._in_tick or self._flushing or self._in_on_exit:
            return
        if not self._pending_ops:
            return
        self._flushing = True
        try:
            self._drain_pending()
        finally:
            self._flushing = False

    def flush_pending_ops(self) -> None:
        """Execute all queued operations, then end tick."""
        self._in_tick = False
        if self._flushing:
            # Re-entrant call (e.g. on_exit triggers pop) — the outer
            # loop will pick up any newly appended ops.
            return
        self._flushing = True
        try:
            self._drain_pending()
        except Exception:
            # Clear remaining ops to prevent stale operations from
            # leaking into the next tick (F57).
            self._pending_ops.clear()
            raise
        finally:
            self._flushing = False

    def _cleanup_exiting_scene(
        self, scene: Scene, *, permanent: bool = True,
    ) -> None:
        """Run common cleanup for a scene whose ``on_exit()`` has been called.

        Called **after** ``scene.on_exit()``.  Cleans up owned sprites,
        particle emitters, and cancels camera pan tweens.

        When *permanent* is ``True`` (pop, replace, clear_and_push), owned
        timers are also cancelled.  When ``False`` (pushed over by another
        scene), timers are preserved so they continue to fire while the
        scene is covered and survive until the scene is revealed or
        permanently removed.

        Note: the UI tree is NOT cleared here because this method is also
        called when a scene is *pushed over* (it stays on the stack and
        may be revealed later).  Use :meth:`_teardown_exited_scene` for
        scenes that are permanently leaving the stack.
        """
        scene._cleanup_owned_sprites()
        if permanent:
            scene._cleanup_owned_timers()
        scene._cleanup_owned_emitters()
        if scene.camera is not None:
            scene.camera._cancel_pan()
        if hasattr(scene.game, "cursor"):
            scene.game.cursor.set("default")

    def _teardown_exited_scene(self, scene: Scene) -> None:
        """Final cleanup for a scene that is permanently leaving the stack.

        Clears the UI tree (including any active drag session) and sets
        ``scene.game = None`` so the entire scene graph can be GC'd.
        """
        if scene._ui is not None:
            if scene._ui._drag_manager is not None:
                scene._ui._drag_manager.cancel_active()
            scene._ui = None
        scene.game = None  # type: ignore[assignment]

    def _apply_push(self, scene: Scene) -> None:
        if self._stack:
            old = self._stack[-1]
            self._in_on_exit = True
            try:
                old.on_exit()
                self._cleanup_exiting_scene(old, permanent=False)
            finally:
                self._in_on_exit = False
        scene.game = self._game
        self._stack.append(scene)
        try:
            scene.on_enter()
        except Exception:
            self._stack.pop()
            raise

    def _apply_pop(self) -> None:
        if not self._stack:
            return
        self._in_on_exit = True
        try:
            old = self._stack[-1]
            try:
                old.on_exit()
            finally:
                self._cleanup_exiting_scene(old)
                self._stack.pop()
                self._teardown_exited_scene(old)
            if self._stack:
                self._stack[-1].on_reveal()
        finally:
            self._in_on_exit = False

    def _apply_replace(self, scene: Scene) -> None:
        if self._stack:
            old = self._stack[-1]
            self._in_on_exit = True
            try:
                try:
                    old.on_exit()
                finally:
                    self._cleanup_exiting_scene(old)
                    self._stack.pop()
                    self._teardown_exited_scene(old)
            finally:
                self._in_on_exit = False
        scene.game = self._game
        self._stack.append(scene)
        try:
            scene.on_enter()
        except Exception:
            self._stack.pop()
            raise

    def _apply_clear_and_push(self, scene: Scene) -> None:
        self._in_on_exit = True
        first_error: Exception | None = None
        try:
            for s in reversed(self._stack):
                try:
                    s.on_exit()
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
                finally:
                    self._cleanup_exiting_scene(s)
                    self._teardown_exited_scene(s)
            self._stack.clear()
        finally:
            self._in_on_exit = False
        if first_error is not None:
            raise first_error
        scene.game = self._game
        self._stack.append(scene)
        try:
            scene.on_enter()
        except Exception:
            self._stack.pop()
            raise

    def update(self, dt: float) -> None:
        """Update the top scene (and below if pause_below=False)."""
        top = self.top()
        if not top:
            return
        scenes_to_update: list[Scene] = []
        i = len(self._stack) - 1
        while i >= 0:
            scenes_to_update.append(self._stack[i])
            if self._stack[i].pause_below:
                break
            i -= 1
        for s in reversed(scenes_to_update):
            s.update(dt)

    def draw(self) -> None:
        """Draw visible scenes from bottom to top, with HUD interleaved.

        Draw order:

        1.  Find the lowest visible scene (walk down from top through
            transparent scenes).
        2.  Draw the **base scene** (the lowest opaque one) + its UI.
        3.  Draw the **HUD** (if it exists, is visible, and the top
            scene's ``show_hud`` is ``True``).
        4.  Draw **transparent overlay scenes** + their UIs, from the
            overlay just above the base upward.

        This ensures the HUD sits above the base scene's content but
        below modal overlays like ``MessageScreen`` or ``ConfirmDialog``.
        """
        if not self._stack:
            return
        # Find the lowest scene we need to draw.  Start at the top and
        # walk downward — stop as soon as we hit an opaque scene because
        # it covers everything below.
        start = len(self._stack) - 1
        while start > 0 and self._stack[start].transparent:
            start -= 1

        backend = self._game._backend

        # --- Step 1: draw the base scene (the opaque one at ``start``).
        backend.set_ui_layer(0)
        base = self._stack[start]
        base.draw()
        if base._ui is not None:
            base._ui._ensure_layout()
            base._ui.draw()

        # --- Step 2: draw the HUD between base and overlays.
        backend.set_ui_layer(1)
        hud = self._game._hud
        if hud is not None:
            top = self._stack[-1]
            if hud._should_draw(top.show_hud):
                hud._draw()

        # --- Step 3: draw overlay scenes above the base.
        for i in range(start + 1, len(self._stack)):
            backend.set_ui_layer(2 + (i - start - 1))
            scene = self._stack[i]
            scene.draw()
            if scene._ui is not None:
                scene._ui._ensure_layout()
                scene._ui.draw()
