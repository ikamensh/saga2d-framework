"""A CpuBudget yields CPU in small blocks without changing its callers' work."""
import pytest

from saga2d.testing.cpu_budget import CpuBudget


class Clock:
    def __init__(self):
        self.wall = self.cpu = 0.0
        self.sleeps = []

    def work(self, seconds):
        self.cpu += seconds
        self.wall += seconds

    def sleep(self, seconds):
        assert seconds > 0
        self.sleeps.append(seconds)
        self.wall += seconds


def test_cpu_budget_yields_in_small_blocks_without_banking_idle_time(monkeypatch):
    """A 25% budget spends three sleeping seconds per CPU second, even after an idle gap."""
    clock = Clock()
    monkeypatch.setattr('saga2d.testing.cpu_budget.time.process_time', lambda: clock.cpu)
    monkeypatch.setattr('saga2d.testing.cpu_budget.time.monotonic', lambda: clock.wall)
    monkeypatch.setattr('saga2d.testing.cpu_budget.time.sleep', clock.sleep)
    budget = CpuBudget(25)
    for _ in range(4):
        clock.work(.02)
        budget.checkpoint()
    assert clock.cpu / clock.wall <= .31  # An unfinished small block remains runnable.
    assert clock.sleeps == pytest.approx([.18])
    clock.wall += 20
    clock.work(.06)
    budget.checkpoint()
    assert len(clock.sleeps) == 1
    clock.work(.06)
    budget.checkpoint()
    assert clock.sleeps[-1] == pytest.approx(.18)


@pytest.mark.parametrize('percent', [0, -1, 101, float('nan'), float('inf')])
def test_cpu_budget_rejects_an_invalid_allowance(percent):
    """A typo must fail visibly instead of silently running unrestricted or hanging."""
    with pytest.raises(ValueError, match='CPU percent'):
        CpuBudget(percent)


def test_explicit_stress_budget_does_not_sleep(monkeypatch):
    """Selecting 100% removes the yield while leaving callers' work unchanged."""
    clock = Clock()
    monkeypatch.setattr('saga2d.testing.cpu_budget.time.process_time', lambda: clock.cpu)
    monkeypatch.setattr('saga2d.testing.cpu_budget.time.monotonic', lambda: clock.wall)
    monkeypatch.setattr('saga2d.testing.cpu_budget.time.sleep', clock.sleep)
    budget = CpuBudget(100)
    for _ in range(4):
        clock.work(.2)
        budget.checkpoint()
    assert not clock.sleeps
