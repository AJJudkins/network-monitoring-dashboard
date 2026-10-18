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


# ---- live (read-only) checks ----
import socket
import threading
import types

import pytest

from netmon.live import (ConfigError, LiveSpec, SnmpDevice, TcpDevice, parse_live_specs,
                         snmp_command)


def _listener():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    return srv, srv.getsockname()[1]


def test_tcp_device_up_and_down():
    srv, port = _listener()
    try:
        d = TcpDevice(LiveSpec("a", "x", "tcp", "127.0.0.1", port, 1.0), sleep=lambda s: None)
        assert d.poll() is not None
    finally:
        srv.close()
    assert d.poll() is None  # port closed now


def test_rate_limit_sleeps():
    sleeps, t = [], [0.0]
    d = TcpDevice(LiveSpec("a", "x", "tcp", "127.0.0.1", 1, 0.2), 5.0,
                  sleep=sleeps.append, clock=lambda: t[0])
    d.poll()
    d.poll()
    assert sleeps and sleeps[0] == pytest.approx(5.0)


def test_min_interval_floor():
    d = TcpDevice(LiveSpec("a", "x", "tcp", "127.0.0.1", 1), 0.0)
    assert d.min_interval_s >= 1.0


@pytest.mark.parametrize("bad", [
    [], [{"name": "a", "host": "-oProxy", "port": 1}], [{"name": "a", "host": "h"}],
    [{"name": "a", "host": "h", "port": 70000}], [{"name": "a", "host": "h", "port": 1, "kind": "ping"}],
    [{"name": "a", "host": "h", "port": 1}, {"name": "a", "host": "h", "port": 2}],
    [{"name": "a", "host": "h", "port": 1, "timeout_s": 999}],
    [{"name": "a", "host": "h", "kind": "snmp", "oid": "1.3;rm"}],
])
def test_bad_live_config(bad):
    with pytest.raises(ConfigError):
        parse_live_specs(bad)


def test_snmp_command_is_get_only_and_secrets_from_env():
    s = LiveSpec("a", "x", "snmp", "192.0.2.1", 161)
    cmd = snmp_command(s, {"NETMON_SNMP_COMMUNITY": "sekret"})
    assert cmd[0] == "snmpget" and "-v2c" in cmd and cmd[-1] == "1.3.6.1.2.1.1.3.0"
    assert not any(c in cmd for c in ("snmpset", "snmpwalk"))
    with pytest.raises(ConfigError):
        snmp_command(s, {})
    s3 = LiveSpec("a", "x", "snmp", "192.0.2.1", 161, snmp_version="3")
    c3 = snmp_command(s3, {"NETMON_SNMP_USER": "u", "NETMON_SNMP_AUTH_PASS": "a" * 8, "NETMON_SNMP_PRIV_PASS": "b" * 8})
    assert "authPriv" in c3


def test_snmp_device_with_mocked_runner(monkeypatch):
    monkeypatch.setenv("NETMON_SNMP_COMMUNITY", "x")
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        return types.SimpleNamespace(returncode=0, stdout="12345\n")

    d = SnmpDevice(LiveSpec("a", "x", "snmp", "192.0.2.1", 161), run=run, sleep=lambda s: None)
    assert d.poll() is not None and calls[0][1]["shell"] is False
    d2 = SnmpDevice(LiveSpec("a", "x", "snmp", "192.0.2.1", 161),
                    run=lambda c, **k: types.SimpleNamespace(returncode=1, stdout=""), sleep=lambda s: None)
    assert d2.poll() is None


def test_cli_live_requires_authorization(tmp_path, capsys):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"targets": [{"name": "a", "host": "127.0.0.1", "port": 1}]}))
    assert main(["--config", str(cfg), "--live", "--rounds", "1"]) == 2
    assert "--i-am-authorized" in capsys.readouterr().err


def test_cli_live_tcp_end_to_end(tmp_path, capsys):
    srv, port = _listener()
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"targets": [{"name": "loop", "host": "127.0.0.1", "port": port}]}))
    try:
        assert main(["--config", str(cfg), "--live", "--i-am-authorized", "--rounds", "1"]) == 0
    finally:
        srv.close()
    assert "loop" in capsys.readouterr().out
