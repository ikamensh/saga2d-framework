"""Explicit game lifetime through the same public interface used by embedders."""

import pytest

from saga2d import Game, Scene


def test_tick_driven_close_releases_the_window_and_allows_restart_even_after_a_failed_exit(game):
    """Closing owns scene and backend cleanup; requesting loop exit alone does not."""
    scene = Scene()
    game.push(scene)
    game.tick(.01)
    game.quit()
    assert not game.running and game.backend.is_running
    assert game.scene is scene

    game.close()
    assert not game.backend.is_running
    assert game.scenes == [] and scene.game is None

    exit_error = RuntimeError('scene exit failed')

    class BrokenExit(Scene):
        def on_exit(self):
            raise exit_error

    restarted = Game('Explicit restart', backend='mock')
    broken = BrokenExit()
    restarted.push(broken)
    restarted.tick(.01)
    with pytest.raises(RuntimeError) as caught:
        restarted.close()
    assert caught.value is exit_error
    assert not restarted.running and not restarted.backend.is_running
    assert restarted.scenes == [] and broken.game is None

    recovered = Game('After failed exit', backend='mock')
    try:
        recovered.push(Scene())
        recovered.tick(.01)
    finally:
        recovered.close()
    assert not recovered.backend.is_running
