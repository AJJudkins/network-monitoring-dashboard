"""Polling loop, per-device statistics and alert rules."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Thresholds:
    latency_warn_ms: float = 100.0
    consecutive_failures_crit: int = 3


@dataclass
class DeviceStats:
    name: str
    role: str
    polls: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    latencies: list = field(default_factory=list)
    last_latency: Optional[float] = None
    status: str = "UNKNOWN"

    @property
    def uptime_pct(self) -> float:
        return 100.0 * (self.polls - self.failures) / self.polls if self.polls else 0.0

    @property
    def avg_latency(self) -> Optional[float]:
        return sum(self.latencies) / len(self.latencies) if self.latencies else None

    @property
    def max_latency(self) -> Optional[float]:
        return max(self.latencies) if self.latencies else None

    @property
    def p95_latency(self) -> Optional[float]:
        if not self.latencies:
            return None
        s = sorted(self.latencies)
        return s[min(len(s) - 1, int(0.95 * len(s)))]


@dataclass
class Alert:
    poll: int
    device: str
    severity: str  # WARNING | CRITICAL | RECOVERED
    message: str


class Monitor:
    def __init__(self, devices, thresholds: Thresholds | None = None):
        self.devices = devices
        self.th = thresholds or Thresholds()
        self.stats = {d.spec.name: DeviceStats(d.spec.name, d.spec.role) for d in devices}
        self.alerts: list[Alert] = []
        self.rounds = 0

    def poll_once(self) -> None:
        self.rounds += 1
        for dev in self.devices:
            st = self.stats[dev.spec.name]
            lat = dev.poll()
            st.polls += 1
            prev = st.status
            if lat is None:
                st.failures += 1
                st.consecutive_failures += 1
                if st.consecutive_failures >= self.th.consecutive_failures_crit:
                    st.status = "DOWN"
                    if prev != "DOWN":
                        self.alerts.append(Alert(self.rounds, st.name, "CRITICAL",
                            f"{st.name} unreachable for {st.consecutive_failures} consecutive polls"))
                continue
            st.consecutive_failures = 0
            st.last_latency = lat
            st.latencies.append(lat)
            if lat > self.th.latency_warn_ms:
                st.status = "DEGRADED"
                self.alerts.append(Alert(self.rounds, st.name, "WARNING",
                    f"{st.name} latency {lat:.1f} ms exceeds {self.th.latency_warn_ms:.0f} ms"))
            else:
                st.status = "UP"
                if prev == "DOWN":
                    self.alerts.append(Alert(self.rounds, st.name, "RECOVERED",
                        f"{st.name} is reachable again"))

    def run(self, rounds: int) -> None:
        for _ in range(rounds):
            self.poll_once()
