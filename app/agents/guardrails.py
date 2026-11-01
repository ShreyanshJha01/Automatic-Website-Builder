import re
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent / "workspaces"
ALLOWED_EXTENSIONS = {".html", ".css", ".js", ".json", ".md", ".txt", ".svg", ".webmanifest"}
MAX_FILE_SIZE = 1_000_000
BLOCKED_PATTERNS = {
    "JavaScript URL": r"javascript\s*:",
    "Obfuscated script execution": r"\beval\s*\(",
    "Dynamic function execution": r"\bnew\s+Function\s*\(",
    "Unsafe document writing": r"\bdocument\s*\.\s*write\s*\(",
}
WARNING_PATTERNS = {
    "Inline event handler": r"\bon[a-z]+\s*=",
    "Direct HTML injection": r"\.innerHTML\s*=",
    "Iframe usage": r"<\s*iframe\b",
    "External script": r"<\s*script[^>]+src\s*=\s*['\"]https?://",
    "Potential exposed API key": r"\b(?:OPENAI_API_KEY|GEMINI_API_KEY|GOOGLE_API_KEY|SECRET_KEY)\s*[:=]\s*['\"][^'\"]{8,}",
    "Potential exposed token": r"\bsk-[a-zA-Z0-9_-]{20,}\b",
}


def validate_project_id(project_id):
    if not isinstance(project_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", project_id):
        raise ValueError("Invalid project ID")
    return True


def resolve_workspace(project_id, create=False):
    validate_project_id(project_id)
    root = WORKSPACE_DIR.resolve()
    workspace = (root / project_id).resolve()
    if not workspace.is_relative_to(root) or workspace == root:
        raise ValueError("Invalid workspace path")
    if create:
        workspace.mkdir(parents=True, exist_ok=True)
    if not workspace.is_dir():
        raise ValueError("Workspace does not exist")
    return workspace


def resolve_file_path(workspace, filename, must_exist=False):
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("A file name is required")
    root = Path(workspace).resolve()
    target = (root / filename).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError("File path escapes workspace")
    if target.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("Unsupported file extension")
    if must_exist and not target.is_file():
        raise FileNotFoundError(f"File does not exist: {filename}")
    return target


def validate_file_type(filename, content):
    extension = Path(filename).suffix.lower()
    errors = []
    stripped = content.strip()
    if not stripped:
        return ["Generated file is empty"]
    if extension == ".html":
        if not re.search(r"<!doctype\s+html\b", content, re.IGNORECASE):
            errors.append("HTML document must include <!DOCTYPE html>")
        if not re.search(r"<html\b", content, re.IGNORECASE) or not re.search(r"</html\s*>", content, re.IGNORECASE):
            errors.append("HTML document must contain opening and closing html tags")
        if not re.search(r"<head\b", content, re.IGNORECASE) or not re.search(r"</head\s*>", content, re.IGNORECASE):
            errors.append("HTML document must contain a complete head section")
        if not re.search(r"<body\b", content, re.IGNORECASE) or not re.search(r"</body\s*>", content, re.IGNORECASE):
            errors.append("HTML document must contain a complete body section")
        if re.search(r"^\s*(?:const|let|var|function|import|export)\b", content):
            errors.append("JavaScript was returned instead of HTML")
    elif extension == ".css":
        if re.search(r"<!doctype\s+html|<html\b|<body\b|<script\b", content, re.IGNORECASE):
            errors.append("HTML or script markup was returned instead of CSS")
        if content.count("{") != content.count("}"):
            errors.append("CSS contains unbalanced braces")
        if not re.search(r"(?:\{|@(?:import|tailwind|layer|charset|media|supports|font-face|keyframes)\b)", content):
            errors.append("CSS does not contain a stylesheet rule or directive")
    elif extension == ".js":
        if re.search(r"<!doctype\s+html|<html\b|<body\b|<head\b|<script\b", content, re.IGNORECASE):
            errors.append("HTML markup was returned instead of JavaScript")
        if re.search(r"^\s*(?:PROJECT STATUS|TEST SUMMARY|Here(?:'s| is) the)", content, re.IGNORECASE):
            errors.append("Explanation or tester report was returned instead of JavaScript")
    return errors


def validate_generated_content(filename, content):
    errors = []
    warnings = []
    if not isinstance(content, str):
        return {"status": "blocked", "errors": ["Generated content must be a string"], "warnings": []}
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        errors.append("Unsupported file extension")
    if len(content.encode("utf-8")) > MAX_FILE_SIZE:
        errors.append("File exceeds the 1 MB size limit")
    if extension in {".html", ".css", ".js"}:
        errors.extend(validate_file_type(filename, content))
    for name, pattern in BLOCKED_PATTERNS.items():
        if re.search(pattern, content, re.IGNORECASE):
            errors.append(f"Potentially unsafe pattern: {name}")
    for name, pattern in WARNING_PATTERNS.items():
        if re.search(pattern, content, re.IGNORECASE):
            warnings.append(f"Review required: {name}")
    return {"status": "blocked" if errors else "passed", "errors": errors, "warnings": warnings}


def validate_project(workspace):
    root = Path(workspace).resolve()
    if not root.is_relative_to(WORKSPACE_DIR.resolve()) or root == WORKSPACE_DIR.resolve():
        raise ValueError("Invalid workspace")
    if not root.is_dir():
        raise ValueError("Workspace does not exist")
    results = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            target = path.resolve()
            if not target.is_relative_to(root):
                results.append({"file": str(path), "status": "blocked", "errors": ["File escapes workspace"], "warnings": []})
                continue
            if target.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            if target.stat().st_size > MAX_FILE_SIZE:
                results.append({"file": str(target.relative_to(root)), "status": "blocked", "errors": ["File exceeds the 1 MB size limit"], "warnings": []})
                continue
            result = validate_generated_content(target.name, target.read_text(encoding="utf-8"))
            result["file"] = str(target.relative_to(root))
            results.append(result)
        except (OSError, UnicodeError) as error:
            results.append({"file": str(path), "status": "error", "errors": [str(error)], "warnings": []})
    return {"status": "blocked" if any(item["status"] == "blocked" for item in results) else "passed", "total_files": len(results), "results": results}
