"""Verify a built game: manifest integrity, a loopback room server and the shipped executable's own checks.

The application process runs outside the checkout with an isolated profile and
no Python on PATH.  A native rendering receipt is separate from the mandatory
socket acceptance; ``--public-server`` additionally exercises the installed
Windows executable against the live TLS endpoint.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import zipfile

from saga2d.packaging import GamePackage, sha256, write_json


@contextmanager
def local_server(*games):
    """Run the real room server for ``games`` (``module:ATTRIBUTE`` registry names) on a loopback port."""
    from saga2d.server import MAX_MESSAGE, RoomServer, load_games
    from websockets.asyncio.server import serve
    ready, errors = queue.Queue(), queue.Queue()

    async def run():
        rooms = RoomServer(load_games(games), max_rooms=4, max_connections=8, room_ttl=30)
        stopped = asyncio.Event()
        async with serve(rooms.handle, "127.0.0.1", 0, process_request=rooms.health, origins=[None], max_size=MAX_MESSAGE,
                         compression=None, close_timeout=2) as server:
            task = asyncio.create_task(rooms.maintain())
            ready.put((asyncio.get_running_loop(), stopped, f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/play"))
            try:
                await stopped.wait()
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    def worker():
        try:
            asyncio.run(run())
        except Exception as exc:
            errors.put(exc)
            ready.put(None)

    thread = threading.Thread(target=worker, name="package-authority", daemon=True)
    thread.start()
    started = ready.get(timeout=15)
    if started is None:
        raise errors.get()
    loop, stopped, endpoint = started
    try:
        yield endpoint
    finally:
        if thread.is_alive():
            loop.call_soon_threadsafe(stopped.set)
            thread.join(10)
        if thread.is_alive():
            raise RuntimeError("Package verification server did not stop")
        if not errors.empty():
            raise errors.get()


def isolated_environment(profile: Path, original=None) -> dict:
    """Keep OS/DLL configuration while excluding user Python and game overrides."""
    env = dict(os.environ if original is None else original)
    for name in ("PYTHONPATH", "PYTHONHOME", "SAGA2D_SERVER_URL", "SAGA2D_HEADLESS"):
        env.pop(name, None)
    env.update(HOME=str(profile), USERPROFILE=str(profile), SAGA2D_SILENT="1")
    if os.name == "nt":
        system_root = next(value for name, value in env.items() if name.upper() == "SYSTEMROOT")
        env["PATH"] = str(Path(system_root) / "System32") + os.pathsep + system_root
        env["APPDATA"], env["LOCALAPPDATA"] = str(profile / "Roaming"), str(profile / "Local")
    else:
        env["PATH"] = "/usr/bin:/bin"
    return env


@contextmanager
def mesa_test_context(executable: Path, mesa_dir: Path):
    """Provide a temporary software GL driver without changing shipping artifacts."""
    files = [(mesa_dir / name, executable.parent / name) for name in ("opengl32.dll", "libgallium_wgl.dll")]
    for origin, target in files:
        if not origin.is_file():
            raise FileNotFoundError(origin)
        if target.exists():
            raise FileExistsError(f"The test driver must not replace an installed file: {target}")
    copied = []
    try:
        for origin, target in files:
            shutil.copyfile(origin, target)
            copied.append(target)
        yield {"driver": "Mesa llvmpipe (test only)", "dll_sha256": {target.name: sha256(target) for target in copied}}
    finally:
        for target in copied:
            target.unlink()


def executable_smoke(executable: Path, endpoint: str, report: Path, manifest: dict, *, native=False, mesa_dir: Path | None = None) -> dict:
    context = mesa_test_context(executable, mesa_dir) if mesa_dir is not None else nullcontext({})
    with tempfile.TemporaryDirectory(prefix="clean-profile-") as directory, context as graphics:
        profile = Path(directory)
        env = isolated_environment(profile)
        if graphics:
            env.update(GALLIUM_DRIVER="llvmpipe", LP_NUM_THREADS="2")
        option = "--package-native-smoke" if native else "--package-smoke"
        target = report.with_suffix(".png") if native else report
        process = subprocess.run([str(executable), option, str(target), "--endpoint", endpoint], cwd=profile,
                                 env=env, capture_output=True, text=True, timeout=300 if native else 90)
        report.with_suffix(".log").write_text(process.stdout + process.stderr, encoding="utf-8")
        if not report.is_file():
            raise RuntimeError(f"The shipped executable produced no receipt: exit {process.returncode}; {process.stderr}")
        result = json.loads(report.read_text(encoding="utf-8"))
        if process.returncode or not result["passed"]:
            raise RuntimeError(f"Packaged check failed: {result}")
        assert result["source_commit"] == manifest["source_commit"] and result["version"] == manifest["version"], result
        assert result["executable_sha256"] == sha256(executable), "The receipt does not identify the launched executable"
        if graphics:
            assert "llvmpipe" in result["renderer"].lower(), result["renderer"]
            result["graphics_test_context"] = graphics
            write_json(report, result)
        return result


def verify(spec: GamePackage, output: Path, *, native=False, public_server: str | None = None, mesa_dir: Path | None = None) -> dict:
    """Check the build manifest, then run the portable (and installed) executable over real sockets."""
    product = spec.product
    if public_server is not None and not public_server.startswith("wss://"):
        raise ValueError("Public-server acceptance requires an explicit wss:// TLS endpoint")
    if mesa_dir is not None and not native:
        raise ValueError("A Mesa test context requires --native")
    output = output.resolve()
    manifest = json.loads((output / "build-manifest.json").read_text(encoding="utf-8"))
    if manifest["product"] != product:
        raise ValueError(f"{output} holds a {manifest['product']} build, not {product}")
    for item in manifest["artifacts"]:
        path = output / item["file"]
        assert path.stat().st_size == item["bytes"] and sha256(path) == item["sha256"], path
    archive = next(output / item["file"] for item in manifest["artifacts"] if item["file"].endswith(".zip"))
    installers = [output / item["file"] for item in manifest["artifacts"] if item["file"].endswith("-setup.exe")]
    if public_server is not None and not installers:
        raise ValueError("Public-server acceptance requires the Windows installer artifact")
    evidence = output / "verification"
    evidence.mkdir(exist_ok=True)
    report = {"source_commit": manifest["source_commit"], "version": manifest["version"], "scope": "Loopback authority; isolated profile on the named CI host"}
    with tempfile.TemporaryDirectory(prefix="extracted-package-") as directory, local_server() as endpoint:
        extracted = Path(directory)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(extracted)
        executable = extracted / product / (f"{product}.exe" if os.name == "nt" else product)
        if os.name != "nt":
            executable.chmod(executable.stat().st_mode | 0o111)
        report["portable"] = executable_smoke(executable, endpoint, evidence / "portable.json", manifest)
        if installers:
            if os.name != "nt":
                raise RuntimeError("Installer verification requires Windows")
            installed = extracted / f"Installed {product}"
            # DisableProgramGroupPage=yes makes Inno ignore /GROUP. Check the
            # same standard per-user shortcut that a normal install creates.
            shortcut = Path(os.environ["APPDATA"]) / f"Microsoft/Windows/Start Menu/Programs/{product}/{product}.lnk"
            if shortcut.exists():
                raise RuntimeError(f"Run installer verification in a Windows account without an existing {product} installation")
            try:
                subprocess.run([str(installers[0]), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
                                f"/DIR={installed}", f"/LOG={evidence / 'install.log'}"], check=True, timeout=120)
                assert shortcut.is_file(), shortcut
                executable = installed / f"{product}.exe"
                report["installed"] = executable_smoke(executable, endpoint, evidence / "installed.json", manifest)
                if public_server is not None:
                    report["public_server"] = {"endpoint": public_server,
                                               **executable_smoke(executable, public_server, evidence / "public-server.json", manifest)}
                if native:
                    report["native"] = executable_smoke(executable, endpoint, evidence / "native.json", manifest, native=True, mesa_dir=mesa_dir)
            finally:
                uninstaller = installed / "unins000.exe"
                if uninstaller.is_file():
                    subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                                    f"/LOG={evidence / 'uninstall.log'}"], check=True, timeout=120)
            assert not executable.exists() and not shortcut.exists(), "Uninstall left the application or Start menu shortcut"
            report["install_shortcut_uninstall"] = True
        elif native:
            report["native"] = executable_smoke(executable, endpoint, evidence / "native.json", manifest, native=True, mesa_dir=mesa_dir)
    report["passed"] = True
    write_json(output / "verification.json", report)
    print(json.dumps(report, indent=2), flush=True)
    return report

