"""Animation templates and playback state.

:class:`AnimationDef` is a **reusable template** — it defines what frames to
play, how fast, and whether it loops.  It does not belong to any specific
sprite.  Multiple sprites may share the same ``AnimationDef``; each sprite
holds its own playback state via an internal :class:`AnimationPlayer`.

:class:`AnimationPlayer` is the **internal playback state tracker**.  It
advances time, tracks the current frame index, and returns a new image handle
only when the frame actually changes — so the sprite avoids redundant backend
calls.

Usage (from game code — via Sprite, not directly)::

    walk = AnimationDef(
        frames=["knight_walk_01", "knight_walk_02", "knight_walk_03"],
        frame_duration=0.15,
        loop=True,
    )

    attack = AnimationDef(
        frames=["knight_atk_01", "knight_atk_02", "knight_atk_03"],
        frame_duration=0.1,
        loop=False,
    )

    knight.play(walk)
    knight.play(attack, on_complete=do_damage)

``AnimationDef`` holds **names** (strings), not image handles.  Handles are
resolved at play-time by the sprite's asset manager, so defs can be created
before assets are loaded.
"""

from __future__ import annotations

from typing import Any, Callable

# ---------------------------------------------------------------------------
# AnimationDef — public, re-exported from easygame
# ---------------------------------------------------------------------------


class AnimationDef:
    """Reusable animation template.

    Parameters:
        frames:         A list of image asset names **or** a single prefix
                        string.  When a ``list[str]``, each name is resolved
                        via ``game.assets.image(name)`` at play time.  When a
                        ``str``, it is resolved via ``game.assets.frames(prefix)``
                        which discovers numbered files on disk
                        (``prefix_01.png``, ``prefix_02.png``, …).
        frame_duration: Seconds per frame (uniform for all frames).
        loop:           If ``True``, cycles forever.  If ``False``, plays once,
                        fires ``on_complete``, and stays on the last frame.
    """

    __slots__ = ("frames", "frame_duration", "loop")

    def __init__(
        self,
        frames: list[str] | str,
        frame_duration: float = 0.15,
        loop: bool = True,
    ) -> None:
        self.frames: list[str] | str = frames
        self.frame_duration: float = frame_duration
        self.loop: bool = loop

    def __repr__(self) -> str:
        if isinstance(self.frames, str):
            desc = f"prefix={self.frames!r}"
        else:
            desc = f"{len(self.frames)} frames"
        return f"AnimationDef({desc}, duration={self.frame_duration}, loop={self.loop})"


# ---------------------------------------------------------------------------
# AnimationPlayer — internal, NOT re-exported
# ---------------------------------------------------------------------------


class AnimationPlayer:
    """Internal per-sprite playback state.

    Created by :meth:`Sprite.play` with **resolved** image handles (not
    names).  Tracks elapsed time, current frame index, and fires the
    ``on_complete`` callback when a non-looping animation finishes.

    Parameters:
        frames:         List of resolved ``ImageHandle`` objects, ready to
                        display.  Must be non-empty.
        frame_duration: Seconds per frame.
        loop:           Whether to cycle or stop at the last frame.
        on_complete:    Called once when a non-looping animation finishes.
                        Never called for looping animations.
    """

    __slots__ = (
        "_frames",
        "_frame_duration",
        "_loop",
        "_on_complete",
        "_frame_index",
        "_elapsed",
        "_finished",
    )

    def __init__(
        self,
        frames: list[Any],
        frame_duration: float,
        loop: bool,
        on_complete: Callable[[], Any] | None = None,
    ) -> None:
        if not frames:
            raise ValueError(
                "Cannot play animation with zero frames. Check that your"
                " AnimationDef has at least one frame name, or that the asset"
                " prefix matches files on disk."
            )
        self._frames = frames
        self._frame_duration = frame_duration
        self._loop = loop
        self._on_complete = on_complete
        self._frame_index: int = 0
        self._elapsed: float = 0.0
        self._finished: bool = False

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def current_frame(self) -> Any:
        """The ``ImageHandle`` for the current frame."""
        return self._frames[self._frame_index]

    @property
    def is_playing(self) -> bool:
        """``True`` while the animation is still advancing frames."""
        return not self._finished

    @property
    def is_complete(self) -> bool:
        """``True`` when a non-looping animation has played to the end."""
        return self._finished

    @property
    def frame_index(self) -> int:
        """Current frame index (0-based)."""
        return self._frame_index

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, dt: float) -> Any | None:
        """Advance playback by *dt* seconds.

        Returns the new ``ImageHandle`` if the displayed frame changed,
        or ``None`` if the frame is the same (so the caller can skip
        redundant backend updates).
        """
        if self._finished:
            return None

        self._elapsed += dt
        old_index = self._frame_index

        while self._elapsed >= self._frame_duration:
            self._elapsed -= self._frame_duration
            self._frame_index += 1

            if self._frame_index >= len(self._frames):
                if self._loop:
                    self._frame_index = 0
                else:
                    # Clamp to last frame.
                    self._frame_index = len(self._frames) - 1
                    self._elapsed = 0.0
                    self._finished = True
                    if self._on_complete is not None:
                        self._on_complete()
                    break

        if self._frame_index != old_index:
            return self._frames[self._frame_index]
        return None
