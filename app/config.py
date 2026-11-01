import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / "app" / ".env", override=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'app.db'}")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-change-this-secret-before-deployment")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
PORT = int(os.getenv("PORT", "8000"))
PREVIEW_PORT = int(os.getenv("PREVIEW_PORT", "4173"))
ENABLE_PREVIEW_SERVER = os.getenv("ENABLE_PREVIEW_SERVER", "false").strip().lower() in {"1", "true", "yes", "on"}
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://localhost:4173,http://127.0.0.1:4173").split(",")
    if origin.strip()
]
