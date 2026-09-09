"""The pyglet backend through a hidden window: what the mock backend cannot prove about pixels."""

from __future__ import annotations

import sys

import pytest
from PIL import Image

from saga2d import Camera, Game, Scene
from saga2d.testing.native_frames import tick


def _display_available() -> bool:
    try:
        import pyglet

        pyglet.display.get_display().get_default_screen()
        return True
    except Exception:  # noqa: BLE001 - no display (CI, a sleeping screen): the test cannot run here
        return False


pytestmark = pytest.mark.skipif(not _display_available(), reason="needs a display for a hidden pyglet window")


class Portraits(Scene):
    """Draws a red square at each spot through the immediate draw_image API, like a HUD's portraits."""

    def __init__(self) -> None:
        super().__init__()
        self.spots: list[tuple[int, int]] = []

    def on_enter(self) -> None:
        self.game.assets.image_from_pil("red", Image.new("RGBA", (16, 16), (255, 0, 0, 255)))

    def draw(self) -> None:
        for x, y in self.spots:
            self.draw_image("red", x, y, 16, 16)


def red_at(game: Game, x: int, y: int) -> bool:
    frame = game.backend.capture_frame()
    scale = frame.width / game.width
    r, g, b, _ = frame.getpixel((int((x + 8) * scale), int((y + 8) * scale)))
    return r > 200 and g < 60 and b < 60


def test_immediate_images_show_where_this_frame_drew_them_and_nowhere_else() -> None:
    # draw_image reuses a pool of GPU sprites across frames; a sprite drawn last frame but not
    # this one must vanish, and a frame that draws more images than the last must show them all.
    game = Game("pyglet", resolution=(200, 120), backend="pyglet", visible=False)
    try:
        scene = Portraits()
        game.push(scene)
        scene.spots = [(10, 10), (60, 10), (110, 10)]
        game.tick(1 / 60)
        assert all(red_at(game, x, y) for x, y in scene.spots)
        scene.spots = [(60, 60)]
        game.tick(1 / 60)
        assert red_at(game, 60, 60)
        assert not any(red_at(game, x, y) for x, y in [(10, 10), (60, 10), (110, 10)])
        scene.spots = [(10, 10), (60, 10), (110, 10), (150, 60)]
        game.tick(1 / 60)
        assert all(red_at(game, x, y) for x, y in scene.spots)
    finally:
        game._teardown()
        game.backend.quit()


@pytest.mark.skipif(sys.platform != "darwin", reason="Control+click stands in for the right button on a Mac only")
def test_control_click_is_a_right_click_on_a_mac() -> None:
    from pyglet.window import key, mouse

    game = Game("pyglet", resolution=(200, 120), backend="pyglet", visible=False)
    try:
        window = game.backend.window
        window.dispatch_event("on_mouse_press", 50, 60, mouse.LEFT, key.MOD_CTRL)
        window.dispatch_event("on_mouse_release", 50, 60, mouse.LEFT, 0)  # Control let go first: still the same button
        window.dispatch_event("on_mouse_press", 50, 60, mouse.LEFT, 0)
        window.dispatch_event("on_mouse_release", 50, 60, mouse.LEFT, 0)
        events = [(e.type, e.button) for e in game.backend.poll_events() if e.type in ("click", "release")]
        assert events == [("click", "right"), ("release", "right"), ("click", "left"), ("release", "left")]
    finally:
        game._teardown()
        game.backend.quit()


def test_scaled_opaque_images_have_no_dark_seams_before_or_after_update() -> None:
    """Bilinear filtering at atlas edges must preserve a continuous opaque surface."""
    class Tiles(Scene):
        background_color = (80, 150, 70, 255)

        def on_enter(self):
            self.game.assets.image_from_pil("tile", Image.new("RGBA", (16, 16), self.background_color))

        def draw(self):
            for x, y in ((30.3, 20.2), (75.7, 20.2), (30.3, 65.6)):
                self.draw_image("tile", x, y, 57.2, 50.4)

    game = Game("texture seams", resolution=(200, 120), backend="pyglet", visible=False)
    try:
        scene = Tiles()
        game.push(scene)
        for color in ((80, 150, 70, 255), (150, 85, 60, 255)):
            scene.background_color = color
            game.assets.update_image("tile", Image.new("RGBA", (16, 16), color))
            tick(game)
            frame = game.backend.capture_frame()
            scale = frame.width / game.width
            pixels = frame.crop(tuple(round(v * scale) for v in (20, 10, 150, 118))).convert("RGB")
            for bounds, expected in zip(pixels.getextrema(), color[:3]):
                assert bounds[0] >= expected - 1 and bounds[1] <= expected + 1, (bounds, expected)
    finally:
        game.close()


def test_transparent_panel_preserves_panned_and_zoomed_world_pixels() -> None:
    """A menu's screen-space drawing must not move the world beneath it to the origin."""
    class Map(Scene):
        def on_enter(self):
            self.camera = Camera(self.game.resolution, zoom=1.5)
            self.camera.scroll(700, 400)

        def draw(self):
            self.draw_rect(730, 440, 16, 16, (255, 0, 0, 255), space="world")

    class Panel(Scene):
        transparent = True

        def draw(self):
            self.draw_rect(140, 10, 50, 30, (0, 0, 255, 255))

    game = Game("overlay camera", resolution=(200, 120), backend="pyglet", visible=False)
    try:
        game.push(Map())
        tick(game)
        assert red_at(game, 45, 60)
        game.push(Panel())
        tick(game)
        assert red_at(game, 45, 60)
    finally:
        game.close()
