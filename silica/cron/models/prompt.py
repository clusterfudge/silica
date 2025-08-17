"""Models for prompts and scheduled jobs."""

from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base
from .id_generator import generate_prompt_id, generate_job_id, generate_execution_id


class Prompt(Base):
    """Model for storing agent prompts."""

    __tablename__ = "prompts"

    id = Column(String(64), primary_key=True, index=True, default=generate_prompt_id)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    prompt_text = Column(Text, nullable=False)
    model = Column(
        String(50), nullable=False, default="haiku"
    )  # haiku, sonnet, sonnet-3.5, opus
    persona = Column(
        String(50), nullable=False, default="basic_agent"
    )  # basic_agent, deep_research_agent, autonomous_engineer
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationship to scheduled jobs
    scheduled_jobs = relationship("ScheduledJob", back_populates="prompt")


class ScheduledJob(Base):
    """Model for cron-scheduled jobs."""

    __tablename__ = "scheduled_jobs"

    id = Column(String(64), primary_key=True, index=True, default=generate_job_id)
    name = Column(String(255), nullable=False, index=True)
    prompt_id = Column(String(64), ForeignKey("prompts.id"), nullable=False)
    cron_expression = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    prompt = relationship("Prompt", back_populates="scheduled_jobs")
    executions = relationship("JobExecution", back_populates="scheduled_job")


class JobExecution(Base):
    """Model for tracking job execution history."""

    __tablename__ = "job_executions"

    id = Column(String(64), primary_key=True, index=True, default=generate_execution_id)
    scheduled_job_id = Column(
        String(64), ForeignKey("scheduled_jobs.id"), nullable=True
    )  # Allow NULL for manual executions
    session_id = Column(
        String(36), nullable=True, index=True
    )  # UUID for hdev session tracking
    started_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime, nullable=True)
    status = Column(
        String(50), default="pending"
    )  # pending, running, completed, failed
    output = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    # Relationship
    scheduled_job = relationship("ScheduledJob", back_populates="executions")
