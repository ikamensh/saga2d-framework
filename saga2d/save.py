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

A slot is a positive number (``save_1.json``) or a name such as
``"autosave"`` (``save_autosave.json``).  ``summary`` is a small dict the
game supplies for its save browser (map, clock, players…); it is returned
by ``list_slots`` without loading the whole state.

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

    def __init__(self, save_dir: Path | str) -> None:
        self._save_dir = Path(save_dir) if not isinstance(save_dir, Path) else save_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(
        self,
        slot: int | str,
        state: dict[str, Any],
        scene_class_name: str,
        *,
        summary: dict[str, Any] | None = None,
    ) -> None:
        """Write *state* to the save file for *slot*.

        Creates the save directory if it doesn't already exist.  Overwrites
        any existing save in the same slot.

        Parameters:
            slot: Slot number (1-indexed by convention) or name.
            state: JSON-serializable dict of game state.
            scene_class_name: Name of the scene class for informational
                purposes (e.g. ``"WorldMapScene"``).
            summary: Small JSON-serializable dict shown by save browsers.

        Raises:
            TypeError: If slot is not an int or str.
            ValueError: If slot < 1 or the name is empty.
            SaveError: If the file cannot be written (permission, I/O, or
                non-serializable state).
        """
        self._check_slot(slot)
        try:
            self._save_dir.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "version": 1,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "scene_class": scene_class_name,
                "summary": summary or {},
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

    def load(self, slot: int | str) -> dict[str, Any] | None:
        """Read the save file for *slot*.

        Returns the full save dict (version, timestamp, scene_class, summary,
        state) or ``None`` if the slot is empty (file doesn't exist).

        Raises:
            TypeError: If slot is not an int or str.
            ValueError: If slot < 1 or the name is empty.
            SaveError: If the file exists but cannot be parsed (corrupted
                JSON, I/O error, etc.).
        """
        self._check_slot(slot)
        path = self._slot_path(slot)
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
            if not isinstance(data, dict) or not isinstance(data.get("state"), dict) or "scene_class" not in data:
                raise SaveError(
                    f"Corrupted save file in slot {slot}: {path} "
                    f"(not a save: delete the file to clear this slot)"
                )
            data.setdefault("summary", {})
            return cast(dict[str, Any], data)
        except (json.JSONDecodeError, TypeError, OSError, UnicodeDecodeError) as exc:
            raise SaveError(
                f"Corrupted save file in slot {slot}: {path} "
                f"(delete the file to clear this slot)"
            ) from exc

    def list_slots(self, count: int = 10, names: tuple[str, ...] = ()) -> list[dict[str, Any] | None]:
        """Metadata for slots 1 through *count* and then each of *names*.

        Each entry is a dict with ``version``, ``timestamp``, ``scene_class``,
        ``summary`` and ``slot`` keys — or ``None`` for an empty slot.  A slot
        whose file is corrupt is reported as ``{"slot": ..., "error": ...}``
        so a browser can show it instead of failing.
        """
        result: list[dict[str, Any] | None] = []
        for slot in [*range(1, count + 1), *names]:
            try:
                data = self.load(slot)
            except SaveError as exc:
                result.append({"slot": slot, "error": str(exc)})
                continue
            if data is not None:
                data["slot"] = slot
                del data["state"]  # the browser only needs the metadata
            result.append(data)
        return result

    def delete(self, slot: int | str) -> None:
        """Delete the save file for *slot*.  No-op if slot is empty."""
        self._check_slot(slot)
        path = self._slot_path(slot)
        if path.exists():
            path.unlink()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_slot(slot: int | str) -> None:
        if isinstance(slot, bool) or not isinstance(slot, (int, str)):
            raise TypeError(f"slot must be an int or a name, got {type(slot).__name__}")
        if isinstance(slot, int) and slot < 1:
            raise ValueError("slot must be >= 1")
        if isinstance(slot, str) and not slot.isidentifier():
            raise ValueError(f"slot name must be a simple word, got {slot!r}")

    def _slot_path(self, slot: int | str) -> Path:
        """Return the file path for a given slot number or name."""
        return self._save_dir / f"save_{slot}.json"
