"""Mutation benchmark for the supplied nine invoice cases.

The goal is stronger than "the generated test passes": a business-relevant
mutation of the invoice result must make the generated test fail. This catches
vacuous tests that only assert the fixture's final status.
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


def mutate_business_evidence(case_name, result):
    mutated = copy.deepcopy(result)

    if case_name.startswith("case-01"):
        # Break the structured within-tolerance outcome while keeping the final
        # status unchanged, so a status-only test would incorrectly pass.
        row = mutated["validation"][0]
        row["outcome_status"] = "OUT_OF_TOLERANCE"
        row["tolerance_outcome"]["matches"][1]["price_within_tolerance"] = False
        return mutated

    if case_name.startswith("case-02"):
        for row in mutated["classification"]:
            if row.get("dimension_name") == "department":
                row["dimension_value_name"] = "KITCHEN"
                return mutated

    if case_name.startswith("case-03"):
        mutated["validation"][0]["severity"] = "WARN"
        mutated["review_queue"] = None
        return mutated

    if case_name.startswith("case-04"):
        # The LEMON boundary is explicitly required to remain below 0.01.
        matches = mutated["validation"][0]["tolerance_outcome"]["matches"]
        for match in matches:
            if match.get("invoice_line_index") == 30:
                match["price_difference"] = 0.02
                match["price_within_tolerance"] = False
                return mutated

    if case_name.startswith("case-05"):
        mutated["lines"].pop()
        return mutated

    if case_name.startswith("case-06"):
        mutated["lines"][0]["matched_po_number"] = None
        return mutated

    if case_name.startswith("case-07"):
        for row in mutated["classification"]:
            if row.get("dimension_name", "").lower() == "voyage code":
                row["dimension_value_name"] = "WRONG"
                return mutated

    if case_name.startswith("case-08"):
        rows = mutated["validation"][0]["tolerance_outcome"]["lines"]
        for row in rows:
            if row.get("line_number") == 1:
                row["checks_failed"] = ["price"]
                return mutated

    if case_name.startswith("case-09"):
        matches = mutated["validation"][0]["tolerance_outcome"]["matches"]
        matches[0]["price_difference"] = 0.02
        matches[0]["price_within_tolerance"] = False
        return mutated

    raise AssertionError(f"No mutation defined for {case_name}")


@pytest.mark.parametrize("case_name", CASES)
def test_generated_mock_test_detects_business_mutation(case_name):
    expectation, result = load_case(case_name)
    code = generate_mock(
        expectation["expectation_criteria"],
        expectation["expected_status"],
        result,
    )

    original = run_generated_test(code, result)
    assert original["status"] == "passed", original

    mutated = mutate_business_evidence(case_name, result)
    mutated_result = run_generated_test(code, mutated)
    assert mutated_result["status"] == "failed", (
        case_name,
        mutated_result,
        code,
    )
