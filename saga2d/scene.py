"""Scene base class and SceneStack.

Scene is a concrete base class with no-op lifecycle hooks. Subclasses override
only what they need. SceneStack manages a stack of scenes with push/pop/replace/
clear_and_push. Operations triggered during update() or handle_input() are
deferred and flushed after those phases complete.
"""

from __future__ import annotations

import collections
import inspect
from typing import TYPE_CHECKING, Any, Callable

from saga2d.util.timer import TimerHandle


def _component_to_json(component: Any) -> dict[str, Any]:
    """Convert a UI component to a JSON-serialisable dict.

    Recursive over children. The returned shape is stable enough for
    tooling to consume — debug overlays, snapshot tests, IDE plugins.
    Keys are omitted when not meaningful (no ``text_style`` key when
    the component has none), so a snapshot diff stays focused on
    actual differences.
    """
    node: dict[str, Any] = {"type": type(component).__name__}

    if hasattr(component, "_text_rv"):
        rv = component._text_rv
        if getattr(rv, "is_reactive", False):
            node["text"] = {"reactive": True}
        else:
            node["text"] = {"reactive": False, "value": rv.value}

    if hasattr(component, "_value_rv"):
        rv = component._value_rv
        if getattr(rv, "is_reactive", False):
            node["value"] = {"reactive": True}
        else:
            node["value"] = {"reactive": False, "value": rv.value}

    text_style = getattr(component, "_text_style", None)
    if isinstance(text_style, str):
        node["text_style"] = text_style

    anchor = getattr(component, "_anchor", None)
    if anchor is not None:
        node["anchor"] = anchor.name

    margin = getattr(component, "_margin", 0)
    if margin:
        node["margin"] = margin

    children = getattr(component, "_children", None)
    if children:
        node["children"] = [_component_to_json(c) for c in children]

    return node


def _describe_component(component: Any) -> str:
    """One-line human-readable description — format from the JSON node.

    Keeping a single canonical data shape (the JSON node) and formatting
    from it means :meth:`Scene.summary` and :meth:`Scene.summary_json`
    can never drift out of sync.
    """
    node = _component_to_json(component)
    return _format_node(node)


def _format_node(node: dict[str, Any]) -> str:
    """Render a ``_component_to_json`` node as the iter-20 one-line form."""
    cls = node["type"]
    parts: list[str] = []

    text = node.get("text")
    if text is not None:
        if text["reactive"]:
            parts.append("← callable")
        else:
            value = text["value"]
            parts.append(f'"{value}"' if value else '""')

    value = node.get("value")
    if value is not None:
        if value["reactive"]:
            parts.append("← callable")
        else:
            parts.append(f"value={value['value']}")

    if "text_style" in node:
        parts.append(f"text_style={node['text_style']}")
    if "anchor" in node:
        parts.append(f"anchor={node['anchor']}")
    if "margin" in node:
        parts.append(f"margin={node['margin']}")

    if parts:
        return f"{cls} " + ", ".join(parts)
    return cls


def _walk_json_with_depth(node: dict[str, Any], depth: int = 0):
    """Depth-first walk over a JSON node's children, yielding
    ``(depth, node)`` pairs starting from direct children."""
    for child in node.get("children", []):
        yield (depth, child)
        yield from _walk_json_with_depth(child, depth + 1)


def _call_with_optional_event(cb: Callable[..., Any], event: Any) -> None:
    """Call *cb*, passing *event* iff the signature accepts ≥1 positional arg.

    Signature inspection runs on every call — ``inspect.signature`` is
    ~1 μs for typical callables and key presses happen at human rate
    (<10/sec), so there is no measurable dispatch overhead. The
    previous id-keyed cache (iter-11) had a lifecycle hazard (bound
    methods get a new object on every access, lambdas GC'd and reused
    ids) for essentially no benefit; simpler is better.
    """
    try:
        params = inspect.signature(cb).parameters
        takes_event = any(
            p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.VAR_POSITIONAL,
            )
            for p in params.values()
        )
    except (ValueError, TypeError):
        # C-implemented builtins sometimes refuse inspect.signature.
        takes_event = False
    if takes_event:
        cb(event)
    else:
        cb()

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

    # Declarative input map — class-level dict from key/action name (or
    # a tuple of aliases) to the name of a method on ``self``. Dispatched
    # automatically after instance-level :meth:`bind_key` handlers. Example::
    #
    #     class RingOfPainScene(Scene):
    #         controls = {
    #             ("right", "d"):         "rotate_cw",
    #             ("left", "a"):          "rotate_ccw",
    #             ("confirm", "space"):   "interact",
    #         }
    #
    # A zero-arg method call for each match. ``bind_key`` overrides
    # the class-level binding when both exist for the same key.
    controls: dict[str | tuple[str, ...], str] = {}

    # Populated at class-definition time with the tuple-keys flattened —
    # kept separate so the user-facing ``controls`` stays readable.
    _normalised_controls: dict[str, str] = {}

    game: Game
    camera: Camera | None = None
    _ui: _UIRoot | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Flatten tuple-aliased keys in ``cls.controls`` once per subclass
        and verify every target method exists on the class.

        Raises :class:`AttributeError` at import time for typo'd method
        names — far better than silently swallowing the keypress at
        runtime (the iter-10 friction point).
        """
        super().__init_subclass__(**kwargs)
        flat: dict[str, str] = {}
        missing: list[str] = []
        for keys, method_name in cls.controls.items():
            if isinstance(keys, tuple):
                for alias in keys:
                    flat[alias] = method_name
            else:
                flat[keys] = method_name
            if not hasattr(cls, method_name):
                missing.append(method_name)
        if missing:
            raise AttributeError(
                f"{cls.__name__}.controls references methods that do not "
                f"exist on the class: {', '.join(sorted(set(missing)))}"
            )
        cls._normalised_controls = flat

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
            self._key_handlers: dict[str, Callable[[], Any]] = {key_or_action: callback}

    def bind_keys(
        self,
        keys_or_actions: list[str] | tuple[str, ...],
        callback: Callable[[], Any],
    ) -> None:
        """Register the same callback for several keys / actions.

        Shortcut for multi-alias bindings (arrows + WASD, confirm +
        space)::

            self.bind_keys(["right", "d"], self._rotate_cw)
            self.bind_keys(["confirm", "space"], self._interact)

        Equivalent to calling :meth:`bind_key` once per name.
        """
        for name in keys_or_actions:
            self.bind_key(name, callback)

    def _dispatch_key_bindings(self, event: InputEvent) -> bool:
        """Dispatch *event* to registered key callbacks.

        Called by the game loop before :meth:`handle_input`.  Returns
        ``True`` if a binding matched and consumed the event.

        Two dispatch layers, checked in order:

        1. Instance-level handlers registered via :meth:`bind_key` /
           :meth:`bind_keys`. These always win when present — explicit
           runtime binding overrides the class-level declaration.
        2. Class-level :attr:`controls` dict. The matched value is a
           method name; the method is resolved on ``self`` at dispatch
           time.

        Handlers may optionally accept the :class:`InputEvent` as a
        single positional argument. The framework inspects the
        callable's signature and passes the event when accepted, or
        calls with no args otherwise. This lets modifier-aware
        handlers receive the raw event without breaking zero-arg
        callers.
        """
        if event.type != "key_press":
            return False

        handlers: dict[str, Callable[[], Any]] | None = getattr(
            self, "_key_handlers", None
        )
        if handlers:
            cb = handlers.get(event.action) or handlers.get(event.key)  # type: ignore[arg-type]
            if cb is not None:
                _call_with_optional_event(cb, event)
                return True

        flat = type(self)._normalised_controls
        if flat:
            method_name = flat.get(event.action) or flat.get(event.key)  # type: ignore[arg-type]
            if method_name is not None:
                method = getattr(self, method_name, None)
                if callable(method):
                    _call_with_optional_event(method, event)
                    return True
        return False

    # ------------------------------------------------------------------
    # Introspection — Keras Model.summary()'s direct parallel
    # ------------------------------------------------------------------

    def summary_json(self) -> dict[str, Any]:
        """Return this scene's declared structure as a JSON-serialisable dict.

        Stable shape for tooling consumption (debug overlays, snapshot
        tests, IDE plugins). Each UI node carries ``type``, optional
        ``text`` / ``value`` sub-objects with a ``reactive`` flag,
        ``text_style`` / ``anchor`` / ``margin`` when set, and a
        ``children`` list. Controls are emitted as a list of
        ``{"keys": [...], "method": "..."}`` objects so a consumer can
        preserve ordering and alias grouping.

        Example::

            {
                "scene": "DialMenuScene",
                "background_color": [16, 18, 28, 255],
                "controls": [
                    {"keys": ["confirm", "space"], "method": "confirm"},
                    {"keys": ["a", "left"], "method": "rotate_ccw"},
                    ...
                ],
                "ui": {"type": "_UIRoot", "children": [...]},
            }
        """
        result: dict[str, Any] = {"scene": type(self).__name__}

        if self.background_color is not None:
            result["background_color"] = list(self.background_color)

        flat = type(self)._normalised_controls
        if flat:
            by_method: dict[str, list[str]] = {}
            for key, method in flat.items():
                by_method.setdefault(method, []).append(key)
            result["controls"] = [
                {"keys": sorted(by_method[method]), "method": method}
                for method in sorted(by_method)
            ]

        if self._ui is not None:
            result["ui"] = _component_to_json(self._ui)

        return result

    def summary(self) -> str:
        """Return a human-readable dump of this scene's structure.

        Formats the same data :meth:`summary_json` produces — the two
        methods can never drift out of sync because :meth:`summary`
        runs through the JSON form internally. See
        :meth:`summary_json` for the underlying schema.

        Typical output::

            Scene: DialMenuScene
              background_color: (16, 18, 28, 255)
              controls:
                confirm, space  → confirm
                a, left         → rotate_ccw
                d, right        → rotate_cw
                cancel          → cancel
              ui:
                Label "Dial Menu", text_style=title, anchor=TOP_LEFT, margin=20
                Label ← callable, text_style=heading, anchor=CENTER
                Label ← callable, text_style=caption, anchor=BOTTOM, margin=24
        """
        data = self.summary_json()
        lines: list[str] = [f"Scene: {data['scene']}"]
        if "background_color" in data:
            lines.append(f"  background_color: {tuple(data['background_color'])}")
        if "controls" in data:
            lines.append("  controls:")
            for entry in data["controls"]:
                keys = ", ".join(entry["keys"])
                lines.append(f"    {keys}  → {entry['method']}")
        if "ui" in data:
            lines.append("  ui:")
            for depth, node in _walk_json_with_depth(data["ui"]):
                lines.append("    " + "  " * depth + _format_node(node))
        return "\n".join(lines)

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
        border_color: tuple[int, int, int, int] | None = None,
        border_width: int = 0,
    ) -> None:
        """Draw a filled rectangle in **screen space**.

        Convenience wrapper around the backend's ``draw_rect`` for use
        inside :meth:`draw`.  Coordinates are in logical screen pixels.

        Parameters:
            x:            Left edge in screen pixels.
            y:            Top edge in screen pixels.
            width:        Width in pixels.
            height:       Height in pixels.
            color:        ``(R, G, B, A)`` fill colour (0–255).
            opacity:      Extra opacity multiplier (0.0–1.0, default 1.0).
            border_color: ``(R, G, B, A)`` border colour. When given with
                          a positive *border_width*, the method draws the
                          border as an outer filled rect, then the inner
                          fill inset by *border_width*. Saves tic-tac-toe-
                          style grids from two calls per cell.
            border_width: Pixel thickness of the border. Ignored when
                          *border_color* is ``None``.
        """
        backend = self.game._backend
        if border_color is not None and border_width > 0:
            backend.draw_rect(
                int(x), int(y), int(width), int(height),
                border_color, opacity=opacity,
            )
            bw = int(border_width)
            backend.draw_rect(
                int(x) + bw,
                int(y) + bw,
                max(0, int(width) - 2 * bw),
                max(0, int(height) - 2 * bw),
                color,
                opacity=opacity,
            )
        else:
            backend.draw_rect(
                int(x), int(y), int(width), int(height),
                color, opacity=opacity,
            )

    def draw_circle(
        self,
        x: float,
        y: float,
        radius: float,
        color: tuple[int, int, int, int],
        *,
        opacity: float = 1.0,
        segments: int | None = None,
    ) -> None:
        """Draw a filled circle in **screen space** centred at ``(x, y)``.

        Parameters match :meth:`draw_rect`; *segments* controls tessellation
        quality (``None`` = backend default).
        """
        self.game._backend.draw_circle(
            int(x),
            int(y),
            int(radius),
            color,
            opacity=opacity,
            segments=segments,
        )

    def draw_text(
        self,
        text: str,
        x: float,
        y: float,
        *,
        style: str | Any = None,
        font_size: int | None = None,
        color: tuple[int, int, int, int] | None = None,
        font: Any | None = None,
        anchor_x: str = "left",
        anchor_y: str = "baseline",
    ) -> None:
        """Draw *text* at ``(x, y)`` in **screen space**.

        Parallel to :meth:`draw_rect` / :meth:`draw_circle`, so a scene
        never needs to touch ``self.game._backend`` for primitive draws.

        *style* may be a string name registered on the active theme
        (``"title"``, ``"heading"``, ``"hud"``, ``"body"``, ``"sub"``,
        ``"caption"`` are pre-registered) or a
        :class:`~saga2d.ui.theme.TextStyle` instance. *font_size* /
        *color* / *font* passed alongside ``style`` override the style's
        value for this one call.

        If neither *style* nor *font_size* / *color* are given, the
        theme's default font size and text colour are used.

        *anchor_x* / *anchor_y* accept pyglet's anchor names
        (``"center"``, ``"left"``, ``"right"``, ``"top"``, ``"bottom"``,
        ``"baseline"``).
        """
        from saga2d.ui.theme import TextStyle as _TextStyle

        theme = self.game.theme
        resolved_font_size: int
        resolved_color: tuple[int, int, int, int]
        resolved_font: Any | None

        if style is not None:
            text_style = (
                theme.get_text_style(style)
                if isinstance(style, str)
                else style
            )
            if not isinstance(text_style, _TextStyle):
                raise TypeError(
                    f"style must be str or TextStyle, got {type(text_style).__name__}"
                )
            resolved_font_size = font_size if font_size is not None else text_style.font_size
            resolved_color = color if color is not None else text_style.color
            resolved_font = font if font is not None else text_style.font
        else:
            resolved_font_size = (
                font_size if font_size is not None else theme.default_font_size
            )
            resolved_color = (
                color if color is not None else theme.default_text_color
            )
            resolved_font = font

        self.game._backend.draw_text(
            text,
            int(x),
            int(y),
            resolved_font_size,
            resolved_color,
            font=resolved_font,
            anchor_x=anchor_x,
            anchor_y=anchor_y,
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

    def _flush_after_direct_op(self) -> None:
        """Flush any deferred ops that accumulated during a direct
        (non-tick) scene operation.

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
            max_iterations = 1000
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
            if iterations >= max_iterations and self._pending_ops:
                import logging
                logging.getLogger(__name__).warning(
                    "SceneStack: deferred ops cap (%d) reached; "
                    "%d ops discarded",
                    max_iterations,
                    len(self._pending_ops),
                )
                self._pending_ops.clear()
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
            if iterations >= max_iterations and self._pending_ops:
                import logging
                logging.getLogger(__name__).warning(
                    "SceneStack: deferred ops cap (%d) reached; "
                    "%d ops discarded",
                    max_iterations,
                    len(self._pending_ops),
                )
                self._pending_ops.clear()
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
        # Remove any particle emitters the scene created from the game's
        # update set so they stop spawning after the scene is gone.
        scene._cleanup_owned_emitters()
        # Cancel camera pan tweens so they don't hold a strong ref to the
        # camera (and therefore the scene) after the scene exits.
        if scene.camera is not None:
            scene.camera._cancel_pan()
        # Reset cursor so the next scene starts with default (no custom cursor).
        if hasattr(scene.game, 'cursor'):
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
