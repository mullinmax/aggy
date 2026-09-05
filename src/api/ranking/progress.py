"""Live progress for the vote-prediction training runs of a feed.

Training a feed cross-validates the whole model zoo, which takes long enough
that the UI should show what is happening rather than freeze on a spinner. The
run itself happens on a background thread, so its state lives here: the API
process is a single uvicorn instance (see main.py), and both the manual
"retrain now" button and the scheduled ranking job report into the same
registry, so the UI shows a scheduled retrain exactly as it shows a requested
one.

Nothing here is persisted. A run that dies with the process leaves no trace,
which is correct: the training is idempotent and simply runs again.
"""

import threading
import time
from typing import Dict, Optional, Tuple

# How long a finished (or failed) run stays readable, so a UI that polls every
# couple of seconds still gets to show the outcome it was waiting for.
FINISHED_TTL_SECONDS = 120

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"

# Phases a run moves through, in order: read the votes, cross-validate the
# zoo against them (the bulk of the work, one step per model), fit the winner
# on every vote, then score the feed's articles with it and save the result.
PHASE_LOADING = "loading"
PHASE_EVALUATING = "evaluating"
PHASE_TRAINING = "training"
PHASE_PREDICTING = "predicting"

_lock = threading.Lock()
_runs: Dict[Tuple[str, str], dict] = {}


def _key(user_hash: str, feed_hash: str) -> Tuple[str, str]:
    return (user_hash, feed_hash)


def _prune(now: float) -> None:
    """Drop finished runs nobody came back for. Callers hold the lock."""
    for key, run in list(_runs.items()):
        if run["status"] == STATUS_RUNNING:
            continue
        if now - run["finished_at"] > FINISHED_TTL_SECONDS:
            del _runs[key]


def is_running(user_hash: str, feed_hash: str) -> bool:
    with _lock:
        run = _runs.get(_key(user_hash, feed_hash))
        return run is not None and run["status"] == STATUS_RUNNING


def start(user_hash: str, feed_hash: str, total_steps: int) -> bool:
    """Register a run. False when one is already going, so a double-click (or
    the scheduler landing on a feed the user just asked for) doesn't train the
    same feed twice at once."""
    now = time.time()
    with _lock:
        _prune(now)
        key = _key(user_hash, feed_hash)
        existing = _runs.get(key)
        if existing is not None and existing["status"] == STATUS_RUNNING:
            return False
        _runs[key] = {
            "status": STATUS_RUNNING,
            "phase": PHASE_LOADING,
            "model_name": None,
            "note": None,
            "step": 0.0,
            "total_steps": max(1, total_steps),
            "started_at": now,
            "finished_at": None,
            "error": None,
        }
        return True


def update(
    user_hash: str,
    feed_hash: str,
    *,
    step: Optional[float] = None,
    phase: Optional[str] = None,
    model_name: Optional[str] = None,
    note: Optional[str] = None,
) -> None:
    """Advance a run. A no-op when no run is registered, so the engine can be
    called directly (tests, a script) without one.

    `step` is fractional on purpose: the slowest models take tens of seconds
    to cross-validate, and a bar that only moves between models looks stuck.
    `note` says what is happening inside the current step ("fold 3 of 5",
    "scoring 4,812 articles").
    """
    with _lock:
        run = _runs.get(_key(user_hash, feed_hash))
        if run is None or run["status"] != STATUS_RUNNING:
            return
        if step is not None:
            run["step"] = max(0.0, min(float(step), run["total_steps"]))
        if phase is not None:
            run["phase"] = phase
        # model_name and note are cleared deliberately between phases, so an
        # explicit None is meaningful and only an omitted argument would leave
        # them alone — which is why neither has a "keep" sentinel
        run["model_name"] = model_name
        run["note"] = note


def finish(user_hash: str, feed_hash: str, error: Optional[str] = None) -> None:
    now = time.time()
    with _lock:
        run = _runs.get(_key(user_hash, feed_hash))
        if run is None:
            return
        run["status"] = STATUS_ERROR if error else STATUS_DONE
        run["error"] = error
        run["finished_at"] = now
        if not error:
            run["step"] = float(run["total_steps"])
            run["model_name"] = None
            run["note"] = None
        _prune(now)


def status(user_hash: str, feed_hash: str) -> Optional[dict]:
    """The feed's current (or just-finished) run, or None when there is
    nothing to report."""
    now = time.time()
    with _lock:
        _prune(now)
        run = _runs.get(_key(user_hash, feed_hash))
        if run is None:
            return None
        elapsed = (run["finished_at"] or now) - run["started_at"]
        return {
            "status": run["status"],
            "phase": run["phase"],
            "model_name": run["model_name"],
            "note": run["note"],
            "step": run["step"],
            "total_steps": run["total_steps"],
            "elapsed_seconds": round(elapsed, 1),
            "error": run["error"],
        }


def reset() -> None:
    """Forget every run — for tests."""
    with _lock:
        _runs.clear()
