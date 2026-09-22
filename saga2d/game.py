"""Game — owns the backend, the scene stack and every per-frame system.

::

    game = Game("My Game", resolution=(1280, 800))
    game.run(TitleScene())

``run()`` loops until :meth:`quit` or the window closes; ``tick(dt)``
runs exactly one frame for deterministic tests. Call :meth:`close` after
driving frames yourself; ``run()`` closes automatically.
"""

from __future__ import annotations

import logging
import math
import os
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
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
    from saga2d.settings import Settings
    from saga2d.ui.theme import Theme

_logger = logging.getLogger(__name__)

#: A string is allowed to touch its region's edge; a pixel of rounding is not a bug.
_TEXT_SLACK = 1.0
#: The tallest canvas ``resolution=None`` chooses, in desktop units; layouts are made for 720 to about this.
MAX_FITTED_HEIGHT = 1440


@dataclass(frozen=True)
class TextOverflow:
    """One string that did not fit the rectangle it was drawn into."""

    text: str
    region: str
    left: float
    top: float
    width: float
    height: float
    region_left: float
    region_top: float
    region_width: float
    region_height: float

    @property
    def over(self) -> tuple[float, float, float, float]:
        """How far it spills past each edge: (left, top, right, bottom); 0 where it fits."""
        return (max(0.0, self.region_left - self.left),
                max(0.0, self.region_top - self.top),
                max(0.0, self.left + self.width - (self.region_left + self.region_width)),
                max(0.0, self.top + self.height - (self.region_top + self.region_height)))

    def __str__(self) -> str:
        left, top, right, bottom = self.over
        spills = ", ".join(f"{name} by {value:.0f}px" for name, value in
                           (("left", left), ("top", top), ("right", right), ("bottom", bottom)) if value > 0)
        return (f"{self.text!r} at ({self.left:.0f}, {self.top:.0f}) {self.width:.0f}x{self.height:.0f} "
                f"runs out of {self.region} ({self.region_left:.0f}, {self.region_top:.0f}) "
                f"{self.region_width:.0f}x{self.region_height:.0f}: {spills}")


def _check_text_by_default() -> bool:
    """``SAGA2D_CHECK_TEXT=0`` turns the check off; anything else leaves it on.

    It costs one cached text measurement per drawn string, which the label cache
    has usually done already, so it is on while you play as well as while you
    test: a label that has outgrown its card should be a line in the terminal the
    first time it is drawn, not something a screenshot catches a week later.
    """
    return os.environ.get("SAGA2D_CHECK_TEXT", "").strip() not in ("0", "false", "no")


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
        icon:       Square PNG of at least 1024 px the desktop draws the game
                    under (see :mod:`saga2d.desktop`); the engine's mark
                    without one. Ship it inside the game package's ``assets``,
                    which is what a built game carries.
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
        icon: Path | str | None = None,
    ) -> None:
        import saga2d.rendering.sprite as sprite_mod
        import saga2d.util.tween as tween_mod
        from saga2d.packaging import icon as packaging_icon  # the engine's mark, and the shaping every icon goes through

        if sprite_mod._current_game is not None:
            raise RuntimeError("A Game instance already exists. Call game.close() before creating another.")
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

        window_size = None
        if resolution is None:
            resolution, window_size = self._fit_screen(fullscreen)
        self._title = title
        self._resolution = (int(resolution[0]), int(resolution[1]))
        self._save_dir = Path(save_dir) if save_dir is not None else None
        self._asset_path = Path(asset_path) if asset_path is not None else Path("assets")
        self._theme = theme
        self._assets: AssetManager | None = None
        self._audio: AudioManager | None = None
        self._save_manager: SaveManager | None = None
        self._settings: Settings | None = None

        self.running = True
        self._window_visible = visible
        self._window_focused = False
        self._scene_stack = SceneStack(self)
        self._input = InputManager()
        self._timer_manager = TimerManager()
        self._tween_manager = TweenManager()
        self._all_sprites: WeakSet[Any] = WeakSet()
        self._animated_sprites: WeakSet[Any] = WeakSet()
        self._action_sprites: WeakSet[Any] = WeakSet()
        self._particle_emitters: set[Any] = set()  # strong: a fire-and-forget burst must live until its particles die
        self._mouse: tuple[float, float] | None = None
        #: Strings drawn outside the rectangle they were drawn into, this frame.
        self.text_overflows: list[TextOverflow] = []
        self.check_text_fit = _check_text_by_default()
        self._warned_text: set[str] = set()

        self._backend.create_window(self._resolution[0], self._resolution[1], title, fullscreen, visible, window_size)
        self._backend.set_icon(str(icon) if icon is not None else str(packaging_icon.DEFAULT))
        tween_mod._tween_manager = self._tween_manager
        sprite_mod._current_game = self

    def _fit_screen(self, fullscreen: bool) -> tuple[tuple[int, int], tuple[int, int]]:
        """The canvas and the window for ``resolution=None``: the window fits the desktop, the canvas stays in range.

        A desktop larger than layouts are made for (3840×2160 at 100 %) would turn into a wall-sized
        canvas with a tiny HUD; its canvas is the window divided by a zoom raised in quarter steps
        until the canvas is at most ``MAX_FITTED_HEIGHT`` units high.
        """
        w, h = self._backend.screen_size()
        window = (w, h) if fullscreen else (w - 80, h - 120)
        zoom = max(1.0, math.ceil(window[1] / MAX_FITTED_HEIGHT * 4) / 4)
        return (int(window[0] / zoom), int(window[1] / zoom)), window

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
    def fullscreen(self) -> bool:
        """Whether the native window is currently fullscreen."""
        return self._backend.fullscreen

    @property
    def window_size(self) -> tuple[int, int]:
        """Current native content size, excluding decorations and HiDPI backing scale.

        This can change through the OS or display methods. ``resolution`` remains
        the game's fixed logical canvas; mismatched aspect ratios are letterboxed.
        """
        return self._backend.window_size

    @property
    def windowed_size(self) -> tuple[int, int]:
        """Actual windowed size, or the size restored when leaving fullscreen.

        Snapshot this with ``fullscreen`` before previewing display changes.
        """
        return self._backend.windowed_size

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
    def mouse_position(self) -> tuple[float, float] | None:
        """Last pointer position in logical screen pixels, or None before any pointer event."""
        return self._mouse

    @property
    def data_dir(self) -> Path:
        """The parent of the save directory, or ``~/.<title>`` by default."""
        if self._save_dir is not None:
            return self._save_dir.parent
        slug = "".join(c if c.isalnum() else "_" for c in self._title.lower()).strip("_")
        return Path.home() / f".{slug}"

    def settings(self, defaults: Mapping[str, Any], *,
                 validator: Callable[[Mapping[str, Any]], None] | None = None) -> Settings:
        """Shared preferences in ``<data_dir>/settings.json``.

        Defaults and the optional game validator are configured on first use;
        later calls return that same object. Check its ``error`` after loading.
        """
        if self._settings is None:
            from saga2d.settings import Settings

            self._settings = Settings(self.data_dir / "settings.json", defaults, validator=validator)
        return self._settings

    @property
    def save_manager(self) -> SaveManager:
        if self._save_manager is None:
            from saga2d.save import SaveManager

            self._save_manager = SaveManager(self._save_dir if self._save_dir is not None else self.data_dir / "saves")
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

    def pop_to(self, scene: Scene) -> None:
        """Close all scenes above *scene*, then reveal that retained scene once.

        Like ``pop``, this is deferred during input, update and lifecycle hooks.
        The target is matched by identity when the operation applies; an absent
        target raises ``ValueError`` before removal. Already-top is a no-op.
        """
        self._scene_stack.pop_to(self._check_scene(scene))

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

    def save(self, slot: int | str, scene: Scene | None = None) -> None:
        """Write *scene*'s :meth:`Scene.get_save_state` to *slot* (default: the top scene),
        with :meth:`Scene.get_save_summary` for save browsers.

        An overlay that offers "Save" passes the scene it covers: its own pop is
        deferred, so it is still the top scene while the handler runs.
        """
        target = scene if scene is not None else self.scene
        if target is not None:
            self.save_manager.save(slot, target.get_save_state(), type(target).__name__, summary=target.get_save_summary())

    def load(self, slot: int | str, scene: Scene | None = None) -> dict[str, Any] | None:
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
        """Request the running loop to stop; ``run()`` then closes the game."""
        self.running = False

    def close(self) -> None:
        """Release scenes and resources, then close the backend window.

        Call from the owner of an explicitly ticked game when finished.
        ``run()`` does this automatically. Scene cleanup failures propagate,
        but the backend still closes and a new Game can be created.
        """
        try:
            self._teardown()
        finally:
            self._backend.quit()

    def set_fullscreen(self, fullscreen: bool) -> None:
        """Enter desktop fullscreen, or restore the last actual windowed size."""
        if type(fullscreen) is not bool:
            raise ValueError("fullscreen must be a boolean")
        if fullscreen and _headless():
            raise RuntimeError("Fullscreen is unavailable while SAGA2D_HEADLESS is set")
        self._backend.set_fullscreen(fullscreen)

    def set_window_size(self, size: tuple[int, int]) -> None:
        """Select a windowed content size, leaving fullscreen if necessary.

        Dimensions must be positive integers. The OS can constrain the requested
        size; read ``window_size`` for the actual result. This never resizes the
        logical canvas or changes scene/UI coordinates.
        """
        if (not isinstance(size, (tuple, list)) or len(size) != 2
                or any(type(value) is not int or value <= 0 for value in size)):
            raise ValueError("window size must be a pair of positive integers")
        self._backend.set_window_size(*size)

    def tick(self, dt: float | None = None) -> None:
        """Run one frame: input → update → systems → draw.

        A scene transition ends dispatch of the current input batch, so queued
        double clicks cannot repeat a completed action or hit the next scene.
        Held-key state still accounts for every press and release in the batch.

        Losing the window (deactivate or hide) clears every transient input
        state after dispatch — pointer capture, held keys, the pointer
        position — because what happens while unfocused never arrives: a
        release elsewhere would otherwise leave a pressed control, a stuck
        key, or a view scrolling on a stale pointer for the whole alt-tab.
        """
        if dt is None:
            dt = self._backend.get_dt()
        if not math.isfinite(dt) or dt < 0:
            raise ValueError(f"dt must be a finite number >= 0, got {dt!r}")

        raw_events: list[Event] = self._backend.poll_events()
        input_events = []
        lost_window_focus = False
        for event in raw_events:
            if isinstance(event, WindowEvent):
                if event.type == "close":
                    self.quit()
                elif event.type in ('activate', 'deactivate'):
                    self._window_focused = event.type == 'activate'
                    lost_window_focus = lost_window_focus or not self._window_focused
                elif event.type in ('show', 'hide'):
                    self._window_visible = event.type == 'show'
                    lost_window_focus = lost_window_focus or not self._window_visible
                continue
            if isinstance(event, MouseEvent):
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
                if stack.transition_pending:
                    break
        finally:
            stack.end_phase()

        # A press in this batch can acquire capture after the OS focus event
        # was collected. Clear after dispatch so nothing held survives
        # focus loss: capture, held keys, and the pointer position.
        if lost_window_focus:
            self._input.release_all()
            self._mouse = None
            for scene in self.scenes:
                if scene._ui is not None:
                    scene._ui._cancel_pointer()
                if scene.camera is not None:
                    scene.camera.release_keys()

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
        if self._audio is not None:
            self._audio.update(dt)
        for sprite in list(self._animated_sprites):
            sprite.update_animation(dt)

        top = stack.top()
        camera = top.camera if top is not None else None
        if camera is not None:
            camera.update(dt, self._mouse)
        else:
            # Screen-space overlays retain the visible map's transform without
            # sending their pointer/key input to the covered camera.
            camera = next((scene.camera for scene in reversed(stack.scenes[stack.base_index():])
                           if scene.camera is not None), None)
        if camera is not None:
            ox, oy = camera.offset
            self._backend.set_camera(ox, oy, camera.zoom)
        else:
            self._backend.set_camera(0.0, 0.0, 1.0)

        base = stack.get_base_scene()
        self.text_overflows = []
        self._backend.begin_frame(base.background_color if base is not None else None)
        try:
            stack.draw()
        finally:
            self._backend.end_frame()

    def _note_text_overflow(self, text: str, left: float, top: float, width: float, height: float,
                            region: str, region_left: float, region_top: float,
                            region_width: float, region_height: float) -> None:
        """Record — and, the first time, warn about — a string that did not fit."""
        if (left >= region_left - _TEXT_SLACK and top >= region_top - _TEXT_SLACK
                and left + width <= region_left + region_width + _TEXT_SLACK
                and top + height <= region_top + region_height + _TEXT_SLACK):
            return
        overflow = TextOverflow(text, region, left, top, width, height,
                                region_left, region_top, region_width, region_height)
        self.text_overflows.append(overflow)
        key = f"{text}|{region}"
        if key not in self._warned_text:
            self._warned_text.add(key)
            _logger.warning("saga2d: text does not fit — %s", overflow)

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

    def run(self, start_scene: Scene, *, fps: float = 60) -> None:
        """Run at most *fps* frames per second, sleeping between completed frames.

        Unfocused or hidden windows run at no more than 15 FPS.
        ``tick(dt)`` remains unpaced for callers that manage their own clock.
        """
        if _headless():
            raise RuntimeError("game.run() is disabled while SAGA2D_HEADLESS is set; use game.tick(dt) or saga2d.testing.render_scene().")
        run_error: BaseException | None = None
        try:
            if not math.isfinite(fps) or fps <= 0:
                raise ValueError('fps must be a finite number greater than zero')
            self.push(start_scene)
            while self.running:
                started = time.perf_counter()
                self.tick()
                limit = fps if self._window_visible and self._window_focused else min(fps, 15)
                remaining = 1 / limit - (time.perf_counter() - started)
                if self.running and remaining > 0:
                    time.sleep(remaining)
        except BaseException as exc:
            run_error = exc
            raise
        finally:
            try:
                self.close()
            except BaseException as cleanup_error:
                if run_error is not None:
                    raise run_error from cleanup_error
                raise

    def _teardown(self) -> None:
        """Release scenes, sprites, timers, audio and the module-level game reference."""
        if not hasattr(self, "_scene_stack"):
            return
        self.running = False
        try:
            self._scene_stack.clear()
        finally:
            try:
                self._timer_manager.cancel_all()
                self._tween_manager.cancel_all()
                for sprite in list(self._all_sprites):
                    sprite.remove()
                self._particle_emitters.clear()
            finally:
                try:
                    try:
                        if self._audio is not None:
                            self._audio.stop_music()
                    finally:
                        self._backend.stop_sounds()
                finally:
                    if sys.meta_path is not None:
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
