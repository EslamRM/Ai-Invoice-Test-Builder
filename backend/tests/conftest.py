import os
import sys
import tempfile
from pathlib import Path

import pytest

# Point the app at an isolated, throwaway SQLite DB for the whole test session,
# before importing anything from `app` that reads config at import time.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["INVOICE_DB_PATH"] = _tmp_db.name
os.environ["INVOICE_FORCE_MOCK"] = "1"  # tests never hit the real network/LLM

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="session", autouse=True)
def _cleanup_db():
    yield
    try:
        os.unlink(_tmp_db.name)
    except OSError:
        pass
