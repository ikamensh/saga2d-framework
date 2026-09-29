"""A game's compiled modules load through the same package as their source."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from saga2d.compiled import CompiledPackage, NoToolchain


def test_a_compiled_package_runs_and_rejects_changed_sources(tmp_path: Path) -> None:
    """The public build/attach path uses fresh code and refuses a stale binary."""
    package = tmp_path / "samplegame"
    (package / "sim").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "sim" / "__init__.py").write_text("")
    (package / "root.py").write_text("def label() -> str:\n    return 'root'\n")
    source = package / "sim" / "world.py"
    source.write_text("def score(value: int) -> int:\n    return value * 2\n")
    runtime = CompiledPackage(package, ("root", "sim.world"), tmp_path / "builds", "SAMPLEGAME_COMPILED", "SAMPLEGAME_INTERPRETED")
    try:
        build = runtime.build()
    except NoToolchain as exc:
        pytest.skip(str(exc))

    script = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from saga2d.compiled import CompiledPackage
import samplegame, samplegame.sim
runtime = CompiledPackage(Path(sys.argv[1]) / 'samplegame', ('root', 'sim.world'), Path(sys.argv[1]) / 'builds',
                          'SAMPLEGAME_COMPILED', 'SAMPLEGAME_INTERPRETED')
runtime.attach(sys.argv[2])
from samplegame import root
from samplegame.sim import world
print(json.dumps({'score': world.score(21), 'label': root.label(),
                  'compiled': all(module.__file__.endswith(('.so', '.pyd')) for module in (root, world))}))
"""
    env = {key: value for key, value in os.environ.items() if key not in (runtime.env, runtime.opt_out)}
    done = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(build)], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == '{"score": 42, "label": "root", "compiled": true}'

    source.write_text("def score(value: int) -> int:\n    return value * 3\n")
    with pytest.raises(ImportError, match="other sources"):
        runtime.attach(build)


def test_prune_keeps_recent_and_active_builds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An old running build survives, while stale and interrupted builds leave the cache."""
    builds = tmp_path / "builds"
    builds.mkdir()
    runtime = CompiledPackage(tmp_path / "samplegame", ("sim.world",), builds,
                              "SAMPLEGAME_COMPILED", "SAMPLEGAME_INTERPRETED")
    day = 24 * 3600

    def made(name: str, days: float) -> Path:
        entry = builds / name
        entry.mkdir()
        os.utime(entry, (time.time() - days * day,) * 2)
        return entry

    old = made("a" * 20, 4)
    interrupted = made("b" * 20 + "-x1y2z3", 5)
    half_pruned = made("c" * 20 + ".pruned", 9)
    recent = made("d" * 20, 2.5)
    running = made("e" * 20, 30)
    new = made("f" * 20, 30)
    monkeypatch.setenv(runtime.env, str(running))
    runtime.prune(keep=new)
    assert sorted(p.name for p in builds.iterdir()) == sorted(p.name for p in (recent, running, new))
    assert not any(p.exists() for p in (old, interrupted, half_pruned))
def test_a_nested_leaf_is_compiled_before_ancestor_initializers_import_it(tmp_path: Path) -> None:
    """A parent package can import a compiled grandchild during its initializer."""
    package = tmp_path / "nestedgame"
    (package / "sim" / "players").mkdir(parents=True)
    (package / "__init__.py").write_text("from .sim import score\n")
    (package / "sim" / "__init__.py").write_text("from .players.hands import score\n")
    (package / "sim" / "players" / "__init__.py").write_text("from .hands import score\n")
    (package / "sim" / "players" / "hands.py").write_text("def score() -> int:\n    return 42\n")
    runtime = CompiledPackage(package, ("sim.players.hands",), tmp_path / "builds",
                              "NESTEDGAME_COMPILED", "NESTEDGAME_INTERPRETED")
    try:
        build = runtime.build()
    except NoToolchain as exc:
        pytest.skip(str(exc))

    script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from saga2d.compiled import CompiledPackage
runtime = CompiledPackage(Path(sys.argv[1]) / 'nestedgame', ('sim.players.hands',),
                          Path(sys.argv[1]) / 'builds', 'NESTEDGAME_COMPILED', 'NESTEDGAME_INTERPRETED')
runtime.attach(sys.argv[2])
from nestedgame.sim.players import hands
import nestedgame
assert nestedgame.score() == 42
assert hands.__file__.endswith(('.so', '.pyd')), hands.__file__
"""
    env = {key: value for key, value in os.environ.items() if key not in (runtime.env, runtime.opt_out)}
    done = subprocess.run([sys.executable, "-c", script, str(tmp_path), str(build)], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
