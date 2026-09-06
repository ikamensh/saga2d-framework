"""The ordinary loop sleeps between frames; explicit test ticks remain caller-driven."""

import math
import time
import pytest

from saga2d import Game, Scene


class BriefRun(Scene):
    """Bound this public scene by wall time so an uncapped loop cannot hang a test."""

    def __init__(self, seconds=.2):
        self.seconds = seconds
        self.frames = 0

    def on_enter(self):
        self.started = time.monotonic()

    def update(self, dt):
        self.frames += 1
        if time.monotonic() - self.started >= self.seconds:
            self.game.quit()


def test_ordinary_run_limits_frame_work_without_a_game_specific_loop():
    """A scene with nothing to do must not consume a CPU core producing useless frames."""
    scene = BriefRun()
    game = Game('paced loop', backend='mock')
    game.run(scene)
    elapsed = time.monotonic() - scene.started
    assert scene.frames <= math.ceil(elapsed * 60) + 2
    assert not game.running and not game.backend.is_running


@pytest.mark.parametrize('condition', ['unfocused', 'hidden', 'shown_without_focus'])
def test_inactive_run_reduces_frames_but_continues_processing_events(condition):
    """Unfocused and minimized windows stay responsive without redrawing at full rate."""
    scene = BriefRun()
    game = Game('inactive loop', backend='mock', visible=condition != 'shown_without_focus')
    try:
        if condition == 'unfocused':
            game.backend.inject_focus(False)
        elif condition == 'hidden':
            game.backend.inject_visibility(False)
        else:
            game.backend.inject_visibility(True)
        game.run(scene)
    finally:
        game._teardown()
        game.backend.quit()
    elapsed = time.monotonic() - scene.started
    assert scene.frames <= math.ceil(elapsed * 15) + 2
    assert scene.frames >= 2 and not game.backend.is_running


def test_custom_cap_and_explicit_ticks_keep_their_distinct_timing_contracts():
    """An application can choose30FPS; deterministic ticks still use exactly their supplied dt."""
    scene = BriefRun()
    game = Game('custom loop', backend='mock')
    game.run(scene, fps=30)
    elapsed = time.monotonic() - scene.started
    assert scene.frames <= math.ceil(elapsed * 30) + 2

    class Steps(Scene):
        def __init__(self):
            self.deltas = []

        def update(self, dt):
            self.deltas.append(dt)

    scene = Steps()
    game = Game('explicit steps', backend='mock', visible=False)
    try:
        game.push(scene)
        game.tick(.01)
        game.tick(.5)
        game.tick(0)
        assert scene.deltas == [.01, .5, 0]
    finally:
        game._teardown()


@pytest.mark.parametrize('fps', [0, -1, float('nan'), float('inf')])
def test_invalid_rate_closes_the_created_game(fps):
    """A bad launch option cannot leave a native window or owned resources behind."""
    game = Game('invalid rate', backend='mock')
    with pytest.raises(ValueError, match='fps'):
        game.run(BriefRun(), fps=fps)
    assert not game.running and not game.backend.is_running
