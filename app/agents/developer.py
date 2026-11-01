import asyncio
import os
import re
import tempfile
from pathlib import Path
from uuid import uuid4

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agents.config import APP_NAME, MODEL, get_model
from app.agents.guardrails import resolve_workspace, resolve_file_path, validate_generated_content

FILES = ["index.html", "style.css", "script.js"]

session_service = InMemorySessionService()


def build_developer_agent():
    agent_model = MODEL or get_model()
    return LlmAgent(
        name="forge_developer",
        model=agent_model,
        description="Generates and updates application source code.",
        instruction="""
You are Forge's Developer Agent. Build complete, functional, responsive frontend applications using HTML, CSS, Tailwind CSS and vanilla JavaScript only. Do not create a backend.

Always follow the user's requirements and the Supervisor's plan. Keep index.html, style.css and script.js separate. Include all required functionality, real navigation and meaningful content. Do not leave placeholder buttons or fake functionality. Keep the three files compatible with each other. Do not put CSS or JavaScript inside the wrong file. Return only the complete source code for the requested file, without explanations or Markdown fences.

In correction mode, inspect the existing file and tester feedback, preserve working features and change only what is necessary. If no change is needed, return exactly NO_CHANGE.
""",
    )


def clean_code(content, filename):
    content = (content or "").strip().lstrip("\ufeff")
    extension = Path(filename).suffix.lower()
    language = {".html": "html", ".css": "css", ".js": "(?:javascript|js)"}.get(extension, "")
    fenced = re.search(r"```\s*" + language + r"\s*\n(.*?)```", content, re.DOTALL | re.IGNORECASE) if language else None
    if not fenced:
        fenced = re.search(r"```(?:html|css|javascript|js)?\s*\n(.*?)```", content, re.DOTALL | re.IGNORECASE)
    if fenced:
        content = fenced.group(1).strip()
    elif extension == ".html":
        match = re.search(r"<!doctype\s+html\b", content, re.IGNORECASE)
        if match:
            content = content[match.start():]
    elif extension == ".css":
        match = re.search(r"(?m)^\s*(?:@(?:import|tailwind|layer|charset|media|supports|font-face|keyframes)\b|[^\s].*\{)", content)
        if match:
            content = content[match.start():]
    elif extension == ".js":
        match = re.search(r"(?m)^\s*(?:import\s|export\s|const\s|let\s|var\s|async\s+function\s|function\s|class\s|document\.|window\.|console\.|//|/\*)", content)
        if match:
            content = content[match.start():]
    return content.strip()


async def generate_file(filename, requirements, project_id, user_id, session_id=None, correction=False):
    workspace = resolve_workspace(project_id, create=True)
    target = resolve_file_path(workspace, filename)
    existing_code = target.read_text(encoding="utf-8") if correction and target.is_file() else ""
    if correction and not target.is_file():
        raise FileNotFoundError(f"Existing file not found: {filename}")

    if correction:
        prompt = f"""CORRECTION MODE
Original requirements and tester feedback:
{requirements}

File to inspect and correct: {filename}
Existing source:
{existing_code}

Return the complete corrected {filename} only. Preserve working behavior and all user requirements. Do not return another file's content. If this file needs no change, return exactly NO_CHANGE. No explanations or Markdown fences."""
    else:
        prompt = f"""PROJECT REQUIREMENTS:
{requirements}

Generate the complete source code for {filename} only.
Responsibilities: index.html is the complete HTML document and references ./style.css and ./script.js; style.css contains all custom styling; script.js contains all interactive behavior. Use HTML, CSS, Tailwind CDN if useful, and vanilla JavaScript. Do not place HTML in CSS/JS or CSS/JS in HTML. Make every requested feature functional and responsive. No explanations, no Markdown fences."""

    current_session = session_id or str(uuid4())
    runner = Runner(agent=build_developer_agent(), app_name=APP_NAME, session_service=session_service)
    await session_service.create_session(app_name=APP_NAME, user_id=user_id, session_id=current_session, state={"workspace_path": str(workspace)})
    message = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    response = ""
    async for event in runner.run_async(user_id=user_id, session_id=current_session, new_message=message):
        if event.is_final_response() and event.content:
            response = "".join(part.text for part in event.content.parts if part.text)

    if not response.strip():
        raise RuntimeError(f"Developer returned an empty response for {filename}")
    if correction and response.strip().strip("` ") == "NO_CHANGE":
        validation = validate_generated_content(filename, existing_code)
        if validation["status"] != "passed":
            raise RuntimeError(f"Existing {filename} is invalid and cannot be left unchanged: " + "; ".join(validation["errors"]))
        return {"file": filename, "status": "unchanged", "characters": len(existing_code)}

    content = clean_code(response, filename)
    validation = validate_generated_content(filename, content)
    if validation["status"] != "passed":
        raise RuntimeError(f"Generated {filename} is invalid: " + "; ".join(validation["errors"]))
    for warning in validation["warnings"]:
        print(f"Guardrail warning [{filename}]: {warning}")

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, target)
    except Exception:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise

    return {"file": filename, "status": "updated" if correction else "created", "characters": len(content), "warnings": validation["warnings"]}


async def run_developer(task, project_id, user_id="local_user", session_id=None, correction=False):
    resolve_workspace(project_id, create=True)
    results = []
    for filename in FILES:
        print(f"\n{'Checking' if correction else 'Generating'} {filename}...")
        result = await generate_file(filename, task, project_id, user_id, f"{session_id}_{filename}" if session_id else None, correction)
        results.append(result)
        print(f"{result['status'].capitalize()} {filename} ({result['characters']} characters)")
    return "\n".join(f"{item['file']}: {item['status']} ({item['characters']} characters)" for item in results)


if __name__ == "__main__":
    project_id = input("Project ID: ")
    task = input("Development task: ")
    print(asyncio.run(run_developer(task, project_id)))
