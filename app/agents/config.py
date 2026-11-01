
import os
from pathlib import Path
from dotenv import load_dotenv
from google.adk.models.lite_llm import LiteLlm

ROOT_DIR = Path(__file__).resolve().parents[2]

load_dotenv(ROOT_DIR / ".env", override=True)
load_dotenv(ROOT_DIR / "app" / ".env", override=True)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL")
APP_NAME = "forge"

if OPENROUTER_API_KEY:
    os.environ["OPENROUTER_API_KEY"] = OPENROUTER_API_KEY


def get_model():
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("OPENROUTER_MODEL")
    if not api_key or not model:
        raise RuntimeError(
            "OPENROUTER_API_KEY and OPENROUTER_MODEL must be set before running Forge agents."
        )
    return LiteLlm(model=model)


MODEL = get_model() if OPENROUTER_API_KEY and OPENROUTER_MODEL else None
