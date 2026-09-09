"""Older native verifiers can advance exact simulation steps without a busy render loop."""
import time

import pytest

from saga2d import Game, Scene
from saga2d.testing.native_frames import tick


@pytest.mark.parametrize('render_cost', [.006, .05])
def test_native_frames_limit_bursts_and_keep_explicit_simulation_time(monkeypatch, render_cost):
    """Screenshot settling includes rendering cost, preserves dt, and never catches up after idle."""
    wall = [0.0]
    starts, deltas = [], []
    monkeypatch.setattr(time, 'monotonic', lambda: wall[0])
    monkeypatch.setattr(time, 'sleep', lambda seconds: wall.__setitem__(0, wall[0] + seconds))

    class MeasuredScene(Scene):
        def update(self, dt):
            starts.append(wall[0])
            deltas.append(dt)

        def draw(self):
            wall[0] += render_cost

    game = Game('Native frame pacing', backend='mock')
    try:
        game.push(MeasuredScene())
        for _ in range(110):
            tick(game)
        assert deltas == pytest.approx([1 / 60] * 110)
        assert [b - a for a, b in zip(starts, starts[1:])] == pytest.approx(
            [max(1 / 30, render_cost)] * 109)
        wall[0] += 10
        tick(game, .5)
        tick(game, 0)
        assert starts[-1] - starts[-2] == pytest.approx(max(1 / 30, render_cost))
        assert deltas[-2:] == [.5, 0]
    finally:
        game._teardown()
        game.backend.quit()
