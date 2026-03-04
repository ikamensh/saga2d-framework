"""Game class — top-level object that owns the backend and scene stack.

The Game is created once and drives the main loop.  It accepts a backend
by name (``"mock"``, ``"pyglet"``) or by instance (duck-typed).

Two entry points:

* ``game.run(start_scene)`` — production loop, runs until ``game.quit()``
  or window close.
* ``game.tick(dt=0.016)`` — single frame, for deterministic testing.

Scene stack convenience methods (``push``, ``pop``, ``replace``,
``clear_and_push``) delegate to the internal :class:`SceneStack`.
"""

from __future__ import annotations

import logging
import sys
import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from weakref import WeakSet

from saga2d.backends.base import Event, MouseEvent, WindowEvent
from saga2d.input import _with_world_coords
from saga2d.scene import Scene, SceneStack

if TYPE_CHECKING:
    from saga2d.assets import AssetManager
    from saga2d.audio import AudioManager
    from saga2d.backends.base import Backend
    from saga2d.cursor import CursorManager
    from saga2d.input import InputManager
    from saga2d.rendering.camera import Camera
    from saga2d.save import SaveManager
    from saga2d.ui.hud import HUD
    from saga2d.ui.theme import Theme
    from saga2d.util.timer import TimerHandle

_logger = logging.getLogger(__name__)


class Game:
    """Top-level game object.  Owns the backend, the scene stack, and the
    ``running`` flag.

    Parameters:
        title:      Window title.
        resolution: ``(width, height)`` logical coordinate space.
        fullscreen: Whether to open in fullscreen mode.
        backend:    ``"mock"`` or ``"pyglet"`` (string), or a backend
                    instance that satisfies the
                    :class:`~saga2d.backends.base.Backend` protocol.
        visible:    Whether the window is initially visible (default
                    ``True``).  Pass ``False`` to create a hidden window
                    (useful for headless rendering or testing).
        save_dir:   Directory for save files.  When provided, the lazy
                    ``game.save_manager`` uses this path instead of the
                    default ``~/.{title_slug}/saves/``.
        asset_path: Base directory for assets.  When provided, the lazy
                    ``game.assets`` uses this path instead of ``"assets"``.
                    Setting ``game.assets = AssetManager(...)`` explicitly
                    still overrides this.
    """

    def __init__(
        self,
        title: str,
        *,
        resolution: tuple[int, int] = (1920, 1080),
        fullscreen: bool = True,
        backend: str | object = "pyglet",
        visible: bool = True,
        save_dir: Path | str | None = None,
        asset_path: Path | str | None = None,
    ) -> None:
        import saga2d.rendering.sprite as _sprite_mod

        if _sprite_mod._current_game is not None:
            raise RuntimeError(
                "A Game instance already exists. "
                "Call game._teardown() or game.quit() before creating a new one."
            )

        self._title = title
        self._save_dir_override = Path(save_dir) if save_dir is not None else None
        self._asset_path = Path(asset_path) if asset_path is not None else None
        self._resolution = resolution
        self._fullscreen = fullscreen
        self._visible = visible

        # --- Backend selection ------------------------------------------------
        self._backend: Backend
        if backend == "mock":
            from saga2d.backends.mock_backend import MockBackend

            self._backend = MockBackend(resolution[0], resolution[1])
        elif backend == "pyglet":
            from saga2d.backends.pyglet_backend import PygletBackend

            self._backend = PygletBackend()
        elif hasattr(backend, "poll_events"):  # duck-type check
            self._backend = backend  # type: ignore[assignment]
        else:
            raise ValueError(
                f"Unknown backend {backend!r}. "
                "Pass 'mock', 'pyglet', or a backend instance."
            )

        # --- Core state -------------------------------------------------------
        self._scene_stack = SceneStack(self)
        self.running: bool = True
        self._assets: AssetManager | None = None
        self._audio: AudioManager | None = None
        self._theme: Theme | None = None
        self._cursor: CursorManager | None = None
        self._save_manager: SaveManager | None = None
        self._hud: HUD | None = None
        self._animated_sprites: WeakSet[Any] = WeakSet()
        self._all_sprites: WeakSet[Any] = WeakSet()
        self._action_sprites: WeakSet[Any] = WeakSet()
        self._particle_emitters: weakref.WeakSet[Any] = weakref.WeakSet()

        # Latest mouse position in logical screen coords (for camera edge scroll).
        self._mouse_x: float | None = None
        self._mouse_y: float | None = None

        import saga2d.util.tween as _tween_mod
        from saga2d.input import InputManager
        from saga2d.util.timer import TimerManager

        self._input = InputManager()

        self._timer_manager = TimerManager()
        self._tween_manager = _tween_mod.TweenManager()

        # Tell the backend to (notionally) create a window.  The mock backend
        # stores the resolution; the pyglet backend opens a real window.
        self._backend.create_window(
            resolution[0],
            resolution[1],
            title,
            fullscreen,
            visible,
        )

        # Only set globals after window creation succeeds — avoids leaving
        # stale references if create_window() raises.
        _tween_mod._tween_manager = self._tween_manager
        import saga2d.rendering.sprite as _sprite_mod

        _sprite_mod._current_game = self

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def backend(self) -> object:
        """The underlying backend (for test assertions).

        Not part of the public game-code API, but necessary for test
        fixtures that need ``mock_game.backend.inject_key(...)`` etc.
        """
        return self._backend

    @property
    def assets(self) -> AssetManager:
        """The :class:`~saga2d.assets.AssetManager`, created lazily.

        Defaults to ``AssetManager(backend, Path("assets"),
        scale_factor=backend.scale_factor)``.  Set ``game.assets``
        directly to override the base path or scale factor.
        """
        if self._assets is None:
            from saga2d.assets import AssetManager as _AM

            scale = getattr(self._backend, "scale_factor", 1.0)
            base_path = (
                self._asset_path if self._asset_path is not None else Path("assets")
            )
            self._assets = _AM(
                self._backend,
                base_path=base_path,
                scale_factor=scale,
            )
        return self._assets

    @assets.setter
    def assets(self, value: AssetManager) -> None:
        self._assets = value

    @property
    def audio(self) -> AudioManager:
        """The :class:`~saga2d.audio.AudioManager`, created lazily.

        Created on first access using the backend and
        :attr:`assets` manager.
        """
        if self._audio is None:
            from saga2d.audio import AudioManager as _AM

            self._audio = _AM(self._backend, self.assets)
        return self._audio

    @audio.setter
    def audio(self, value: AudioManager) -> None:
        self._audio = value

    @property
    def theme(self) -> Theme:
        """The :class:`~saga2d.ui.theme.Theme`, created lazily.

        Components access the theme via ``self._game.theme`` to resolve
        styles.  Set ``game.theme`` to override the default theme.
        """
        if self._theme is None:
            from saga2d.ui.theme import Theme as _Theme

            self._theme = _Theme()
        return self._theme

    @theme.setter
    def theme(self, value: Theme) -> None:
        self._theme = value

    @property
    def cursor(self) -> "CursorManager":
        """The :class:`~saga2d.cursor.CursorManager`, created lazily.

        Use to register and switch cursors::

            game.cursor.register("attack", "ui/cursor_attack", hotspot=(8, 8))
            game.cursor.set("attack")
            game.cursor.set("default")  # restore system cursor
        """
        if self._cursor is None:
            from saga2d.cursor import CursorManager as _CM

            self._cursor = _CM(self._backend, self.assets)
        return self._cursor

    @property
    def input(self) -> InputManager:
        """The :class:`~saga2d.input.InputManager`.

        Use to rebind actions at runtime::

            game.input.bind("attack", "a")
            game.input.unbind("cancel")
        """
        return self._input

    @property
    def save_manager(self) -> "SaveManager":
        """The :class:`~saga2d.save.SaveManager`, created lazily.

        Save files are stored in ``save_dir`` (if provided at construction)
        or ``~/.{game_title_slug}/saves/`` by default.
        """
        if self._save_manager is None:
            from saga2d.save import SaveManager as _SM

            if self._save_dir_override is not None:
                save_dir = self._save_dir_override
            else:
                # Derive slug from title: lowercase, replace non-alnum with _.
                slug = "".join(
                    c if c.isalnum() else "_" for c in self._title.lower()
                ).strip("_")
                save_dir = Path.home() / f".{slug}" / "saves"
            self._save_manager = _SM(save_dir)
        return self._save_manager

    @property
    def hud(self) -> "HUD":
        """The :class:`~saga2d.ui.hud.HUD` layer, created lazily.

        Persistent UI that renders above the base scene but below overlay
        scenes.  Visibility is controlled by ``hud.visible`` and the top
        scene's ``show_hud`` attribute.

        Usage::

            game.hud.add(Label("Gold: 0", anchor=Anchor.TOP_RIGHT))
        """
        if self._hud is None:
            from saga2d.ui.hud import HUD as _HUD

            self._hud = _HUD(self)
        return self._hud

    # ------------------------------------------------------------------
    # Save / Load convenience methods
    # ------------------------------------------------------------------

    def save(self, slot: int) -> None:
        """Save the top scene's state to *slot*.

        Calls :meth:`Scene.get_save_state` on the current top scene and
        writes the result to disk via the :class:`SaveManager`.

        Does nothing if the scene stack is empty.
        """
        top = self._scene_stack.top()
        if top is None:
            return
        state = top.get_save_state()
        scene_class_name = type(top).__name__
        self.save_manager.save(slot, state, scene_class_name)

    def load(self, slot: int) -> dict[str, Any] | None:
        """Load save data from *slot* and restore the top scene's state.

        Reads the save file and calls
        :meth:`Scene.load_save_state(data["state"])
        <Scene.load_save_state>` on the current top scene (if one exists
        and the save file contains a ``"state"`` key).

        Returns the full save dict (``version``, ``timestamp``,
        ``scene_class``, ``state``) or ``None`` if the slot is empty.

        If the game needs to reconstruct a *different* scene class based
        on the save data, use ``game.save_manager.load(slot)`` directly,
        create the scene, push/replace it, then call
        ``scene.load_save_state(data["state"])`` manually.
        """
        data = self.save_manager.load(slot)
        if data is not None:
            top = self._scene_stack.top()
            if top is not None and "state" in data:
                top.load_save_state(data["state"])
        return data

    # ------------------------------------------------------------------
    # Scene stack convenience methods (delegate to SceneStack)
    # ------------------------------------------------------------------

    def push(self, scene: Scene) -> None:
        """Push *scene* onto the stack.  Current top gets ``on_exit``,
        new scene gets ``on_enter``."""
        if not isinstance(scene, Scene):
            raise TypeError(
                f"scene must be a Scene instance, got {type(scene).__name__}"
            )
        self._scene_stack.push(scene)

    def pop(self) -> None:
        """Pop the top scene.  It gets ``on_exit``; the new top (if any)
        gets ``on_reveal``."""
        self._scene_stack.pop()

    def replace(self, scene: Scene) -> None:
        """Replace the top scene.  Old top gets ``on_exit``, new scene
        gets ``on_enter``.  No ``on_reveal``."""
        if not isinstance(scene, Scene):
            raise TypeError(
                f"scene must be a Scene instance, got {type(scene).__name__}"
            )
        self._scene_stack.replace(scene)

    def clear_and_push(self, scene: Scene) -> None:
        """Clear the entire stack (all scenes get ``on_exit``), then push
        *scene*."""
        if not isinstance(scene, Scene):
            raise TypeError(
                f"scene must be a Scene instance, got {type(scene).__name__}"
            )
        self._scene_stack.clear_and_push(scene)

    # ------------------------------------------------------------------
    # Convenience screen methods
    # ------------------------------------------------------------------

    def show_sequence(
        self,
        screens: list[Any],
        *,
        on_complete: Callable[[], Any] | None = None,
    ) -> None:
        """Push a chain of screens that auto-advance.

        Each screen in *screens* is shown in order.  When one is
        dismissed, the next is pushed automatically.  After the last
        screen is dismissed, *on_complete* is called.

        Uses an internal ``_SequenceRunner`` scene that sits below the
        message screens and uses :meth:`on_reveal` to chain pushes.

        Parameters:
            screens:     List of :class:`MessageScreen` instances.
            on_complete: Callback fired after the last screen is dismissed.
        """
        from saga2d.ui.screens import _SequenceRunner

        runner = _SequenceRunner(screens, on_complete=on_complete)
        self.push(runner)

    def push_settings(self) -> None:
        """Push the built-in settings screen onto the scene stack.

        The settings screen provides volume controls for audio channels
        (master, music, sfx, ui) and key rebinding for all registered
        input actions.  It is an internal transparent overlay that pauses
        the scene below and hides the HUD.

        Press Escape or click Back to dismiss.
        """
        from saga2d.ui.screens import _SettingsScene

        self.push(_SettingsScene())

    # ------------------------------------------------------------------
    # Timers
    # ------------------------------------------------------------------

    def after(self, delay: float, callback: Callable[[], Any]) -> TimerHandle:
        """Schedule a one-shot callback after *delay* seconds.

        Returns a TimerHandle for cancellation and chaining.
        """
        return self._timer_manager.after(delay, callback)

    def every(self, interval: float, callback: Callable[[], Any]) -> TimerHandle:
        """Schedule a repeating callback every *interval* seconds.

        Returns a TimerHandle for cancellation and chaining.
        """
        return self._timer_manager.every(interval, callback)

    def cancel(self, timer_id: int | TimerHandle) -> None:
        """Cancel a timer by ID or TimerHandle. If a TimerHandle is given,
        cancels the entire chain.
        """
        self._timer_manager.cancel(timer_id)

    def cancel_tween(self, tween_id: int) -> None:
        """Cancel a tween by ID."""
        self._tween_manager.cancel(tween_id)

    # ------------------------------------------------------------------
    # Quit / Teardown
    # ------------------------------------------------------------------

    def quit(self) -> None:
        """Set ``running`` to False.

        ``run()`` will exit its loop on the next iteration.  ``tick()``
        callers can inspect ``game.running`` after each tick.
        """
        self.running = False

    def _teardown(self) -> None:
        """Release resources and clear module-level references.

        Called automatically by :meth:`run` on exit and by ``__del__``
        as a safety net.  Safe to call multiple times.

        Drains the scene stack (calling ``on_exit`` / cleanup for each
        scene), clears all sprite and emitter tracking sets, and nulls
        out subsystem references so the entire game object graph becomes
        eligible for garbage collection.
        """
        # Cancel all outstanding timers and tweens so their callbacks
        # (which may capture scenes, sprites, etc.) can be GC'd.
        self._timer_manager.cancel_all()
        self._tween_manager.cancel_all()

        # Drain the scene stack: call on_exit + cleanup for every scene
        # so owned sprites, timers, and emitters are released.
        while self._scene_stack._stack:
            scene = self._scene_stack._stack.pop()
            try:
                scene.on_exit()
            except Exception:
                _logger.exception(
                    "Error in on_exit() during teardown for %s",
                    type(scene).__name__,
                )
            try:
                self._scene_stack._cleanup_exiting_scene(scene)
                self._scene_stack._teardown_exited_scene(scene)
            except Exception:
                _logger.exception(
                    "Error in cleanup during teardown for %s",
                    type(scene).__name__,
                )

        # Clear sprite and emitter tracking sets so remaining objects
        # (e.g. sprites not owned by any scene) can be GC'd.
        self._all_sprites.clear()
        self._animated_sprites.clear()
        self._action_sprites.clear()
        self._particle_emitters.clear()

        # Null out subsystem references to break reference cycles and
        # allow GC of the entire game graph.
        self._hud = None
        self._assets = None
        if self._audio is not None:
            self._audio._teardown()
        self._audio = None
        self._cursor = None
        self._save_manager = None
        self._theme = None

        # Clear module-level globals only if they still point to *this*
        # Game instance, so concurrent Game objects don't clobber each
        # other (relevant in test suites).
        if sys.meta_path is None:
            return  # Python shutting down; imports would fail
        import saga2d.rendering.sprite as _sprite_mod
        import saga2d.util.tween as _tween_mod

        if _sprite_mod._current_game is self:
            _sprite_mod._current_game = None
        if _tween_mod._tween_manager is self._tween_manager:
            _tween_mod._tween_manager = None

        import saga2d.rendering.color_swap as _cs_mod

        _cs_mod._clear_palettes()

    def __del__(self) -> None:
        # Best-effort cleanup if the caller forgot to call run() or
        # the Game is collected without a clean shutdown.
        try:
            self._teardown()
        except Exception:
            _logger.exception("Error during Game.__del__ teardown")

    # ------------------------------------------------------------------
    # Tick — single frame (primary test entry point)
    # ------------------------------------------------------------------

    def tick(self, dt: float | None = None) -> None:
        """Run exactly **one** iteration of the game loop.

        Parameters:
            dt: Delta time in seconds.  Pass explicitly for deterministic
                tests (e.g. ``dt=0.016`` for 60 fps).  If ``None``, the
                backend's clock is queried via ``get_dt()``.

        Order of operations (matches architecture doc)::

            poll_events → translate → handle_input (deferred) → flush
            → update (deferred) → flush → timers → tweens → animations
            → camera update → camera sprite sync → begin_frame → draw
            → end_frame → restore sprite positions
        """
        if dt is None:
            dt = self._backend.get_dt()

        # -- Input phase ---------------------------------------------------
        raw_events: list[Event] = self._backend.poll_events()

        # Handle window events before translation.  Track latest mouse
        # position from move/drag events for camera edge scroll.
        non_window: list[Event] = []
        for event in raw_events:
            if isinstance(event, WindowEvent) and event.type == "close":
                self.quit()
            elif not isinstance(event, WindowEvent):
                non_window.append(event)
                # Track mouse position from move and drag events.
                if isinstance(event, MouseEvent) and event.type in (
                    "move",
                    "drag",
                ):
                    self._mouse_x = float(event.x)
                    self._mouse_y = float(event.y)

        # Translate raw key/mouse events to InputEvents with action mapping.
        input_events = self._input.translate(non_window)

        self._scene_stack.begin_tick()
        try:
            for ev in input_events:
                top = self._scene_stack.top()
                if top is not None:
                    # Populate world_x/world_y before any handler sees the event.
                    camera = getattr(top, "camera", None)
                    translated_event = _with_world_coords(ev, camera)

                    # HUD gets first crack at input.
                    if (
                        self._hud is not None
                        and self._hud._should_draw(top.show_hud)
                        and self._hud._handle_event(translated_event)
                    ):
                        continue
                    # Scene UI gets second crack.
                    if top._ui is not None:
                        top._ui._ensure_layout()
                        if top._ui.handle_event(translated_event):
                            continue
                    # Camera key scroll gets third crack (before scene).
                    if camera is not None and camera.handle_input(translated_event):
                        continue
                    # Key bindings registered via bind_key() get fourth crack.
                    if top._dispatch_key_bindings(translated_event):
                        continue
                    # Scene handle_input gets last crack.
                    consumed = top.handle_input(translated_event)
                    # pop_on_cancel: auto-pop if scene declares it and cancel
                    # was not already consumed by handle_input or a binding.
                    if (
                        not consumed
                        and top.pop_on_cancel
                        and translated_event.type == "key_press"
                        and translated_event.action == "cancel"
                    ):
                        self.pop()
        finally:
            self._scene_stack.flush_pending_ops()

        # -- Update phase --------------------------------------------------
        self._scene_stack.begin_tick()
        try:
            self._scene_stack.update(dt)

            # Update the active scene's UI tree (typewriter, tooltips, etc.).
            top = self._scene_stack.top()
            if top is not None and top._ui is not None:
                top._ui._update_tree(dt)

            # Update the HUD's UI tree.
            if self._hud is not None and top is not None:
                if self._hud._should_draw(top.show_hud):
                    self._hud._update(dt)
        finally:
            self._scene_stack.flush_pending_ops()

        # -- Action phase --------------------------------------------------
        self._update_actions(dt)

        # -- Particle phase ------------------------------------------------
        self._update_particles(dt)

        # -- Timer phase ---------------------------------------------------
        self._timer_manager.update(dt)

        # -- Tween phase ---------------------------------------------------
        self._tween_manager.update(dt)

        # -- Animation phase -----------------------------------------------
        self._update_animations(dt)

        # -- Draw phase ----------------------------------------------------
        # If the active scene has a camera, update it and apply sprite
        # offsets + frustum culling before drawing.
        top = self._scene_stack.top()
        camera = getattr(top, "camera", None) if top is not None else None

        if camera is not None:
            camera.update(dt, self._mouse_x, self._mouse_y)
            saved = self._sync_sprites_to_camera(camera)
        else:
            saved = None

        base = self._scene_stack.get_base_scene()
        clear_color = None
        if base is not None:
            bc = getattr(base.__class__, "background_color", None)
            if bc is not None and len(bc) >= 3:
                clear_color = bc

        self._backend.begin_frame(clear_color)
        try:
            self._scene_stack.draw()
        finally:
            self._backend.end_frame()
            if saved is not None:
                self._restore_sprites(saved)

    # ------------------------------------------------------------------
    # Action update
    # ------------------------------------------------------------------

    def _update_actions(self, dt: float) -> None:
        """Advance all sprite actions.

        Iterates a *copy* of the set because action callbacks may add or
        remove sprites (mutating the set during iteration).
        """
        for sprite in list(self._action_sprites):
            sprite.update_action(dt)

    # ------------------------------------------------------------------
    # Particle update
    # ------------------------------------------------------------------

    def _update_particles(self, dt: float) -> None:
        """Advance all particle emitters.

        Iterates a *copy* of the set because emitter updates may spawn or
        remove sprites (mutating game sets during iteration).  Inactive
        emitters (done spawning, no living particles) are deregistered.
        """
        for emitter in list(self._particle_emitters):
            emitter.update(dt)
            if not emitter.is_active:
                self._particle_emitters.discard(emitter)

    # ------------------------------------------------------------------
    # Animation update
    # ------------------------------------------------------------------

    def _update_animations(self, dt: float) -> None:
        """Advance all animated sprites.

        Iterates a *copy* of the set because ``on_complete`` callbacks may
        add or remove sprites (mutating the set during iteration).
        """
        for sprite in list(self._animated_sprites):
            sprite.update_animation(dt)

    # ------------------------------------------------------------------
    # Camera render sync
    # ------------------------------------------------------------------

    def _sync_sprites_to_camera(
        self,
        camera: Camera,
    ) -> list[tuple[Any, int, int, bool]]:
        """Shift all sprite backend positions by the camera offset.

        For each live sprite, compute the camera-adjusted screen position
        and push it to the backend.  Sprites entirely outside the viewport
        are temporarily hidden (frustum culling).

        Returns a list of ``(sprite, orig_x, orig_y, orig_visible)`` tuples
        so positions can be restored after drawing.
        """
        from saga2d.rendering.sprite import _anchor_offset

        cam_x = camera._x + camera.shake_offset_x
        cam_y = camera._y + camera.shake_offset_y
        vw = camera._vw
        vh = camera._vh

        saved: list[tuple[Any, int, int, bool]] = []

        for sprite in list(self._all_sprites):
            # Compute the draw corner (world-space top-left of the image).
            anchor_dx, anchor_dy = _anchor_offset(
                sprite._anchor,
                sprite._img_w,
                sprite._img_h,
            )
            world_draw_x = sprite._x - anchor_dx
            world_draw_y = sprite._y - anchor_dy

            # Apply camera offset → screen-space draw corner.
            screen_x = int(world_draw_x - cam_x)
            screen_y = int(world_draw_y - cam_y)

            # Frustum culling: hide sprites entirely outside the viewport.
            # Use image dimensions as margin.
            img_w = sprite._img_w
            img_h = sprite._img_h
            in_view = (
                screen_x + img_w > 0
                and screen_x < vw
                and screen_y + img_h > 0
                and screen_y < vh
            )

            # Determine effective visibility: user-set _visible AND in-view.
            effective_visible = sprite._visible and in_view

            # Save original backend state for restoration.
            rec = (
                self._backend.sprites[sprite._sprite_id]
                if hasattr(self._backend, "sprites")
                else None
            )
            if rec is not None:
                saved.append((sprite, rec["x"], rec["y"], rec["visible"]))
            else:
                # For non-mock backends, save the pre-camera draw coords.
                orig_dx = int(sprite._x - anchor_dx)
                orig_dy = int(sprite._y - anchor_dy)
                saved.append((sprite, orig_dx, orig_dy, sprite._visible))

            # Push camera-adjusted position to the backend.
            self._backend.update_sprite(
                sprite._sprite_id,
                screen_x,
                screen_y,
                opacity=sprite._opacity,
                visible=effective_visible,
                tint=sprite.tint,
            )

        return saved

    def _restore_sprites(
        self,
        saved: list[tuple[Any, int, int, bool]],
    ) -> None:
        """Restore sprite backend positions after the camera-adjusted draw.

        This undoes the camera offset so that sprites' backend state reflects
        their world positions again, ready for the next frame's eager syncs.
        """
        for sprite, orig_x, orig_y, orig_visible in saved:
            if sprite._removed:
                continue
            self._backend.update_sprite(
                sprite._sprite_id,
                orig_x,
                orig_y,
                opacity=sprite._opacity,
                visible=orig_visible,
                tint=sprite.tint,
            )

    # ------------------------------------------------------------------
    # Run — production game loop
    # ------------------------------------------------------------------

    def run(self, start_scene: Scene) -> None:
        """Enter the main loop.  Pushes *start_scene* and loops until
        ``game.quit()`` is called or the window is closed.

        Each iteration calls :meth:`tick` (which internally handles
        ``poll_events``, ``get_dt``, input dispatch, update, and draw).
        After the loop exits the backend is torn down via ``quit()``.

        This is the production entry point.  For testing, use
        :meth:`tick` instead.
        """
        self.push(start_scene)

        try:
            while self.running:
                self.tick()
        finally:
            self._teardown()
            self._backend.quit()
