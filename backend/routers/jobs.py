from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from backend.schemas.overview import JobResponse
import backend.store as store

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _response(job: dict) -> JobResponse:
    return JobResponse(
        jobId=job["job_id"],
        type=job["type"],
        status=job["status"],
        articleId=job["article_id"],
        result=job["result"],
        error=job["error"],
        queue=job["queue"],
        priority=job["priority"],
        attemptCount=job["attempt_count"],
        maxAttempts=job["max_attempts"],
        availableAt=job["available_at"],
        heartbeatAt=job["heartbeat_at"],
        leaseExpiresAt=job["lease_expires_at"],
        createdAt=job["created_at"],
        updatedAt=job["updated_at"],
        completedAt=job["completed_at"],
        checkpoint=job["checkpoint"],
    )


@router.get("")
def list_jobs(
    request: Request, status: str | None = None, queue: str | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
):
    jobs = store.list_jobs(
        request.state.user_id, status=status, queue=queue, limit=limit, offset=offset
    )
    return {"jobs": [_response(job) for job in jobs], "count": len(jobs)}


@router.get("/metrics")
def get_queue_metrics():
    return store.queue_metrics()


@router.get("/{job_id}", response_model=JobResponse)
def get_job(request: Request, job_id: str):
    job = store.get_job(request.state.user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _response(job)


@router.post("/{job_id}/cancel", response_model=JobResponse)
def cancel_job(request: Request, job_id: str):
    job = store.request_job_cancellation(request.state.user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _response(job)


@router.post("/{job_id}/retry", response_model=JobResponse)
def retry_job(request: Request, job_id: str):
    try:
        job = store.retry_job(request.state.user_id, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _response(job)
