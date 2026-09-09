"""Build, verify and install standalone saga2d games with PyInstaller.

A game describes itself with a :class:`GamePackage` and exposes the three
commands through a ten-line ``tools/package.py``::

    uv run --extra package python tools/package.py build --version 0.1.0 --installer
    uv run --extra package python tools/package.py verify dist/warband --native
    uv run --extra package python tools/package.py install

``build`` freezes a snapshot of the installed ``saga2d``, ``sagaforge`` and game
packages with this module's PyInstaller recipe; ``verify`` (``saga2d.packaging.verify``)
runs the shipped executable against a real room server; ``install`` puts the
Mac app bundle into /Applications after both self-tests pass.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from importlib import import_module, metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig

PYTHON = "3.13.2"
RUNTIME = ("numpy", "Pillow", "pyglet", "websockets")
TOOLS = ("pyinstaller", "pyinstaller-hooks-contrib")
RECIPE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class GamePackage:
    """Everything the shared recipe needs to know about one game."""
    game: str                 # artifact and build directory name, e.g. "warband"
    product: str              # display name, e.g. "Warband"
    package: str              # importable package, e.g. "warband"
    online: str               # server registry, e.g. "warband.multiplayer:ONLINE"
    bundle_id: str            # macOS bundle identifier
    installer_id: str         # stable Inno Setup AppId GUID
    hiddenimports: tuple[str, ...]
    documents: dict[str, str]  # release document name -> path relative to root
    root: Path                # the game repository: git identity, LICENSE, uv.lock, docs
    check: Path               # the game's package_check.py with smoke() and native_smoke()


def version(value: str) -> str:
    """Use a filename-safe version that Inno Setup can also represent numerically."""
    match = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?", value)
    if match is None or any(int(part) > 65535 for part in match.groups()):
        raise argparse.ArgumentTypeError("Use MAJOR.MINOR.PATCH with an optional prerelease suffix; each number must be <=65535.")
    return value


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def package_dir(name: str) -> Path:
    """The installed location of a Python package, wherever its repository lives."""
    return Path(import_module(name).__file__).resolve().parent


def copy_licenses(output: Path) -> None:
    output.mkdir(parents=True)
    for name in (*RUNTIME, "pyinstaller"):
        distribution = metadata.distribution(name)
        found = False
        for item in distribution.files or ():
            if any(part.upper().startswith(("LICENSE", "COPYING")) for part in item.parts):
                origin = Path(distribution.locate_file(item))
                if origin.is_file():
                    target = output / name / item
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(origin, target)
                    found = True
        if not found:
            raise RuntimeError(f"No license files found for {name}")
    candidates = [Path(sys.base_prefix) / "LICENSE.txt", Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"]
    python_license = next((path for path in candidates if path.is_file()), None)
    if python_license is None:
        raise FileNotFoundError("The build interpreter must include CPython's LICENSE.txt")
    shutil.copyfile(python_license, output / "CPython-LICENSE.txt")


def snapshot(spec: GamePackage, version: str) -> tuple[Path, dict]:
    """Freeze the installed packages, recipe and release documents; return the source dir and build info."""
    root = spec.root.resolve()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip())
    source = root / "build" / spec.game / "source"
    if source.exists():
        shutil.rmtree(source)
    source.mkdir(parents=True)
    for name in ("saga2d", "sagaforge", spec.package):
        shutil.copytree(package_dir(name), source / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    entry = (RECIPE / "entry.py").read_text(encoding="utf-8").replace('"__PACKAGE__"', repr(spec.package))
    (source / "entry.py").write_text(entry, encoding="utf-8")
    shutil.copyfile(spec.check, source / "package_check.py")
    for name in ("game.spec", "game.iss"):
        shutil.copyfile(RECIPE / name, source / name)
    release = source / "release"
    release.mkdir()
    documents = {"LICENSE": "LICENSE", **spec.documents, "uv.lock": "uv.lock"}
    for name, origin in documents.items():
        shutil.copyfile(root / origin, release / name)
    (release / "build-tools.txt").write_text("".join(f"{name}=={metadata.version(name)}\n" for name in TOOLS), encoding="utf-8")
    copy_licenses(release / "licenses")
    info = {
        "product": spec.product, "game": spec.game, "version": version, "source_commit": commit, "working_tree_dirty": dirty,
        "built_at_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
        "architecture": platform.machine(), "python": platform.python_version(),
        "packages": {name: metadata.version(name) for name in (*RUNTIME, *TOOLS)},
        "source_sha256": {path.relative_to(source).as_posix(): sha256(path) for path in sorted(source.rglob("*")) if path.is_file()},
        "packaging": {"package": spec.package, "entry": "entry.py", "bundle_id": spec.bundle_id,
                      "hiddenimports": [*spec.hiddenimports, f"{spec.package}.__main__", "package_check"],
                      "excludes": ["pytest", "tkinter"]},
        "runtime_verified": False,
    }
    write_json(release / "build-info.json", info)
    return source, info


def build(spec: GamePackage, version: str, *, output: Path | None = None, installer: bool = False,
          iscc: Path | None = None, require_clean: bool = False) -> Path:
    """Build the portable archive (and on Windows the installer) into ``output``; return that directory."""
    if platform.python_version() != PYTHON:
        raise RuntimeError(f"Build with the pinned CPython {PYTHON}, for example `uv run --python {PYTHON}`")
    if installer and platform.system() != "Windows":
        raise RuntimeError("The Windows installer must be built on Windows")
    root = spec.root.resolve()
    source, info = snapshot(spec, version)
    if require_clean and info["working_tree_dirty"]:
        raise RuntimeError("Release builds require a clean working tree")
    output = (output or root / "dist" / spec.game).resolve()
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(output),
                    "--workpath", str(source.parent / "pyinstaller"), str(source / "game.spec")], cwd=root,
                   env={**os.environ, "SAGA2D_BUILD_SOURCE": str(source)}, check=True)
    product = spec.product
    target = "windows-x64" if platform.system() == "Windows" else f"{platform.system().lower()}-{platform.machine().lower()}"
    archive = Path(shutil.make_archive(str(output / f"{product}-{version}-{target}-portable"), "zip", output, product))
    artifacts = [archive]
    if installer:
        compiler = iscc or shutil.which("ISCC.exe")
        if not compiler:
            candidate = Path(os.environ["ProgramFiles(x86)"]) / "Inno Setup 6" / "ISCC.exe"
            if candidate.is_file():
                compiler = str(candidate)
        if not compiler:
            raise FileNotFoundError("Install Inno Setup or pass --iscc with the path to ISCC.exe")
        subprocess.run([str(compiler), f"/DAppName={product}", f"/DAppId={spec.installer_id}",
                        f"/DAppVersion={version}", f"/DAppNumericVersion={version.partition('-')[0]}.0",
                        f"/DSourceDir={output / product}", f"/DOutputDir={output}", str(source / "game.iss")], check=True)
        artifacts.append(output / f"{product}-{version}-windows-x64-setup.exe")
    info["artifacts"] = [{"file": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)} for path in artifacts]
    write_json(output / "build-manifest.json", info)
    (output / "SHA256SUMS").write_text("".join(f"{item['sha256']}  {item['file']}\n" for item in info["artifacts"]), encoding="ascii")
    print(f"Built {product} {version} from {info['source_commit']}. Verify before publishing.", flush=True)
    return output


def main(spec: GamePackage, argv: list[str] | None = None) -> None:
    """The command line shared by every game's ``tools/package.py``."""
    from saga2d.packaging.install import install_mac
    from saga2d.packaging.verify import verify

    parser = argparse.ArgumentParser(description=f"Build, verify and install the standalone {spec.product} app")
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build", help="freeze a versioned portable archive (and Windows installer)")
    builder.add_argument("--version", required=True, type=version)
    builder.add_argument("--output", type=Path)
    builder.add_argument("--installer", action="store_true")
    builder.add_argument("--iscc", type=Path)
    builder.add_argument("--require-clean", action="store_true")
    verifier = commands.add_parser("verify", help="run the built executable against a real room server")
    verifier.add_argument("output", type=Path)
    verifier.add_argument("--native", action="store_true")
    verifier.add_argument("--public-server", help="also require the installed executable to pass its online check over this wss:// endpoint")
    verifier.add_argument("--mesa-dir", type=Path, help="test-only x64 Mesa WGL DLLs for CI hosts without a graphics driver")
    installer = commands.add_parser("install", help="build, self-test and install the Mac app bundle")
    installer.add_argument("--version", default=None, help="build version (default: <project version>-local.<commit>)")
    installer.add_argument("--output", type=Path, default=None, help="build directory (default: dist/<game>-local)")
    installer.add_argument("--skip-build", action="store_true", help="install the bundle already in --output")
    installer.add_argument("--allow-dirty", action="store_true", help="build from an uncommitted working tree")
    installer.add_argument("--applications", type=Path, default=Path("/Applications"))
    args = parser.parse_args(argv)
    if args.command == "build":
        build(spec, args.version, output=args.output, installer=args.installer, iscc=args.iscc, require_clean=args.require_clean)
    elif args.command == "verify":
        verify(spec, args.output, native=args.native, public_server=args.public_server, mesa_dir=args.mesa_dir)
    else:
        install_mac(spec, version=args.version, output=args.output, skip_build=args.skip_build,
                    allow_dirty=args.allow_dirty, applications=args.applications)
