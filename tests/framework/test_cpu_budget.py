"""Development stress tools yield CPU without changing their deterministic work."""
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


@pytest.mark.parametrize('scenario', ['shardbound', 'linked_setup', 'shard_scene', 'tribes_ai', 'tribes_scene'])
def test_fuzzer_work_yields_inside_runs_without_changing_reproducible_results(monkeypatch, scenario):
    """Every model/scene loop, including the linked setup policy, checks its shared CPU allowance."""
    from collections import Counter
    from tools import fuzz, fuzz_eador

    def run(budget):
        metrics = Counter()
        if scenario == 'linked_setup':
            from eador.model import State
            from tools.eador_linked_campaign import play_stage
            return play_stage(State.new_campaign(1), budget=budget).to_json()
        elif scenario == 'shardbound':
            fuzz_eador.campaign_run(1, 2, metrics, budget=budget)
        elif scenario == 'shard_scene':
            fuzz_eador.scene_run(0, 1, metrics, budget=budget)
        elif scenario == 'tribes_ai':
            metrics['failures'] = fuzz.ai_games(range(1, 2), budget=budget)
        else:
            metrics['failures'] = fuzz.monkey_runs(range(1, 2), 2, budget=budget)
        return metrics

    expected = run(CpuBudget(100))
    clock = Clock()

    def process_time():
        clock.work(.02)  # Controlled CPU-work samples, independent of machine speed.
        return clock.cpu

    monkeypatch.setattr('saga2d.testing.cpu_budget.time.process_time', process_time)
    monkeypatch.setattr('saga2d.testing.cpu_budget.time.monotonic', lambda: clock.wall)
    monkeypatch.setattr('saga2d.testing.cpu_budget.time.sleep', clock.sleep)
    assert run(CpuBudget(25)) == expected
    assert clock.sleeps, 'The tool completed a run without honoring its CPU allowance'
