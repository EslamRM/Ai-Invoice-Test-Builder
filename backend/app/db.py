"""Tiny persistence layer for saved test cases, built on plain sqlite3.

No ORM: the schema is small and this keeps the dependency footprint (and the
amount of code an AI-review has to trust) minimal.
"""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS saved_tests (
    id TEXT PRIMARY KEY,
    case_folder TEXT NOT NULL,
    name TEXT NOT NULL,
    expectation_text TEXT NOT NULL,
    code TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'mock',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_run_status TEXT,
    last_run_result TEXT,
    last_run_at REAL
);
"""


@contextmanager
def get_conn():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(SCHEMA)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    if d.get("last_run_result"):
        d["last_run_result"] = json.loads(d["last_run_result"])
    return d


def create_test(case_folder: str, name: str, expectation_text: str, code: str, source: str) -> dict[str, Any]:
    test_id = str(uuid.uuid4())
    now = time.time()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO saved_tests
               (id, case_folder, name, expectation_text, code, source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (test_id, case_folder, name, expectation_text, code, source, now, now),
        )
    return get_test(test_id)


def list_tests(case_folder: Optional[str] = None) -> list[dict[str, Any]]:
    with get_conn() as conn:
        if case_folder:
            rows = conn.execute(
                "SELECT * FROM saved_tests WHERE case_folder = ? ORDER BY updated_at DESC", (case_folder,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM saved_tests ORDER BY updated_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_test(test_id: str) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM saved_tests WHERE id = ?", (test_id,)).fetchone()
    return _row_to_dict(row) if row else None


def update_test(test_id: str, *, name: Optional[str] = None, expectation_text: Optional[str] = None,
                 code: Optional[str] = None) -> Optional[dict[str, Any]]:
    existing = get_test(test_id)
    if not existing:
        return None
    name = existing["name"] if name is None else name
    expectation_text = existing["expectation_text"] if expectation_text is None else expectation_text
    code = existing["code"] if code is None else code
    with get_conn() as conn:
        conn.execute(
            """UPDATE saved_tests SET name = ?, expectation_text = ?, code = ?, updated_at = ?
               WHERE id = ?""",
            (name, expectation_text, code, time.time(), test_id),
        )
    return get_test(test_id)


def record_run(test_id: str, status: str, result: dict[str, Any]) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        conn.execute(
            """UPDATE saved_tests SET last_run_status = ?, last_run_result = ?, last_run_at = ?
               WHERE id = ?""",
            (status, json.dumps(result), time.time(), test_id),
        )
    return get_test(test_id)


def delete_test(test_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM saved_tests WHERE id = ?", (test_id,))
    return cur.rowcount > 0
