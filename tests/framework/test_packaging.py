"""The shared packaging recipe's checks, exercised without PyInstaller."""
import argparse
import hashlib
import json
from pathlib import Path
import os
import plistlib

from PIL import Image
import pytest

from saga2d.packaging import GamePackage, icon, version
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
    assert icon.DEFAULT.is_file(), "the engine's mark, which a game also wears while it runs"
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


# -- The icon a build carries ----------------------------------------------------------


def picture(path: Path, size=(1024, 1024)) -> Path:
    Image.new("RGBA", size, (200, 40, 40, 255)).save(path)
    return path


def test_the_engine_ships_a_default_picture_that_its_own_rules_accept():
    """A game that names no icon is built with the engine's mark, so the mark must pass the same refusals."""
    assert icon.load(icon.DEFAULT).size[0] >= icon.SIDE


@pytest.mark.parametrize("size", ((1024, 1000), (512, 512)))
def test_a_picture_that_is_not_square_or_too_small_stops_the_build(tmp_path, size):
    """The error names the file and what it measured; nothing is stretched or padded to fit."""
    source = picture(tmp_path / "icon.png", size)
    with pytest.raises(ValueError, match=f"icon.png is {size[0]}x{size[1]}"):
        icon.write(source, tmp_path, "Windows")


def test_the_windows_icon_holds_every_size_the_shell_asks_for(tmp_path):
    """Explorer, the taskbar and the window pick a stored size each; a missing one gets a blurry stand-in."""
    written = icon.write(picture(tmp_path / "icon.png"), tmp_path, "Windows")
    with Image.open(written) as stored:
        assert stored.info["sizes"] == {(size, size) for size in icon.ICO_SIZES}
    assert len(icon.ico_images(written.read_bytes())) == len(icon.ICO_SIZES)


def test_an_edge_to_edge_picture_gets_each_platforms_outline():
    """The Mac grid leaves a clear margin around a rounded square; Windows keeps the canvas and rounds the corners."""
    full = Image.new("RGBA", (2048, 2048), (200, 40, 40, 255))
    for system, margin in (("Darwin", True), ("Windows", False)):
        alpha = icon.shaped(full, system).getchannel("A")
        assert alpha.size == (icon.SIDE, icon.SIDE)
        assert alpha.getpixel((icon.SIDE // 2, icon.SIDE // 2)) == 255
        assert alpha.getpixel((2, 2)) == 0, system
        assert (alpha.getpixel((icon.SIDE // 2, 40)) < 255) is margin, system


def test_other_systems_get_no_icon_file(tmp_path):
    """An ELF executable holds no icon; the build records none rather than writing an unused file."""
    assert icon.write(picture(tmp_path / "icon.png"), tmp_path, "Linux") is None
    assert [path.name for path in tmp_path.iterdir()] == ["icon.png"]


def test_an_executable_carries_the_icon_only_with_every_stored_image(tmp_path):
    """What the resource writer copies into the executable is each image of the .ico, byte for byte."""
    written = icon.write(picture(tmp_path / "icon.png"), tmp_path, "Windows")
    images = icon.ico_images(written.read_bytes())
    executable = tmp_path / "Demo.exe"
    executable.write_bytes(b"MZ" + b"".join(b"\0" * 64 + image for image in images))
    icon.carried(executable, written)
    executable.write_bytes(b"MZ" + b"".join(b"\0" * 64 + image for image in images[1:]))
    with pytest.raises(AssertionError, match=r"does not carry images \[0\]"):
        icon.carried(executable, written)


def bundle_build(tmp_path: Path, shipped: bytes) -> Path:
    """A finished Mac build directory whose bundle holds ``shipped`` as its icon."""
    converted = icon.write(picture(tmp_path / "icon.png"), tmp_path, "Darwin")
    archive = tmp_path / "Demo-portable.zip"
    archive.write_bytes(b"fixture")
    resources = tmp_path / "Demo.app" / "Contents" / "Resources"
    resources.mkdir(parents=True)
    (resources / "icon.icns").write_bytes(shipped or converted.read_bytes())
    (resources.parent / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIconFile": "icon.icns"}))
    manifest = {"product": "Demo", "packaging": {"icon": converted.name},
                "source_sha256": {converted.name: hashlib.sha256(converted.read_bytes()).hexdigest()},
                "artifacts": [{"file": archive.name, "bytes": archive.stat().st_size,
                               "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}]}
    (tmp_path / "build-manifest.json").write_text(json.dumps(manifest))
    return tmp_path


def test_verify_fails_a_bundle_that_shows_another_icon(tmp_path):
    """The packager's default picture in the bundle is exactly the defect this guards against."""
    with pytest.raises(AssertionError, match="icon.icns differs"):
        verify(package(tmp_path), bundle_build(tmp_path, b"icns of the packager's snake"))


def test_verify_fails_an_icon_that_changed_after_the_build(tmp_path):
    """The converted file beside the manifest must be the one the manifest recorded."""
    output = bundle_build(tmp_path, b"")
    (output / "icon.icns").write_bytes(b"replaced")
    with pytest.raises(AssertionError, match="icon.icns"):
        verify(package(tmp_path), output)
