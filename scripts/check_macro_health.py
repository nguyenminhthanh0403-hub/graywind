"""Raises an alarm when the macro gate has been unable to answer for a
sustained run of cycles.

Why this exists: evaluate_macro_gate (pipeline.py) fails CLOSED -- when the
upstream Bullion data.json cannot be read or is past its staleness ceiling, it
returns passed=False, which makes decide_trade block. That is the safe default,
but it means a dead upstream silently halts EVERY new entry indefinitely while
the pipeline still looks perfectly healthy: cron green, no pipeline-alarm issue,
equity flat. In decision_log.csv the result was previously indistinguishable
from a genuine risk-off reading, so nothing could alarm on it.

live_loop.py now writes the MACRO_UNAVAILABLE_SENTINEL into the macro_breaches
column for exactly that case. This script reads it back and reports whether the
condition has persisted long enough to be a real outage rather than a blip --
fetch_bullion_macro_snapshot converts ANY exception into MacroDataUnavailable,
so a single transient network error must not page anyone.

Deliberately exits 0 even when unhealthy. The workflow's live-cycle-small job
declares `needs: live-cycle`, so failing this step would skip the small account
entirely; and the "Close the alarm issue on success" step closes every open
pipeline-alarm issue, so this condition gets its own label instead. The workflow
reads the status from stdout / GITHUB_OUTPUT and manages a separate issue.
"""
import csv
import os
import sys

DECISION_LOG_FILENAME = "decision_log.csv"
MACRO_UNAVAILABLE_SENTINEL = "unavailable"
# ~2 hours at the 15-minute cron cadence. Long enough that a transient fetch
# failure clears on its own; short enough to catch a real outage the same day.
DEFAULT_STREAK_THRESHOLD = 8


def read_macro_cycles(decision_log_path):
    """Returns [(timestamp, was_unavailable)] oldest first, one entry per CYCLE
    (not per symbol-row), skipping cycles where the macro gate never ran because
    an earlier gate short-circuited.
    """
    if not os.path.exists(decision_log_path):
        return []
    by_timestamp = {}
    order = []
    with open(decision_log_path, newline="") as f:
        for row in csv.DictReader(f):
            reading = (row.get("macro_breaches") or "").strip()
            if not reading:
                continue  # gate never reached this row
            timestamp = row.get("timestamp", "")
            if timestamp not in by_timestamp:
                by_timestamp[timestamp] = False
                order.append(timestamp)
            # macro is symbol-independent, so any unavailable row marks the cycle
            if reading == MACRO_UNAVAILABLE_SENTINEL:
                by_timestamp[timestamp] = True
    return [(timestamp, by_timestamp[timestamp]) for timestamp in order]


def unavailable_streak(cycles):
    """How many consecutive most-recent cycles were unavailable. Any cycle that
    got a real reading resets it -- a recovered feed is a recovered feed.
    """
    streak = 0
    for _, was_unavailable in reversed(cycles):
        if not was_unavailable:
            break
        streak += 1
    return streak


def is_unhealthy(cycles, threshold=DEFAULT_STREAK_THRESHOLD):
    return unavailable_streak(cycles) >= threshold


def main():
    state_dir = os.environ.get("GRAYWIND_STATE_DIR", "state")
    threshold = int(os.environ.get("MACRO_ALARM_STREAK", DEFAULT_STREAK_THRESHOLD))
    path = os.path.join(state_dir, DECISION_LOG_FILENAME)

    cycles = read_macro_cycles(path)
    streak = unavailable_streak(cycles)
    unhealthy = streak >= threshold
    status = "unhealthy" if unhealthy else "healthy"

    print(
        f"macro health: {status} "
        f"(unavailable streak {streak}/{threshold} cycles, "
        f"{len(cycles)} cycles with a macro reading in {path})"
    )
    if unhealthy:
        print(
            "The macro gate has been unable to answer for a sustained run of cycles. "
            "Because it fails closed, NO new entries are being opened. Check that the "
            "Bullion data.json pipeline is still updating.",
            file=sys.stderr,
        )

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"macro_health={status}\n")
            f.write(f"macro_streak={streak}\n")
    return 0  # never fail the job -- see module docstring


if __name__ == "__main__":
    sys.exit(main())
