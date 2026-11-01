import sys
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ALLOWED_ORIGINS, JWT_ALGORITHM, JWT_SECRET_KEY, PORT
from app.database import Base, engine, get_db
from app.dependencies import get_current_user
from app.models import Project, User
from app.routes import auth, chat, projects
from app.security import create_preview_token, decode_preview_token

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Website Builder API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(projects.router, prefix="/api/projects", tags=["Projects"])
app.include_router(chat.router, prefix="/api/projects", tags=["Chat"])


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/projects/{project_id}/preview-token")
def project_preview_token(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    project = db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.owner_id == user.id,
        )
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    token = create_preview_token(user.id, project.id)
    preview_url = f"/preview/{project.id}/t/{token}/index.html"
    return {"preview_url": preview_url}


def _authorize_preview(project_id: int, token: str, db: Session) -> User:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        user_id, token_project_id = decode_preview_token(token)
    except (ValueError, jwt.PyJWTError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired preview token")

    if token_project_id != project_id:
        raise HTTPException(status_code=401, detail="Preview token does not match the project")

    user = db.get(User, user_id)
    if not user or user.id != project.owner_id:
        raise HTTPException(status_code=401, detail="Preview access denied")

    return user


@app.get("/preview/{project_id}/t/{token}")
@app.get("/preview/{project_id}/t/{token}/{file_path:path}")
def preview_file(
    project_id: int,
    token: str,
    request: Request,
    file_path: str = "index.html",
    db: Session = Depends(get_db),
):
    _authorize_preview(project_id, token, db)

    workspace = (
        Path(__file__).resolve().parent / "workspaces" / str(project_id)
    ).resolve()
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail="Project preview not found")

    file_path = file_path or "index.html"
    target = (workspace / file_path).resolve()
    if not target.is_relative_to(workspace) or not target.is_file():
        raise HTTPException(status_code=404, detail="Preview asset not found")

    preview_base = f"/preview/{project_id}/t/{token}/"
    headers = {
        "Content-Security-Policy": (
            "default-src 'self' data: blob: https:; "
            "img-src 'self' data: blob: https:; "
            "style-src 'self' 'unsafe-inline' https:; "
            "script-src 'self' 'unsafe-inline' https:; "
            "connect-src 'self' https:; "
            "font-src 'self' data: https:; "
            "object-src 'none'; "
            "frame-ancestors 'self'; "
            "base-uri 'self'"
        ),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }

    if target.name.lower().endswith((".html", ".htm")):
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=415, detail="Preview HTML must be UTF-8")

        import re

        base_tag = f'<base href="{preview_base}">'
        if re.search(r"<base\b", content, flags=re.IGNORECASE):
            content = re.sub(
                r"<base\b[^>]*>", base_tag, content, count=1, flags=re.IGNORECASE
            )
        elif re.search(r"<head\b[^>]*>", content, flags=re.IGNORECASE):
            content = re.sub(
                r"<head\b[^>]*>",
                lambda match: match.group(0) + base_tag,
                content,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            content = base_tag + content

        return HTMLResponse(content, headers=headers)

    return FileResponse(target, headers=headers)


frontend_dir = Path(__file__).resolve().parent / "frontend"
if frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, reload=False)