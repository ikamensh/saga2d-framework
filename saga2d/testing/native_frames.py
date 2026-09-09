"""Paced explicit frames for standalone native verification scripts."""
import time


def tick(game, dt=1 / 60):
    """Advance the supplied simulation step, then yield the rest of a 30 FPS frame.

    Rendering time counts toward the interval; slow frames and pauses never
    accumulate catch-up work. Keep ordinary mock/model tests on ``game.tick``.
    """
    started = time.monotonic()
    game.tick(dt)
    remaining = 1 / 30 - (time.monotonic() - started)
    if remaining > 0:
        time.sleep(remaining)
