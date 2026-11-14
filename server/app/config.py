"""Runtime configuration. Everything is overridable through environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("LEXISCAN_DATA_DIR", BASE_DIR / "var"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

APP_DB = DATA_DIR / "lexiscan.db"
CHECKPOINT_DB = DATA_DIR / "checkpoints.db"

MODEL = os.getenv("LEXISCAN_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("LEXISCAN_EFFORT", "medium")

# Offline mode is used when no Anthropic credentials are configured, or when forced.
FORCE_OFFLINE = os.getenv("LEXISCAN_OFFLINE", "").lower() in {"1", "true", "yes"}

MAX_UPLOAD_BYTES = int(os.getenv("LEXISCAN_MAX_UPLOAD_MB", "15")) * 1024 * 1024
MAX_REVISIONS = int(os.getenv("LEXISCAN_MAX_REVISIONS", "4"))

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("LEXISCAN_CORS_ORIGINS", "*").split(",")
    if o.strip()
]
