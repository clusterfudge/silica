"""API routes for managing executions."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from datetime import datetime

from ..models import get_db, JobExecution, ScheduledJob, Prompt

router = APIRouter()


class ExecutionResponse(BaseModel):
    id: int
    scheduled_job_id: Optional[int] = None
    job_name: Optional[str] = None
    prompt_name: str
    session_id: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str
    output: Optional[str] = None
    error_message: Optional[str] = None


class ExecutionStatsResponse(BaseModel):
    total: int
    running: int
    completed: int
    failed: int


@router.get("/recent", response_model=List[ExecutionResponse])
async def get_recent_executions(
    limit: int = Query(default=20, le=100),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Get recent executions."""
    query = (
        db.query(
            JobExecution,
            ScheduledJob.name.label("job_name"),
            Prompt.name.label("prompt_name"),
        )
        .outerjoin(ScheduledJob, JobExecution.scheduled_job_id == ScheduledJob.id)
        .outerjoin(Prompt, ScheduledJob.prompt_id == Prompt.id)
        .order_by(JobExecution.started_at.desc())
    )

    if status:
        query = query.filter(JobExecution.status == status)

    results = query.limit(limit).all()

    return [
        ExecutionResponse(
            id=execution.id,
            scheduled_job_id=execution.scheduled_job_id,
            job_name=job_name,
            prompt_name=prompt_name or "Unknown",
            session_id=execution.session_id,
            started_at=execution.started_at,
            completed_at=execution.completed_at,
            status=execution.status,
            output=execution.output,
            error_message=execution.error_message,
        )
        for execution, job_name, prompt_name in results
    ]


@router.get("/stats", response_model=ExecutionStatsResponse)
async def get_execution_stats(db: Session = Depends(get_db)):
    """Get execution statistics."""
    # Count by status
    stats = (
        db.query(JobExecution.status, func.count(JobExecution.id))
        .group_by(JobExecution.status)
        .all()
    )

    # Convert to dict for easier access
    status_counts = {status: count for status, count in stats}

    return ExecutionStatsResponse(
        total=sum(status_counts.values()),
        running=status_counts.get("running", 0),
        completed=status_counts.get("completed", 0),
        failed=status_counts.get("failed", 0),
    )


@router.get("/{execution_id}")
async def get_execution(execution_id: int, db: Session = Depends(get_db)):
    """Get specific execution details."""
    execution = db.query(JobExecution).filter(JobExecution.id == execution_id).first()
    if not execution:
        return {"error": "Execution not found"}

    # Get job name and prompt name
    job_name = None
    prompt_name = None

    if execution.scheduled_job_id:
        job = (
            db.query(ScheduledJob)
            .filter(ScheduledJob.id == execution.scheduled_job_id)
            .first()
        )
        if job:
            job_name = job.name
            prompt = db.query(Prompt).filter(Prompt.id == job.prompt_id).first()
            if prompt:
                prompt_name = prompt.name

    return ExecutionResponse(
        id=execution.id,
        scheduled_job_id=execution.scheduled_job_id,
        job_name=job_name,
        prompt_name=prompt_name or "Unknown",
        session_id=execution.session_id,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        status=execution.status,
        output=execution.output,
        error_message=execution.error_message,
    )
