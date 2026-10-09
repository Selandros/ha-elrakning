#!/usr/bin/env python3
"""Read-only external watcher for bounded Elräkning activation diagnostics."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import subprocess
import time


REMOTE_SCRIPT = r'''
set +e
core_info="$(ha core info 2>/dev/null)"
core_stats="$(ha core stats 2>/dev/null)"
jobs="$(ha jobs info 2>/dev/null)"
http="$(curl -sS -o /dev/null -w 'code=%{http_code},connect_ms=%{time_connect},start_ms=%{time_starttransfer},total_ms=%{time_total}' --max-time 2 http://172.30.32.1:8123/ 2>&1)"
supervisor_signals="$(ha supervisor logs 2>/dev/null | grep -Ei 'watchdog missed|SIGSEGV|segmentation|exit code 139|OOM|out of memory|Errno 12' | tail -4 | tr '\n' ' ' | cut -c1-800)"
core_signals="$(ha core logs 2>/dev/null | grep -Ei 'watchdog|SIGSEGV|segmentation|exit code 139|OOM|out of memory|Errno 12|elrakning|highspy|sqlite|database is locked' | tail -4 | tr '\n' ' ' | cut -c1-1000)"
core_state="$(printf '%s\n' "$core_info" | awk -F': ' '/^(boot|version|ip_address|port|watchdog):/{printf "%s=%s,", $1, $2}')"
core_usage="$(printf '%s\n' "$core_stats" | awk -F': ' '/^(cpu_percent|memory_percent|memory_usage):/{printf "%s=%s,", $1, $2}')"
active_jobs="$(printf '%s\n' "$jobs" | grep -E 'done: false|name: (home_assistant_core_restart|docker_interface_restart)' | tr '\n' ' ' | cut -c1-500)"
printf 'state=%s stats=%s jobs=%s http=%s supervisor_signals=%s core_signals=%s\n' "$core_state" "$core_usage" "$active_jobs" "$http" "$supervisor_signals" "$core_signals"
'''


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="root@192.168.51.39")
    parser.add_argument("--ssh-port", type=int, default=2222)
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--duration", type=float, default=0.0)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    started = time.monotonic()
    while True:
        timestamp = datetime.now(timezone.utc).isoformat()
        command = [
            "ssh",
            "-p",
            str(args.ssh_port),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=3",
            args.target,
            "sh",
            "-s",
        ]
        try:
            result = subprocess.run(
                command,
                input=REMOTE_SCRIPT,
                text=True,
                capture_output=True,
                timeout=max(8.0, args.interval + 5.0),
                check=False,
            )
            output = result.stdout.strip() or result.stderr.strip() or "ssh_no_output"
            print(f"watcher_timestamp={timestamp} exit={result.returncode} {output}", flush=True)
        except subprocess.TimeoutExpired:
            print(f"watcher_timestamp={timestamp} exit=timeout ssh_timeout", flush=True)
        if args.once or (args.duration > 0 and time.monotonic() - started >= args.duration):
            return 0
        time.sleep(max(0.5, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
