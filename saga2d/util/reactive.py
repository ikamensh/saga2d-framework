"""Reactive value holder — a slot that accepts a fixed value **or** a
zero-argument callable producing that value.

Three saga2d widgets use this pattern already (``Label.text``,
``ProgressBar.value``, ``ProgressBar.max_value``). Rather than retype
the "store callable, refresh on read, unbind on explicit set" dance in
each one, they share a single :class:`ReactiveValue` helper.

Widgets still own their own validation (e.g. ``ProgressBar`` rejects
NaN) because that's widget-specific; the helper only owns the binding
mechanics::

    self._text = ReactiveValue(text_or_callable, default="")

    # Every frame before draw:
    self._text.refresh()
    rendered = self._text.value

    # User assigns explicitly — unbind the callable:
    self._text.set(new_value)
"""

from __future__ import annotations

from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class ReactiveValue(Generic[T]):
    """A slot holding either a fixed ``T`` or a callable returning ``T``.

    The callable is re-evaluated on :meth:`refresh`. Reading
    :attr:`value` after :meth:`refresh` returns the latest snapshot.
    Calling :meth:`set` unbinds any callable — explicit assignment
    always wins.

    *on_change* is an optional callback fired when the snapshot value
    actually changes between refreshes. Widgets use it to invalidate
    cached layout (e.g. the text glyph-width estimate).
    """

    __slots__ = ("_fn", "_value", "_on_change")

    def __init__(
        self,
        source: T | Callable[[], T],
        *,
        default: T,
        on_change: Callable[[T, T], None] | None = None,
    ) -> None:
        if callable(source):
            self._fn: Callable[[], T] | None = source
            self._value: T = default
        else:
            self._fn = None
            self._value = source if source is not None else default  # type: ignore[assignment]
        self._on_change = on_change

    @property
    def value(self) -> T:
        """Latest snapshot — reading does *not* re-evaluate. Call
        :meth:`refresh` first when freshness matters."""
        return self._value

    @property
    def is_reactive(self) -> bool:
        """True if a callable source is currently bound."""
        return self._fn is not None

    def refresh(self) -> bool:
        """Re-evaluate the bound callable. Returns ``True`` when the
        snapshot value changed (useful for layout invalidation).
        ``False`` when no callable is bound or the value is unchanged.
        """
        if self._fn is None:
            return False
        new_value = self._fn()
        if new_value != self._value:
            old = self._value
            self._value = new_value
            if self._on_change is not None:
                self._on_change(old, new_value)
            return True
        return False

    def set(self, value: T) -> None:
        """Explicit assignment — unbinds the callable and stores *value*."""
        self._fn = None
        old = self._value
        self._value = value
        if old != value and self._on_change is not None:
            self._on_change(old, value)
