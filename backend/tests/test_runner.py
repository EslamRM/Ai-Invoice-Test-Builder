"""Tests for the sandboxed execution engine — the core of the "run the test" flow."""
from app import runner


def test_passing_test_reports_passed():
    code = "def run_test(invoice):\n    return {'passed': True, 'checks': [{'name': 'x', 'passed': True, 'detail': 'ok'}]}\n"
    result = runner.run_generated_test(code, {"final_status": "Ready to Post"})
    assert result["status"] == "passed"
    assert result["passed"] is True
    assert result["checks"][0]["name"] == "x"


def test_failing_assertion_is_distinguished_from_a_crash():
    code = "def run_test(invoice):\n    return {'passed': False, 'checks': [{'name': 'x', 'passed': False, 'detail': 'nope'}]}\n"
    result = runner.run_generated_test(code, {})
    assert result["status"] == "failed"
    assert result["passed"] is False


def test_syntax_error_is_reported_as_syntax_error_not_runtime_error():
    code = "def run_test(invoice)\n    return 1\n"  # missing colon
    result = runner.run_generated_test(code, {})
    assert result["status"] == "syntax_error"
    assert "error" in result


def test_runtime_exception_is_reported_as_runtime_error():
    code = "def run_test(invoice):\n    return 1 / 0\n"
    result = runner.run_generated_test(code, {})
    assert result["status"] == "runtime_error"
    assert "ZeroDivisionError" in result["error"]


def test_missing_entry_point_is_a_runtime_error():
    code = "x = 1\n"  # no run_test defined at all
    result = runner.run_generated_test(code, {})
    assert result["status"] == "runtime_error"


def test_non_dict_return_value_is_a_runtime_error():
    code = "def run_test(invoice):\n    return 'not a dict'\n"
    result = runner.run_generated_test(code, {})
    # A str return value violates the run_test() contract -> treated as a
    # runtime/contract error, never silently coerced into pass/fail.
    assert result["status"] == "runtime_error"


def test_infinite_loop_is_killed_by_timeout():
    code = "def run_test(invoice):\n    while True:\n        pass\n"
    result = runner.run_generated_test(code, {})
    assert result["status"] == "timeout"


def test_generated_code_cannot_import_environment_module():
    # The child still receives a stripped environment, but generated code is
    # now also rejected from importing os in the first place.
    code = (
        "import os\n"
        "def run_test(invoice):\n"
        "    return {'passed': True, 'checks': []}\n"
    )
    result = runner.run_generated_test(code, {})
    assert result["status"] == "runtime_error"
    assert result["error_type"] == "code_validation"


def test_can_evaluate_real_case_expectation_against_its_own_result():
    from app import cases, llm

    case = cases.get_case("case-01-over-supply-within-tolerance")
    code, source = llm.generate_test_code(
        case["expectation"]["expectation_criteria"],
        case["expectation"]["expected_status"],
        case["result"],
        use_llm=False,
    )
    assert source == "mock"
    result = runner.run_generated_test(code, case["result"])
    assert result["status"] == "passed"


def test_imports_are_rejected_before_execution():
    code = "import os\ndef run_test(invoice):\n    return {'passed': True, 'checks': []}\n"
    result = runner.run_generated_test(code, {})
    assert result["status"] == "runtime_error"
    assert result["error_type"] == "code_validation"
    assert "Imports are not allowed" in result["error"]


def test_dangerous_builtins_are_rejected_before_execution():
    code = "def run_test(invoice):\n    return {'passed': True, 'checks': [{'name': 'x', 'passed': open('/etc/passwd') is not None, 'detail': 'x'}]}\n"
    result = runner.run_generated_test(code, {})
    assert result["status"] == "runtime_error"
    assert result["error_type"] == "code_validation"
    assert "open" in result["error"]


def test_dunder_attribute_access_is_rejected():
    code = "def run_test(invoice):\n    x = invoice.__class__\n    return {'passed': True, 'checks': []}\n"
    result = runner.run_generated_test(code, {})
    assert result["status"] == "runtime_error"
    assert result["error_type"] == "code_validation"


def test_string_passed_value_is_contract_violation_not_truthy_pass():
    code = "def run_test(invoice):\n    return {'passed': 'false', 'checks': []}\n"
    result = runner.run_generated_test(code, {})
    assert result["status"] == "runtime_error"
    assert result["error_type"] == "contract_violation"
    assert "real boolean" in result["error"]


def test_check_contract_is_strict():
    code = "def run_test(invoice):\n    return {'passed': True, 'checks': [{'name': 'x', 'passed': 1, 'detail': 'ok'}]}\n"
    result = runner.run_generated_test(code, {})
    assert result["status"] == "runtime_error"
    assert result["error_type"] == "contract_violation"


def test_normal_invoice_assertion_code_remains_allowed():
    code = """def run_test(invoice):
    checks = []
    expected = 'Ready to Post'
    actual = invoice.get('final_status')
    checks.append({'name': 'Final status', 'passed': actual == expected, 'detail': f'Expected {expected}, got {actual}'})
    return {'passed': all(check['passed'] for check in checks), 'checks': checks}
"""
    result = runner.run_generated_test(code, {"final_status": "Ready to Post"})
    assert result["status"] == "passed"
