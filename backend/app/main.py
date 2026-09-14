"""FastAPI application wiring together cases, LLM generation, execution and persistence."""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import cases, db, llm, runner
from .config import ANTHROPIC_API_KEY, FORCE_MOCK, REPO_ROOT


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="AI-Assisted Invoice Test Builder", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

@app.get("/api/cases")
def api_list_cases() -> list[dict[str, Any]]:
    return cases.list_cases()


@app.get("/api/cases/{folder}")
def api_get_case(folder: str) -> dict[str, Any]:
    try:
        return cases.get_case(folder)
    except cases.CaseNotFoundError:
        raise HTTPException(status_code=404, detail=f"Case '{folder}' not found")


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    case_folder: str
    expectation_text: str
    use_llm: bool = True


class GenerateResponse(BaseModel):
    code: str
    source: str  # "llm" or "mock"
    llm_available: bool


@app.post("/api/generate", response_model=GenerateResponse)
def api_generate(req: GenerateRequest) -> GenerateResponse:
    try:
        case = cases.get_case(req.case_folder)
    except cases.CaseNotFoundError:
        raise HTTPException(status_code=404, detail=f"Case '{req.case_folder}' not found")

    expected_status = case["expectation"].get("expected_status")
    try:
        code, source = llm.generate_test_code(
            req.expectation_text, expected_status, case["result"], req.use_llm
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM generation failed: {exc}")

    return GenerateResponse(code=code, source=source, llm_available=bool(ANTHROPIC_API_KEY and not FORCE_MOCK))


# ---------------------------------------------------------------------------
# Ad-hoc run (no persistence) — used by the "Run" button before saving
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    case_folder: str
    code: str


@app.post("/api/run")
def api_run(req: RunRequest) -> dict[str, Any]:
    try:
        invoice = cases.get_result(req.case_folder)
    except cases.CaseNotFoundError:
        raise HTTPException(status_code=404, detail=f"Case '{req.case_folder}' not found")
    return runner.run_generated_test(req.code, invoice)


# ---------------------------------------------------------------------------
# Saved tests
# ---------------------------------------------------------------------------

class SaveTestRequest(BaseModel):
    case_folder: str
    name: str
    expectation_text: str
    code: str
    source: str = "mock"


class UpdateTestRequest(BaseModel):
    name: Optional[str] = None
    expectation_text: Optional[str] = None
    code: Optional[str] = None


@app.post("/api/tests")
def api_create_test(req: SaveTestRequest) -> dict[str, Any]:
    try:
        cases.get_case(req.case_folder)
    except cases.CaseNotFoundError:
        raise HTTPException(status_code=404, detail=f"Case '{req.case_folder}' not found")
    return db.create_test(req.case_folder, req.name, req.expectation_text, req.code, req.source)


@app.get("/api/tests")
def api_list_tests(case_folder: Optional[str] = None) -> list[dict[str, Any]]:
    return db.list_tests(case_folder)


@app.get("/api/tests/{test_id}")
def api_get_test(test_id: str) -> dict[str, Any]:
    test = db.get_test(test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")
    return test


@app.put("/api/tests/{test_id}")
def api_update_test(test_id: str, req: UpdateTestRequest) -> dict[str, Any]:
    test = db.update_test(test_id, name=req.name, expectation_text=req.expectation_text, code=req.code)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")
    return test


@app.delete("/api/tests/{test_id}")
def api_delete_test(test_id: str) -> dict[str, str]:
    if not db.delete_test(test_id):
        raise HTTPException(status_code=404, detail="Test not found")
    return {"status": "deleted"}


@app.post("/api/tests/{test_id}/run")
def api_run_test(test_id: str) -> dict[str, Any]:
    test = db.get_test(test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")
    try:
        invoice = cases.get_result(test["case_folder"])
    except cases.CaseNotFoundError:
        raise HTTPException(status_code=404, detail=f"Case '{test['case_folder']}' not found")

    result = runner.run_generated_test(test["code"], invoice)
    db.record_run(test_id, result["status"], result)
    return result


# ---------------------------------------------------------------------------
# Health + static frontend
# ---------------------------------------------------------------------------

@app.get("/api/health")
def api_health() -> dict[str, Any]:
    return {"status": "ok", "llm_available": bool(ANTHROPIC_API_KEY and not FORCE_MOCK)}


_frontend_dir = REPO_ROOT / "frontend"
if _frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
