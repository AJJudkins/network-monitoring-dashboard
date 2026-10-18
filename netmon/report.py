"""Static HTML + text report rendering."""
from __future__ import annotations

import html

COLORS = {"UP": "#2e7d32", "DEGRADED": "#f9a825", "DOWN": "#c62828", "UNKNOWN": "#757575"}


def _f(v):
    return "-" if v is None else f"{v:.1f}"


def render_text(monitor) -> str:
    lines = [f"{'DEVICE':<16}{'ROLE':<10}{'STATUS':<10}{'UPTIME%':>8}{'AVG ms':>9}{'P95 ms':>9}{'MAX ms':>9}"]
    for s in monitor.stats.values():
        lines.append(f"{s.name:<16}{s.role:<10}{s.status:<10}{s.uptime_pct:>8.1f}"
                     f"{_f(s.avg_latency):>9}{_f(s.p95_latency):>9}{_f(s.max_latency):>9}")
    crit = sum(a.severity == "CRITICAL" for a in monitor.alerts)
    warn = sum(a.severity == "WARNING" for a in monitor.alerts)
    lines.append(f"\n{monitor.rounds} polls/device | alerts: {crit} critical, {warn} warning")
    return "\n".join(lines)


def render_html(monitor) -> str:
    rows = []
    for s in monitor.stats.values():
        c = COLORS.get(s.status, "#757575")
        rows.append(
            f"<tr><td>{html.escape(s.name)}</td><td>{html.escape(s.role)}</td>"
            f"<td><span class='b' style='background:{c}'>{s.status}</span></td>"
            f"<td>{s.uptime_pct:.1f}</td><td>{_f(s.avg_latency)}</td>"
            f"<td>{_f(s.p95_latency)}</td><td>{_f(s.max_latency)}</td></tr>")
    alerts = "".join(
        f"<li><b>{a.severity}</b> (poll {a.poll}): {html.escape(a.message)}</li>"
        for a in monitor.alerts[-50:]) or "<li>No alerts</li>"
    up = sum(s.status == "UP" for s in monitor.stats.values())
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Network Dashboard</title>
<style>body{{font-family:sans-serif;margin:2em}}table{{border-collapse:collapse}}
td,th{{border:1px solid #ccc;padding:6px 12px;text-align:left}}th{{background:#eee}}
.b{{color:#fff;padding:2px 8px;border-radius:4px}}</style></head><body>
<h1>Network Monitoring Dashboard</h1>
<p>SIMULATED DATA &mdash; {up}/{len(monitor.stats)} devices UP after {monitor.rounds} polls.</p>
<table><tr><th>Device</th><th>Role</th><th>Status</th><th>Uptime %</th><th>Avg ms</th><th>P95 ms</th><th>Max ms</th></tr>
{''.join(rows)}</table><h2>Recent alerts (last 50)</h2><ul>{alerts}</ul></body></html>"""
