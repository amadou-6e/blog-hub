from fastapi import APIRouter, HTTPException
from backend.schemas.overview import JobResponse
import backend.store.memory as store

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str):
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(
        jobId=job["job_id"],
        type=job["type"],
        status=job["status"],
        articleId=job["article_id"],
        result=job["result"],
        error=job["error"],
    )
