from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.schemas.overview import JobResponse
import backend.store as store

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class SyncScheduleRequest(BaseModel):
    platform: str
    interval_seconds: int = Field(alias="intervalSeconds", ge=300, le=2_592_000)
    enabled: bool = True

    model_config = {"populate_by_name": True}


def _response(job: dict) -> JobResponse:
    public_status = job["status"]
    if public_status == "waiting":
        public_status = "retrying" if job["available_at"] is not None else "parked"
    return JobResponse(
        jobId=job["job_id"],
        type=job["type"],
        status=public_status,
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
        operation=job["type"],
        retryable=(
            job["type"] in {"push", "inspect"}
            and (
                job["status"] in {"failed", "canceled", "expired"}
                or (job["status"] == "waiting" and job["available_at"] is None)
            )
        ),
        pollUrl=f"/api/jobs/{job['job_id']}",
        pollAfterMs=2000,
        timeoutSeconds=job["timeout_seconds"],
        cancelRequested=job["cancel_requested_at"] is not None,
    )


@router.get("")
def list_jobs(
    request: Request, status: str | None = None, queue: str | None = None,
    article_id: str | None = None, active: bool | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
):
    jobs = store.list_jobs(
        request.state.user_id, status=status, queue=queue, article_id=article_id,
        active=active, limit=limit, offset=offset
    )
    return {"jobs": [_response(job) for job in jobs], "count": len(jobs)}


@router.get("/metrics")
def get_queue_metrics():
    return store.queue_metrics()


@router.get("/sync-schedules")
def list_sync_schedules(request: Request):
    return {"schedules": store.list_sync_schedules(request.state.user_id)}


@router.put("/sync-schedules")
def upsert_sync_schedule(request: Request, body: SyncScheduleRequest):
    try:
        return store.upsert_sync_schedule(
            request.state.user_id,
            body.platform,
            body.interval_seconds,
            enabled=body.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/sync-schedules/{platform}", status_code=204)
def delete_sync_schedule(request: Request, platform: str):
    if not store.delete_sync_schedule(request.state.user_id, platform):
        raise HTTPException(status_code=404, detail="Sync schedule not found")


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


@router.post("/{job_id}/retry", response_model=JobResponse, status_code=202)
def retry_job(request: Request, job_id: str):
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key is required")
    try:
        job = store.retry_job(
            request.state.user_id, job_id, idempotency_key=idempotency_key
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _response(job)
