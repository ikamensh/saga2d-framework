"""Save/Load system — manages save file I/O, slot listing, and metadata.

A :class:`SaveManager` is owned lazily by :class:`~saga2d.game.Game`.  Save
files are stored as JSON in a configurable save directory.  Each slot is a
separate file: ``save_1.json``, ``save_2.json``, etc.

File format::

    {
        "version": 1,
        "timestamp": "2026-02-23T14:30:00",
        "scene_class": "WorldMapScene",
        "state": { ... game-defined state dict ... }
    }

The ``version`` field is for forward compatibility.  ``scene_class`` is
informational — the game code decides how to reconstruct scenes.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast


class SaveError(Exception):
    """Raised when a save file cannot be read or is corrupted."""

    pass


class SaveManager:
    """Manages save file I/O, slot listing, and metadata.

    Parameters:
        save_dir: Directory where save files are stored.  Created
            automatically if it doesn't exist.
    """

    def __init__(self, save_dir: Path) -> None:
        self._save_dir = save_dir

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

        Creates the save directory if it doesn't already exist.  Overwrites
        any existing save in the same slot.

        Parameters:
            slot: Slot number (1-indexed by convention).
            state: JSON-serializable dict of game state.
            scene_class_name: Name of the scene class for informational
                purposes (e.g. ``"WorldMapScene"``).

        Raises:
            TypeError: If slot is not an int.
            ValueError: If slot < 1.
            SaveError: If the file cannot be written (permission, I/O, or
                non-serializable state).
        """
        if not isinstance(slot, int):
            raise TypeError(f"slot must be an int, got {type(slot).__name__}")
        if slot < 1:
            raise ValueError("slot must be >= 1")
        try:
            self._save_dir.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "version": 1,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "scene_class": scene_class_name,
                "state": state,
            }
            path = self._slot_path(slot)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(path)  # atomic on POSIX, near-atomic on Windows
        except (PermissionError, OSError, TypeError) as exc:
            raise SaveError(
                f"Cannot write save file for slot {slot}: {self._slot_path(slot)}: {exc}"
            ) from exc

    def load(self, slot: int) -> dict[str, Any] | None:
        """Read the save file for *slot*.

        Returns the full save dict (version, timestamp, scene_class, state)
        or ``None`` if the slot is empty (file doesn't exist).

        Raises:
            TypeError: If slot is not an int.
            ValueError: If slot < 1.
            SaveError: If the file exists but cannot be parsed (corrupted
                JSON, I/O error, etc.).
        """
        if not isinstance(slot, int):
            raise TypeError(f"slot must be an int, got {type(slot).__name__}")
        if slot < 1:
            raise ValueError("slot must be >= 1")
        path = self._slot_path(slot)
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8")
            return cast(dict[str, Any], json.loads(text))
        except (json.JSONDecodeError, TypeError, OSError) as exc:
            raise SaveError(
                f"Corrupted save file in slot {slot}: {path} "
                f"(delete the file to clear this slot)"
            ) from exc

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
        """Delete the save file for *slot*.  No-op if slot is empty."""
        if not isinstance(slot, int):
            raise TypeError(f"slot must be an int, got {type(slot).__name__}")
        if slot < 1:
            raise ValueError("slot must be >= 1")
        path = self._slot_path(slot)
        if path.exists():
            path.unlink()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _slot_path(self, slot: int) -> Path:
        """Return the file path for a given slot number."""
        return self._save_dir / f"save_{slot}.json"
