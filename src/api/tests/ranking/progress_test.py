"""Unit tests for the in-memory training progress registry."""

import pytest

from ranking import progress


@pytest.fixture(autouse=True)
def _clean_registry():
    progress.reset()
    yield
    progress.reset()


def test_no_run_reports_nothing():
    assert progress.status("user", "feed") is None
    assert progress.is_running("user", "feed") is False


def test_run_reports_its_phase_and_model():
    assert progress.start("user", "feed", total_steps=5) is True
    assert progress.is_running("user", "feed") is True

    progress.update(
        "user", "feed", step=2, phase=progress.PHASE_EVALUATING, model_name="ridge"
    )
    status = progress.status("user", "feed")
    assert status["status"] == progress.STATUS_RUNNING
    assert status["phase"] == progress.PHASE_EVALUATING
    assert status["model_name"] == "ridge"
    assert (status["step"], status["total_steps"]) == (2, 5)


def test_second_start_is_refused_while_running():
    assert progress.start("user", "feed", total_steps=5) is True
    assert progress.start("user", "feed", total_steps=5) is False
    # a different feed is untouched by the first feed's run
    assert progress.start("user", "other-feed", total_steps=5) is True


def test_finished_run_is_readable_and_complete():
    progress.start("user", "feed", total_steps=5)
    progress.update("user", "feed", step=1, model_name="ridge")
    progress.finish("user", "feed")

    status = progress.status("user", "feed")
    assert status["status"] == progress.STATUS_DONE
    assert status["step"] == status["total_steps"]
    assert status["model_name"] is None
    assert status["error"] is None
    # and the feed is free to be trained again
    assert progress.is_running("user", "feed") is False
    assert progress.start("user", "feed", total_steps=5) is True


def test_failed_run_keeps_its_error():
    progress.start("user", "feed", total_steps=5)
    progress.finish("user", "feed", error="database went away")

    status = progress.status("user", "feed")
    assert status["status"] == progress.STATUS_ERROR
    assert status["error"] == "database went away"


def test_update_without_a_run_is_a_no_op():
    progress.update("user", "feed", step=3)
    assert progress.status("user", "feed") is None


def test_finished_runs_expire(monkeypatch):
    progress.start("user", "feed", total_steps=5)
    progress.finish("user", "feed")

    real_time = progress.time.time

    monkeypatch.setattr(
        progress.time,
        "time",
        lambda: real_time() + progress.FINISHED_TTL_SECONDS + 1,
    )
    assert progress.status("user", "feed") is None
