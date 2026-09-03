"""TimerManager — delayed and repeating callbacks, driven by the game loop."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class _Timer:
    callback: Callable[[], Any]
    remaining: float
    interval: float | None  # None = one-shot


class TimerManager:
    def __init__(self) -> None:
        self._timers: dict[int, _Timer] = {}
        self._next_id = 0

    def after(self, delay: float, callback: Callable[[], Any]) -> int:
        """Call *callback* once after *delay* seconds.  Returns a timer id."""
        if not math.isfinite(delay) or delay < 0:
            raise ValueError(f"delay must be a finite number >= 0, got {delay}")
        return self._add(_Timer(callback, delay, None))

    def every(self, interval: float, callback: Callable[[], Any]) -> int:
        """Call *callback* every *interval* seconds (at most once per update)."""
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError(f"interval must be a finite number > 0, got {interval}")
        return self._add(_Timer(callback, interval, interval))

    def cancel(self, timer_id: int) -> None:
        self._timers.pop(timer_id, None)

    def cancel_all(self) -> None:
        self._timers.clear()

    def is_active(self, timer_id: int) -> bool:
        return timer_id in self._timers

    def update(self, dt: float) -> None:
        for timer_id, timer in list(self._timers.items()):
            if timer_id not in self._timers:
                continue  # cancelled by an earlier callback this frame
            timer.remaining -= dt
            if timer.remaining > 0:
                continue
            if timer.interval is None:
                del self._timers[timer_id]
            else:
                timer.remaining = timer.interval
            timer.callback()

    def _add(self, timer: _Timer) -> int:
        timer_id = self._next_id
        self._next_id += 1
        self._timers[timer_id] = timer
        return timer_id
