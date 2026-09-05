"""SceneStack — push/pop/replace/clear_and_push with deferred application.

Operations requested while the game loop is dispatching input or updating
are queued and applied afterwards, so a scene never mutates the stack
underneath its own ``update``.
"""

from __future__ import annotations

import collections
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from saga2d.game import Game
    from saga2d.scene import Scene

_logger = logging.getLogger(__name__)
_MAX_FLUSH_ITERATIONS = 1000


class SceneStack:
    def __init__(self, game: Game) -> None:
        self._game = game
        self._stack: list[Scene] = []
        self._pending: collections.deque[tuple[str, Scene | None]] = collections.deque()
        self._busy = False  # inside a tick phase, a flush, or a lifecycle hook

    @property
    def scenes(self) -> list[Scene]:
        return list(self._stack)

    def top(self) -> Scene | None:
        return self._stack[-1] if self._stack else None

    @property
    def transition_pending(self) -> bool:
        """Whether a callback has requested a scene change for the current phase."""
        return bool(self._pending)

    def base_index(self) -> int:
        """Index of the lowest scene that must be drawn."""
        i = len(self._stack) - 1
        while i > 0 and self._stack[i].transparent:
            i -= 1
        return i

    def get_base_scene(self) -> Scene | None:
        return self._stack[self.base_index()] if self._stack else None

    # -- Public operations -----------------------------------------------------

    def push(self, scene: Scene) -> None:
        self._request("push", scene)

    def pop(self) -> None:
        self._request("pop", None)

    def replace(self, scene: Scene) -> None:
        self._request("replace", scene)

    def clear_and_push(self, scene: Scene) -> None:
        self._request("clear_and_push", scene)

    def _request(self, kind: str, scene: Scene | None) -> None:
        self._pending.append((kind, scene))
        if not self._busy:
            self.flush()

    # -- Tick integration ------------------------------------------------------

    def begin_phase(self) -> None:
        self._busy = True

    def end_phase(self) -> None:
        self._busy = False
        self.flush()

    def flush(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            iterations = 0
            while self._pending and iterations < _MAX_FLUSH_ITERATIONS:
                iterations += 1
                kind, scene = self._pending.popleft()
                getattr(self, f"_apply_{kind}")(scene)
            if self._pending:
                _logger.warning("SceneStack: %d queued operations discarded after %d iterations", len(self._pending), iterations)
                self._pending.clear()
        except BaseException:
            self._pending.clear()
            raise
        finally:
            self._busy = False

    # -- Application -----------------------------------------------------------

    def _enter(self, scene: Scene) -> None:
        scene.game = self._game
        scene._level = len(self._stack)
        self._stack.append(scene)
        try:
            scene.on_enter()
        except BaseException as enter_error:
            self._stack.pop()
            try:
                scene._release_resources()
            except BaseException as cleanup_error:
                raise enter_error from cleanup_error
            raise

    def _leave(self, scene: Scene) -> None:
        try:
            scene.on_exit()
        finally:
            scene._release_resources()

    def _apply_push(self, scene: Scene) -> None:
        if self._stack:
            self._stack[-1].on_exit()
        self._enter(scene)

    def _apply_pop(self, _scene: Scene | None) -> None:
        if not self._stack:
            return
        old = self._stack.pop()
        try:
            self._leave(old)
        finally:
            if self._stack:
                self._stack[-1].on_reveal()

    def _apply_replace(self, scene: Scene) -> None:
        if self._stack:
            self._leave(self._stack.pop())
        self._enter(scene)

    def _apply_clear_and_push(self, scene: Scene) -> None:
        self.clear()
        self._enter(scene)

    def clear(self) -> None:
        """Remove every scene, even if an exit hook fails (used by teardown)."""
        first_error: BaseException | None = None
        while self._stack:
            try:
                self._leave(self._stack.pop())
            except BaseException as exc:
                first_error = first_error or exc
        if first_error is not None:
            raise first_error

    # -- Per-frame -------------------------------------------------------------

    def update(self, dt: float) -> None:
        if not self._stack:
            return
        i = len(self._stack) - 1
        while i > 0 and not self._stack[i].pause_below:
            i -= 1
        for scene in self._stack[i:]:
            scene.update(dt)

    def draw(self) -> None:
        for scene in self._stack[self.base_index():]:
            scene.draw()
            if scene._ui is not None:
                scene._ui._ensure_layout()
                scene._ui.draw()
