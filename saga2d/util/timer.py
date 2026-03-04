"""TimerManager — delayed and repeating callbacks.

Internal class. Users interact via :meth:`Game.after`, :meth:`Game.every`,
and :meth:`Game.cancel`. Not re-exported from saga2d.

Timer IDs are monotonic ints. Safe iteration: snapshot copy, cancelled flag
checked before firing, no catch-up on large dt for repeating timers.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Callable

_logger = logging.getLogger(__name__)


@dataclass
class _Timer:
    """Internal timer state."""

    callback: Callable[[], Any]
    remaining: float  # seconds until next fire
    interval: float | None  # None for one-shot, >0 for repeating
    cancelled: bool = False
    then_chain: list[tuple[Callable[[], Any], float]] = field(
        default_factory=list,
    )
    chain_ids: list[int] = field(default_factory=list)


class TimerHandle:
    """Lightweight handle returned by :meth:`TimerManager.after` /
    :meth:`TimerManager.every`.  Supports ``.then()`` chaining and is
    backward-compatible with bare ``int`` timer IDs via ``__eq__``,
    ``__hash__``, and ``__int__``.
    """

    __slots__ = ("timer_id", "_manager", "_chain_ids")

    def __init__(
        self,
        timer_id: int,
        manager: TimerManager,
        chain_ids: list[int],
    ) -> None:
        self.timer_id = timer_id
        self._manager = manager
        self._chain_ids = chain_ids  # shared with _Timer.chain_ids

    # -- chaining -----------------------------------------------------

    def then(
        self,
        callback: Callable[[], Any],
        delay: float = 0.0,
    ) -> TimerHandle:
        """Schedule *callback* to fire *delay* seconds after the parent.

        Returns the same handle for fluent chaining::

            game.after(1, cb1).then(cb2, 0.5).then(cb3, 0.2)
        """
        root = self._manager._timers.get(self.timer_id)
        if root is not None:
            root.then_chain.append((callback, delay))
        return self

    # -- backward compatibility with int ------------------------------

    def __eq__(self, other: object) -> bool:
        if isinstance(other, TimerHandle):
            return self.timer_id == other.timer_id
        if isinstance(other, int):
            return self.timer_id == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.timer_id)

    def __int__(self) -> int:
        return self.timer_id

    def __lt__(self, other: object) -> bool:
        if isinstance(other, TimerHandle):
            return self.timer_id < other.timer_id
        if isinstance(other, int):
            return self.timer_id < other
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, TimerHandle):
            return self.timer_id <= other.timer_id
        if isinstance(other, int):
            return self.timer_id <= other
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, TimerHandle):
            return self.timer_id > other.timer_id
        if isinstance(other, int):
            return self.timer_id > other
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, TimerHandle):
            return self.timer_id >= other.timer_id
        if isinstance(other, int):
            return self.timer_id >= other
        return NotImplemented

    def __repr__(self) -> str:
        return f"TimerHandle(timer_id={self.timer_id})"


class TimerManager:
    """Manages delayed and repeating callbacks.

    Timer IDs are opaque monotonic ints. Callbacks run during update(dt).
    """

    def __init__(self) -> None:
        self._timers: dict[int, _Timer] = {}
        self._next_id: int = 0

    def after(self, delay: float, callback: Callable[[], Any]) -> TimerHandle:
        """Schedule a one-shot callback after *delay* seconds.

        Returns a :class:`TimerHandle` for cancellation and chaining.

        Raises:
            ValueError: If delay is negative.
        """
        if delay < 0:
            raise ValueError("delay must be >= 0")
        timer_id = self._next_id
        self._next_id += 1
        chain_ids: list[int] = [timer_id]
        self._timers[timer_id] = _Timer(
            callback=callback,
            remaining=delay,
            interval=None,
            chain_ids=chain_ids,
        )
        return TimerHandle(timer_id, self, chain_ids)

    def every(self, interval: float, callback: Callable[[], Any]) -> TimerHandle:
        """Schedule a repeating callback every *interval* seconds.

        Returns a :class:`TimerHandle` for cancellation and chaining.
        No catch-up on large dt — fires at most once per update.

        Raises:
            ValueError: If *interval* is zero or negative.
        """
        if interval <= 0:
            raise ValueError(f"interval must be > 0, got {interval}")
        timer_id = self._next_id
        self._next_id += 1
        chain_ids: list[int] = [timer_id]
        self._timers[timer_id] = _Timer(
            callback=callback,
            remaining=interval,
            interval=interval,
            chain_ids=chain_ids,
        )
        return TimerHandle(timer_id, self, chain_ids)

    def cancel(self, timer_id: int | TimerHandle) -> None:
        """Cancel a timer (or an entire chain). Safe to call during a callback.

        If *timer_id* is a :class:`TimerHandle`, every timer in the
        chain (root + already-scheduled children) is cancelled.
        """
        if isinstance(timer_id, TimerHandle):
            for tid in list(timer_id._chain_ids):
                if tid in self._timers:
                    self._timers[tid].cancelled = True
                    del self._timers[tid]
        else:
            if timer_id in self._timers:
                self._timers[timer_id].cancelled = True
                del self._timers[timer_id]

    def cancel_all(self) -> None:
        """Cancel all active timers."""
        for timer in self._timers.values():
            timer.cancelled = True
        self._timers.clear()

    def update(self, dt: float) -> None:
        """Advance all timers by *dt* seconds. Fire due callbacks.

        Iterates a snapshot copy. Cancelled timers (e.g. via callback) are
        skipped. Repeating timers fire at most once per update (no catch-up).

        After a timer fires, if it has a ``then_chain``, the next step is
        scheduled as a new one-shot timer inheriting the rest of the chain.
        For repeating timers the entire chain is cloned each repetition.
        """
        if not math.isfinite(dt):
            return
        to_remove: list[int] = []
        for timer_id, timer in list(self._timers.items()):
            if timer.cancelled:
                continue
            timer.remaining -= dt
            if timer.remaining <= 0:
                try:
                    timer.callback()
                except Exception:
                    _logger.exception(
                        "Timer callback %r raised; removing timer %d",
                        timer.callback,
                        timer_id,
                    )
                    to_remove.append(timer_id)
                    continue
                # The callback may have cancelled this timer.
                if timer.cancelled:
                    continue
                if timer.interval is None:
                    # One-shot: propagate then-chain
                    if timer.then_chain:
                        self._schedule_chain_step(
                            timer.then_chain,
                            timer.chain_ids,
                        )
                    to_remove.append(timer_id)
                else:
                    # Repeating: reset, no catch-up
                    timer.remaining = timer.interval
                    # Clone the full chain as a one-shot sequence. Reset
                    # chain_ids to [root_id] before scheduling so we don't
                    # grow indefinitely; new children replace old ones.
                    if timer.then_chain:
                        timer.chain_ids.clear()
                        timer.chain_ids.append(timer_id)
                        self._schedule_chain_step(
                            list(timer.then_chain),
                            timer.chain_ids,
                        )
        for timer_id in to_remove:
            if timer_id in self._timers:
                del self._timers[timer_id]

    def _schedule_chain_step(
        self,
        chain: list[tuple[Callable[[], Any], float]],
        chain_ids: list[int],
    ) -> None:
        """Schedule the first step of *chain* and thread the rest forward."""
        next_cb, next_delay = chain[0]
        rest = chain[1:]
        child = self.after(next_delay, next_cb)
        child_timer = self._timers[child.timer_id]
        child_timer.then_chain = rest
        # Share the cancellation list so cancel() reaches all children.
        child_timer.chain_ids = chain_ids
        child._chain_ids = chain_ids
        chain_ids.append(child.timer_id)
