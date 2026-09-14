"""Read-only access to the provided invoice test-case fixtures under data/."""
import json
from pathlib import Path
from typing import Any

from .config import DATA_DIR


class CaseNotFoundError(Exception):
    pass


def list_cases() -> list[dict[str, Any]]:
    """Return the summary index of all available cases."""
    index_path = DATA_DIR / "index.json"
    if not index_path.exists():
        return []
    with open(index_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _case_dir(folder: str) -> Path:
    # Guard against path traversal since `folder` comes from the client.
    safe = Path(folder).name
    case_dir = DATA_DIR / safe
    if not case_dir.is_dir():
        raise CaseNotFoundError(folder)
    return case_dir


def get_case(folder: str) -> dict[str, Any]:
    """Return the full expectation + result payload for one case."""
    case_dir = _case_dir(folder)
    expectation_path = case_dir / "expectation.json"
    result_path = case_dir / "result.json"
    if not expectation_path.exists() or not result_path.exists():
        raise CaseNotFoundError(folder)

    with open(expectation_path, "r", encoding="utf-8") as f:
        expectation = json.load(f)
    with open(result_path, "r", encoding="utf-8") as f:
        result = json.load(f)

    return {"folder": folder, "expectation": expectation, "result": result}


def get_result(folder: str) -> dict[str, Any]:
    """Return only the result.json content for a case (used by the runner)."""
    case_dir = _case_dir(folder)
    result_path = case_dir / "result.json"
    if not result_path.exists():
        raise CaseNotFoundError(folder)
    with open(result_path, "r", encoding="utf-8") as f:
        return json.load(f)
