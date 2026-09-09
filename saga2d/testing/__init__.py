"""Offscreen rendering for visual verification.

::

    from saga2d.testing import render_scene

    def setup(game):
        game.push(MyScene())

    image = render_scene(setup, resolution=(800, 600), tick_count=2)
    image.save("out.png")   # then LOOK at it

The window is created hidden; the returned PIL image is the framebuffer
at physical resolution (2× the logical size on HiDPI displays).
"""

from __future__ import annotations

import collections
import statistics
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from saga2d.game import Game

if TYPE_CHECKING:
    from PIL import Image


def render_scene(
    setup: Callable[[Game], None],
    *,
    resolution: tuple[int, int] = (800, 600),
    tick_count: int = 1,
    dt: float = 1 / 60,
) -> "Image.Image":
    game = Game("Screenshot", resolution=resolution, backend="pyglet", visible=False)
    try:
        setup(game)
        for _ in range(tick_count):
            game.tick(dt=dt)
        return game.backend.capture_frame()
    finally:
        game.close()



class FrameTimer:
    """Wall-clock frame times and the share each wrapped phase takes.

    ::

        timer = FrameTimer()
        timer.wrap(scene.world, "step", "world.step")
        timer.wrap(game.backend, "end_frame", "backend.end_frame")
        for _ in range(600):
            timer.frame(lambda: game.tick(1 / 60))
        print(timer.report())

    Wrapping replaces the method on that object with a timed version; the
    label defaults to the method name.  Time frames this way rather than under
    a profiler or ``tracemalloc``, which slow tight Python loops several times
    over and shift the blame.
    """

    def __init__(self) -> None:
        self.frames: list[float] = []  # milliseconds per frame
        self.seconds: dict[str, float] = collections.defaultdict(float)
        self.calls: collections.Counter[str] = collections.Counter()

    def wrap(self, obj: Any, name: str, label: str | None = None) -> None:
        fn = getattr(obj, name)
        label = label or name

        def timed(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                self.seconds[label] += time.perf_counter() - t0
                self.calls[label] += 1

        setattr(obj, name, timed)

    def frame(self, fn: Callable[[], Any]) -> float:
        """Run one frame through *fn* and record its wall-clock time; returns it in ms."""
        t0 = time.perf_counter()
        fn()
        ms = (time.perf_counter() - t0) * 1000
        self.frames.append(ms)
        return ms

    def percentile(self, p: float) -> float:
        if not self.frames:
            raise ValueError("no frames timed yet")
        ordered = sorted(self.frames)
        return ordered[min(len(ordered) - 1, int(p / 100 * len(ordered)))]

    def report(self) -> str:
        """Frame percentiles, then every phase by share of the timed frames."""
        total = sum(self.frames) / 1000
        lines = [f"{len(self.frames)} frames: p50 {statistics.median(self.frames):.1f} ms, p95 {self.percentile(95):.1f} ms, max {max(self.frames):.1f} ms"]
        for label, seconds in sorted(self.seconds.items(), key=lambda kv: -kv[1]):
            calls = self.calls[label]
            lines.append(f"  {label:20s} {seconds * 1000:8.0f} ms  {100 * seconds / total if total else 0:5.1f}%  {calls} calls, {seconds * 1000 / max(1, calls):.2f} ms each")
        return "\n".join(lines)


@dataclass(frozen=True)
class TextBox:
    """Where one drawn text lands, in logical pixels of its space."""

    text: str
    left: float
    top: float
    width: float
    height: float
    space: str
    order: int

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height

    def __str__(self) -> str:
        return f"{self.text!r} at ({self.left:.0f}, {self.top:.0f})–({self.right:.0f}, {self.bottom:.0f})"


_ANCHOR_X = {"left": 0.0, "center": 0.5, "right": 1.0}
_ANCHOR_Y = {"top": 0.0, "center": 0.5, "baseline": 0.8, "bottom": 1.0}


def text_boxes(backend: Any) -> list[TextBox]:
    """The boxes of every text the mock backend drew in its last frame.

    Sizes come from the backend's own ``measure_text``, the same numbers the
    UI layout used, so this sees the layout the way the layout sees itself.
    """
    boxes = []
    for t in backend.texts:
        if not str(t["text"]).strip():
            continue
        width, height = backend.measure_text(t["text"], t["font_size"], t["font"])
        left = t["x"] - width * _ANCHOR_X[t["anchor_x"]]
        top = t["y"] - height * _ANCHOR_Y[t["anchor_y"]]
        boxes.append(TextBox(str(t["text"]), left, top, width, height, t["space"], t["order"]))
    return boxes


def overlapping_texts(target: Any, *, spaces: tuple[str, ...] = ("screen",), slack: float = 2.0,
                      top_scene_only: bool = False) -> list[tuple[TextBox, TextBox]]:
    """Pairs of texts drawn over each other in the last frame of a mock-backed game.

    *target* is a :class:`Game` or its mock backend.  Only texts in the same
    space are compared, screen space by default (world text such as damage
    numbers may pile up on purpose).  A second pass of the same text within
    four pixels is a shadow or outline, not an overlap.  *slack* forgives
    boxes that merely touch.  With *top_scene_only* (a :class:`Game` target),
    texts of the scenes beneath an overlay are ignored: an overlay's panel
    covers them on purpose.
    """
    backend = target.backend if hasattr(target, "backend") else target
    boxes = [b for b in text_boxes(backend) if b.space in spaces]
    if top_scene_only:
        from saga2d.scene import UI_ORDER_BASE, UI_ORDER_STRIDE

        floor = UI_ORDER_BASE + (len(target.scenes) - 1) * UI_ORDER_STRIDE
        boxes = [b for b in boxes if b.space != "screen" or b.order >= floor]
    pairs = []
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a.space != b.space:
                continue
            if a.text == b.text and abs(a.left - b.left) <= 4 and abs(a.top - b.top) <= 4:
                continue
            if min(a.right, b.right) - max(a.left, b.left) > slack and min(a.bottom, b.bottom) - max(a.top, b.top) > slack:
                pairs.append((a, b))
    return pairs


def assert_no_text_overlap(target: Any, *, spaces: tuple[str, ...] = ("screen",), slack: float = 2.0, top_scene_only: bool = False) -> None:
    """Fail with every offending pair when texts overlap; see :func:`overlapping_texts`."""
    pairs = overlapping_texts(target, spaces=spaces, slack=slack, top_scene_only=top_scene_only)
    if pairs:
        raise AssertionError("text drawn over text:\n" + "\n".join(f"  {a}  over  {b}" for a, b in pairs))
