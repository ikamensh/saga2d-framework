"""Scene base class and SceneStack.

Scene is a concrete base class with no-op lifecycle hooks. Subclasses override
only what they need. SceneStack manages a stack of scenes with push/pop/replace/
clear_and_push. Operations triggered during update() or handle_input() are
deferred and flushed after those phases complete.
"""

from __future__ import annotations

import collections
from typing import TYPE_CHECKING, Any, Callable

from saga2d.util.timer import TimerHandle

if TYPE_CHECKING:
    from saga2d.game import Game
    from saga2d.input import InputEvent
    from saga2d.rendering.camera import Camera
    from saga2d.rendering.sprite import Sprite
    from saga2d.ui.component import _UIRoot


class Scene:
    """Self-contained game state: title screen, world map, inventory, etc.

    Lifecycle hooks (all no-op by default):
    - on_enter: called when scene becomes active (after push/replace/clear_and_push)
    - on_exit:  called when scene is removed OR covered (pushed over)
    - on_reveal: called when the scene above is popped
    - update:    called every frame (only top scene, or below if pause_below=False)
    - draw:     called every frame (bottom-up from lowest visible)
    - handle_input: return True to consume event, False to pass through

    The `game` attribute is set by SceneStack before on_enter() so scenes can
    call self.game.push(), self.game.pop(), etc.

    The `camera` attribute is ``None`` for UI-only scenes.  World scenes set
    it (typically in :meth:`on_enter`) to enable camera-aware rendering with
    automatic sprite offset and frustum culling.
    """

    transparent: bool = False
    pause_below: bool = True
    pop_on_cancel: bool = False
    show_hud: bool = True
    real_time: bool = True

    # When set to (R,G,B) or (R,G,B,A), the framework clears the screen with
    # this color before drawing. Values 0–255. Default None = no clear.
    background_color: tuple[int, ...] | None = None

    game: Game
    camera: Camera | None = None
    _ui: _UIRoot | None = None

    # ------------------------------------------------------------------
    # Sprite ownership
    # ------------------------------------------------------------------

    def _get_owned_sprites(self) -> set[Sprite]:
        """Return the owned-sprites set, creating it lazily."""
        try:
            return self._owned_sprites
        except AttributeError:
            self._owned_sprites: set[Sprite] = set()
            return self._owned_sprites

    def add_sprite(self, sprite: Sprite) -> Sprite:
        """Register *sprite* as owned by this scene.

        Owned sprites are automatically removed when the scene exits
        (after the user's :meth:`on_exit` runs).  Individual early removal
        via :meth:`Sprite.remove` or :meth:`remove_sprite` still works.

        Returns the sprite for convenient chaining::

            self.knight = self.add_sprite(
                Sprite("sprites/knight", position=(400, 300))
            )
        """
        if sprite.is_removed:
            return sprite
        self._get_owned_sprites().add(sprite)
        sprite._owning_scene = self
        return sprite

    def remove_sprite(self, sprite: Sprite) -> None:
        """Explicitly remove *sprite* from this scene's ownership and destroy it.

        Calls :meth:`Sprite.remove` on the sprite after deregistering it.
        Safe to call on sprites that are already removed or not owned by
        this scene.
        """
        self._get_owned_sprites().discard(sprite)
        if not sprite.is_removed:
            sprite._owning_scene = None
            sprite.remove()

    def _cleanup_owned_sprites(self) -> None:
        """Remove all owned sprites.  Called by SceneStack after on_exit()."""
        owned = self._get_owned_sprites()
        # Iterate over a copy because Sprite.remove() discards from the set.
        for sprite in list(owned):
            if not sprite.is_removed:
                sprite.remove()
        owned.clear()

    # ------------------------------------------------------------------
    # Timer ownership
    # ------------------------------------------------------------------

    def _get_owned_timers(self) -> set[TimerHandle]:
        """Return the owned-timer set, creating it lazily."""
        try:
            return self._owned_timers
        except AttributeError:
            self._owned_timers: set[TimerHandle] = set()
            return self._owned_timers

    def after(self, delay: float, callback: Callable[[], Any]) -> TimerHandle:
        """Schedule a one-shot callback after *delay* seconds.

        The timer is automatically cancelled when this scene exits (after
        the user's :meth:`on_exit` runs).  Returns a TimerHandle that can be
        passed to :meth:`cancel_timer` for early manual cancellation.

        Equivalent to ``self.game.after(delay, callback)`` with automatic
        lifecycle management.
        """
        owned = self._get_owned_timers()
        handle: TimerHandle | None = None

        def _wrapper() -> None:
            # Only remove from the owned set when the root timer fires
            # AND there is no pending then-chain.  If a chain exists the
            # handle must stay owned so that scene-exit cleanup can cancel
            # the still-running child timers via the shared _chain_ids.
            if handle is not None:
                root = handle._manager._timers.get(handle.timer_id)
                has_chain = root is not None and bool(root.then_chain)
                if not has_chain:
                    owned.discard(handle)
            callback()

        handle = self.game.after(delay, _wrapper)
        owned.add(handle)
        return handle

    def every(self, interval: float, callback: Callable[[], Any]) -> TimerHandle:
        """Schedule a repeating callback every *interval* seconds.

        The timer is automatically cancelled when this scene exits (after
        the user's :meth:`on_exit` runs).  Returns a TimerHandle that can be
        passed to :meth:`cancel_timer` for early manual cancellation.

        Equivalent to ``self.game.every(interval, callback)`` with automatic
        lifecycle management.
        """
        handle = self.game.every(interval, callback)
        self._get_owned_timers().add(handle)
        return handle

    def cancel_timer(self, timer_id: int | TimerHandle) -> None:
        """Manually cancel a scene-owned timer.

        Accepts a timer ID or TimerHandle. If a TimerHandle is given, cancels
        the entire chain. Safe to call on already-fired or already-cancelled.
        """
        if isinstance(timer_id, TimerHandle):
            self._get_owned_timers().discard(timer_id)
        self.game.cancel(timer_id)

    def _cleanup_owned_timers(self) -> None:
        """Cancel all owned timers.  Called by SceneStack after on_exit()."""
        owned = self._get_owned_timers()
        for timer_id in list(owned):
            self.game.cancel(timer_id)
        owned.clear()

    # ------------------------------------------------------------------
    # Particle emitter ownership
    # ------------------------------------------------------------------

    def _get_owned_emitters(self) -> set[Any]:
        """Return the owned-emitter set, creating it lazily."""
        try:
            return self._owned_emitters
        except AttributeError:
            self._owned_emitters: set[Any] = set()
            return self._owned_emitters

    def add_emitter(self, emitter: Any) -> Any:
        """Register a :class:`~saga2d.rendering.particles.ParticleEmitter`
        as owned by this scene.

        Owned emitters are automatically removed (stopped + unregistered)
        when the scene exits.  Returns the emitter for chaining.
        """
        self._get_owned_emitters().add(emitter)
        return emitter

    def _cleanup_owned_emitters(self) -> None:
        """Remove all owned emitters.  Called by SceneStack after on_exit()."""
        owned = self._get_owned_emitters()
        for emitter in list(owned):
            emitter.remove()
        owned.clear()

    # ------------------------------------------------------------------
    # Key binding shortcuts
    # ------------------------------------------------------------------

    def bind_key(self, key_or_action: str, callback: Callable[[], Any]) -> None:
        """Register a callback for a key press.

        *key_or_action* may be a raw key name (``"i"``, ``"space"``) or a
        named action (``"cancel"``, ``"confirm"``).  Named actions are
        checked first so rebinding works automatically.

        Call from :meth:`on_enter` alongside your UI setup::

            def on_enter(self):
                self.bind_key("i",      lambda: self.game.push(InventoryScreen()))
                self.bind_key("c",      lambda: self.game.push(CharScreen()))
                self.bind_key("cancel", lambda: self.game.push(PauseMenu()))

        Only one callback per key/action.  Calling ``bind_key`` with the
        same string again replaces the previous callback.
        """
        try:
            self._key_handlers[key_or_action] = callback
        except AttributeError:
            self._key_handlers: dict[str, Callable[[], Any]] = {
                key_or_action: callback
            }

    def _dispatch_key_bindings(self, event: InputEvent) -> bool:
        """Dispatch *event* to registered key callbacks.

        Called by the game loop before :meth:`handle_input`.  Returns
        ``True`` if a binding matched and consumed the event.
        """
        handlers: dict[str, Callable[[], Any]] | None = getattr(
            self, "_key_handlers", None
        )
        if not handlers or event.type != "key_press":
            return False
        cb = handlers.get(event.action) or handlers.get(event.key)  # type: ignore[arg-type]
        if cb is not None:
            cb()
            return True
        return False

    def on_enter(self) -> None:
        """Called when this scene becomes active (top of stack)."""
        pass

    def on_exit(self) -> None:
        """Called when this scene is removed or covered by another scene."""
        pass

    def on_reveal(self) -> None:
        """Called when the scene above this one is popped."""
        pass

    def update(self, dt: float) -> None:
        """Called every frame. Override for game logic."""
        pass

    def draw(self) -> None:
        """Called every frame. Override for rendering."""
        pass

    def handle_input(self, event: InputEvent) -> bool:
        """Handle input event. Return True to consume, False to pass through."""
        return False

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def draw_rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        color: tuple[int, int, int, int],
        *,
        opacity: float = 1.0,
    ) -> None:
        """Draw a filled rectangle in **screen space**.

        Convenience wrapper around the backend's ``draw_rect`` for use
        inside :meth:`draw`.  Coordinates are in logical screen pixels.

        Parameters:
            x:       Left edge in screen pixels.
            y:       Top edge in screen pixels.
            width:   Width in pixels.
            height:  Height in pixels.
            color:   ``(R, G, B, A)`` with values 0–255.
            opacity: Extra opacity multiplier (0.0–1.0, default 1.0).
        """
        self.game._backend.draw_rect(
            int(x),
            int(y),
            int(width),
            int(height),
            color,
            opacity=opacity,
        )

    def draw_world_rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        color: tuple[int, int, int, int],
        *,
        opacity: float = 1.0,
    ) -> None:
        """Draw a filled rectangle in **world space**.

        The rectangle position ``(x, y)`` is automatically transformed
        through the scene's :attr:`camera` to screen coordinates.  Use
        this for health bars, selection highlights, or any overlay that
        should scroll with the world.

        Requires :attr:`camera` to be set (typically in :meth:`on_enter`).
        Raises :class:`RuntimeError` if no camera is attached.

        Parameters:
            x:       Left edge in world pixels.
            y:       Top edge in world pixels.
            width:   Width in pixels (not transformed).
            height:  Height in pixels (not transformed).
            color:   ``(R, G, B, A)`` with values 0–255.
            opacity: Extra opacity multiplier (0.0–1.0, default 1.0).
        """
        if self.camera is None:
            raise RuntimeError(
                "draw_world_rect() requires a camera.  "
                "Set self.camera in on_enter() before drawing in world space."
            )
        sx, sy = self.camera.world_to_screen(x, y)
        self.game._backend.draw_rect(
            int(sx),
            int(sy),
            int(width),
            int(height),
            color,
            opacity=opacity,
        )

    # ------------------------------------------------------------------
    # Save / Load
    # ------------------------------------------------------------------

    def get_save_state(self) -> dict[str, Any]:
        """Return a JSON-serializable dict of scene state.

        Called by :meth:`Game.save`.  Only the **top** scene's state is
        saved.  Override in subclasses to persist game-specific data.

        Returns an empty dict by default.
        """
        return {}

    def load_save_state(self, state: dict[str, Any]) -> None:
        """Restore scene state from a previously saved dict.

        Called by game code **after** :meth:`on_enter` to reinitialise
        the scene from saved data.  Override in subclasses.
        """
        pass

    @property
    def ui(self) -> _UIRoot:
        """The UI component tree root, created lazily on first access.

        Returns a :class:`~saga2d.ui.component._UIRoot` that covers the
        full logical screen.  Add components via ``self.ui.add(panel)``.

        The root is created on first access (after ``game`` is set by the
        scene stack), so it is safe to use inside :meth:`on_enter`.
        """
        if self._ui is None:
            from saga2d.ui.component import _UIRoot

            self._ui = _UIRoot(self.game)
        return self._ui


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

    def pop(self) -> None:
        """Pop top scene. Top gets on_exit, new top (if any) gets on_reveal."""
        if self._should_defer():
            self._pending_ops.append(("pop",))
            return
        self._apply_pop()

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

    def clear_and_push(self, scene: Scene) -> None:
        """Clear stack, push scene. All cleared scenes get on_exit."""
        if scene is None:
            raise ValueError("clear_and_push() requires a Scene instance, got None")
        if self._should_defer():
            self._pending_ops.append(("clear_and_push", scene))
            return
        self._apply_clear_and_push(scene)

    def begin_tick(self) -> None:
        """Mark start of tick. Operations will be deferred until flush."""
        self._in_tick = True

    def flush_pending_ops(self) -> None:
        """Execute all queued operations, then end tick."""
        self._in_tick = False
        if self._flushing:
            # Re-entrant call (e.g. on_exit triggers pop) — the outer
            # loop will pick up any newly appended ops.
            return
        self._flushing = True
        try:
            max_iterations = 1000  # Cap to prevent infinite hang if on_enter
            iterations = 0
            while self._pending_ops and iterations < max_iterations:
                iterations += 1
                op = self._pending_ops.popleft()
                kind = op[0]
                if kind == "pop":
                    self._apply_pop()
                elif kind == "push":
                    scene = op[1]  # type: ignore[misc]
                    self._apply_push(scene)
                elif kind == "replace":
                    scene = op[1]  # type: ignore[misc]
                    self._apply_replace(scene)
                elif kind == "clear_and_push":
                    scene = op[1]  # type: ignore[misc]
                    self._apply_clear_and_push(scene)
        finally:
            self._flushing = False

    def _cleanup_exiting_scene(self, scene: Scene) -> None:
        """Run common cleanup for a scene whose ``on_exit()`` has been called.

        Called **after** ``scene.on_exit()``.  Cleans up owned sprites,
        timers, particle emitters, and cancels camera pan tweens.

        Note: the UI tree is NOT cleared here because this method is also
        called when a scene is *pushed over* (it stays on the stack and
        may be revealed later).  Use :meth:`_teardown_exited_scene` for
        scenes that are permanently leaving the stack.
        """
        scene._cleanup_owned_sprites()
        scene._cleanup_owned_timers()
        # Remove any particle emitters the scene created from the game's
        # update set so they stop spawning after the scene is gone.
        scene._cleanup_owned_emitters()
        # Cancel camera pan tweens so they don't hold a strong ref to the
        # camera (and therefore the scene) after the scene exits.
        if scene.camera is not None:
            scene.camera._cancel_pan()

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
                self._cleanup_exiting_scene(old)
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
            old.on_exit()
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
                old.on_exit()
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
        try:
            for s in reversed(self._stack):
                s.on_exit()
                self._cleanup_exiting_scene(s)
                self._teardown_exited_scene(s)
            self._stack.clear()
        finally:
            self._in_on_exit = False
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
