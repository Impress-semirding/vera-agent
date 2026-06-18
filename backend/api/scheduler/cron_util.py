"""Lightweight cron expression parser (no external deps).

Supports: *  */n  specific values  comma lists  ranges
5 fields: minute hour day-of-month month day-of-week

All cron times are interpreted in the configured timezone (default UTC+8).
Set VERA_TIMEZONE_HOURS env var to override (e.g. 8 for China Standard Time).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

# Server-local timezone offset in hours. Cron expressions are interpreted
# in this timezone. Default UTC+8 (China Standard Time / Beijing).
_TIMEZONE_HOURS = int(os.environ.get("VERA_TIMEZONE_HOURS", "8"))
_TZ = timezone(timedelta(hours=_TIMEZONE_HOURS))

_FIELD_RANGES = [
    (0, 59),   # minute
    (0, 23),   # hour
    (1, 31),   # day of month
    (1, 12),   # month
    (0, 7),    # day of week (0=Sun, 1=Mon, ..., 6=Sat, 7=Sun — standard cron)
]


def _now() -> datetime:
    """Current time in the configured timezone (naive, like utcnow)."""
    return datetime.now(_TZ).replace(tzinfo=None)


def _parse_field(expr: str, lo: int, hi: int) -> set[int]:
    """Parse one cron field into a set of valid values."""
    result: set[int] = set()
    for part in expr.split(","):
        part = part.strip()
        # */n
        if m := re.match(r"^\*/(\d+)$", part):
            step = int(m.group(1))
            result.update(range(lo, hi + 1, step))
        # * (all)
        elif part == "*":
            result.update(range(lo, hi + 1))
        # n-m (range)
        elif m := re.match(r"^(\d+)-(\d+)$", part):
            a, b = int(m.group(1)), int(m.group(2))
            result.update(range(a, b + 1))
        # n-m/k (range with step)
        elif m := re.match(r"^(\d+)-(\d+)/(\d+)$", part):
            a, b, k = int(m.group(1)), int(m.group(2)), int(m.group(3))
            result.update(range(a, b + 1, k))
        # n/k (from n to max with step)
        elif m := re.match(r"^(\d+)/(\d+)$", part):
            a, k = int(m.group(1)), int(m.group(2))
            result.update(range(a, hi + 1, k))
        # n (single)
        elif part.isdigit():
            v = int(part)
            if lo <= v <= hi:
                result.add(v)
            else:
                raise ValueError(f"value {v} out of range [{lo},{hi}]")
        else:
            raise ValueError(f"invalid cron field: {part}")
    return result


def validate_cron(expr: str) -> bool:
    """Check if a cron expression is valid."""
    try:
        _next_run(expr, _now())
        return True
    except Exception:
        return False


def _next_run(expr: str, after: datetime) -> datetime:
    """Compute the next time this cron expression fires after `after`."""
    fields = expr.strip().split()
    if len(fields) != 5:
        raise ValueError(f"cron must have 5 fields, got {len(fields)}")

    sets = []
    for i, field in enumerate(fields):
        lo, hi = _FIELD_RANGES[i]
        sets.append(_parse_field(field, lo, hi))

    # Normalize DoW: 7 = Sunday = 0 (standard cron)
    if 7 in sets[4]:
        sets[4].add(0)
        sets[4].discard(7)

    # Scan minute by minute (brute force — fine for short intervals)
    t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(525600):  # max 1 year
        if (t.minute in sets[0]
                and t.hour in sets[1]
                and t.day in sets[2]
                and t.month in sets[3]
                and ((t.weekday() + 1) % 7) in sets[4]):  # Python Mon=0 → cron Sun=0
            return t
        t += timedelta(minutes=1)
    raise ValueError("no matching time within 1 year")


def next_run(expr: str, after: datetime | None = None) -> datetime:
    """Public API: next fire time after `after` (default: now)."""
    return _next_run(expr, after or _now())
