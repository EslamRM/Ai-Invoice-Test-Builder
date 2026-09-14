"""Golden-case verification for the nine supplied invoice fixtures.

These tests intentionally verify business-significant evidence, not just the
fixture's final_status. They are a regression benchmark for generated tests:
when the LLM is enabled, generated code should assert equivalent evidence.
"""
import copy
import json
from pathlib import Path

import pytest

from app.llm import generate_mock
from app.runner import run_generated_test

ROOT = Path(__file__).resolve().parents[2] / "data"

CASES = [
    "case-01-over-supply-within-tolerance",
    "case-02-rooftop-data-capture-and-classification",
    "case-03-over-supply-out-of-threshold",
    "case-04-test-policy-boundary-errors",
    "case-05-perfect-match-with-unit-conversions",
    "case-06-perfect-po-match",
    "case-07-attribute-dimension-data-capture",
    "case-08-bakery-catalog-matching-2",
    "case-09-test-minor-price-differences",
]


def load_case(name):
    folder = ROOT / name
    return (
        json.loads((folder / "expectation.json").read_text(encoding="utf-8")),
        json.loads((folder / "result.json").read_text(encoding="utf-8")),
    )


@pytest.mark.parametrize("case_name", CASES)
def test_fixture_final_status_matches_expectation(case_name):
    expectation, result = load_case(case_name)
    assert result["final_status"] == expectation["expected_status"]


def test_case_01_has_two_matches_and_within_tolerance():
    _, result = load_case(CASES[0])
    row = result["validation"][0]
    assert len(result["lines"]) == 2
    assert row["outcome_status"] == "WITHIN_TOLERANCE"
    matches = row["tolerance_outcome"]["matches"]
    assert len(matches) == 2
    assert all(match["price_within_tolerance"] is True for match in matches)
    assert row["tolerance_outcome"]["quantity_overages"][1]["tier"] == "review"


def test_case_02_routes_every_line_to_rooftop_restaurant():
    _, result = load_case(CASES[1])
    department_rows = [
        row for row in result["classification"]
        if row.get("dimension_name") == "department"
    ]
    assert len(department_rows) == len(result["lines"]) == 3
    assert {row["dimension_value_name"] for row in department_rows} == {"ROOFTOP RESTAURANT"}
    assert all(row["dimension_confidence"] == 0.99 for row in department_rows)


def test_case_03_is_blocked_by_over_supply():
    _, result = load_case(CASES[2])
    assert result["review_queue"]["status"] == "Pending"
    assert any("overage exceeds the acceptance band" in warning for warning in result["warnings"])
    assert any(row["severity"] == "BLOCK" for row in result["validation"])


def test_case_04_only_mango_price_is_outside_tolerance():
    _, result = load_case(CASES[3])
    row = result["validation"][0]
    matches = row["tolerance_outcome"]["matches"]
    outside = [m for m in matches if m["price_within_tolerance"] is False]
    assert len(outside) == 1
    assert outside[0]["invoice_line_index"] == 26
    assert outside[0]["price_difference"] >= 0.01
    lemon = next(m for m in matches if m["invoice_line_index"] == 30)
    assert lemon["price_difference"] < 0.01
    assert lemon["price_within_tolerance"] is True


def test_case_05_has_15_lines_and_no_price_quantity_warnings():
    _, result = load_case(CASES[4])
    assert len(result["lines"]) == 15
    assert result["header"]["net_amount"] == "476.16"
    serialized = json.dumps(result["warnings"] + result["failures"]).lower()
    assert "price" not in serialized
    assert "quantity" not in serialized


def test_case_06_all_lines_are_matched():
    _, result = load_case(CASES[5])
    assert result["lines"]
    assert all(line.get("matched_po_number") for line in result["lines"])
    assert result["final_status"] == "Ready to Post"


def test_case_07_captures_iban_and_assigns_voyage_to_every_line():
    _, result = load_case(CASES[6])
    assert result["header"]["document_number"] == "INV-8841"
    assert result["header"]["assigned_dimensions"]["code"] == ["V7X0042"]
    voyage_rows = [
        row for row in result["classification"]
        if row.get("dimension_name", "").lower() == "voyage code"
    ]
    assert len(voyage_rows) == len(result["lines"]) == 3
    assert all(row["dimension_value_name"] == "V7X0042" for row in voyage_rows)
    assert all(row["dimension_confidence"] == 1 for row in voyage_rows)
    assert all(row["decision"] == "fixed" for row in voyage_rows)
    # The supplied fixture stores the captured IBAN in the classification
    # context rather than a dedicated top-level field.
    context = json.dumps(result["classification_explanations"], ensure_ascii=False)
    assert "IBAN_Number: MT40BANK22013000000012345678901" in context


def test_case_08_only_bun_bloomer_small_fails_price_check():
    _, result = load_case(CASES[7])
    row = result["validation"][0]["tolerance_outcome"]
    failed = [line for line in row["lines"] if line["checks_failed"]]
    assert len(failed) == 1
    assert failed[0]["line_number"] == 4
    assert failed[0]["checks_failed"] == ["price"]
    assert result["header"]["net_amount"] == "6.37"


def test_case_09_minor_price_difference_is_within_tolerance():
    _, result = load_case(CASES[8])
    matches = result["validation"][0]["tolerance_outcome"]["matches"]
    target = next(m for m in matches if m["invoice_line_index"] == 0)
    assert target["price_difference"] < 0.01
    assert target["price_within_tolerance"] is True
    assert result["final_status"] == "Ready to Post"


def test_case_07_mock_generation_is_not_false_positive():
    expectation, result = load_case(CASES[6])
    code = generate_mock(
        expectation["expectation_criteria"],
        expectation["expected_status"],
        result,
    )
    outcome = run_generated_test(code, result)
    assert outcome["status"] == "passed"

    mutated = copy.deepcopy(result)
    mutated["classification"][0]["dimension_value_name"] = "WRONG"
    mutated_outcome = run_generated_test(code, mutated)
    assert mutated_outcome["status"] == "failed"
