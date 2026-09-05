"""Display changes preserve the game's logical canvas and its input/UI state."""

from saga2d import Anchor, Button, Game, Scene


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
