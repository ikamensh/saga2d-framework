"""The shared packaging recipe's checks, exercised without PyInstaller."""
import argparse
import hashlib
import json
from pathlib import Path
import os

import pytest

from saga2d.packaging import GamePackage, version
from saga2d.packaging.verify import isolated_environment, mesa_test_context, verify

RECIPE = Path(__file__).resolve().parents[2] / "saga2d" / "packaging"


def package(root: Path) -> GamePackage:
    return GamePackage(game="demo", product="Demo", package="saga2d", online="saga2d.testing.online:GAMES",
                       bundle_id="org.saga2d.demo", installer_id="{00000000-0000-0000-0000-000000000000}",
                       hiddenimports=(), documents={}, root=root, check=root / "package_check.py")


def test_recipe_ships_its_spec_installer_script_and_entry():
    """The build copies these by name; a missing file must fail before PyInstaller runs."""
    for name in ("game.spec", "game.iss", "entry.py"):
        assert (RECIPE / name).is_file(), name
    assert '"__PACKAGE__"' in (RECIPE / "entry.py").read_text(encoding="utf-8")


def test_isolated_package_profile_preserves_windows_dll_environment(tmp_path):
    """A clean launch removes user Python overrides without deleting OS configuration."""
    original = {**os.environ, "SystemRoot": "C:\\Windows", "PYTHONPATH": "unrelated-checkout", "PYTHONHOME": "developer-python"}
    clean = isolated_environment(tmp_path, original)
    assert clean["SystemRoot"] == original["SystemRoot"]
    assert clean["USERPROFILE"] == str(tmp_path)
    assert "PYTHONPATH" not in clean and "PYTHONHOME" not in clean
    assert original["PYTHONPATH"] == "unrelated-checkout"


@pytest.mark.parametrize("value", ("", "latest", "1.2", "1.2.3/other", "65536.0.0", "1.2.3;echo"))
def test_release_identity_rejects_unsafe_or_non_numeric_installer_versions(value):
    """An explicit release version must fit both the artifact filename and Windows metadata."""
    with pytest.raises(argparse.ArgumentTypeError):
        version(value)


def test_public_acceptance_cannot_succeed_without_an_installer(tmp_path):
    """An explicit installed-client check must not silently become a portable-only run."""
    archive = tmp_path / "Demo-portable.zip"
    archive.write_bytes(b"fixture")
    manifest = {"product": "Demo", "artifacts": [{"file": archive.name, "bytes": archive.stat().st_size,
                                                 "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}]}
    (tmp_path / "build-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="requires the Windows installer"):
        verify(package(tmp_path), tmp_path, public_server="wss://games.tachyon-ai.eu/play")
    other = GamePackage(**{**package(tmp_path).__dict__, "product": "Other"})
    with pytest.raises(ValueError, match="not Other"):
        verify(other, tmp_path)


def test_public_acceptance_requires_tls(tmp_path):
    """Public acceptance must exercise TLS rather than accidentally testing loopback."""
    with pytest.raises(ValueError, match="TLS endpoint"):
        verify(package(tmp_path), tmp_path, public_server="ws://127.0.0.1/play")


def test_mesa_context_is_temporary_and_preserves_the_shipping_executable(tmp_path):
    """A failed native check must still remove only its test DLLs and keep app bytes."""
    installed, mesa = tmp_path / "installed", tmp_path / "mesa"
    installed.mkdir()
    mesa.mkdir()
    executable = installed / "Demo.exe"
    executable.write_bytes(b"shipping executable")
    for name in ("opengl32.dll", "libgallium_wgl.dll"):
        (mesa / name).write_bytes(name.encode())
    with pytest.raises(RuntimeError, match="native failure"):
        with mesa_test_context(executable, mesa) as receipt:
            assert set(receipt["dll_sha256"]) == {"opengl32.dll", "libgallium_wgl.dll"}
            assert (installed / "opengl32.dll").read_bytes() == (mesa / "opengl32.dll").read_bytes()
            raise RuntimeError("native failure")
    assert list(installed.iterdir()) == [executable]
    assert executable.read_bytes() == b"shipping executable"
