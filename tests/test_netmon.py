import json
import random

from netmon.cli import main
from netmon.monitor import Monitor, Thresholds
from netmon.report import render_html
from netmon.simulator import DeviceSpec, SimulatedDevice, build_fleet


class Scripted:
    """Device returning a scripted sequence of latencies/None."""
    def __init__(self, seq, name="d"):
        self.spec = DeviceSpec(name, "test", 1)
        self.seq = list(seq)

    def poll(self):
        return self.seq.pop(0)


def test_down_after_consecutive_failures_and_recovery():
    m = Monitor([Scripted([None, None, None, 5.0])], Thresholds(100, 3))
    m.run(3)
    assert m.stats["d"].status == "DOWN"
    assert [a.severity for a in m.alerts] == ["CRITICAL"]
    m.poll_once()
    assert m.stats["d"].status == "UP"
    assert m.alerts[-1].severity == "RECOVERED"


def test_single_failure_is_not_down():
    m = Monitor([Scripted([None, 5.0])], Thresholds(100, 3))
    m.run(2)
    assert m.stats["d"].status == "UP" and m.alerts == []
    assert m.stats["d"].uptime_pct == 50.0


def test_latency_warning():
    m = Monitor([Scripted([250.0])], Thresholds(100, 3))
    m.poll_once()
    assert m.stats["d"].status == "DEGRADED"
    assert m.alerts[0].severity == "WARNING"


def test_simulator_is_reproducible():
    spec = [{"name": "a", "role": "x", "base_latency_ms": 10, "failure_rate": 0.3}]
    r1 = [build_fleet(spec, 7)[0].poll() for _ in range(1)]
    f1, f2 = build_fleet(spec, 7)[0], build_fleet(spec, 7)[0]
    assert [f1.poll() for _ in range(20)] == [f2.poll() for _ in range(20)]


def test_html_report_escapes(tmp_path):
    d = Scripted([1.0], name="<script>")
    m = Monitor([d]); m.poll_once()
    assert "<script>" not in render_html(m)


def test_cli_writes_html(tmp_path, capsys):
    out = tmp_path / "d.html"
    rc = main(["--config", "examples/devices.json", "--rounds", "20", "--html", str(out)])
    assert rc == 0 and out.exists() and "SIMULATED" in out.read_text()


def test_cli_bad_config(tmp_path):
    assert main(["--config", str(tmp_path / "nope.json")]) == 2
