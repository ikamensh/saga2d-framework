"""Build and attach a game's mypyc modules without putting game rules in Saga2D.

``CompiledPackage`` owns the source-keyed build cache and the import handoff.
The game chooses its modules and calls ``activate`` before importing them. A
spawned worker inherits the selected build through ``env`` and attaches that
same build, refusing sources edited since its parent started.

mypyc and setuptools are needed only when building, not when running a game
with an existing build or running from source.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time

NO_TOOLCHAIN = 3
STALE_AFTER = 3 * 24 * 3600


class NoToolchain(RuntimeError):
    """mypyc or a C compiler is unavailable on this machine."""


_BUILD_SCRIPT = """
import json, sys
from pathlib import Path

config = json.loads(sys.argv[1])
try:
    from mypyc.build import mypycify
    from setuptools import Extension, setup
except ImportError:
    print("mypyc or setuptools is not installed", file=sys.stderr)
    sys.exit(config["no_toolchain"])

probe = Path(config["obj"], "probe.c")
probe.parent.mkdir(parents=True)
probe.write_text("#include <Python.h>\\nPyMODINIT_FUNC PyInit_probe(void) { return NULL; }\\n")
try:
    setup(name="probe", packages=[], py_modules=[], ext_modules=[Extension("probe", [str(probe)])],
          script_args=["build_ext", "--build-lib", str(probe.parent), "--build-temp", str(probe.parent)])
except SystemExit as failed:
    print("no C compiler (" + " ".join(str(failed).split()) + ")", file=sys.stderr)
    sys.exit(config["no_toolchain"])

modules = mypycify([*config["mypy_options"], "--cache-dir=" + config["cache"], *config["paths"]],
                   target_dir=config["c"])
for module in modules:
    module.extra_compile_args.extend(config["flags"])
setup(name=config["name"], packages=[], py_modules=[], ext_modules=modules,
      script_args=["build_ext", "--build-lib", config["out"], "--build-temp", config["obj"]])
"""


class CompiledPackage:
    """One source package's compiled modules, cached and loaded by source identity.

    ``package`` is its source directory, ``modules`` are names relative to it,
    and ``builds`` is a writable cache directory. The game owns the chosen
    module set, compiler flags, and source/compiled equivalence tests.
    """

    def __init__(self, package: Path, modules: tuple[str, ...], builds: Path, env: str, opt_out: str,
                 *, flags: tuple[str, ...] = (), mypy_options: tuple[str, ...] = ("--follow-imports=silent",),
                 stale_after: float = STALE_AFTER) -> None:
        if not modules:
            raise ValueError("A compiled package needs at least one module")
        self.package = Path(package)
        self.modules = modules
        self.builds = Path(builds)
        self.env = env
        self.opt_out = opt_out
        self.flags = flags
        self.mypy_options = mypy_options
        self.stale_after = stale_after
        self._finder: _CompiledFirst | None = None

    @staticmethod
    def source(module: str) -> str:
        """Source path relative to ``package`` for a relative module name."""
        return module.replace(".", "/") + ".py"

    def key(self) -> str:
        """Identity of the module sources, build options, Python and platform."""
        digest = hashlib.sha256()
        digest.update(self.package.name.encode() + b"\0" + _BUILD_SCRIPT.encode() + b"\0")
        for module in self.modules:
            digest.update(module.encode() + b"\0" + (self.package / self.source(module)).read_bytes() + b"\0")
        digest.update(repr((self.flags, self.mypy_options, sys.implementation.cache_tag,
                            sysconfig.get_platform())).encode())
        return digest.hexdigest()[:20]

    def build(self) -> Path:
        """Return a complete compiled build of the current sources, building once if absent."""
        target = self.builds / self.key()
        if target.is_dir():
            return target
        self.builds.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f"{target.name}-", dir=self.builds))
        config = {
            "name": f"{self.package.name}-compiled",
            "paths": [f"{self.package.name}/{self.source(module)}" for module in self.modules],
            "flags": list(self.flags), "mypy_options": list(self.mypy_options), "no_toolchain": NO_TOOLCHAIN,
            "cache": str(staging / "mypy"), "c": str(staging / "c"), "out": str(staging), "obj": str(staging / "obj"),
        }
        print(f"compiling {self.package.name} with mypyc into {target}, once per source change...",
              file=sys.stderr, flush=True)
        done = subprocess.run([sys.executable, "-c", _BUILD_SCRIPT, json.dumps(config)], cwd=self.package.parent,
                              capture_output=True, text=True)
        if done.returncode:
            shutil.rmtree(staging)
            if done.returncode == NO_TOOLCHAIN:
                raise NoToolchain(f"{done.stderr.strip().splitlines()[-1]}; {self.opt_out}=1 runs the source")
            raise RuntimeError(f"mypyc could not compile {self.package.name}:\n{done.stdout[-4000:]}\n{done.stderr[-4000:]}")
        for scratch in ("mypy", "c", "obj"):
            shutil.rmtree(staging / scratch)
        try:
            staging.rename(target)
        except OSError:  # another process published the same build first
            if not target.is_dir():
                raise
            shutil.rmtree(staging)
        self.prune(keep=target)
        return target

    def prune(self, keep: Path) -> None:
        """Remove old builds no process has started on recently."""
        spared = {keep.name, Path(os.environ.get(self.env, keep)).name}
        now = time.time()
        for entry in self.builds.iterdir():
            if entry.name in spared:
                continue
            try:
                if now - entry.stat().st_mtime < self.stale_after:
                    continue
                doomed = entry if entry.name.endswith(".pruned") else entry.rename(entry.with_name(entry.name + ".pruned"))
            except OSError:  # a concurrent build or prune moved it
                if entry.exists():
                    raise
                continue
            try:
                shutil.rmtree(doomed)
            except FileNotFoundError:  # another prune finished first
                pass

    def attach(self, path: str | os.PathLike[str]) -> None:
        """Make the build's modules import before source modules in this process.

        The caller must attach before importing any compiled module. Package
        ``__init__.py`` files stay in source, and nested package initializers
        see the compiled modules when they import them.
        """
        root = Path(path)
        if not root.is_dir():
            raise ImportError(f"the compiled package {root.name} is missing")
        if root.name != self.key():
            raise ImportError(f"the compiled package {root.name} was built from other sources: the current ones make {self.key()}")
        os.utime(root)
        prefix = self.package.name + "."
        packages = {self.package.name}
        for module in self.modules:
            parts = module.split(".")[:-1]
            for depth in range(1, len(parts) + 1):
                packages.add(self.package.name + "." + ".".join(parts[:depth]))
        folders = {name: str(root / name.replace(".", "/")) for name in packages}
        if self._finder is not None and self._finder.folders == folders:
            return
        loaded = sorted(name for name in sys.modules if name.startswith(prefix) and name.removeprefix(prefix) in self.modules)
        if loaded:
            raise RuntimeError(f"the compiled package must be activated before its modules are imported: {loaded}")
        if self._finder is not None:
            sys.meta_path.remove(self._finder)
        self._finder = _CompiledFirst(folders)
        sys.meta_path.insert(0, self._finder)
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        for name, folder in folders.items():
            package = sys.modules.get(name)
            if package is not None:
                package.__path__ = [folder, *package.__path__]
                package.__spec__.submodule_search_locations = package.__path__
        os.environ[self.env] = str(root)

    def activate(self) -> Path | None:
        """Attach this process to its inherited build, or build once and attach it."""
        if os.environ.get(self.opt_out):
            return None
        inherited = os.environ.get(self.env)
        root = Path(inherited) if inherited else self.build()
        self.attach(root)
        return root


class _CompiledFirst:
    """Extend each ancestor's search path before its initializer imports a compiled child."""

    def __init__(self, folders: dict[str, str]) -> None:
        self.folders = folders

    def find_spec(self, fullname: str, path=None, target=None):
        folder = self.folders.get(fullname)
        if folder is None:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.submodule_search_locations is None:
            raise ImportError(f"{fullname} is not a package")
        spec.submodule_search_locations = [folder, *spec.submodule_search_locations]
        return spec
