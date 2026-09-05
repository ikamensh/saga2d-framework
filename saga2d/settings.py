"""Settings — a JSON file of user preferences with defaults.

::

    settings = Settings(game.data_dir / "settings.json", {"music": 0.6, "sfx": 0.8, "edge_scroll": True})
    settings["music"] = 0.4
    settings.save()

Missing keys take their default; a corrupt file is ignored (``error`` says
why) rather than crashing the game, and the next ``save`` overwrites it.
Values are whatever JSON can hold.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, MutableMapping
from pathlib import Path
from typing import Any


class Settings(MutableMapping[str, Any]):
    def __init__(self, path: Path | str, defaults: Mapping[str, Any]) -> None:
        self.path = Path(path).expanduser()
        self.defaults = dict(defaults)
        self._values: dict[str, Any] = dict(defaults)
        self.error: str | None = None
        self.load()

    def load(self) -> None:
        """Read the file, keeping defaults for whatever it lacks."""
        self._values = dict(self.defaults)
        self.error = None
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.error = f"{self.path}: {exc}"
            return
        if not isinstance(data, dict):
            self.error = f"{self.path}: expected an object, got {type(data).__name__}"
            return
        for key, value in data.items():
            if key in self.defaults and type(value) is not type(self.defaults[key]) and not (isinstance(value, (int, float)) and isinstance(self.defaults[key], (int, float))):
                continue  # the wrong kind of value; keep the default
            self._values[key] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._values, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def reset(self) -> None:
        self._values = dict(self.defaults)

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._values[key] = value

    def __delitem__(self, key: str) -> None:
        del self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"Settings({self.path}, {self._values})"
