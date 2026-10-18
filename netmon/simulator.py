"""Simulated network devices. No real network traffic is generated."""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional


@dataclass
class DeviceSpec:
    name: str
    role: str
    base_latency_ms: float
    jitter_ms: float = 3.0
    failure_rate: float = 0.0  # probability a poll fails (device "down")
    degraded_rate: float = 0.0  # probability of a latency spike


class SimulatedDevice:
    """Returns latency in ms for a poll, or None when the device is down."""

    def __init__(self, spec: DeviceSpec, rng: random.Random):
        self.spec = spec
        self.rng = rng

    def poll(self) -> Optional[float]:
        s = self.spec
        if self.rng.random() < s.failure_rate:
            return None
        latency = max(0.1, self.rng.gauss(s.base_latency_ms, s.jitter_ms))
        if self.rng.random() < s.degraded_rate:
            latency *= self.rng.uniform(4, 10)
        return round(latency, 2)


def build_fleet(specs: list[dict], seed: int = 42) -> list[SimulatedDevice]:
    rng = random.Random(seed)
    return [SimulatedDevice(DeviceSpec(**s), rng) for s in specs]
