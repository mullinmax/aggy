"""Ingest attempt history: how reliably each site has been answering.

Every pass of the ingest job records one row here -- ``ok``, ``error``, or
``skipped`` (the site was in its failure cooldown and never contacted). The
stats page groups them by registrable domain to answer the question a single
``last_ingest_error`` column can't: is this site broken right now, has it been
broken all week, and is it getting better or worse?

``skipped`` is kept distinct from ``error`` deliberately. A skip is the circuit
breaker working as intended, not a fresh failure, and folding the two together
would make a site look worse the more effectively we were avoiding it.
"""

import logging
from datetime import date, timedelta
from typing import List, Optional

from config import config

from .base import get_db_con
from .stats import base_domain

OUTCOME_OK = "ok"
OUTCOME_ERROR = "error"
OUTCOME_SKIPPED = "skipped"

# Errors are long (a quoted bridge error page, a stack trace tail). The column
# is TEXT, but the page only ever shows one line of it.
_ERROR_MAX_CHARS = 500


def record_attempt(
    user_hash: str,
    feed_hash: str,
    source_hash: str,
    host: str,
    outcome: str,
    error: Optional[str] = None,
) -> None:
    """Log one ingest attempt.

    Never raises: this is bookkeeping alongside ingestion, and a failure to
    record an attempt must not turn a successful ingest into a failed one.
    """
    if error is not None and len(error) > _ERROR_MAX_CHARS:
        error = error[: _ERROR_MAX_CHARS - 1] + "…"
    try:
        with get_db_con() as cur:
            cur.execute(
                "INSERT INTO source_ingest_attempts "
                "(user_hash, feed_hash, source_hash, host, outcome, error) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (user_hash, feed_hash, source_hash, host, outcome, error),
            )
    except Exception as e:
        logging.error(f"Could not record ingest attempt for {host}: {e}")


def prune_attempts(days: Optional[int] = None) -> int:
    """Drop attempts older than the retention window. Returns rows deleted."""
    if days is None:
        days = config.get_int("SOURCE_ATTEMPT_HISTORY_DAYS")
    with get_db_con() as cur:
        cur.execute(
            "DELETE FROM source_ingest_attempts "
            "WHERE attempted_at < NOW() - make_interval(days => %s)",
            (days,),
        )
        return cur.rowcount or 0


_HOST_SQL = """
SELECT
    host,
    COUNT(*) FILTER (WHERE outcome <> 'skipped') AS attempts,
    COUNT(*) FILTER (WHERE outcome = 'ok') AS successes,
    COUNT(*) FILTER (WHERE outcome = 'error') AS failures,
    COUNT(*) FILTER (WHERE outcome = 'skipped') AS skipped,
    COUNT(DISTINCT source_hash) AS source_count,
    MAX(attempted_at) FILTER (WHERE outcome = 'ok') AS last_success_at,
    MAX(attempted_at) FILTER (WHERE outcome = 'error') AS last_failure_at,
    (ARRAY_AGG(error ORDER BY attempted_at DESC)
        FILTER (WHERE outcome = 'error'))[1] AS last_error
FROM source_ingest_attempts
WHERE user_hash = %s
  AND attempted_at >= date_trunc('day', NOW()) - make_interval(days => %s)
GROUP BY host
"""

# Daily totals across every host, for the trend line. Skips are excluded from
# the rate for the same reason as above -- they say the breaker is holding, not
# that a request failed -- but are carried through so the chart can show how
# much traffic the breaker suppressed.
_TIMELINE_SQL = """
SELECT
    date_trunc('day', attempted_at)::date AS day,
    COUNT(*) FILTER (WHERE outcome <> 'skipped') AS attempts,
    COUNT(*) FILTER (WHERE outcome = 'error') AS failures,
    COUNT(*) FILTER (WHERE outcome = 'skipped') AS skipped
FROM source_ingest_attempts
WHERE user_hash = %s
  AND attempted_at >= date_trunc('day', NOW()) - make_interval(days => %s)
GROUP BY 1
ORDER BY 1
"""


def _error_rate(failures: int, attempts: int) -> Optional[float]:
    """Share of contacted attempts that failed, or None if none were made.

    None rather than 0.0: a host that was skipped every time this window has no
    error rate to report, and showing it as 0% would read as "healthy" when the
    truth is the opposite.
    """
    if not attempts:
        return None
    return failures / attempts


def host_stats(user_hash: str, days: int) -> List[dict]:
    """Per-site ingest reliability over the window, worst first.

    Hosts are folded to their registrable domain in SQL already (the column is
    written that way), so this is a straight read.
    """
    with get_db_con() as cur:
        cur.execute(_HOST_SQL, (user_hash, days))
        rows = [dict(row) for row in cur.fetchall()]

    # Imported lazily: the breaker lives in the ingest package, which imports
    # this module's neighbours, and only the stats path needs its live state.
    from ingest.host_circuit import open_hosts

    cooldowns = open_hosts()

    for row in rows:
        row["error_rate"] = _error_rate(row["failures"], row["attempts"])
        remaining = cooldowns.get(row["host"])
        row["in_cooldown"] = remaining is not None
        row["cooldown_seconds_remaining"] = (
            round(remaining) if remaining is not None else None
        )

    return sorted(
        rows,
        # worst first, and among equally-broken hosts the busiest -- the page
        # is for finding what to fix, so a site failing 100 fetches outranks one
        # failing 2. Hosts with no contacted attempts sort as fully failing,
        # since the only reason to have none is the breaker holding them back.
        key=lambda row: (
            -(row["error_rate"] if row["error_rate"] is not None else 1.0),
            -(row["failures"] + row["skipped"]),
            row["host"],
        ),
    )


def attempt_timeline(user_hash: str, days: int) -> List[dict]:
    """Daily attempt/failure totals, zero-filled so the axis stays even."""
    with get_db_con() as cur:
        cur.execute(_TIMELINE_SQL, (user_hash, days))
        by_day = {row["day"]: row for row in cur.fetchall()}
        cur.execute("SELECT date_trunc('day', NOW())::date AS today")
        today: date = cur.fetchone()["today"]

    timeline = []
    for offset in range(days, -1, -1):
        day = today - timedelta(days=offset)
        row = by_day.get(day)
        attempts = row["attempts"] if row else 0
        failures = row["failures"] if row else 0
        timeline.append(
            {
                "day": day,
                "attempts": attempts,
                "failures": failures,
                "skipped": row["skipped"] if row else 0,
                "error_rate": _error_rate(failures, attempts),
            }
        )
    return timeline


def _summarize(hosts: List[dict]) -> dict:
    attempts = sum(row["attempts"] for row in hosts)
    failures = sum(row["failures"] for row in hosts)
    return {
        "host_count": len(hosts),
        "attempts": attempts,
        "failures": failures,
        "skipped": sum(row["skipped"] for row in hosts),
        "error_rate": _error_rate(failures, attempts),
        "hosts_in_cooldown": sum(1 for row in hosts if row["in_cooldown"]),
    }


def source_stats(user_hash: str, days: int = 7) -> dict:
    """Everything the source-reliability panel shows."""
    hosts = host_stats(user_hash, days)
    return {
        "summary": _summarize(hosts),
        "hosts": hosts,
        "timeline": attempt_timeline(user_hash, days),
        "days": days,
    }
