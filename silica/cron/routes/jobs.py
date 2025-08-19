"""API routes for managing scheduled jobs."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
from croniter import croniter
from datetime import datetime

from ..models import get_db, ScheduledJob, Prompt, JobExecution

router = APIRouter()


class ScheduledJobCreate(BaseModel):
    name: str
    prompt_id: str
    cron_expression: str


class ScheduledJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    prompt_id: str
    prompt_name: str
    cron_expression: str
    is_active: bool
    created_at: datetime


class JobExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scheduled_job_id: Optional[str]
    session_id: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str
    output: Optional[str] = None
    error_message: Optional[str] = None


@router.get("/", response_model=List[ScheduledJobResponse])
async def list_scheduled_jobs(db: Session = Depends(get_db)):
    """List all scheduled jobs."""
    jobs = db.query(ScheduledJob).join(Prompt).all()
    result = []
    for job in jobs:
        result.append(
            {
                "id": job.id,
                "name": job.name,
                "prompt_id": job.prompt_id,
                "prompt_name": job.prompt.name,
                "cron_expression": job.cron_expression,
                "is_active": job.is_active,
                "created_at": job.created_at,
            }
        )
    return result


@router.post("/", response_model=ScheduledJobResponse)
async def create_scheduled_job(job: ScheduledJobCreate, db: Session = Depends(get_db)):
    """Create a new scheduled job."""
    # Validate cron expression
    try:
        croniter(job.cron_expression)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cron expression")

    # Validate prompt exists
    prompt = db.query(Prompt).filter(Prompt.id == job.prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    db_job = ScheduledJob(
        name=job.name, prompt_id=job.prompt_id, cron_expression=job.cron_expression
    )
    db.add(db_job)
    db.commit()
    db.refresh(db_job)

    return {
        "id": db_job.id,
        "name": db_job.name,
        "prompt_id": db_job.prompt_id,
        "prompt_name": prompt.name,
        "cron_expression": db_job.cron_expression,
        "is_active": db_job.is_active,
        "created_at": db_job.created_at,
    }


@router.put("/{job_id}/toggle")
async def toggle_job_status(job_id: str, db: Session = Depends(get_db)):
    """Toggle job active status."""
    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.is_active = not job.is_active
    db.commit()
    return {"message": f"Job {'activated' if job.is_active else 'deactivated'}"}


@router.delete("/{job_id}")
async def delete_scheduled_job(job_id: str, db: Session = Depends(get_db)):
    """Delete a scheduled job."""
    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    db.delete(job)
    db.commit()
    return {"message": "Job deleted successfully"}


@router.get("/{job_id}/executions", response_model=List[JobExecutionResponse])
async def get_job_executions(
    job_id: str, limit: int = 50, db: Session = Depends(get_db)
):
    """Get execution history for a job."""
    executions = (
        db.query(JobExecution)
        .filter(JobExecution.scheduled_job_id == job_id)
        .order_by(JobExecution.started_at.desc())
        .limit(limit)
        .all()
    )
    return executions


class RecentExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_name: Optional[str] = None
    prompt_name: Optional[str] = None
    scheduled_job_id: Optional[str]
    session_id: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str
    output: Optional[str] = None
    error_message: Optional[str] = None


@router.get("/recent-executions", response_model=List[RecentExecutionResponse])
async def get_recent_executions(limit: int = 50, db: Session = Depends(get_db)):
    """Get recent execution history across all jobs."""
    executions = (
        db.query(JobExecution)
        .outerjoin(ScheduledJob, JobExecution.scheduled_job_id == ScheduledJob.id)
        .outerjoin(Prompt, ScheduledJob.prompt_id == Prompt.id)
        .order_by(JobExecution.started_at.desc())
        .limit(limit)
        .all()
    )

    result = []
    for execution in executions:
        job_name = execution.scheduled_job.name if execution.scheduled_job else None
        prompt_name = (
            execution.scheduled_job.prompt.name
            if execution.scheduled_job and execution.scheduled_job.prompt
            else None
        )

        result.append(
            {
                "id": execution.id,
                "job_name": job_name,
                "prompt_name": prompt_name,
                "scheduled_job_id": execution.scheduled_job_id,
                "session_id": execution.session_id,
                "started_at": execution.started_at,
                "completed_at": execution.completed_at,
                "status": execution.status,
                "output": execution.output,
                "error_message": execution.error_message,
            }
        )

    return result
