
import asyncio
import re
import subprocess
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import ToolContext
from google.genai import types
from html.parser import HTMLParser

from app.agents.config import APP_NAME, MODEL, get_model
from app.agents.guardrails import validate_generated_content


WORKSPACE_DIR = Path(__file__).resolve().parent.parent / "workspaces"

ALLOWED_EXTENSIONS = {
    ".html", ".css", ".js", ".json", ".md", ".txt",
    ".svg", ".webmanifest"
}

EXPECTED_FILES = ["index.html", "style.css", "script.js"]


def get_workspace(tool_context: ToolContext):
    workspace = tool_context.state.get("workspace_path")

    if not workspace:
        raise ValueError("No workspace assigned to this session")

    root = Path(workspace).resolve()
    base = WORKSPACE_DIR.resolve()

    if not root.is_relative_to(base) or root == base:
        raise ValueError("Invalid workspace path")

    if not root.is_dir():
        raise ValueError("Workspace does not exist")

    return root


def get_safe_path(path: str, tool_context: ToolContext):
    if not isinstance(path, str) or not path.strip():
        raise ValueError("A file path is required")

    root = get_workspace(tool_context)
    target = (root / path).resolve()

    if not target.is_relative_to(root) or target == root:
        raise ValueError("Invalid file path")

    if target.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported file extension")

    if not target.is_file():
        raise ValueError(f"File does not exist: {path}")

    return target


def tool_error(error):
    return {
        "status": "error",
        "message": str(error),
    }


def list_files(tool_context: ToolContext):
    """List all files in the assigned project workspace."""

    try:
        root = get_workspace(tool_context)

        files = [
            str(path.relative_to(root))
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in ALLOWED_EXTENSIONS
            and path.resolve().is_relative_to(root)
        ]

        return {
            "status": "success",
            "files": files,
        }

    except (ValueError, OSError) as e:
        return tool_error(e)


def read_file(path: str, tool_context: ToolContext):
    """Read a project file for inspection."""

    try:
        target = get_safe_path(path, tool_context)

        if target.stat().st_size > 1_000_000:
            return {
                "status": "error",
                "message": "File exceeds 1 MB",
            }

        return {
            "status": "success",
            "path": path,
            "content": target.read_text(encoding="utf-8"),
        }

    except (ValueError, OSError, UnicodeError) as e:
        return tool_error(e)


class HTMLValidator(HTMLParser):

    def __init__(self):
        super().__init__()
        self.ids = set()
        self.references = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if "id" in attrs:
            if attrs["id"] in self.ids:
                self.errors.append(
                    f"Duplicate HTML id: {attrs['id']}"
                )

            self.ids.add(attrs["id"])

        if tag == "script" and attrs.get("src"):
            self.references.append(attrs["src"])

        if tag == "link" and attrs.get("href"):
            if "stylesheet" in (attrs.get("rel") or "").lower().split():
                self.references.append(attrs["href"])


def resolve_reference(reference, html_file, workspace):
    reference = reference.strip()

    if not reference:
        return None

    parsed = urlsplit(reference)

    if parsed.scheme or parsed.netloc:
        return None

    if reference.startswith("#"):
        return None

    reference_path = parsed.path

    if not reference_path:
        return None

    if reference_path.startswith("/"):
        target = (workspace / reference_path.lstrip("/")).resolve()
    else:
        target = (html_file.parent / reference_path).resolve()

    if not target.is_relative_to(workspace):
        raise ValueError(f"Reference escapes workspace: {reference}")

    return target


def validate_html(path: str, tool_context: ToolContext):
    """Validate HTML structure, duplicate IDs and local CSS/JS references."""

    try:
        target = get_safe_path(path, tool_context)

        if target.suffix.lower() != ".html":
            return {
                "status": "error",
                "message": "Expected an HTML file",
            }

        if target.stat().st_size > 1_000_000:
            return {
                "status": "error",
                "message": "HTML file exceeds 1 MB",
            }

        content = target.read_text(encoding="utf-8")
        type_validation = validate_generated_content(path, content)
        errors = list(type_validation["errors"])
        parser = HTMLValidator()

        try:
            parser.feed(content)
            parser.close()
        except Exception as e:
            errors.append(f"HTML parsing error: {e}")

        errors.extend(parser.errors)

        root = get_workspace(tool_context)

        for reference in parser.references:
            try:
                referenced_file = resolve_reference(
                    reference,
                    target,
                    root,
                )

                if referenced_file is None:
                    continue

                if not referenced_file.is_file():
                    errors.append(
                        f"Missing referenced file: {reference}"
                    )

            except ValueError as e:
                errors.append(str(e))

        return {
            "status": "passed" if not errors else "failed",
            "file": path,
            "errors": errors,
            "duplicate_ids": parser.errors,
            "references_checked": len(parser.references),
        }

    except (ValueError, OSError, UnicodeError) as e:
        return tool_error(e)


def validate_css(path: str, tool_context: ToolContext):
    """Validate stylesheet content and basic CSS structure without executing it."""
    try:
        target = get_safe_path(path, tool_context)
        if target.suffix.lower() != ".css":
            return {"status": "error", "message": "Expected a CSS file"}
        if target.stat().st_size > 1_000_000:
            return {"status": "error", "message": "CSS file exceeds 1 MB"}
        content = target.read_text(encoding="utf-8")
        validation = validate_generated_content(path, content)
        return {
            "status": "passed" if validation["status"] == "passed" else "failed",
            "file": path,
            "errors": validation["errors"],
            "warnings": validation["warnings"],
        }
    except (ValueError, OSError, UnicodeError) as e:
        return tool_error(e)


def validate_javascript(path: str, tool_context: ToolContext):
    """Check JavaScript syntax using Node.js without executing the file."""

    try:
        target = get_safe_path(path, tool_context)

        if target.suffix.lower() != ".js":
            return {
                "status": "error",
                "message": "Expected a JavaScript file",
            }

        if target.stat().st_size > 1_000_000:
            return {
                "status": "error",
                "message": "JavaScript file exceeds 1 MB",
            }

        try:
            result = subprocess.run(
                ["node", "--check", str(target)],
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
            )

            return {
                "status": "passed" if result.returncode == 0 else "failed",
                "file": path,
                "errors": result.stderr.strip(),
            }

        except FileNotFoundError:
            return {
                "status": "unavailable",
                "message": "Node.js is not installed or is not available in PATH",
            }

        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "message": "JavaScript validation timed out",
            }

    except (ValueError, OSError) as e:
        return tool_error(e)


def inspect_project(tool_context: ToolContext):
    """Get a summary of the generated project files."""

    try:
        root = get_workspace(tool_context)

        files = [
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in ALLOWED_EXTENSIONS
            and path.resolve().is_relative_to(root)
        ]

        relative_files = [
            str(path.relative_to(root))
            for path in files
        ]

        missing = [
            filename
            for filename in EXPECTED_FILES
            if filename not in relative_files
        ]

        return {
            "status": "success",
            "total_files": len(files),
            "files": relative_files,
            "missing_required_files": missing,
            "html_files": [
                str(p.relative_to(root))
                for p in files
                if p.suffix.lower() == ".html"
            ],
            "css_files": [
                str(p.relative_to(root))
                for p in files
                if p.suffix.lower() == ".css"
            ],
            "javascript_files": [
                str(p.relative_to(root))
                for p in files
                if p.suffix.lower() == ".js"
            ],
            "other_files": [
                str(p.relative_to(root))
                for p in files
                if p.suffix.lower() not in {".html", ".css", ".js"}
            ],
        }

    except (ValueError, OSError) as e:
        return tool_error(e)


session_service = InMemorySessionService()


def build_tester_agent():
    agent_model = MODEL or get_model()
    return LlmAgent(
        name="forge_tester",
        model=agent_model,
        description="Independently tests and validates generated applications.",
        instruction="""
You are the Tester Agent of Forge.

Your responsibility is to independently validate applications created
by the Developer Agent.

You have read-only access to the project workspace.

TOOLS:

- inspect_project: Inspect the project structure.
- list_files: List available project files.
- read_file: Read source code.
- validate_html: Validate HTML structure and local references.
- validate_css: Validate stylesheet content and basic structure.
- validate_javascript: Check JavaScript syntax using Node.js.

TESTING PROCESS:

1. Inspect the project structure.
2. Check whether the expected files exist.
3. Read the HTML, CSS and JavaScript files.
4. Validate every HTML file.
5. Validate every CSS file with validate_css.
6. Validate every JavaScript file.
7. Check whether local CSS and JavaScript references resolve.
8. Compare the implementation against the original requirements.
9. Identify missing features, broken functionality and potential issues.

RULES:

- Never modify, create or delete project files.
- Never execute generated application code.
- Do not assume a feature works just because its code exists.
- Distinguish verified failures from potential issues.
- If Node.js is unavailable, report JavaScript syntax testing as unavailable.
- Do not claim that browser functionality has been tested.
- Do not invent test results.
- If a tool returns an error, report it and continue testing other files.
- A missing expected file must be reported as a failure.
- Do not mark a project PASS if required files are missing.
- Do not report a tool being unavailable as a defect in the generated application.
- Do not request corrections for optional improvements or code-style preferences.
- Do not treat an unverified suspicion as a confirmed defect.
- Root-relative references such as /style.css are valid when the referenced file exists at the workspace root.

CORRECTION DECISION:

Set CORRECTION REQUIRED to YES only when you identify at least one
confirmed defect that the Developer can fix.

Examples:
- A required file is missing.
- A referenced local file does not exist.
- HTML contains duplicate IDs that break required behavior.
- JavaScript has a confirmed syntax error.
- A required feature is clearly missing from the implementation.
- The implementation contradicts an explicit user requirement.

Set CORRECTION REQUIRED to NO when:
- Testing is inconclusive.
- A tool is unavailable.
- Node.js is unavailable.
- Browser-level behavior cannot be verified.
- You have only warnings or optional improvements.
- You cannot confirm that a suspected issue is actually a defect.
- The implementation satisfies the requirements but some checks could not be performed.

A PARTIAL result does not automatically mean that a correction is required.

FINAL REPORT:

Always use this exact format:

PROJECT STATUS: PASS / FAIL / PARTIAL
CORRECTION REQUIRED: YES / NO

TEST SUMMARY:
Report the number of checks passed, failed and unavailable.
Do not invent counts.

STRUCTURAL VALIDATION:
Report missing files and broken references.

CODE VALIDATION:
Report HTML and JavaScript validation results.

REQUIREMENT VALIDATION:
Compare requested features against the implementation.

ISSUES:
List each confirmed issue with its file and explanation.
Separate potential issues from confirmed defects.

UNVERIFIED:
List checks that could not be completed and explain why.

RECOMMENDATION:
Explain whether the Developer should make corrections.

The PROJECT STATUS and CORRECTION REQUIRED fields must always be
present and must use the exact labels shown above.

Use PASS when all required checks and requirements pass.
Use FAIL when confirmed defects or missing required features exist.
Use PARTIAL when testing is inconclusive or some checks are unavailable
without a confirmed defect.

Never set CORRECTION REQUIRED to YES solely because the status is PARTIAL.
""",
        tools=[
            inspect_project,
            list_files,
            read_file,
            validate_html,
            validate_css,
            validate_javascript,
        ],
    )


async def run_tester(
    requirements,
    project_id,
    user_id="local_user",
    session_id=None,
):
    if not isinstance(project_id, str) or not re.fullmatch(
        r"[a-zA-Z0-9_-]{1,64}",
        project_id,
    ):
        raise ValueError("Invalid project ID")

    workspace = (WORKSPACE_DIR / project_id).resolve()

    if not workspace.is_relative_to(WORKSPACE_DIR.resolve()):
        raise ValueError("Invalid workspace")

    if not workspace.is_dir():
        raise ValueError("Project workspace does not exist")

    session_id = session_id or str(uuid4())
    runner = Runner(
        agent=build_tester_agent(),
        app_name=APP_NAME,
        session_service=session_service,
    )

    await session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
        state={
            "workspace_path": str(workspace),
        },
    )

    message = types.Content(
        role="user",
        parts=[
            types.Part.from_text(
                text=(
                    "Test this application against these requirements:\n"
                    f"{requirements}\n\n"
                    "Inspect the project using your tools before writing "
                    "your final report."
                )
            )
        ],
    )

    response = ""

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=message,
    ):
        if event.is_final_response() and event.content:
            response = "".join(
                part.text
                for part in event.content.parts
                if part.text
            )

    if not response.strip():
        raise RuntimeError("Tester Agent returned an empty response")

    return response


if __name__ == "__main__":
    project_id = input("Project ID: ")
    requirements = input("Original project requirements: ")

    result = asyncio.run(
        run_tester(requirements, project_id)
    )

    print("\nTESTER AGENT REPORT\n")
    print(result)
