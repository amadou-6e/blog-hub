from fastapi import APIRouter, HTTPException, Request
from backend.schemas.overview import JobResponse
import backend.store as store

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
def get_job(request: Request, job_id: str):
    user_id: str = request.state.user_id
    job = store.get_job(user_id, job_id)
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
