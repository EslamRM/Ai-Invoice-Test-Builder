"""Executes untrusted, LLM-generated Python code against an invoice result.

Trust boundary
--------------
The code passed into `run_generated_test` originates from an LLM (or from a
user editing an LLM-generated test in the browser). It must be treated as
untrusted input. This module is the one place in the codebase where that
untrusted code actually executes, so every other module can assume generated
code has already been through here.

What this implementation does:
  * Runs the code in a **separate OS process** (subprocess), not in-process,
    so a crash, infinite loop or unexpected exception can't take down the
    API server or corrupt its memory.
  * Applies a **wall-clock timeout** (subprocess.run(timeout=...)) and kills
    the process tree if it's exceeded.
  * Applies **POSIX resource limits** (CPU time, address space / memory, no
    forking, no new files beyond a small cap) via `resource.setrlimit` in a
    `preexec_fn`, best-effort on platforms that support it (Linux/macOS).
  * Runs Python in **isolated mode** (`-I`), which ignores the user's
    environment variables and site-packages tampering, and with `-S` to skip
    importing the `site` module.
  * Executes with a **stripped environment** — it inherits no credentials or
    API keys. Network access is not guaranteed to be blocked at the OS level.
  * Distinguishes three distinct failure modes the UI must be able to show
    separately: SyntaxError before anything runs, a runtime exception while
    the harness loads/executes the code, and a normal `run_test()` return
    where `passed` is False (an assertion failure, not a crash).

What this implementation deliberately does NOT do (documented, not hidden):
  * It does not use a container, gVisor, nsjail, or a seccomp filter. On a
    single Linux host `os.system`, `subprocess`, or `open()` on arbitrary
    files are still technically reachable from inside the child process
    within its resource limits. A production system should run generated
    code in a locked-down container/microVM with no filesystem or network
    access instead of relying on rlimits alone. See AI_USAGE.md / README.md.
"""
import json
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any

from .code_validation import GeneratedCodeValidationError, validate_or_raise
from .config import EXEC_CPU_LIMIT_SECONDS, EXEC_MEMORY_LIMIT_MB, EXEC_TIMEOUT_SECONDS

HARNESS_SOURCE = textwrap.dedent(
    '''
    import json
    import sys
    import traceback

    def main():
        code_path, invoice_path = sys.argv[1], sys.argv[2]

        with open(code_path, "r", encoding="utf-8") as f:
            source = f.read()
        with open(invoice_path, "r", encoding="utf-8") as f:
            invoice = json.load(f)

        try:
            compiled = compile(source, "<generated_test>", "exec")
        except SyntaxError as exc:
            print(json.dumps({
                "stage": "syntax_error",
                "error": str(exc),
                "line": exc.lineno,
                "offset": exc.offset,
            }))
            return

        namespace: dict = {}
        try:
            exec(compiled, namespace)
        except Exception as exc:
            print(json.dumps({
                "stage": "load_error",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }))
            return

        run_test = namespace.get("run_test")
        if not callable(run_test):
            print(json.dumps({
                "stage": "load_error",
                "error": "Generated code must define a callable run_test(invoice).",
            }))
            return

        try:
            outcome = run_test(invoice)
        except Exception as exc:
            print(json.dumps({
                "stage": "runtime_error",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }))
            return

        try:
            json.dumps(outcome)
        except TypeError:
            print(json.dumps({
                "stage": "runtime_error",
                "error": "run_test() must return a JSON-serialisable dict.",
            }))
            return

        print(json.dumps({"stage": "completed", "result": outcome}))

    if __name__ == "__main__":
        main()
    '''
)


def _preexec_fn():
    """Best-effort POSIX resource limits, applied inside the child process."""
    try:
        import resource

        mem_bytes = EXEC_MEMORY_LIMIT_MB * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (EXEC_CPU_LIMIT_SECONDS, EXEC_CPU_LIMIT_SECONDS))
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
        # Cap how large a file the child can create.
        resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 1024 * 1024, 10 * 1024 * 1024))
    except Exception:
        # Not available on this platform (e.g. Windows) — timeout + subprocess
        # isolation still apply.
        pass


def _validate_result_contract(result: Any) -> str | None:
    if not isinstance(result, dict):
        return f"run_test() must return a dict, got {type(result).__name__}."
    if type(result.get("passed")) is not bool:
        return "run_test() result['passed'] must be a real boolean."
    checks = result.get("checks")
    if not isinstance(checks, list):
        return "run_test() result['checks'] must be a list."
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            return f"Check {index} must be a dict."
        if not isinstance(check.get("name"), str):
            return f"Check {index} field 'name' must be a string."
        if type(check.get("passed")) is not bool:
            return f"Check {index} field 'passed' must be a real boolean."
        if not isinstance(check.get("detail"), str):
            return f"Check {index} field 'detail' must be a string."
    return None


def run_generated_test(code: str, invoice: dict[str, Any]) -> dict[str, Any]:
    """Execute `code` (must define run_test(invoice)) against `invoice`.

    Returns a dict with at least a "status" key, one of:
      "passed", "failed", "syntax_error", "runtime_error", "timeout"
    """
    start = time.monotonic()
    try:
        validate_or_raise(code)
    except GeneratedCodeValidationError as exc:
        first = exc.issues[0] if exc.issues else None
        return {
            "status": "syntax_error" if exc.kind == "syntax_error" else "runtime_error",
            "checks": [],
            "error_type": "code_validation" if exc.kind != "syntax_error" else "syntax",
            "error": str(exc),
            "line": first.line if first else None,
            "column": first.column if first else None,
            "duration_ms": round((time.monotonic() - start) * 1000, 1),
        }

    with tempfile.TemporaryDirectory(prefix="invoice_test_") as tmp:
        tmp_path = Path(tmp)
        harness_path = tmp_path / "_harness.py"
        code_path = tmp_path / "generated_test.py"
        invoice_path = tmp_path / "invoice.json"

        harness_path.write_text(HARNESS_SOURCE, encoding="utf-8")
        code_path.write_text(code, encoding="utf-8")
        invoice_path.write_text(json.dumps(invoice), encoding="utf-8")

        cmd = [sys.executable, "-I", "-S", str(harness_path), str(code_path), str(invoice_path)]

        kwargs: dict[str, Any] = dict(
            cwd=tmp,
            capture_output=True,
            text=True,
            timeout=EXEC_TIMEOUT_SECONDS,
            env={},  # no inherited environment, no leaked API keys
        )
        try:
            import resource  # noqa: F401  (probe availability before wiring preexec_fn)

            kwargs["preexec_fn"] = _preexec_fn
        except ImportError:
            pass

        try:
            proc = subprocess.run(cmd, **kwargs)
        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "checks": [],
                "error": f"Execution exceeded the {EXEC_TIMEOUT_SECONDS}s timeout.",
                "duration_ms": round((time.monotonic() - start) * 1000, 1),
            }

        duration_ms = round((time.monotonic() - start) * 1000, 1)

        stdout = proc.stdout.strip()
        if not stdout:
            return {
                "status": "runtime_error",
                "checks": [],
                "error": proc.stderr.strip() or f"Process exited with code {proc.returncode} and no output "
                                                  "(likely killed for exceeding a resource limit).",
                "duration_ms": duration_ms,
            }

        try:
            payload = json.loads(stdout.splitlines()[-1])
        except json.JSONDecodeError:
            return {
                "status": "runtime_error",
                "checks": [],
                "error": "Harness produced non-JSON output.",
                "raw_stdout": stdout,
                "raw_stderr": proc.stderr.strip(),
                "duration_ms": duration_ms,
            }

        stage = payload.get("stage")
        if stage == "syntax_error":
            return {
                "status": "syntax_error",
                "checks": [],
                "error": payload.get("error"),
                "line": payload.get("line"),
                "duration_ms": duration_ms,
            }
        if stage in ("load_error", "runtime_error"):
            return {
                "status": "runtime_error",
                "checks": [],
                "error": payload.get("error"),
                "traceback": payload.get("traceback"),
                "duration_ms": duration_ms,
            }
        if stage == "completed":
            result = payload.get("result")
            contract_error = _validate_result_contract(result)
            if contract_error:
                return {
                    "status": "runtime_error",
                    "checks": [],
                    "error_type": "contract_violation",
                    "error": contract_error,
                    "duration_ms": duration_ms,
                }
            passed = result["passed"]
            return {
                "status": "passed" if passed else "failed",
                "passed": passed,
                "checks": result["checks"],
                "duration_ms": duration_ms,
            }

        return {
            "status": "runtime_error",
            "checks": [],
            "error": f"Unrecognised harness stage: {stage!r}",
            "duration_ms": duration_ms,
        }
