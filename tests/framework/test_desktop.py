"""The icon and the name the desktop draws a running game under (:mod:`saga2d.desktop`)."""

from __future__ import annotations

import platform
import sys

import pytest
from PIL import Image

from saga2d import Game, desktop
from saga2d.packaging import icon


def _display_available() -> bool:
    try:
        import pyglet

        pyglet.display.get_display().get_default_screen()
        return True
    except Exception:  # noqa: BLE001 - no display (CI, a sleeping screen): the window tests cannot run here
        return False


def test_pictures_are_every_size_a_desktop_asks_for(tmp_path):
    picture = tmp_path / "icon.png"
    Image.new("RGBA", (icon.SIDE, icon.SIDE), (200, 40, 60, 255)).save(picture)

    sizes = [(image.width, image.height) for image in desktop.pictures(picture)]

    assert sizes == [(side, side) for side in desktop.SIZES]


def test_pictures_wear_the_outline_the_built_app_wears(tmp_path):
    """A picture painted to the edges is a rounded tile in the Dock and the taskbar, as it is on disk."""
    picture = tmp_path / "icon.png"
    Image.new("RGBA", (icon.SIDE, icon.SIDE), (200, 40, 60, 255)).save(picture)

    largest = desktop.pictures(picture)[0]

    assert largest.getpixel((largest.width // 2, largest.height // 2))[3] == 255
    shaped = platform.system() in icon.FORMATS
    assert (largest.getpixel((0, 0))[3] == 0) is shaped


def test_a_game_wears_its_own_picture(tmp_path):
    picture = tmp_path / "icon.png"
    Image.new("RGBA", (icon.SIDE, icon.SIDE), (10, 120, 200, 255)).save(picture)

    game = Game("Test", backend="mock", resolution=(800, 600), icon=picture)
    try:
        assert game.backend.icon == str(picture)
    finally:
        game._teardown()


def test_a_game_without_a_picture_wears_the_engine_mark(backend):
    assert backend.icon == str(icon.DEFAULT)
    assert icon.DEFAULT.is_file(), "the mark ships inside the package, so a built game finds it too"


@pytest.mark.skipif(sys.platform != "darwin" or not _display_available(),
                    reason="the Dock's tile and name are macOS, and need a display")
def test_macos_draws_the_window_under_the_game_picture_and_its_name(tmp_path):
    """The whole chain: a hidden window still hands macOS the tile and the name a checkout otherwise lacks."""
    from pyglet.libs.darwin import cocoapy

    picture = tmp_path / "icon.png"
    Image.new("RGBA", (icon.SIDE, icon.SIDE), (10, 120, 200, 255)).save(picture)

    game = Game("Saga2D icon test", resolution=(320, 200), visible=False, save_dir=tmp_path, icon=picture)
    try:
        tile = cocoapy.ObjCClass("NSApplication").sharedApplication().applicationIconImage()
        assert (tile.size().width, tile.size().height) == (float(desktop.SIZES[0]), float(desktop.SIZES[0]))
        running = cocoapy.ObjCClass("NSRunningApplication").currentApplication()
        assert cocoapy.cfstring_to_string(running.localizedName()) == "Saga2D icon test"
    finally:
        game.close()
