from jobs.job_registry import jobs


def test_jobs():
    assert isinstance(jobs, list)
    for job in jobs:
        assert isinstance(job, dict)
        assert "func" in job
        assert "trigger" in job
        assert "id" in job
        assert "replace_existing" in job
