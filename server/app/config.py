"""Runtime configuration. Everything is overridable through environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("LEXISCAN_DATA_DIR", BASE_DIR / "var"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Set DATABASE_URL (postgresql://...) to keep data across deploys on hosts with an ephemeral disk.
DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip() or None
APP_DB = DATA_DIR / "lexiscan.db"
CHECKPOINT_DB = DATA_DIR / "checkpoints.db"

# Any Groq chat model id works; gpt-oss models get strict JSON-schema outputs.
MODEL = os.getenv("GROQ_MODEL") or os.getenv("LEXISCAN_MODEL") or "openai/gpt-oss-120b"
EFFORT = os.getenv("LEXISCAN_EFFORT", "medium")

# Offline mode is used when no Groq API key is configured, or when forced.
FORCE_OFFLINE = os.getenv("LEXISCAN_OFFLINE", "").lower() in {"1", "true", "yes"}

MAX_UPLOAD_BYTES = int(os.getenv("LEXISCAN_MAX_UPLOAD_MB", "15")) * 1024 * 1024
MAX_REVISIONS = int(os.getenv("LEXISCAN_MAX_REVISIONS", "4"))
# Parallel model calls. Groq's free tier has low tokens-per-minute limits, so default to one.
LLM_CONCURRENCY = int(os.getenv("LEXISCAN_LLM_CONCURRENCY", "1"))

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("LEXISCAN_CORS_ORIGINS", "*").split(",")
    if o.strip()
]
