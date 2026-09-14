"""Central configuration, read from environment variables."""
import os
from pathlib import Path

# Repo root is two levels up from this file (backend/app/config.py -> repo root)
REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ.get("INVOICE_DATA_DIR", REPO_ROOT / "data"))
DB_PATH = Path(os.environ.get("INVOICE_DB_PATH", REPO_ROOT / "backend" / "app_data.db"))

# LLM configuration
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.environ.get("INVOICE_LLM_MODEL", "claude-sonnet-4-5")
# If no API key is present we always fall back to mock generation, regardless
# of what the client asked for. This satisfies the "mock mode without a key" requirement.
FORCE_MOCK = os.environ.get("INVOICE_FORCE_MOCK", "").lower() in ("1", "true", "yes")

# Execution sandboxing
EXEC_TIMEOUT_SECONDS = float(os.environ.get("INVOICE_EXEC_TIMEOUT", "5"))
EXEC_MEMORY_LIMIT_MB = int(os.environ.get("INVOICE_EXEC_MEMORY_MB", "256"))
EXEC_CPU_LIMIT_SECONDS = int(os.environ.get("INVOICE_EXEC_CPU_LIMIT", "5"))
