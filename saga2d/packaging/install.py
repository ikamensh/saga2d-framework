"""Install a freshly built Mac app bundle into /Applications after two self-tests.

The previous ``/Applications/<Game>.app`` is kept under ``dist/local-app-backups/``
before the new bundle is copied in with ``ditto`` (which preserves the ad-hoc
signature).  Both the fresh bundle and the installed one must pass the game's
``--selftest`` (a hidden window, one frame saved to PNG); the display must be
awake for that, so the self-tests run under ``caffeinate``.  A receipt with the
commit, version and executable hash is written beside the build.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tomllib

from saga2d.packaging import GamePackage, build, sha256


def run(command: list[str], cwd: Path, **kwargs) -> None:
    print("$", " ".join(str(part) for part in command), flush=True)
    subprocess.run(command, cwd=cwd, check=True, **kwargs)


def default_version(root: Path) -> str:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=root, text=True).strip()
    return f"{project}-local.{commit}"


def selftest(app: Path, png: Path) -> None:
    """The bundle starts a match in a hidden window and writes one frame, or fails loudly."""
    executable = app / "Contents" / "MacOS" / app.stem
    png.parent.mkdir(parents=True, exist_ok=True)
    run(["caffeinate", "-u", "-i", str(executable), "--selftest", str(png)], cwd=app.parent, timeout=300)
    if not png.is_file() or png.stat().st_size < 10_000:
        raise RuntimeError(f"{app} self-test wrote no usable frame at {png}")


def install_mac(spec: GamePackage, *, version: str | None = None, output: Path | None = None, skip_build: bool = False,
                allow_dirty: bool = False, applications: Path = Path("/Applications")) -> Path:
    """Build (unless ``skip_build``), self-test, back up the installed app, install and self-test again."""
    if platform.system() != "Darwin":
        raise SystemExit("install works on Mac app bundles; on Windows run the installer from `build --installer`.")
    root = spec.root.resolve()
    product = spec.product
    output = (output or root / "dist" / f"{spec.game}-local").resolve()
    version = version or default_version(root)
    if not skip_build:
        if output.exists():
            shutil.rmtree(output)
        build(spec, version, output=output, require_clean=not allow_dirty)
    app = output / f"{product}.app"
    if not app.is_dir():
        raise SystemExit(f"No {app}; build first or pass --output")
    manifest = json.loads((output / "build-manifest.json").read_text(encoding="utf-8"))
    selftest(app, output / "selftest-built.png")

    installed = applications / f"{product}.app"
    backup = None
    if installed.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        backup = root / "dist" / "local-app-backups" / f"{product}-before-{version}-{stamp}.app"
        backup.parent.mkdir(parents=True, exist_ok=True)
        run(["ditto", str(installed), str(backup)], cwd=root)
        shutil.rmtree(installed)
    run(["ditto", str(app), str(installed)], cwd=root)
    selftest(installed, output / "selftest-installed.png")

    executable = installed / "Contents" / "MacOS" / product
    receipt = {
        "game": spec.game, "version": version, "commit": manifest["source_commit"], "installed": str(installed),
        "executable_sha256": sha256(executable), "backup": str(backup) if backup else None,
        "installed_at_utc": datetime.now(timezone.utc).isoformat(), "frames": ["selftest-built.png", "selftest-installed.png"],
    }
    (output / "install-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"Installed {product} {version} ({receipt['commit']}) at {installed}; previous app backed up to {backup}. "
          f"Frames: {output / 'selftest-built.png'}, {output / 'selftest-installed.png'}")
    return installed
