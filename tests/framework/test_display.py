"""Display changes preserve the game's logical canvas and its input/UI state."""

import pytest

from saga2d import Anchor, Button, Game, Scene
from saga2d.backends.mock_backend import MockBackend


def test_window_and_fullscreen_changes_preserve_the_playable_canvas():
    """The same logical button works after size changes and fullscreen restoration."""
    class Play(Scene):
        def on_enter(self):
            self.clicks = 0
            self.target = self.ui.add(Button('Target', on_click=self.hit, width=160, height=60,
                                            anchor=Anchor.BOTTOM_RIGHT, margin=90))

        def hit(self):
            self.clicks += 1

    game = Game('Display test', backend='mock', resolution=(1280, 800))
    try:
        game.push(Play())
        game.tick(1 / 60)
        scene = game.scene
        assert game.window_size == (1280, 800) and not game.fullscreen
        for size in ((960, 600), (1000, 800), (1280, 720)):
            game.set_window_size(size)
            assert game.window_size == size and not game.fullscreen
            game.set_fullscreen(True)
            assert game.fullscreen and game.window_size == game.backend.screen_size()
            game.set_fullscreen(True)
            game.set_fullscreen(False)
            assert not game.fullscreen and game.window_size == size
            assert game.resolution == (1280, 800) and (game.width, game.height) == (1280, 800)
            x, y, width, height = scene.target.bounds
            game.backend.inject_click(int(x + width / 2), int(y + height / 2))
            game.tick(1 / 60)
        assert game.scene is scene and scene.clicks == 3
    finally:
        game._teardown()


def test_fullscreen_start_can_select_windowed_size_without_changing_resolution():
    """Starting fullscreen reports that state, then a chosen size exits it predictably."""
    game = Game('Fullscreen start', backend='mock', resolution=(1280, 800), fullscreen=True)
    try:
        assert game.fullscreen and game.window_size == game.backend.screen_size()
        game.set_fullscreen(False)
        assert game.window_size == (1280, 800)
        game.set_fullscreen(True)
        game.set_window_size((960, 600))
        assert not game.fullscreen and game.window_size == (960, 600)
        game.set_fullscreen(True)
        game.set_fullscreen(False)
        assert game.window_size == (960, 600) and game.resolution == (1280, 800)
    finally:
        game._teardown()


def test_os_resize_becomes_the_fullscreen_restore_size(game):
    """Fullscreen remembers the actual OS-adjusted size rather than the last requested preset."""
    game.backend.inject_resize(910, 710)
    game.tick(1 / 60)
    assert game.window_size == (910, 710)
    game.set_fullscreen(True)
    game.set_fullscreen(False)
    assert game.window_size == (910, 710)
    assert game.backend.capture_frame().size == (910, 710)
    assert game.resolution == (800, 600)


def test_invalid_display_requests_leave_the_current_mode_intact(game):
    """Invalid preference data fails before any native transition, including bool-as-size."""
    import pytest

    game.set_fullscreen(True)
    original = game.window_size
    for size in (None, (), (900,), (900, 600, 1), '900x600', (True, 600), (900, False),
                 (900.0, 600), (900, 0), (-1, 600)):
        with pytest.raises(ValueError, match='positive integers'):
            game.set_window_size(size)
        assert game.fullscreen and game.window_size == original
    for fullscreen in (1, None, 'false'):
        with pytest.raises(ValueError, match='boolean'):
            game.set_fullscreen(fullscreen)
        assert game.fullscreen and game.window_size == original


def test_headless_mode_cannot_open_fullscreen(game, monkeypatch):
    """The explicit hidden-window process policy also applies to runtime toggles."""
    import pytest

    monkeypatch.setenv('SAGA2D_HEADLESS', '1')
    with pytest.raises(RuntimeError, match='SAGA2D_HEADLESS'):
        game.set_fullscreen(True)
    assert not game.fullscreen
    game.set_window_size((900, 600))
    assert game.window_size == (900, 600)


def test_fullscreen_preview_cancel_restores_the_actual_windowed_size(game):
    """A settings dialog can snapshot fullscreen, preview a size, then cancel faithfully."""
    game.backend.inject_resize(940, 720)
    game.tick(1 / 60)
    assert game.windowed_size == game.window_size == (940, 720)
    game.set_fullscreen(True)
    entry_size, entry_fullscreen = game.windowed_size, game.fullscreen
    game.set_window_size((1280, 800))
    assert game.windowed_size == game.window_size == (1280, 800)
    game.set_window_size(entry_size)
    game.set_fullscreen(entry_fullscreen)
    assert game.fullscreen and game.windowed_size == (940, 720)
    game.set_fullscreen(False)
    assert game.windowed_size == game.window_size == (940, 720)


def test_the_mock_derives_the_texture_scale_from_the_window_like_the_pyglet_backend():
    """Games rasterise textures at ``backend.scale_factor``; the OS-adjusted window decides it, not the request."""
    game = Game('Scale', backend='mock', resolution=(1280, 800))
    try:
        assert game.backend.scale_factor == 1.0
        game.backend.inject_resize(1280, 791)  # clipped under a taskbar: the height binds
        game.tick(1 / 60)
        assert game.backend.scale_factor == 791 / 800
        game.set_fullscreen(True)  # 1920×1080 is wider than 16:10, so the height binds again
        assert game.backend.scale_factor == 1080 / 800
        game.set_fullscreen(False)
        assert game.backend.scale_factor == 791 / 800
        game.set_window_size((2560, 1600))
        assert game.backend.scale_factor == 2.0
        assert game.resolution == (1280, 800)
    finally:
        game._teardown()


def test_a_fixed_resolution_game_opens_at_the_desktops_scale():
    """On a 200 % desktop a 1280×800 game is 1280×800 desktop units: twice the pixels, textures rasterised at 2."""
    game = Game('Scaled', backend=MockBackend(screen=(1920, 1080), desktop_scale=2.0), resolution=(1280, 800))
    try:
        assert game.window_size == (1280, 800) and game.backend.scale_factor == 2.0
        game.set_window_size((960, 600))
        assert game.window_size == (960, 600) and game.backend.scale_factor == 1.5
        game.set_fullscreen(True)
        assert game.window_size == (1920, 1080) and game.backend.scale_factor == 2.0 * 1080 / 800
    finally:
        game._teardown()


@pytest.mark.parametrize("screen, scale, canvas, factor", [
    ((1920, 1080), 1.0, (1840, 960), 1.0),    # 1920×1080 at 100 %, as it always was
    ((2560, 1440), 1.0, (2480, 1320), 1.0),   # 2560×1440 at 100 %
    ((1920, 1080), 2.0, (1840, 960), 2.0),    # 3840×2160 at 200 %: the desktop's units are half its pixels
    ((2560, 1440), 1.5, (2480, 1320), 1.5),   # 3840×2160 at 150 %
    ((3840, 2160), 1.0, (2506, 1360), 1.5),   # 3840×2160 at 100 %: no wall-sized canvas with a HUD for ants
    ((5120, 2880), 1.0, (2520, 1380), 2.0),   # 5120×2880 at 100 %
])
def test_a_fitted_game_gets_a_canvas_made_for_the_desktop(screen, scale, canvas, factor):
    """``resolution=None`` fits the window to the desktop and keeps the canvas in the range layouts are made for."""
    game = Game('Fit', resolution=None, backend=MockBackend(screen=screen, desktop_scale=scale))
    try:
        assert game.resolution == canvas
        assert game.window_size == (screen[0] - 80, screen[1] - 120)
        assert game.backend.scale_factor == pytest.approx(factor, abs=0.001)
    finally:
        game._teardown()


def test_a_fitted_fullscreen_game_covers_the_screen_with_the_same_canvas_rule():
    game = Game('Fit', resolution=None, backend=MockBackend(screen=(3840, 2160)), fullscreen=True)
    try:
        assert game.resolution == (2560, 1440) and game.window_size == (3840, 2160)
        assert game.backend.scale_factor == 1.5
    finally:
        game._teardown()


class ScaledWindow:
    """What pyglet hands the backend on a Windows desktop at 200 %: sizes in physical pixels, the scale beside them."""
    scale = 2.0
    fullscreen = False

    def __init__(self):
        self.size = (3680, 1920)

    def get_size(self):
        return self.size

    def set_size(self, width, height):
        self.size = (width, height)

    width = property(lambda self: self.size[0])
    height = property(lambda self: self.size[1])


def test_the_pyglet_backend_speaks_desktop_units_on_a_scaled_windows_desktop(monkeypatch):
    """Measured on 3840×2160 at 200 %: pyglet says 3680×1920 px and scale 2; the game must see 1840×960 units."""
    from saga2d.backends.pyglet_backend import PygletBackend

    monkeypatch.setattr("sys.platform", "win32")
    backend = PygletBackend()
    backend.window = ScaledWindow()
    monkeypatch.setattr(backend, "_compute_viewport", lambda width, height: None)  # needs a GL context
    assert backend.window_size == (1840, 960)
    backend.set_window_size(1280, 800)
    assert backend.window.size == (2560, 1600) and backend.window_size == (1280, 800)
    monkeypatch.setattr("sys.platform", "darwin")  # Cocoa takes points as they are
    backend.set_window_size(1280, 800)
    assert backend.window.size == (1280, 800)
