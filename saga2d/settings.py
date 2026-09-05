"""Settings — a JSON file of user preferences with defaults.

::

    settings = Settings(game.data_dir / "settings.json", {"music": 0.6, "sfx": 0.8, "edge_scroll": True})
    settings["music"] = 0.4
    settings.save()

Missing keys take their default. A failed load exposes ``error`` and keeps
defaults in memory; ordinary ``save`` refuses to overwrite invalid disk data.
To recover explicitly, call ``reset()`` then ``save()``. The displaced file
is retained unchanged alongside the new settings in a unique recovery file.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterator, Mapping, MutableMapping
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from saga2d._fileio import durable_write


class SettingsError(Exception):
    """Preferences cannot be validated, read or written safely."""


def _check_json(value: Any) -> None:
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 64:
            raise ValueError("Settings exceed the supported nesting depth of 64")
        kind = type(item)
        if kind is dict:
            if any(type(key) is not str for key in item):
                raise ValueError("Settings object keys must be strings")
            pending.extend((child, depth + 1) for child in item.values())
        elif kind is list:
            pending.extend((child, depth + 1) for child in item)
        elif kind is float:
            if not math.isfinite(item):
                raise ValueError("Settings numbers must be finite")
        elif kind not in (str, bool, int, type(None)):
            raise ValueError(f"Settings cannot contain {kind.__name__} values")


def _kind(value: Any) -> type:
    return float if type(value) in (int, float) else type(value)


def _finite_number(text: str) -> float:
    number = float(text)
    if not math.isfinite(number):
        raise ValueError("Settings numbers must be finite")
    return number


class Settings(MutableMapping[str, Any]):
    """A small persisted mapping, separate from campaign save state.

    Known keys retain their default's JSON kind. Finite integers and floats
    share the numeric kind; booleans do not. Unknown keys survive load/save.
    All values must be JSON data with string object keys and nesting <= 64.
    Nested containers are JSON data, not an inferred options schema.

    ``validator`` inspects values and raises ``ValueError`` for game-owned
    ranges/enums. It runs on defaults, loads, assignments and saves, and must
    not mutate values. Invalid edits/defaults/writes raise ``SettingsError``;
    a load failure instead sets ``error`` so a game can show a recovery screen.
    """

    def __init__(self, path: Path | str, defaults: Mapping[str, Any], *,
                 validator: Callable[[Mapping[str, Any]], None] | None = None) -> None:
        self.path = Path(path).expanduser()
        self.defaults = dict(defaults)
        self._validator = validator
        try:
            self._validate(self.defaults)
        except (ValueError, RecursionError) as exc:
            raise SettingsError(f"Invalid settings defaults: {exc}") from exc
        self.defaults = deepcopy(self.defaults)
        self._values: dict[str, Any] = deepcopy(self.defaults)
        self.error: str | None = None
        self.load()

    def load(self) -> None:
        """Reload, discarding unsaved edits/reset; invalid data sets ``error``."""
        self._values = deepcopy(self.defaults)
        self.error = None
        self._reset_pending = False
        try:
            data = self._decode(self.path.read_bytes())
        except FileNotFoundError:
            return
        except (OSError, ValueError, RecursionError) as exc:
            self.error = f"{self.path}: {exc}"
            return
        self._values = data

    def _decode(self, raw: bytes) -> dict[str, Any]:
        data = json.loads(raw.decode("utf-8"), parse_constant=_finite_number, parse_float=_finite_number)
        if type(data) is not dict:
            raise ValueError(f"Expected a settings object, got {type(data).__name__}")
        values = {**deepcopy(self.defaults), **data}
        self._validate(values)
        return values

    def _validate(self, values: dict[str, Any]) -> None:
        _check_json(values)
        for key, value in values.items():
            if key in self.defaults and _kind(value) is not _kind(self.defaults[key]):
                raise ValueError(f"Setting {key!r} must have the same JSON kind as its default")
        if self._validator is not None:
            self._validator(values)

    def save(self) -> None:
        """Durably write preferences, retaining previous data before replacement.

        Ordinary saves revalidate the current file and retain it at
        ``<stem>.backup.json``. After ``reset()``, the next successful save
        retains current bytes at ``<stem>.recovery-<unique id><suffix>`` instead,
        including malformed/non-UTF8 data. Existing recovery files and the
        ordinary backup are left intact. Failed writes raise ``SettingsError``
        and keep reset pending for retry. A post-replacement sync failure can
        leave the new file visible; the retained copy still holds prior data.
        """
        try:
            self._validate(self._values)
            data = json.dumps(self._values, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
            try:
                previous = self.path.read_bytes()
            except FileNotFoundError:
                previous = None
            backup = None
            if previous is not None:
                if self._reset_pending:
                    backup_path = self.path.with_name(f"{self.path.stem}.recovery-{uuid4().hex}{self.path.suffix}")
                else:
                    self._decode(previous)
                    backup_path = self.path.with_suffix(".backup.json")
                backup = (backup_path, previous)
            durable_write(self.path, data, backup=backup)
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            self.error = f"Cannot save settings {self.path}: {exc}"
            raise SettingsError(self.error) from exc
        self.error = None
        self._reset_pending = False

    def reset(self) -> None:
        """Restore defaults in memory and authorize retained recovery on save.

        No file changes until ``save()``; an existing error remains visible
        until that save succeeds. ``load()`` cancels an unsaved reset.
        """
        self._values = deepcopy(self.defaults)
        self._reset_pending = True

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __setitem__(self, key: str, value: Any) -> None:
        values = {**self._values, key: value}
        try:
            self._validate(values)
        except (ValueError, RecursionError) as exc:
            raise SettingsError(f"Invalid settings edit: {exc}") from exc
        self._values = values

    def __delitem__(self, key: str) -> None:
        del self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"Settings({self.path}, {self._values})"
