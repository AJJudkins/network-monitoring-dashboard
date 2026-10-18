"""Read-only live checks: TCP connect and (optional) SNMP GET via net-snmp's `snmpget`.

Safety properties:
* Only outbound TCP connects and SNMP GET requests are ever issued. No SET, no
  walks, no writes, no ICMP, no payload is sent on TCP connections.
* Every poll has a hard timeout.
* A per-device minimum interval is enforced (rate limit).
* SNMP credentials are read from environment variables, never from the config.
* Use only against systems you own or are explicitly authorized to monitor.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from .simulator import DeviceSpec

MAX_TARGETS = 50
MIN_INTERVAL_S = 1.0
SYS_UPTIME_OID = "1.3.6.1.2.1.1.3.0"  # sysUpTime.0, read-only and universally supported


class ConfigError(ValueError):
    pass


@dataclass
class LiveSpec:
    name: str
    role: str
    kind: str  # "tcp" | "snmp"
    host: str
    port: int
    timeout_s: float = 2.0
    snmp_version: str = "2c"  # "2c" | "3"
    oid: str = SYS_UPTIME_OID


def _check_host(host):
    if not isinstance(host, str) or not host or any(c.isspace() or c in "/;|&$`'\"" for c in host) or host.startswith("-"):
        raise ConfigError(f"invalid host: {host!r}")


def parse_live_specs(raw: list[dict]) -> list[LiveSpec]:
    """Validate the `targets` list from a config file."""
    if not isinstance(raw, list) or not raw:
        raise ConfigError("config 'targets' must be a non-empty list")
    if len(raw) > MAX_TARGETS:
        raise ConfigError(f"too many targets ({len(raw)} > {MAX_TARGETS})")
    specs, seen = [], set()
    for t in raw:
        try:
            kind = t.get("kind", "tcp")
            if kind not in ("tcp", "snmp"):
                raise ConfigError(f"unknown kind {kind!r} (use 'tcp' or 'snmp')")
            name = str(t["name"])
            if name in seen:
                raise ConfigError(f"duplicate target name {name!r}")
            seen.add(name)
            host = t["host"]
            _check_host(host)
            port = int(t.get("port", 161 if kind == "snmp" else 0))
            if not 1 <= port <= 65535:
                raise ConfigError(f"{name}: port must be 1-65535 (tcp targets require 'port')")
            timeout = float(t.get("timeout_s", 2.0))
            if not 0 < timeout <= 30:
                raise ConfigError(f"{name}: timeout_s must be in (0, 30]")
            ver = str(t.get("snmp_version", "2c"))
            if ver not in ("2c", "3"):
                raise ConfigError(f"{name}: snmp_version must be '2c' or '3'")
            oid = str(t.get("oid", SYS_UPTIME_OID))
            if not all(p.isdigit() for p in oid.split(".")):
                raise ConfigError(f"{name}: oid must be numeric dotted form")
            specs.append(LiveSpec(name, str(t.get("role", "device")), kind, host, port, timeout, ver, oid))
        except KeyError as e:
            raise ConfigError(f"target missing required field {e}") from None
        except (TypeError, AttributeError) as e:
            raise ConfigError(f"malformed target: {e}") from None
    return specs


class _RateLimited:
    def __init__(self, min_interval_s: float, sleep=time.sleep, clock=time.monotonic):
        self.min_interval_s = max(min_interval_s, MIN_INTERVAL_S)
        self._sleep, self._clock = sleep, clock
        self._last: Optional[float] = None

    def _wait(self):
        if self._last is not None:
            delay = self.min_interval_s - (self._clock() - self._last)
            if delay > 0:
                self._sleep(delay)
        self._last = self._clock()


class TcpDevice(_RateLimited):
    """TCP connect check. Connects then immediately closes; sends no data."""

    def __init__(self, spec: LiveSpec, min_interval_s=MIN_INTERVAL_S, **kw):
        super().__init__(min_interval_s, **kw)
        self.live = spec
        self.spec = DeviceSpec(spec.name, spec.role, 0)

    def poll(self) -> Optional[float]:
        self._wait()
        t0 = time.perf_counter()
        try:
            with socket.create_connection((self.live.host, self.live.port), timeout=self.live.timeout_s):
                pass
        except OSError:
            return None
        return round((time.perf_counter() - t0) * 1000, 2)


def snmp_command(spec: LiveSpec, env=None) -> list[str]:
    """Build the (read-only) snmpget argv. Secrets come from env vars only."""
    env = os.environ if env is None else env
    cmd = ["snmpget", "-Oqv", "-t", str(spec.timeout_s), "-r", "0"]
    if spec.snmp_version == "2c":
        community = env.get("NETMON_SNMP_COMMUNITY")
        if not community:
            raise ConfigError("set NETMON_SNMP_COMMUNITY for SNMP v2c targets")
        cmd += ["-v2c", "-c", community]
    else:
        user = env.get("NETMON_SNMP_USER")
        if not user:
            raise ConfigError("set NETMON_SNMP_USER (and ..._AUTH_PASS / ..._PRIV_PASS) for SNMP v3 targets")
        auth, priv = env.get("NETMON_SNMP_AUTH_PASS"), env.get("NETMON_SNMP_PRIV_PASS")
        cmd += ["-v3", "-u", user]
        if auth and priv:
            cmd += ["-l", "authPriv", "-a", "SHA", "-A", auth, "-x", "AES", "-X", priv]
        elif auth:
            cmd += ["-l", "authNoPriv", "-a", "SHA", "-A", auth]
        else:
            cmd += ["-l", "noAuthNoPriv"]
    cmd += [f"{spec.host}:{spec.port}", spec.oid]
    return cmd


class SnmpDevice(_RateLimited):
    """SNMP GET of one OID via `snmpget`. Latency = round-trip of the request."""

    def __init__(self, spec: LiveSpec, min_interval_s=MIN_INTERVAL_S, run=subprocess.run, **kw):
        super().__init__(min_interval_s, **kw)
        if run is subprocess.run and shutil.which("snmpget") is None:
            raise ConfigError("snmpget not found; install net-snmp (e.g. `apt install snmp`)")
        self.live, self._run = spec, run
        self.spec = DeviceSpec(spec.name, spec.role, 0)
        snmp_command(spec)  # fail fast on missing credentials

    def poll(self) -> Optional[float]:
        self._wait()
        t0 = time.perf_counter()
        try:
            r = self._run(snmp_command(self.live), capture_output=True, text=True,
                          timeout=self.live.timeout_s + 2, shell=False)
        except (subprocess.TimeoutExpired, OSError):
            return None
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return round((time.perf_counter() - t0) * 1000, 2)


def build_live_fleet(specs: list[LiveSpec], min_interval_s=MIN_INTERVAL_S):
    return [TcpDevice(s, min_interval_s) if s.kind == "tcp" else SnmpDevice(s, min_interval_s) for s in specs]
