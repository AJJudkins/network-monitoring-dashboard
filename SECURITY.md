# Security policy

## Scope and safety
default mode is simulated and sends no traffic. `--live` is opt-in, needs `--i-am-authorized`, issues only TCP connects and SNMP GETs (no SET/walk/ICMP), has timeouts, a minimum 1 s per-target interval and a 50-target cap, and takes SNMP credentials from environment variables only.

## What was and was not tested
**Tested (automated, in CI and locally):** simulator and alert logic; live config validation; TCP checks against local listeners on 127.0.0.1; SNMP command construction and polling against a mocked `snmpget` runner; CLI authorization gate.

**Not tested:** live polling of any real network device; real `snmpget`/SNMPv2c/v3 exchanges (the SNMP path has only been exercised with a mocked runner); behavior with firewalls, rate-limiting devices or IPv6-only targets.

## Reporting a problem
This is a small personal portfolio project, not a supported product. If you find a security issue, please open a GitHub issue **without** secrets, credentials or real system details, or use GitHub's "Report a vulnerability" button on the Security tab if it is enabled.
