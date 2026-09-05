"""Game — owns the backend, the scene stack and every per-frame system.

::

    game = Game("My Game", resolution=(1280, 800))
    game.run(TitleScene())

``run()`` loops until :meth:`quit` or the window closes; ``tick(dt)``
runs exactly one frame for deterministic tests.
"""

from __future__ import annotations

import logging
import math
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from weakref import WeakSet

from saga2d.backends.base import Event, MouseEvent, WindowEvent
from saga2d.input import InputManager, with_world_coords
from saga2d._scene_stack import SceneStack
from saga2d.scene import Scene
from saga2d.util.timer import TimerManager
from saga2d.util.tween import TweenManager

if TYPE_CHECKING:
    from saga2d.assets import AssetManager
    from saga2d.audio import AudioManager
    from saga2d.backends.base import Backend
    from saga2d.save import SaveManager
    from saga2d.ui.theme import Theme

_logger = logging.getLogger(__name__)


def _headless() -> bool:
    """``SAGA2D_HEADLESS=1`` keeps windows hidden so agents never steal focus."""
    return os.environ.get("SAGA2D_HEADLESS", "").strip() not in ("", "0")


class Game:
    """Parameters:
        title:      Window title.
        resolution: Logical ``(width, height)``; ``None`` fits the screen.
        fullscreen: Open fullscreen.
        backend:    ``"pyglet"``, ``"mock"``, or a backend instance.
        visible:    Show the window (hidden windows still render, for screenshots).
        save_dir:   Directory for save slots (default ``~/.<title>/saves``).
        asset_path: Root of the assets directory (default ``assets``).
        theme:      UI theme; default :class:`Theme()`.
    """

    def __init__(
        self,
        title: str,
        *,
        resolution: tuple[int, int] | None = (1280, 800),
        fullscreen: bool = False,
        backend: str | object = "pyglet",
        visible: bool = True,
        save_dir: Path | str | None = None,
        asset_path: Path | str | None = None,
        theme: Theme | None = None,
    ) -> None:
        import saga2d.rendering.sprite as sprite_mod
        import saga2d.util.tween as tween_mod

        if sprite_mod._current_game is not None:
            raise RuntimeError("A Game instance already exists. Call game._teardown() before creating another.")
        if _headless():
            fullscreen = False
            visible = False

        if backend == "mock":
            from saga2d.backends.mock_backend import MockBackend

            self._backend: Backend = MockBackend()
        elif backend == "pyglet":
            from saga2d.backends.pyglet_backend import PygletBackend

            self._backend = PygletBackend()
        elif hasattr(backend, "poll_events"):
            self._backend = backend  # type: ignore[assignment]
        else:
            raise ValueError(f"Unknown backend {backend!r}. Pass 'mock', 'pyglet', or a backend instance.")

        if resolution is None:
            resolution = self._fit_screen(fullscreen)
        self._title = title
        self._resolution = (int(resolution[0]), int(resolution[1]))
        self._save_dir = Path(save_dir) if save_dir is not None else None
        self._asset_path = Path(asset_path) if asset_path is not None else Path("assets")
        self._theme = theme
        self._assets: AssetManager | None = None
        self._audio: AudioManager | None = None
        self._save_manager: SaveManager | None = None

        self.running = True
        self._scene_stack = SceneStack(self)
        self._input = InputManager()
        self._timer_manager = TimerManager()
        self._tween_manager = TweenManager()
        self._all_sprites: WeakSet[Any] = WeakSet()
        self._animated_sprites: WeakSet[Any] = WeakSet()
        self._action_sprites: WeakSet[Any] = WeakSet()
        self._particle_emitters: set[Any] = set()  # strong: a fire-and-forget burst must live until its particles die
        self._mouse: tuple[float, float] | None = None

        self._backend.create_window(self._resolution[0], self._resolution[1], title, fullscreen, visible)
        tween_mod._tween_manager = self._tween_manager
        sprite_mod._current_game = self

    def _fit_screen(self, fullscreen: bool) -> tuple[int, int]:
        w, h = self._backend.screen_size()
        return (w, h) if fullscreen else (w - 80, h - 120)

    # -- Subsystems ------------------------------------------------------------

    @property
    def backend(self) -> Backend:
        return self._backend

    @property
    def resolution(self) -> tuple[int, int]:
        return self._resolution

    @property
    def width(self) -> int:
        return self._resolution[0]

    @property
    def height(self) -> int:
        return self._resolution[1]

    @property
    def assets(self) -> AssetManager:
        if self._assets is None:
            from saga2d.assets import AssetManager

            self._assets = AssetManager(self._backend, self._asset_path)
        return self._assets

    @assets.setter
    def assets(self, value: AssetManager) -> None:
        self._assets = value

    @property
    def audio(self) -> AudioManager:
        if self._audio is None:
            from saga2d.audio import AudioManager

            self._audio = AudioManager(self._backend, self.assets)
        return self._audio

    @property
    def theme(self) -> Theme:
        if self._theme is None:
            from saga2d.ui.theme import Theme

            self._theme = Theme()
        return self._theme

    @theme.setter
    def theme(self, value: Theme) -> None:
        self._theme = value

    @property
    def input(self) -> InputManager:
        return self._input

    @property
    def save_manager(self) -> SaveManager:
        if self._save_manager is None:
            from saga2d.save import SaveManager

            save_dir = self._save_dir
            if save_dir is None:
                slug = "".join(c if c.isalnum() else "_" for c in self._title.lower()).strip("_")
                save_dir = Path.home() / f".{slug}" / "saves"
            self._save_manager = SaveManager(save_dir)
        return self._save_manager

    @property
    def scene(self) -> Scene | None:
        """The active (top) scene."""
        return self._scene_stack.top()

    @property
    def scenes(self) -> list[Scene]:
        return self._scene_stack.scenes

    # -- Scene stack -----------------------------------------------------------

    def push(self, scene: Scene) -> None:
        self._scene_stack.push(self._check_scene(scene))

    def pop(self) -> None:
        self._scene_stack.pop()

    def replace(self, scene: Scene) -> None:
        self._scene_stack.replace(self._check_scene(scene))

    def clear_and_push(self, scene: Scene) -> None:
        self._scene_stack.clear_and_push(self._check_scene(scene))

    @staticmethod
    def _check_scene(scene: Scene) -> Scene:
        if not isinstance(scene, Scene):
            raise TypeError(f"scene must be a Scene instance, got {type(scene).__name__}")
        return scene

    # -- Save / load -----------------------------------------------------------

    def save(self, slot: int, scene: Scene | None = None) -> None:
        """Write *scene*'s :meth:`Scene.get_save_state` to *slot* (default: the top scene).

        An overlay that offers "Save" passes the scene it covers: its own pop is
        deferred, so it is still the top scene while the handler runs.
        """
        target = scene if scene is not None else self.scene
        if target is not None:
            self.save_manager.save(slot, target.get_save_state(), type(target).__name__)

    def load(self, slot: int, scene: Scene | None = None) -> dict[str, Any] | None:
        """Read *slot* into *scene* (default: the top scene).  Returns the raw save,
        or ``None`` when the slot is empty.  A slot written by another scene class
        is refused: feeding it to the wrong scene would fail half-way through."""
        from saga2d.save import SaveError

        data = self.save_manager.load(slot)
        target = scene if scene is not None else self.scene
        if data is None or target is None:
            return data
        if data["scene_class"] != type(target).__name__:
            raise SaveError(f"Slot {slot} holds a {data['scene_class']} save; cannot load it into {type(target).__name__}")
        target.load_save_state(data["state"])
        return data

    # -- Timers ----------------------------------------------------------------

    def after(self, delay: float, callback: Callable[[], Any]) -> int:
        return self._timer_manager.after(delay, callback)

    def every(self, interval: float, callback: Callable[[], Any]) -> int:
        return self._timer_manager.every(interval, callback)

    def cancel(self, timer_id: int) -> None:
        self._timer_manager.cancel(timer_id)

    # -- Loop ------------------------------------------------------------------

    def quit(self) -> None:
        self.running = False

    def tick(self, dt: float | None = None) -> None:
        """Run one frame: input → update → systems → draw."""
        if dt is None:
            dt = self._backend.get_dt()
        if not math.isfinite(dt) or dt < 0:
            raise ValueError(f"dt must be a finite number >= 0, got {dt!r}")

        raw_events: list[Event] = self._backend.poll_events()
        input_events = []
        for event in raw_events:
            if isinstance(event, WindowEvent):
                if event.type == "close":
                    self.quit()
                continue
            if isinstance(event, MouseEvent) and event.type in ("move", "drag"):
                self._mouse = (float(event.x), float(event.y))
            input_events.append(event)

        stack = self._scene_stack
        stack.begin_phase()
        try:
            for event in self._input.translate(input_events):
                top = stack.top()
                if top is None:
                    break
                self._dispatch(top, event)
        finally:
            stack.end_phase()

        stack.begin_phase()
        try:
            stack.update(dt)
            top = stack.top()
            if top is not None and top._ui is not None:
                top._ui._update_tree(dt)
        finally:
            stack.end_phase()

        for sprite in list(self._action_sprites):
            sprite.update_action(dt)
        for emitter in list(self._particle_emitters):
            emitter.update(dt)
            if not emitter.is_active:
                self._particle_emitters.discard(emitter)
        self._timer_manager.update(dt)
        self._tween_manager.update(dt)
        for sprite in list(self._animated_sprites):
            sprite.update_animation(dt)

        top = stack.top()
        camera = top.camera if top is not None else None
        if camera is not None:
            camera.update(dt, self._mouse)
            ox, oy = camera.offset
            self._backend.set_camera(ox, oy, camera.zoom)
        else:
            self._backend.set_camera(0.0, 0.0, 1.0)

        base = stack.get_base_scene()
        self._backend.begin_frame(base.background_color if base is not None else None)
        try:
            stack.draw()
        finally:
            self._backend.end_frame()

    def _dispatch(self, top: Scene, event: Any) -> None:
        event = with_world_coords(event, top.camera)
        if top._ui is not None:
            top._ui._ensure_layout()
            if top._ui.handle_event(event):
                return
        if top.camera is not None and top.camera.handle_input(event):
            return
        if top._dispatch_key(event):
            return
        if top.handle_input(event):
            return
        if top.pop_on_cancel and event.type == "key_press" and event.key == "escape":
            self.pop()

    def run(self, start_scene: Scene) -> None:
        """Push *start_scene* and loop until :meth:`quit` or window close."""
        if _headless():
            raise RuntimeError("game.run() is disabled while SAGA2D_HEADLESS is set; use game.tick(dt) or saga2d.testing.render_scene().")
        self.push(start_scene)
        try:
            while self.running:
                self.tick()
        finally:
            self._teardown()
            self._backend.quit()

    def _teardown(self) -> None:
        """Release scenes, sprites, timers and the module-level game reference."""
        if not hasattr(self, "_scene_stack"):
            return
        self._timer_manager.cancel_all()
        self._tween_manager.cancel_all()
        self._scene_stack.clear()
        for sprite in list(self._all_sprites):
            sprite.remove()
        self._particle_emitters.clear()
        if self._audio is not None:
            self._audio.stop_music()
        if sys.meta_path is None:
            return
        import saga2d.rendering.sprite as sprite_mod
        import saga2d.util.tween as tween_mod

        if sprite_mod._current_game is self:
            sprite_mod._current_game = None
        if tween_mod._tween_manager is self._tween_manager:
            tween_mod._tween_manager = None

    def __del__(self) -> None:
        try:
            self._teardown()
        except Exception:
            _logger.exception("Error during Game teardown")
