"""API routes for managing prompts."""

from typing import List, Literal
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
from datetime import datetime
import threading

from ..models import get_db, Prompt, JobExecution, SessionLocal, ScheduledJob
from ..scheduler import scheduler

router = APIRouter()


class PromptCreate(BaseModel):
    name: str
    description: str = ""
    prompt_text: str
    model: Literal["haiku", "sonnet", "sonnet-3.5", "opus"] = "haiku"
    persona: Literal["basic_agent", "deep_research_agent", "autonomous_engineer"] = (
        "basic_agent"
    )


class PromptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    prompt_text: str
    model: str
    persona: str
    created_at: datetime
    updated_at: datetime


class ExecutionResponse(BaseModel):
    execution_id: str
    status: str
    message: str


@router.get("/", response_model=List[PromptResponse])
async def list_prompts(db: Session = Depends(get_db)):
    """List all prompts."""
    prompts = db.query(Prompt).all()
    return prompts


@router.post("/", response_model=PromptResponse)
async def create_prompt(prompt: PromptCreate, db: Session = Depends(get_db)):
    """Create a new prompt."""
    db_prompt = Prompt(
        name=prompt.name,
        description=prompt.description,
        prompt_text=prompt.prompt_text,
        model=prompt.model,
        persona=prompt.persona,
    )
    db.add(db_prompt)
    db.commit()
    db.refresh(db_prompt)
    return db_prompt


@router.get("/{prompt_id}", response_model=PromptResponse)
async def get_prompt(prompt_id: str, db: Session = Depends(get_db)):
    """Get a specific prompt."""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return prompt


@router.put("/{prompt_id}", response_model=PromptResponse)
async def update_prompt(
    prompt_id: str, prompt: PromptCreate, db: Session = Depends(get_db)
):
    """Update a prompt."""
    db_prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not db_prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    db_prompt.name = prompt.name
    db_prompt.description = prompt.description
    db_prompt.prompt_text = prompt.prompt_text
    db_prompt.model = prompt.model
    db_prompt.persona = prompt.persona
    db.commit()
    db.refresh(db_prompt)
    return db_prompt


@router.delete("/{prompt_id}")
async def delete_prompt(prompt_id: str, db: Session = Depends(get_db)):
    """Delete a prompt."""
    db_prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not db_prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    db.delete(db_prompt)
    db.commit()
    return {"message": "Prompt deleted successfully"}


@router.post("/{prompt_id}/execute", response_model=ExecutionResponse)
async def execute_prompt_manually(
    prompt_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """Execute a prompt manually without scheduling."""
    # Get the prompt
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # Create execution record for manual execution
    execution = JobExecution(
        scheduled_job_id=None,  # None indicates manual execution
        status="running",
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)

    # Execute in background
    def execute_in_background():
        """Execute the prompt in a background thread."""
        db_bg = SessionLocal()
        try:
            execution_bg = (
                db_bg.query(JobExecution)
                .filter(JobExecution.id == execution.id)
                .first()
            )

            session_id = None  # Initialize session_id
            try:
                # Execute the prompt via scheduler's hdev integration with prompt settings
                result, session_id = scheduler._call_agent(
                    prompt=prompt.prompt_text,
                    model=prompt.model,
                    persona=prompt.persona,
                )

                # Update execution with success
                execution_bg.completed_at = datetime.now()
                execution_bg.status = "completed"
                execution_bg.output = result
                execution_bg.session_id = session_id
                db_bg.commit()

            except Exception as e:
                # Update execution with error (session_id might still be available)
                execution_bg.completed_at = datetime.now()
                execution_bg.status = "failed"
                execution_bg.error_message = str(e)
                execution_bg.session_id = (
                    session_id  # Store session_id even on failure if available
                )
                db_bg.commit()

        except Exception as e:
            print(f"Background execution error: {e}")
        finally:
            db_bg.close()

    # Start background execution
    thread = threading.Thread(target=execute_in_background, daemon=True)
    thread.start()

    return ExecutionResponse(
        execution_id=execution.id,
        status="running",
        message=f"Prompt '{prompt.name}' execution started",
    )


@router.get("/{prompt_id}/executions/{execution_id}")
async def get_execution_status(
    prompt_id: str, execution_id: str, db: Session = Depends(get_db)
):
    """Get the status of a manual execution."""
    execution = db.query(JobExecution).filter(JobExecution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    return {
        "id": execution.id,
        "status": execution.status,
        "session_id": execution.session_id,
        "started_at": execution.started_at,
        "completed_at": execution.completed_at,
        "output": execution.output,
        "error_message": execution.error_message,
    }


class PromptExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_name: str = None
    scheduled_job_id: str = None
    session_id: str = None
    started_at: datetime
    completed_at: datetime = None
    status: str
    output: str = None
    error_message: str = None


@router.get("/{prompt_id}/executions", response_model=List[PromptExecutionResponse])
async def get_prompt_executions(
    prompt_id: str, limit: int = 50, db: Session = Depends(get_db)
):
    """Get execution history for a specific prompt."""
    # Verify prompt exists
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # Get executions through scheduled jobs that use this prompt, plus manual executions
    scheduled_job_ids = (
        db.query(ScheduledJob.id).filter(ScheduledJob.prompt_id == prompt_id).subquery()
    )

    executions = (
        db.query(JobExecution)
        .outerjoin(ScheduledJob, JobExecution.scheduled_job_id == ScheduledJob.id)
        .filter(
            (JobExecution.scheduled_job_id.in_(scheduled_job_ids))
            | (JobExecution.scheduled_job_id.is_(None))  # Include manual executions
        )
        .order_by(JobExecution.started_at.desc())
        .limit(limit)
        .all()
    )

    result = []
    for execution in executions:
        job_name = (
            execution.scheduled_job.name
            if execution.scheduled_job
            else "Manual Execution"
        )

        result.append(
            {
                "id": execution.id,
                "job_name": job_name,
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
