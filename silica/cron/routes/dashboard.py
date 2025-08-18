"""Dashboard routes for HTML interface."""

import json
from os.path import dirname, join
from pathlib import Path
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..models import get_db, Prompt, ScheduledJob

router = APIRouter()
templates = Jinja2Templates(directory=join(dirname(dirname(__file__)), "templates"))


@router.get("/prompts", response_class=HTMLResponse)
async def prompts_page(request: Request, db: Session = Depends(get_db)):
    """Prompts management page."""
    prompts = db.query(Prompt).all()
    return templates.TemplateResponse(
        request, "prompts.html", {"prompts": prompts, "title": "Manage Prompts"}
    )


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request, db: Session = Depends(get_db)):
    """Scheduled jobs management page."""
    jobs = db.query(ScheduledJob).join(Prompt).all()
    prompts = db.query(Prompt).all()
    return templates.TemplateResponse(
        request,
        "jobs.html",
        {"jobs": jobs, "prompts": prompts, "title": "Scheduled Jobs"},
    )


@router.post("/prompts/create")
async def create_prompt_form(
    name: str = Form(...),
    description: str = Form(""),
    prompt_text: str = Form(...),
    model: str = Form("haiku"),
    persona: str = Form("basic_agent"),
    db: Session = Depends(get_db),
):
    """Create prompt from form submission."""
    prompt = Prompt(
        name=name,
        description=description,
        prompt_text=prompt_text,
        model=model,
        persona=persona,
    )
    db.add(prompt)
    db.commit()
    return RedirectResponse(url="/prompts", status_code=303)


@router.post("/jobs/create")
async def create_job_form(
    name: str = Form(...),
    prompt_id: str = Form(...),
    cron_expression: str = Form(...),
    db: Session = Depends(get_db),
):
    """Create scheduled job from form submission."""
    job = ScheduledJob(name=name, prompt_id=prompt_id, cron_expression=cron_expression)
    db.add(job)
    db.commit()
    return RedirectResponse(url="/jobs", status_code=303)


@router.get("/sessions/{session_id}", response_class=HTMLResponse)
async def view_session_history(session_id: str, request: Request):
    """View hdev session history."""
    # Build path to session file
    session_file = Path.home() / ".hdev" / "history" / session_id / "root.json"

    if not session_file.exists():
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        # Load session data
        with open(session_file, "r") as f:
            session_data = json.load(f)

        return templates.TemplateResponse(
            request,
            "session_history.html",
            {
                "session_data": session_data,
                "session_id": session_id,
                "title": f"Session {session_id[:8]}...",
            },
        )
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid session file format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading session: {str(e)}")
