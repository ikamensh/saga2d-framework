"""FrameTimer: wall-clock frame times and phase shares, on any object."""

import time

from saga2d.testing import FrameTimer


class Engine:
    def __init__(self) -> None:
        self.steps = 0

    def step(self) -> int:
        self.steps += 1
        deadline = time.perf_counter() + 0.002
        while time.perf_counter() < deadline:
            pass
        return self.steps


def test_wrapped_phases_keep_working_and_show_up_as_shares_of_the_frames() -> None:
    engine = Engine()
    timer = FrameTimer()
    timer.wrap(engine, "step", "engine.step")
    for _ in range(5):
        ms = timer.frame(lambda: engine.step())
        assert ms >= 2.0
    assert engine.steps == 5 and engine.step() == 6  # the wrapper passes results through
    assert timer.calls["engine.step"] == 6 and timer.seconds["engine.step"] >= 0.012
    assert timer.percentile(50) <= timer.percentile(95) <= max(timer.frames)
    report = timer.report()
    assert report.startswith("5 frames: p50 ") and "engine.step" in report and "6 calls" in report
