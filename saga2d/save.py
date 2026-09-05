"""Save/Load system — manages save file I/O, slot listing, and metadata.

A :class:`SaveManager` is owned lazily by :class:`~saga2d.game.Game`.  Save
files are stored as JSON in a configurable save directory.  Each slot is a
separate file: ``save_1.json``, ``save_2.json``, etc. A successful overwrite
retains the previous valid envelope in ``save_1.backup.json``. Recovery is
explicit through :meth:`SaveManager.load_backup`; damaged current files
are never silently replaced or loaded from backups.

File format::

    {
        "version": 1,
        "timestamp": "2026-02-23T14:30:00",
        "scene_class": "WorldMapScene",
        "state": { ... game-defined state dict ... }
    }

Only envelope version 1 is supported; missing and unknown versions fail
explicitly. ``scene_class`` is informational — the game code decides how
to reconstruct scenes and owns versioning/validation of its nested state.
``state`` is the game-provided dict from :meth:`Scene.get_save_state`.

Usage::

    # Saving (framework calls this internally via game.save):
    game.save(slot=1)

    # Loading (returns data dict, game code handles reconstruction):
    data = game.load(slot=1)
    if data:
        scene = MyScene()
        game.replace(scene)
        scene.load_save_state(data["state"])
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from saga2d._fileio import durable_write


class SaveError(Exception):
    """A save cannot be read/written, or its envelope is invalid/unsupported."""


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"Non-finite JSON number {value} is not supported")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        _reject_nonfinite(value)
    return number


class SaveManager:
    """Manages save file I/O, slot listing, and metadata.

    Parameters:
        save_dir: Directory where save files are stored.  Created
            automatically if it doesn't exist.
    """

    def __init__(self, save_dir: Path | str) -> None:
        self._save_dir = Path(save_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(
        self,
        slot: int,
        state: dict[str, Any],
        scene_class_name: str,
    ) -> None:
        """Write *state* to the save file for *slot*.

        Creates the directory if needed. New content is serialized and synced
        to a unique temporary file before replacement; the preceding valid
        save is retained as a backup. POSIX directory entries are also synced.
        An invalid current file blocks overwrite and leaves both files intact.

        Parameters:
            slot: Slot number (1-indexed by convention).
            state: JSON-serializable dict of game state.
            scene_class_name: Name of the scene class for informational
                purposes (e.g. ``"WorldMapScene"``).

        Raises:
            TypeError: If slot is not an int.
            ValueError: If slot < 1.
            SaveError: Invalid current envelope, invalid new state, or I/O
                failure. Before replacement, a failure leaves current data
                unchanged; a retained backup remains available for recovery.
        """
        path = self._slot_path(slot)
        try:
            payload: dict[str, Any] = {
                "version": 1,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "scene_class": scene_class_name,
                "state": state,
            }
            self._validate_payload(payload)
            text = json.dumps(payload, indent=2, allow_nan=False)
            previous = self.load(slot)
            backup = None if previous is None else (
                self._backup_path(slot), json.dumps(previous, indent=2, allow_nan=False).encode("utf-8")
            )
            durable_write(path, text.encode("utf-8"), backup=backup)
        except (OSError, TypeError, ValueError, RecursionError) as exc:
            raise SaveError(
                f"Cannot write save file for slot {slot}: {path}: {exc}"
            ) from exc

    def load(self, slot: int) -> dict[str, Any] | None:
        """Read the save file for *slot*.

        Returns the full save dict (version, timestamp, scene_class, state)
        or ``None`` if the slot is empty (file doesn't exist).

        Raises:
            TypeError: If slot is not an int.
            ValueError: If slot < 1.
            SaveError: Corrupt JSON, unsupported envelope version, invalid
                metadata/state shape, or I/O failure. Game-state semantics
                belong to the game's own decoder.
        """
        return self._load_path(self._slot_path(slot))

    def load_backup(self, slot: int) -> dict[str, Any] | None:
        """Read the previous valid save without replacing the current file.

        Recovery is explicit: :meth:`load` never substitutes a backup for a
        damaged current save. Missing backups return ``None``; invalid ones
        raise ``SaveError``. Callers decide whether to resume or save elsewhere.
        """
        return self._load_path(self._backup_path(slot))

    def list_slots(self, count: int = 10) -> list[dict[str, Any] | None]:
        """Return metadata for slots 1 through *count*.

        Each entry is a dict with ``version``, ``timestamp``,
        ``scene_class``, and ``slot`` keys — or ``None`` for empty slots.

        If *count* <= 0, returns an empty list.
        """
        result: list[dict[str, Any] | None] = []
        for i in range(1, count + 1):
            data = self.load(i)
            if data is not None:
                # Add the slot number for convenience.
                data["slot"] = i
            result.append(data)
        return result

    def delete(self, slot: int) -> None:
        """Delete the current file, retaining its recovery backup; empty is a no-op."""
        path = self._slot_path(slot)
        path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _slot_path(self, slot: int) -> Path:
        """Return the file path for a given slot number."""
        if not isinstance(slot, int):
            raise TypeError(f"slot must be an int, got {type(slot).__name__}")
        if slot < 1:
            raise ValueError("slot must be >= 1")
        return self._save_dir / f"save_{slot}.json"

    def _backup_path(self, slot: int) -> Path:
        return self._slot_path(slot).with_suffix(".backup.json")

    def _load_path(self, path: Path) -> dict[str, Any] | None:
        try:
            text = path.read_text(encoding="utf-8")
            return self._validate_payload(json.loads(text, parse_constant=_reject_nonfinite, parse_float=_finite_float))
        except FileNotFoundError:
            return None
        except (ValueError, TypeError, OSError, RecursionError) as exc:
            raise SaveError(f"Cannot load save file {path}: {exc}") from exc

    @staticmethod
    def _validate_payload(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError(f"Expected a JSON object, got {type(data).__name__}")
        if type(data.get("version")) is not int or data["version"] != 1:
            raise ValueError(f"Unsupported save format version {data.get('version')!r}; expected version 1")
        if not isinstance(data.get("timestamp"), str):
            raise ValueError("Save timestamp must be an ISO date/time string")
        try:
            datetime.fromisoformat(data["timestamp"])
        except ValueError as exc:
            raise ValueError(f"Invalid save timestamp {data['timestamp']!r}") from exc
        if not isinstance(data.get("scene_class"), str) or not data["scene_class"].strip():
            raise ValueError("Save scene_class must be a nonempty string")
        if not isinstance(data.get("state"), dict):
            raise ValueError("Save state must be a JSON object")
        return data
