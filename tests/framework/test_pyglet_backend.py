"""The pyglet backend through a hidden window: what the mock backend cannot prove about pixels."""

from __future__ import annotations

import pytest
from PIL import Image

from saga2d import Game, Scene


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
