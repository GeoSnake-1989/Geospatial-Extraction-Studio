from app import main
from app.models import JobResponse, JobState


def _job(job_id: str, state: JobState = JobState.queued) -> JobResponse:
    return JobResponse(
        id=job_id,
        state=state,
        progress=100 if state in {JobState.completed, JobState.failed} else 2,
        message="test job",
        result={"preview": {"grid": {"values": [[1.0]]}}} if state == JobState.completed else None,
    )


def test_completed_job_history_is_bounded_without_removing_active_jobs(monkeypatch):
    previous_jobs = dict(main.jobs)
    main.jobs.clear()
    monkeypatch.setattr(main, "MAX_COMPLETED_JOB_RECORDS", 2)
    try:
        main.jobs["active"] = _job("active")
        for index in range(3):
            job_id = f"complete-{index}"
            main.jobs[job_id] = _job(job_id)
            main.set_job(
                job_id,
                state=JobState.completed,
                progress=100,
                result={"preview": {"grid": {"values": [[float(index)]]}}},
            )

        assert "active" in main.jobs
        assert "complete-0" not in main.jobs
        assert [job_id for job_id in main.jobs if job_id.startswith("complete-")] == [
            "complete-1",
            "complete-2",
        ]
    finally:
        main.jobs.clear()
        main.jobs.update(previous_jobs)
