"""Command line interface: python -m netmon.cli ..."""
from __future__ import annotations

import argparse
import json
import sys

from .monitor import Monitor, Thresholds
from .report import render_html, render_text
from .live import ConfigError, build_live_fleet, parse_live_specs
from .simulator import build_fleet


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="netmon", description="Poll simulated (default) or real (--live, read-only) network devices.")
    p.add_argument("--config", default="examples/devices.json", help="JSON list of device specs")
    p.add_argument("--rounds", type=int, default=60, help="polls per device")
    p.add_argument("--seed", type=int, default=42, help="simulator seed (reproducible)")
    p.add_argument("--latency-warn", type=float, default=100.0)
    p.add_argument("--fail-crit", type=int, default=3, help="consecutive failures => DOWN")
    p.add_argument("--html", metavar="FILE", help="write static HTML dashboard")
    p.add_argument("--live", action="store_true",
                   help="poll real targets (TCP connect / SNMP GET) from the config's 'targets' list")
    p.add_argument("--i-am-authorized", action="store_true",
                   help="required with --live: confirms you may monitor every listed target")
    p.add_argument("--interval", type=float, default=1.0,
                   help="seconds between polls of the same target in --live mode (minimum 1)")
    p.add_argument("--alerts", action="store_true", help="print alerts")
    a = p.parse_args(argv)
    if a.rounds < 1:
        p.error("--rounds must be >= 1")
    try:
        with open(a.config) as fh:
            specs = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: cannot load config: {e}", file=sys.stderr)
        return 2
    if a.live:
        if not a.i_am_authorized:
            print("error: --live requires --i-am-authorized (only monitor systems you own or may test)",
                  file=sys.stderr)
            return 2
        try:
            raw = specs.get("targets") if isinstance(specs, dict) else None
            fleet = build_live_fleet(parse_live_specs(raw), a.interval)
        except ConfigError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    else:
        if isinstance(specs, dict):
            specs = specs.get("simulated", [])
        fleet = build_fleet(specs, a.seed)
    mon = Monitor(fleet, Thresholds(a.latency_warn, a.fail_crit))
    mon.run(a.rounds)
    print(render_text(mon))
    if a.alerts:
        print()
        for al in mon.alerts:
            print(f"[{al.severity}] poll {al.poll}: {al.message}")
    if a.html:
        with open(a.html, "w") as fh:
            fh.write(render_html(mon))
        print(f"\nHTML dashboard written to {a.html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
