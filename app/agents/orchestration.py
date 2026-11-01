import asyncio
import re
from pathlib import Path

from app.agents.supervisor import run_supervisor
from app.agents.developer import run_developer
from app.agents.tester import run_tester
from app.agents.guardrails import resolve_workspace, validate_generated_content

MAX_RETRIES = 1
EXPECTED_FILES = ["index.html", "style.css", "script.js"]


def get_test_status(report):
    match = re.search(r"(?im)^\s*\**\s*PROJECT STATUS\s*\**\s*:\s*\**\s*(PASS|FAIL|PARTIAL)\b", report or "")
    return match.group(1).upper() if match else "PARTIAL"


def get_correction_required(report, status):
    match = re.search(r"(?im)^\s*\**\s*CORRECTION REQUIRED\s*\**\s*:\s*\**\s*(YES|NO)\b", report or "")
    return match.group(1).upper() == "YES" if match else status == "FAIL"


def validate_generated_files(workspace):
    files = []
    errors = []
    for filename in EXPECTED_FILES:
        path = workspace / filename
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"Missing or empty required file: {filename}")
            continue
        validation = validate_generated_content(filename, path.read_text(encoding="utf-8"))
        if validation["status"] != "passed":
            errors.extend(f"{filename}: {error}" for error in validation["errors"])
        else:
            files.append(filename)
    return {"valid": not errors, "files": files, "errors": errors, "has_files": all((workspace / name).is_file() and (workspace / name).stat().st_size > 0 for name in EXPECTED_FILES)}


def finish_with_available_files(result, workspace, preferred_status, report):
    generated = validate_generated_files(workspace)
    result["has_generated_files"] = generated["has_files"]
    result["file_validation"] = generated["errors"]
    if generated["has_files"]:
        result["status"] = "completed" if preferred_status == "PASS" and generated["valid"] else "partially_completed"
    else:
        result["status"] = "failed"
    result["final_report"] = report
    return result


async def run_workflow(prompt, project_id, user_id="local_user"):
    workspace = resolve_workspace(project_id, create=True)
    result = {
        "project_id": project_id,
        "workspace": str(workspace),
        "status": "in_progress",
        "test_status": None,
        "has_generated_files": False,
        "file_validation": [],
        "plan": None,
        "development": [],
        "testing": [],
        "retries": 0,
        "final_report": None,
    }

    print("\n[1/3] Supervisor is analyzing requirements...")
    try:
        plan = await run_supervisor(prompt, user_id=user_id)
        if not plan.strip():
            raise RuntimeError("Supervisor returned an empty development plan")
        result["plan"] = plan
    except Exception as error:
        result["status"] = "failed"
        result["final_report"] = f"Supervisor failed: {error}"
        return result

    development_task = f"""Build the application according to the user's requirements.

USER REQUIREMENTS:
{prompt}

SUPERVISOR DEVELOPMENT PLAN:
{plan}

Generate the complete frontend in the assigned workspace. Implement the actual requested content and behavior. Do not substitute a generic template unrelated to the request."""

    print("\n[2/3] Developer is building the application...")
    try:
        result["development"].append(await run_developer(development_task, project_id, user_id=user_id))
    except Exception as error:
        generated = validate_generated_files(workspace)
        result["has_generated_files"] = generated["has_files"]
        result["file_validation"] = generated["errors"]
        result["status"] = "partially_completed" if generated["has_files"] else "failed"
        result["final_report"] = f"Developer failed: {error}"
        return result

    generated = validate_generated_files(workspace)
    if not generated["valid"]:
        result["has_generated_files"] = generated["has_files"]
        result["file_validation"] = generated["errors"]
        result["status"] = "partially_completed" if generated["has_files"] else "failed"
        result["final_report"] = "Generated files failed structural validation: " + "; ".join(generated["errors"])
        return result

    print("\n[3/3] Tester is validating the application...")
    for attempt in range(MAX_RETRIES + 1):
        try:
            report = str(await run_tester(prompt, project_id, user_id=user_id) or "Tester returned an empty report.")
        except Exception as error:
            return finish_with_available_files(result, workspace, "PARTIAL", f"Tester execution failed: {error}")

        result["testing"].append(report)
        test_status = get_test_status(report)
        correction_required = get_correction_required(report, test_status)
        result["test_status"] = test_status
        print(f"\nTesting attempt {attempt + 1}: {test_status}")
        print(f"Correction required: {correction_required}")

        if test_status == "PASS":
            return finish_with_available_files(result, workspace, "PASS", report)
        if not correction_required:
            return finish_with_available_files(result, workspace, test_status, report)
        if attempt >= MAX_RETRIES:
            return finish_with_available_files(result, workspace, test_status, report)

        result["retries"] += 1
        correction_task = f"""Correct confirmed defects reported by the independent Tester. Preserve the user's original requirements and all working functionality.

ORIGINAL USER REQUIREMENTS:
{prompt}

SUPERVISOR PLAN:
{plan}

TESTER REPORT:
{report}

Fix only confirmed defects. Do not weaken validation or claim that tests passed. Return complete source for each file that needs changes."""
        try:
            result["development"].append(await run_developer(correction_task, project_id, user_id=user_id, correction=True))
        except Exception as error:
            return finish_with_available_files(result, workspace, "PARTIAL", f"Developer correction could not be completed: {error}\n\nPrevious tester report:\n{report}")

        generated = validate_generated_files(workspace)
        if not generated["valid"]:
            return finish_with_available_files(result, workspace, "PARTIAL", "Correction output failed file validation: " + "; ".join(generated["errors"]) + f"\n\nPrevious tester report:\n{report}")

    return finish_with_available_files(result, workspace, "PARTIAL", "Workflow ended without a final tester result.")


if __name__ == "__main__":
    project_id = input("Project ID: ")
    prompt = input("Describe the application you want to build: ")
    result = asyncio.run(run_workflow(prompt, project_id))
    print("\n========== FORGE WORKFLOW RESULT ==========")
    print(f"Project: {result['project_id']}\nStatus: {result['status']}\nTest Status: {result['test_status']}\nRetries: {result['retries']}\nWorkspace: {result['workspace']}")
    print("\nFINAL TEST REPORT:\n" + str(result["final_report"]))
