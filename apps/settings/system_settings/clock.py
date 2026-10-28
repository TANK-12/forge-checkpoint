"""Date and time: the clock, time zone and network time (timedatectl).
Read-only: changing them needs root."""

from __future__ import annotations

import time

from .runner import Run


def parse_show(raw: str) -> dict:
    """timedatectl show -> its Key=value lines."""
    out = {}
    for line in raw.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


def status(run: Run) -> dict:
    now = time.time()
    tm = time.localtime(now)
    shown = run(["timedatectl", "show"], timeout=5)
    info = parse_show(shown.out) if shown.ok else {}
    return {
        "available": True,
        "now": now,
        # "%-d" is glibc-only (ValueError on Windows), so the day is added by hand.
        "local": time.strftime("%A ", tm)
        + str(tm.tm_mday)
        + time.strftime(" %B %Y, %H:%M:%S", tm),
        "utc_offset": time.strftime("%z", tm),
        "timezone": info.get("Timezone") or time.tzname[0],
        "ntp": info.get("NTP") == "yes" if info else None,
        "synced": info.get("NTPSynchronized") == "yes" if info else None,
        "rtc_local": info.get("LocalRTC") == "yes" if info else None,
    }


ACTIONS: dict = {}
