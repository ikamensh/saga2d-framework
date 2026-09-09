"""Cooperative CPU allowance for development tools; independent of the game loop."""
from __future__ import annotations

import math
import time


class CpuBudget:
    """Yield after about 50 ms of CPU work, targeting *percent* of one core.

    Call ``checkpoint()`` between commands or frames. Atomic commands can exceed
    the work allowance; this is cooperative pacing, not an operating-system quota.
    Idle time is not banked for a later burst. 100 explicitly disables sleeping.
    """

    def __init__(self, percent: float = 25):
        if not math.isfinite(percent) or not 0 < percent <= 100:
            raise ValueError('CPU percent must be greater than 0 and at most 100')
        self.percent = percent
        self._cpu = time.process_time()
        self._wall = time.monotonic()

    def checkpoint(self) -> None:
        if self.percent == 100:
            return
        cpu = time.process_time()
        if cpu - self._cpu < .05:
            return
        remaining = (cpu - self._cpu) / (self.percent / 100) - (time.monotonic() - self._wall)
        if remaining > 0:
            time.sleep(remaining)
        self._cpu = time.process_time()
        self._wall = time.monotonic()
