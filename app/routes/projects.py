from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import re

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Project, User
from app.schemas import ProjectCreate, ProjectResponse
from app.agents.guardrails import validate_generated_content

router = APIRouter()
WORKSPACE_DIR = Path(__file__).resolve().parents[1] / "workspaces"
ALLOWED_EXTENSIONS = {".html", ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp4", ".webm", ".pdf", ".json", ".txt"}
REQUIRED_FILES = ["index.html", "style.css", "script.js"]


def owned_project(project_id: int, user: User, db: Session) -> Project:
    project = db.scalar(select(Project).where(Project.id == project_id, Project.owner_id == user.id))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def project_workspace(project_id: int):
    root = WORKSPACE_DIR.resolve()
    workspace = (root / str(project_id)).resolve()
    if not workspace.is_relative_to(root) or workspace == root or not workspace.is_dir():
        raise HTTPException(status_code=404, detail="Project workspace not found")
    return workspace


def inspect_artifacts(workspace):
    errors = []
    for filename in REQUIRED_FILES:
        path = workspace / filename
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"Missing or empty {filename}")
            continue
        validation = validate_generated_content(filename, path.read_text(encoding="utf-8"))
        errors.extend(f"{filename}: {error}" for error in validation["errors"])
    return {"available": not errors, "errors": errors}


@router.get("", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(Project).where(Project.owner_id == user.id).order_by(Project.created_at.desc())).all()


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = Project(name=payload.name.strip(), description=payload.description.strip(), owner_id=user.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return owned_project(project_id, user, db)


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    project = owned_project(project_id, user, db)
    db.delete(project)
    db.commit()
    workspace = (WORKSPACE_DIR / str(project_id)).resolve()
    if workspace.is_relative_to(WORKSPACE_DIR.resolve()) and workspace != WORKSPACE_DIR.resolve() and workspace.is_dir():
        import shutil
        shutil.rmtree(workspace, ignore_errors=True)
    return {"message": "Project deleted"}


@router.get("/{project_id}/artifacts")
def project_artifacts(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned_project(project_id, user, db)
    try:
        workspace = project_workspace(project_id)
        result = inspect_artifacts(workspace)
        return {"has_generated_files": result["available"], "errors": result["errors"]}
    except (OSError, UnicodeError):
        return {"has_generated_files": False, "errors": ["Generated files could not be read"]}


@router.get("/{project_id}/download")
def download_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned_project(project_id, user, db)
    workspace = project_workspace(project_id)
    result = inspect_artifacts(workspace)
    if not result["available"]:
        raise HTTPException(status_code=404, detail="A complete valid website is not available to download: " + "; ".join(result["errors"]))
    archive = BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as zip_file:
        for path in sorted(workspace.rglob("*")):
            if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS and path.resolve().is_relative_to(workspace):
                zip_file.write(path, path.relative_to(workspace))
    archive.seek(0)
    return StreamingResponse(iter([archive.getvalue()]), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="forge-project-{project_id}.zip"'})


@router.get("/{project_id}/preview", response_class=HTMLResponse)
def preview_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    owned_project(project_id, user, db)
    workspace = project_workspace(project_id)
    result = inspect_artifacts(workspace)
    if not result["available"]:
        raise HTTPException(status_code=404, detail="A complete valid website is not available to preview: " + "; ".join(result["errors"]))

    html = (workspace / "index.html").read_text(encoding="utf-8")
    css = (workspace / "style.css").read_text(encoding="utf-8")
    javascript = (workspace / "script.js").read_text(encoding="utf-8")
    style_tag = "<style>\n" + re.sub(r"</style", r"<\\/style", css, flags=re.IGNORECASE) + "\n</style>"
    script_tag = "<script>\n" + re.sub(r"</script", r"<\\/script", javascript, flags=re.IGNORECASE) + "\n</script>"

    html, style_count = re.subn(r"<link\b(?=[^>]*\bhref=[\"'](?:\./|/)?style\.css(?:[?#][^\"']*)?[\"'])[^>]*>", lambda _: style_tag, html, count=1, flags=re.IGNORECASE)
    if not style_count:
        html = re.sub(r"</head\s*>", lambda _: style_tag + "\n</head>", html, count=1, flags=re.IGNORECASE)
    html, script_count = re.subn(r"<script\b(?=[^>]*\bsrc=[\"'](?:\./|/)?script\.js(?:[?#][^\"']*)?[\"'])[^>]*>\s*</script>", lambda _: script_tag, html, count=1, flags=re.IGNORECASE | re.DOTALL)
    if not script_count:
        html = re.sub(r"</body\s*>", lambda _: script_tag + "\n</body>", html, count=1, flags=re.IGNORECASE)

    return HTMLResponse(content=html, headers={"Content-Security-Policy": "default-src https: data: blob:; script-src 'unsafe-inline' https:; style-src 'unsafe-inline' https:; img-src https: data: blob:; connect-src https:; object-src 'none'; base-uri 'none'"})
