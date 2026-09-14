"""Defense-in-depth validation for LLM/user-edited Python test code.

This is intentionally a *pre-execution* safety layer, not a production-grade
sandbox. The actual execution still happens in a separate subprocess with
resource limits. The validator rejects imports, dynamic code execution,
filesystem/process/network primitives, dunder access, and other constructs that
are unnecessary for an invoice assertion function.
"""
import ast
from dataclasses import dataclass


ALLOWED_BUILTINS = {
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "isinstance",
    "len", "list", "max", "min", "round", "set", "sorted", "str", "sum", "tuple",
    "zip",
}

FORBIDDEN_NAMES = {
    "__import__", "eval", "exec", "compile", "open", "input", "breakpoint",
    "globals", "locals", "vars", "dir", "help", "memoryview",
    "os", "sys", "subprocess", "socket", "pathlib", "shutil", "requests",
    "urllib", "http", "ftplib", "ctypes", "pickle", "marshal", "signal",
    "resource", "importlib", "builtins",
}

FORBIDDEN_CALLS = FORBIDDEN_NAMES | {
    "getattr", "setattr", "delattr", "hasattr", "type", "object", "super",
}


@dataclass(frozen=True)
class ValidationIssue:
    message: str
    line: int | None = None
    column: int | None = None


class GeneratedCodeValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue], kind: str = "validation"):
        self.issues = issues
        self.kind = kind
        summary = "; ".join(issue.message for issue in issues[:5])
        if len(issues) > 5:
            summary += f"; and {len(issues) - 5} more issue(s)"
        super().__init__(summary)


def _issue(node: ast.AST, message: str) -> ValidationIssue:
    return ValidationIssue(
        message=message,
        line=getattr(node, "lineno", None),
        column=getattr(node, "col_offset", None),
    )


def validate_generated_code(source: str) -> list[ValidationIssue]:
    """Return static validation issues; do not execute the supplied source."""
    issues: list[ValidationIssue] = []
    try:
        tree = ast.parse(source, filename="<generated_test>", mode="exec")
    except SyntaxError as exc:
        return [ValidationIssue(str(exc), exc.lineno, exc.offset)]

    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    run_tests = [node for node in functions if node.name == "run_test"]
    if len(run_tests) != 1:
        issues.append(ValidationIssue("Generated code must define exactly one run_test(invoice) function."))
    elif len(run_tests[0].args.args) != 1:
        issues.append(_issue(run_tests[0], "run_test() must accept exactly one argument: invoice."))
    
    allowed_top_level = (ast.FunctionDef, ast.Assign, ast.AnnAssign, ast.Expr, ast.Constant)
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            issues.append(_issue(node, "Imports are not allowed in generated tests."))
        elif not isinstance(node, allowed_top_level):
            # Avoid allowing class definitions, decorators, async constructs, etc.
            if not (isinstance(node, ast.FunctionDef) and node.name == "run_test"):
                issues.append(_issue(node, f"Top-level construct {type(node).__name__} is not allowed."))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, (ast.Global, ast.Nonlocal, ast.Lambda, ast.AsyncFunctionDef, ast.ClassDef)):
            issues.append(_issue(node, f"{type(node).__name__} is not allowed in generated tests."))
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES or node.id.startswith("__"):
                issues.append(_issue(node, f"Use of '{node.id}' is not allowed."))
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                issues.append(_issue(node, f"Dunder attribute '{node.attr}' is not allowed."))
            if node.attr in FORBIDDEN_NAMES:
                issues.append(_issue(node, f"Access to '{node.attr}' is not allowed."))
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in FORBIDDEN_CALLS or node.func.id.startswith("__"):
                    issues.append(_issue(node, f"Call to '{node.func.id}' is not allowed."))
                elif node.func.id not in ALLOWED_BUILTINS and node.func.id not in {"run_test"}:
                    # Locally defined helper functions are allowed; external/global
                    # callables are not. The later name-resolution check keeps this
                    # conservative without forbidding normal helper functions.
                    defined_names = {n.name for n in functions}
                    if node.func.id not in defined_names:
                        issues.append(_issue(node, f"Call to unknown function '{node.func.id}' is not allowed."))
        elif isinstance(node, ast.NamedExpr):
            issues.append(_issue(node, "Assignment expressions are not allowed."))
        elif isinstance(node, ast.Await):
            issues.append(_issue(node, "Async execution is not allowed."))

    return _dedupe_issues(issues)


def _dedupe_issues(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    seen = set()
    result = []
    for item in issues:
        key = (item.message, item.line, item.column)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def validate_or_raise(source: str) -> None:
    try:
        ast.parse(source, filename="<generated_test>", mode="exec")
    except SyntaxError as exc:
        raise GeneratedCodeValidationError(
            [ValidationIssue(str(exc), exc.lineno, exc.offset)], kind="syntax_error"
        ) from exc

    issues = validate_generated_code(source)
    if issues:
        raise GeneratedCodeValidationError(issues, kind="validation")
