import asyncio
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.dependencies import get_current_user
from app.models import Message, Project, User
from app.schemas import MessageCreate, MessageResponse
from app.agents.orchestration import run_workflow

router = APIRouter()


def get_owned_project(project_id: int, user: User, db: Session):
    project = db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == user.id
        )
    )

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return project


def process_generation(project_id: int, user_id: int, prompt: str, assistant_message_id: int):
    db = SessionLocal()

    try:
        project = db.get(Project, project_id)
        assistant_message = db.get(Message, assistant_message_id)

        if not project or not assistant_message:
            return

        result = asyncio.run(
            run_workflow(
                prompt=prompt,
                project_id=str(project_id),
                user_id=str(user_id),
            )
        )

        project.status = result["status"]
        report = result.get("final_report") or "No final report was returned."

        if result.get("has_generated_files"):
            if result["status"] == "completed":
                heading = "Your website has been generated and passed the available checks."
            else:
                heading = "Your website files are available, but some checks remain incomplete or failed. You can preview and download the current version."
            assistant_message.content = f"{heading}\n\n{report}"
        else:
            assistant_message.content = f"Forge could not generate a complete website.\n\n{report}"

        db.commit()

    except Exception as e:
        db.rollback()
        project = db.get(Project, project_id)
        assistant_message = db.get(Message, assistant_message_id)

        if project:
            project.status = "failed"

        if assistant_message:
            assistant_message.content = f"Forge generation failed: {e}"

        db.commit()

    finally:
        db.close()


@router.get("/{project_id}/messages", response_model=list[MessageResponse])
def list_messages(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    get_owned_project(project_id, user, db)

    return db.scalars(
        select(Message)
        .where(Message.project_id == project_id)
        .order_by(Message.created_at, Message.id)
    ).all()


@router.post(
    "/{project_id}/messages",
    response_model=list[MessageResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
def send_message(
    project_id: int,
    payload: MessageCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    project = get_owned_project(project_id, user, db)
    content = payload.content.strip()

    if not content:
        raise HTTPException(status_code=422, detail="Message cannot be empty")

    if project.status == "in_progress":
        raise HTTPException(
            status_code=409,
            detail="This project is already being generated. Please wait for it to finish.",
        )

    user_message = Message(
        project_id=project.id,
        role="user",
        content=content,
    )

    assistant_message = Message(
        project_id=project.id,
        role="assistant",
        content="Forge is working on your application. This may take a few minutes...",
    )

    project.status = "in_progress"
    db.add_all([user_message, assistant_message])
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)

    background_tasks.add_task(
        process_generation,
        project.id,
        user.id,
        content,
        assistant_message.id,
    )

    return [user_message, assistant_message]
