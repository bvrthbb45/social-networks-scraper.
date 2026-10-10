"""Runs the daily maintenance (python -m app.cli daily) once a day at a fixed UTC hour.

python -m app.scheduler [HOUR]
"""

import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone


def seconds_until(hour: int, now: datetime) -> float:
    """Seconds from ``now`` to the next occurrence of ``hour``:00 UTC (never zero)."""
    target = now.astimezone(timezone.utc).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def main(hour: int) -> None:
    if not 0 <= hour <= 23:
        raise SystemExit("hour must be 0-23")
    while True:
        time.sleep(seconds_until(hour, datetime.now(timezone.utc)))
        result = subprocess.run([sys.executable, "-m", "app.cli", "daily"], check=False)
        print(f"daily run finished with exit code {result.returncode}", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
