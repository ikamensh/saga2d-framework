"""The pyglet backend through a hidden window: what the mock backend cannot prove about pixels."""

from __future__ import annotations

import sys

import pytest
from PIL import Image

from saga2d import Camera, Game, Scene, Sprite
from saga2d.testing.native_frames import tick


def _display_available() -> bool:
    try:
        import pyglet

        pyglet.display.get_display().get_default_screen()
        return True
    except Exception:  # noqa: BLE001 - no display (CI, a sleeping screen): the test cannot run here
        return False


pytestmark = pytest.mark.skipif(not _display_available(), reason="needs a display for a hidden pyglet window")


def test_repeated_shape_layers_do_not_accumulate_discarded_render_storage(tmp_path):
    """Returning to two HUD layers reuses storage instead of deferring cycles to GC."""
    import gc

    class Shapes(Scene):
        layer = 0

        def draw(self):
            with self.screen_layer(self.layer):
                self.draw_rect(20, 20, 60, 40, (255, 50, 70, 255))

    game = Game("shape lifetime", resolution=(320, 120), visible=False, save_dir=tmp_path)
    flags, enabled = gc.get_debug(), gc.isenabled()
    try:
        scene = Shapes()
        game.push(scene)
        for layer in (0, 1, 0, 1):
            scene.layer = layer
            tick(game)
        gc.collect(2)
        assert not gc.garbage
        # Deferred collection exposes allocation churn; production GC is unchanged.
        gc.disable()
        for index in range(60):
            scene.layer = index % 2
            tick(game)
        gc.set_debug(gc.DEBUG_SAVEALL)
        gc.collect(2)
        retained = sum(sys.getsizeof(obj) for obj in gc.garbage)
        assert retained < 128 * 1024, f"Discarded renderer cycles retain {retained:,} bytes after 60 frames"
    finally:
        gc.set_debug(flags)
        gc.garbage.clear()
        if enabled:
            gc.enable()
        gc.collect(2)
        game.close()


@pytest.mark.parametrize("space", ["screen", "world"])
def test_reused_shapes_match_fresh_frames_through_resize_hide_and_return(tmp_path, space):
    """Cached geometry preserves transparency, order and camera transforms without stale pixels."""
    class Shapes(Scene):
        rows = ()

        def on_enter(self):
            self.camera = Camera(self.game.resolution)

        def draw(self):
            for x, y, width, color, layer in self.rows:
                with self.screen_layer(layer):
                    self.draw_rect(x, y, width, 30, color, space=space)
                    self.draw_circle(x + width, y + 15, width / 3, color, space=space)

    red, blue = (255, 50, 70, 190), (50, 150, 255, 160)
    first = ((30, 35, 60, red, 0), (60, 45, 80, blue, 0))
    states = ((1, (0, 0), first),
              (1.25, (10, 5), ((40, 60, 110, blue, 0), (60, 45, 40, red, 1))),
              (.75, (20, 10), ()),
              (1, (0, 0), first),
              (1, (0, 0), ((20, 50, 40, blue, 4),)),
              (1, (0, 0), ((100, 35, 60, red, 5),)),
              (.75, (20, 10), first),
              (1, (0, 0), ()))

    def capture(sequence):
        game = Game("shape history", resolution=(320, 180), visible=False, save_dir=tmp_path)
        try:
            scene = Shapes()
            game.push(scene)
            frames = []
            for zoom, offset, rows in sequence:
                scene.camera.zoom = zoom
                scene.camera.scroll(*offset)
                scene.rows = rows
                for _ in range(3):
                    tick(game)
                frames.append(game.backend.capture_frame())
                scene.camera.scroll(-offset[0], -offset[1])
            return frames
        finally:
            game.close()

    history = capture(states)
    for index, (state, actual) in enumerate(zip(states, history, strict=True)):
        expected = capture((state,))[0]
        actual.save(tmp_path / f"{space}-{index}.png")
        expected.save(tmp_path / f"{space}-{index}-fresh.png")
        assert actual.size == expected.size
        assert actual.tobytes() == expected.tobytes(), f"Shape pixels changed with drawing history at state {index}"


def test_moving_sprite_keeps_its_geometry_when_size_or_image_changes(tmp_path):
    """Skipping unchanged transform uploads must retain scaling after image swaps."""
    class Moving(Scene):
        def on_enter(self):
            for name, size, color in (("wide", (40, 20), (255, 40, 70, 255)),
                                      ("tall", (20, 40), (40, 150, 255, 255))):
                self.game.assets.image_from_pil(name, Image.new("RGBA", size, color))
            self.body = self.add_sprite(Sprite("wide", position=(80, 70), size=(60, 40), space="screen"))

    states = (((80, 70), (60, 40), "wide", 0),
              ((120, 80), (60, 40), "wide", 0),
              ((120, 80), (60, 40), "tall", 30),
              ((160, 60), (40, 80), "tall", -20),
              ((80, 70), (60, 40), "wide", 0))

    def capture(sequence):
        game = Game("sprite geometry", resolution=(320, 180), visible=False, save_dir=tmp_path)
        try:
            scene = Moving()
            game.push(scene)
            frames = []
            for position, size, image, rotation in sequence:
                scene.body.position = position
                scene.body.size = size
                scene.body.image = image
                scene.body.rotation = rotation
                tick(game)
                frames.append(game.backend.capture_frame())
            return frames
        finally:
            game.close()

    for index, (state, actual) in enumerate(zip(states, capture(states), strict=True)):
        expected = capture((state,))[0]
        actual.save(tmp_path / f"sprite-{index}.png")
        assert actual.tobytes() == expected.tobytes(), f"Sprite transform depends on prior images at state {index}"


def test_sprite_tint_preserves_opacity_through_movement(tmp_path):
    """Pyglet's RGB colour assignment resets alpha; the backend must send RGBA."""
    class Fading(Scene):
        def on_enter(self):
            self.game.assets.image_from_pil("white", Image.new("RGBA", (20, 20), (255, 255, 255, 255)))
            self.body = self.add_sprite(Sprite("white", position=(50, 50), space="screen"))

    game = Game("sprite opacity", resolution=(200, 120), visible=False, save_dir=tmp_path)
    try:
        scene = Fading()
        game.push(scene)
        for alpha in (0, 64, 128, 255):
            scene.body.tint = (.5, 1, .25)
            scene.body.opacity = alpha
            scene.body.position = (60, 50)
            tick(game)
            frame = game.backend.capture_frame()
            frame.save(tmp_path / f"opacity-{alpha}.png")
            scale = frame.width / game.width
            actual = frame.getpixel((round(60 * scale), round(50 * scale)))[:3]
            expected = tuple(round(channel * alpha / 255) for channel in (127, 255, 63))
            assert all(abs(a - b) <= 1 for a, b in zip(actual, expected)), (alpha, actual, expected)
    finally:
        game.close()


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
