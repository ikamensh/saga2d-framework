"""TweenManager and tween() — property interpolation with easing.

The module-level :func:`tween` is the public API. :class:`Ease` and
:class:`TweenManager` are also public. :class:`_Tween` is internal.

Uses module-level ``_tween_manager`` set by :class:`Game` during init.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Easing functions (quadratic, t in 0.0..1.0)
# ---------------------------------------------------------------------------


def _ease_linear(t: float) -> float:
    return t


def _ease_in(t: float) -> float:
    return t * t


def _ease_out(t: float) -> float:
    return 1 - (1 - t) * (1 - t)


def _ease_in_out(t: float) -> float:
    return 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2


# ---------------------------------------------------------------------------
# Ease enum
# ---------------------------------------------------------------------------


class Ease(Enum):
    """Easing curves for tween interpolation (quadratic)."""

    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"


_EASE_FNS: dict[Ease, Callable[[float], float]] = {
    Ease.LINEAR: _ease_linear,
    Ease.EASE_IN: _ease_in,
    Ease.EASE_OUT: _ease_out,
    Ease.EASE_IN_OUT: _ease_in_out,
}


# ---------------------------------------------------------------------------
# _Tween — internal
# ---------------------------------------------------------------------------


@dataclass
class _Tween:
    """Internal tween state."""

    target: Any
    prop: str
    from_val: float
    to_val: float
    duration: float
    ease_fn: Callable[[float], float]
    on_complete: Callable[[], Any] | None
    elapsed: float = 0.0
    cancelled: bool = False


# ---------------------------------------------------------------------------
# TweenManager
# ---------------------------------------------------------------------------


class TweenManager:
    """Manages active tweens. Updates property values each frame."""

    def __init__(self) -> None:
        self._tweens: dict[int, _Tween] = {}
        self._next_id: int = 0

    def create(
        self,
        target: Any,
        prop: str,
        from_val: float,
        to_val: float,
        duration: float,
        *,
        ease: Ease = Ease.LINEAR,
        on_complete: Callable[[], Any] | None = None,
    ) -> int:
        """Create a tween. Returns tween_id for cancellation."""
        if not hasattr(target, prop):
            raise AttributeError(f"'{type(target).__name__}' has no attribute '{prop}'")
        if not math.isfinite(from_val):
            raise ValueError(f"from_val must be finite, got {from_val}")
        if not math.isfinite(to_val):
            raise ValueError(f"to_val must be finite, got {to_val}")
        tween_id = self._next_id
        self._next_id += 1
        self._tweens[tween_id] = _Tween(
            target=target,
            prop=prop,
            from_val=from_val,
            to_val=to_val,
            duration=duration,
            ease_fn=_EASE_FNS[ease],
            on_complete=on_complete,
        )
        return tween_id

    def cancel(self, tween_id: int) -> None:
        """Cancel a tween."""
        if tween_id in self._tweens:
            self._tweens[tween_id].cancelled = True
            del self._tweens[tween_id]

    def cancel_by_target(self, target: object) -> None:
        """Cancel all active tweens targeting *target*."""
        to_remove = [tid for tid, t in self._tweens.items() if t.target is target]
        for tid in to_remove:
            self._tweens[tid].cancelled = True
            del self._tweens[tid]

    def cancel_all(self) -> None:
        """Cancel all active tweens."""
        for t in self._tweens.values():
            t.cancelled = True
        self._tweens.clear()

    def update(self, dt: float) -> None:
        """Advance all tweens by *dt* seconds."""
        if not math.isfinite(dt):
            return
        to_remove: list[int] = []
        for tween_id, t in list(self._tweens.items()):
            if t.cancelled:
                continue
            t.elapsed += dt
            if t.elapsed >= t.duration:
                setattr(t.target, t.prop, t.to_val)
                if t.on_complete is not None:
                    try:
                        t.on_complete()
                    except Exception:
                        _logger.exception(
                            "Tween on_complete callback %r raised; "
                            "removing tween %d",
                            t.on_complete,
                            tween_id,
                        )
                to_remove.append(tween_id)
            else:
                progress = t.elapsed / t.duration
                eased = t.ease_fn(progress)
                val = t.from_val + (t.to_val - t.from_val) * eased
                setattr(t.target, t.prop, val)
        for tween_id in to_remove:
            if tween_id in self._tweens:
                del self._tweens[tween_id]


# ---------------------------------------------------------------------------
# Module-level manager (set by Game.__init__)
# ---------------------------------------------------------------------------

_tween_manager: TweenManager | None = None


# ---------------------------------------------------------------------------
# Public tween() function
# ---------------------------------------------------------------------------


def tween(
    target: Any,
    prop: str,
    from_val: float,
    to_val: float,
    duration: float,
    *,
    ease: Ease = Ease.LINEAR,
    on_complete: Callable[[], Any] | None = None,
) -> int:
    """Create a tween. Returns tween_id for cancellation.

    Raises RuntimeError if called before a Game exists.
    """
    if _tween_manager is None:
        raise RuntimeError(
            "No active Game. Create a Game instance before calling tween()."
        )
    return _tween_manager.create(
        target,
        prop,
        from_val,
        to_val,
        duration,
        ease=ease,
        on_complete=on_complete,
    )
