"""End-to-end API tests covering the required workflow:
select case -> generate -> run -> save -> rerun.
"""
import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app

db.init_db()  # TestClient only fires startup/shutdown events inside a `with` block
client = TestClient(app)


def test_list_cases_returns_all_nine_fixtures():
    resp = client.get("/api/cases")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 9
    assert {"folder", "name", "expected_status"}.issubset(data[0].keys())


def test_get_case_returns_expectation_and_result():
    resp = client.get("/api/cases/case-01-over-supply-within-tolerance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["expectation"]["expected_status"] == "Ready to Post"
    assert "lines" in body["result"]


def test_get_unknown_case_is_404():
    resp = client.get("/api/cases/does-not-exist")
    assert resp.status_code == 404


def test_get_case_rejects_path_traversal():
    resp = client.get("/api/cases/..%2F..%2Fetc")
    assert resp.status_code == 404


def test_full_workflow_generate_run_save_rerun():
    case_folder = "case-01-over-supply-within-tolerance"
    case = client.get(f"/api/cases/{case_folder}").json()

    # 1. generate
    gen = client.post("/api/generate", json={
        "case_folder": case_folder,
        "expectation_text": case["expectation"]["expectation_criteria"],
        "use_llm": True,  # forced to mock by test config; exercises the same code path
    })
    assert gen.status_code == 200
    gen_body = gen.json()
    assert gen_body["source"] == "mock"
    code = gen_body["code"]
    assert "run_test" in code

    # 2. run without saving
    run = client.post("/api/run", json={"case_folder": case_folder, "code": code})
    assert run.status_code == 200
    assert run.json()["status"] == "passed"

    # 3. save
    save = client.post("/api/tests", json={
        "case_folder": case_folder,
        "name": "Over-supply within tolerance - generated",
        "expectation_text": case["expectation"]["expectation_criteria"],
        "code": code,
        "source": "mock",
    })
    assert save.status_code == 200
    test_id = save.json()["id"]

    # 4. it shows up in the saved list
    listed = client.get("/api/tests").json()
    assert any(t["id"] == test_id for t in listed)

    # 5. rerun by id, persisted
    rerun = client.post(f"/api/tests/{test_id}/run")
    assert rerun.status_code == 200
    assert rerun.json()["status"] == "passed"

    fetched = client.get(f"/api/tests/{test_id}").json()
    assert fetched["last_run_status"] == "passed"


def test_editing_saved_code_to_assert_something_false_then_fails():
    case_folder = "case-01-over-supply-within-tolerance"
    broken_code = (
        "def run_test(invoice):\n"
        "    checks = [{'name': 'deliberately false', 'passed': False, 'detail': 'edited to fail'}]\n"
        "    return {'passed': False, 'checks': checks}\n"
    )
    save = client.post("/api/tests", json={
        "case_folder": case_folder,
        "name": "Deliberately broken",
        "expectation_text": "n/a",
        "code": broken_code,
    })
    test_id = save.json()["id"]

    rerun = client.post(f"/api/tests/{test_id}/run")
    body = rerun.json()
    assert body["status"] == "failed"
    assert body["checks"][0]["passed"] is False


def test_syntax_error_surfaces_distinctly_through_the_api():
    resp = client.post("/api/run", json={
        "case_folder": "case-01-over-supply-within-tolerance",
        "code": "def run_test(invoice)\n  return 1",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "syntax_error"


def test_update_and_delete_saved_test():
    case_folder = "case-06-perfect-po-match"
    save = client.post("/api/tests", json={
        "case_folder": case_folder,
        "name": "temp",
        "expectation_text": "n/a",
        "code": "def run_test(invoice):\n    return {'passed': True, 'checks': []}\n",
    })
    test_id = save.json()["id"]

    upd = client.put(f"/api/tests/{test_id}", json={"name": "renamed"})
    assert upd.status_code == 200
    assert upd.json()["name"] == "renamed"

    dele = client.delete(f"/api/tests/{test_id}")
    assert dele.status_code == 200
    assert client.get(f"/api/tests/{test_id}").status_code == 404


def test_health_endpoint():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
