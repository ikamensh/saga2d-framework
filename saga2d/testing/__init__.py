"""Testing helpers for saga2d games.

One public helper today: :func:`assert_scene_matches_snapshot`, which
compares a scene's declared structure (via :meth:`Scene.summary_json`
from iter-22) against a stored JSON snapshot. First run writes the
snapshot; subsequent runs compare and fail with a unified-diff message
on mismatch.

Snapshot testing is the natural consumer of ``summary_json`` — once
you have a stable, machine-readable representation of a scene, you can
regression-test that a feature addition didn't silently restructure an
unrelated scene's UI tree or rebind a key.

Example usage in a test::

    from saga2d.testing import assert_scene_matches_snapshot

    def test_dial_menu_scene_shape(game, snapshot_dir):
        scene = DialMenuScene()
        game._scene_stack.push(scene)
        game.tick(dt=1 / 60)
        assert_scene_matches_snapshot(scene, "dial_menu", snapshot_dir)
"""

from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from saga2d.scene import Scene


_UPDATE_ENV_VAR = "SAGA2D_UPDATE_SNAPSHOTS"


def _should_update_snapshots() -> bool:
    """True when the current env requests wholesale snapshot updates.

    Recognises ``SAGA2D_UPDATE_SNAPSHOTS=1`` / ``true`` / ``yes`` /
    ``on`` (case-insensitive). Empty, unset, or ``0`` means no
    update — a matched snapshot still passes without rewriting.
    """
    raw = os.environ.get(_UPDATE_ENV_VAR, "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


def assert_scene_matches_snapshot(
    scene: Scene,
    name: str,
    snapshot_dir: Path | str,
) -> None:
    """Compare a scene's ``summary_json()`` output to a stored snapshot.

    On the **first run** (no snapshot file exists), the current output
    is written to ``{snapshot_dir}/{name}.json`` and the function
    returns without raising — bootstrapping the snapshot.

    On **subsequent runs**, the stored JSON is loaded and compared to
    the current ``summary_json`` dict. If the two differ, an
    ``AssertionError`` is raised whose message contains a unified
    diff of the two pretty-printed JSON forms so the caller can see
    exactly which field changed.

    **Bulk update mode.** Run the whole test suite with
    ``SAGA2D_UPDATE_SNAPSHOTS=1 pytest`` and every snapshot assertion
    overwrites its file with the current value and passes. Use after
    an intentional framework change that legitimately shifts many
    scene structures at once. Review the resulting diff in git
    before committing.

    To accept a single new snapshot without the env-var, delete
    ``{snapshot_dir}/{name}.json`` and re-run.

    Parameters
    ----------
    scene:        Any saga2d :class:`Scene` whose ``summary_json()``
                  returns a JSON-serialisable dict.
    name:         Snapshot file basename (without extension). Use one
                  name per scene to avoid cross-test pollution.
    snapshot_dir: Directory containing the snapshot JSON files. Usually
                  a path alongside the test file.
    """
    snapshot_path = Path(snapshot_dir) / f"{name}.json"
    actual = scene.summary_json()
    actual_text = json.dumps(actual, indent=2) + "\n"

    if _should_update_snapshots():
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(actual_text)
        return

    if not snapshot_path.exists():
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(actual_text)
        return

    expected_text = snapshot_path.read_text()
    expected = json.loads(expected_text)

    if actual == expected:
        return

    diff_lines = difflib.unified_diff(
        expected_text.splitlines(),
        actual_text.rstrip("\n").splitlines(),
        fromfile=f"{name}.json (stored)",
        tofile=f"{name}.json (actual)",
        lineterm="",
        n=3,
    )
    diff = "\n".join(diff_lines)
    raise AssertionError(
        f"Scene snapshot '{name}' does not match {snapshot_path}.\n"
        f"{diff}\n"
        f"To accept the new snapshot: delete the file above and re-run,\n"
        f"or bulk-accept with SAGA2D_UPDATE_SNAPSHOTS=1 pytest."
    )
