# AI-Assisted Invoice Test Builder

A small full-stack tool that turns a QA engineer's natural-language expectation for an
invoice-processing result into a deterministic, re-runnable Python test.

Workflow: **load a case → describe the expected outcome → generate Python → review/edit →
run it in a sandboxed subprocess → see pass / fail / syntax error / runtime error → save →
rerun later.** The generated Python code — not the LLM — decides pass/fail.

## Stack

- **Backend:** FastAPI + plain `sqlite3` (no ORM), Python 3.11+.
- **Frontend:** a single static page (`frontend/index.html` + `app.js` + `styles.css`), no
  build step — vanilla JS against the JSON API. Served directly by FastAPI at `/`.
- **LLM:** Anthropic Messages API (`anthropic` SDK), used only to *generate text* (Python
  source). A rule-based **mock generator** is used automatically whenever no API key is
  configured, so the whole app works offline.
- **Execution:** generated code runs in a separate OS process with a wall-clock timeout,
  POSIX resource limits, and a stripped environment. See [Execution boundary / trust boundary](#execution-boundary--trust-boundary) below.

## Quick start

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt

# Optional: enable real LLM generation. Without this, the app runs entirely in mock mode.
export ANTHROPIC_API_KEY="<your-anthropic-api-key>"

uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** — the frontend is served by the same process, no separate
dev server needed. `data/` (the 9 provided cases) ships inside the repo and is read
directly from disk; nothing needs to be imported or seeded.

### Running the automated tests

```bash
cd backend
pytest -v
```

57 tests cover: case loading (incl. path-traversal guard), the mock generator, the sandbox
runner's handling of pass / fail / syntax error / runtime error / timeout / contract
violations, and the full API workflow (generate → run → save → rerun → edit → rerun again).
Tests never hit the network or a real model (`INVOICE_FORCE_MOCK=1` is set in
`tests/conftest.py`) and use a throwaway SQLite file.

## Using it

1. Pick one of the 9 cases in the left sidebar (badge shows the case's expected status).
2. The expectation textarea is pre-filled from `expectation.json`'s
   `expectation_criteria` — edit it freely, it's just the prompt.
3. **Generate test** calls `/api/generate`. If `ANTHROPIC_API_KEY` is set and the "Use LLM"
   toggle is on, it calls the model; otherwise it uses the offline mock generator. Either
   way you get back editable Python that defines `run_test(invoice: dict) -> dict`.
4. **Run test** executes the code against that case's `result.json` in the sandbox and
   shows a pass/fail banner with a per-check breakdown, or a syntax/runtime/timeout error
   with the relevant detail.
5. **Save test case** persists `{case, name, expectation text, code}` to SQLite. Saved
   tests appear in the right-hand column with their last run status and can be reopened,
   edited, rerun, or deleted — no model call is needed to rerun.
6. Try the benchmark from the brief: generate case-01's test, run it (passes), then edit
   the code so an assertion is false (e.g. change the expected status string) and rerun —
   you'll see a clear `failed` result with the specific check that broke, distinct from a
   `syntax_error` or `runtime_error`.

## API

| Method | Path                    | Purpose                                            |
|--------|--------------------------|----------------------------------------------------|
| GET    | `/api/cases`             | List the 9 fixtures (from `data/index.json`)       |
| GET    | `/api/cases/{folder}`    | Full `expectation.json` + `result.json` for a case |
| POST   | `/api/generate`          | `{case_folder, expectation_text, use_llm}` → `{code, source}` |
| POST   | `/api/run`               | `{case_folder, code}` → run once, no persistence   |
| POST   | `/api/tests`             | Save a test `{case_folder, name, expectation_text, code}` |
| GET    | `/api/tests`             | List saved tests                                   |
| GET/PUT/DELETE | `/api/tests/{id}` | Fetch / edit / delete a saved test                 |
| POST   | `/api/tests/{id}/run`    | Rerun a saved test, persists `last_run_status`      |
| GET    | `/api/health`            | `{status, llm_available}`                           |

### `run_test` contract

```python
def run_test(invoice: dict) -> dict:
    """Evaluate the expectation against an invoice-processing output.

    Args:
        invoice: parsed content of a result.json file.

    Returns:
        {"passed": bool, "checks": [{"name": str, "passed": bool, "detail": str}, ...]}
    """
```

`checks` is a required list in the execution contract. Every check must contain a string `name`,
a real boolean `passed`, and a string `detail`. The runner validates this shape before it accepts
the result, so values such as `"false"` cannot be accidentally coerced into a passing boolean.

### Result shape returned by `/api/run` and `/api/tests/{id}/run`

```jsonc
{
  "status": "passed" | "failed" | "syntax_error" | "runtime_error" | "timeout",
  "passed": true,               // present when status is passed/failed
  "checks": [ { "name": "...", "passed": true, "detail": "..." } ],
  "error": "...",                // present for syntax_error / runtime_error / timeout
  "traceback": "...",            // present for runtime_error
  "duration_ms": 12.3
}
```

`failed` (the code ran fine but an assertion in it evaluated to false) is deliberately a
different status from `runtime_error` (the code itself blew up) and from `syntax_error`
(the code never even compiled) — see requirement #7 in the brief.

## Execution boundary / trust boundary

Generated Python is **untrusted input**: it originates from an LLM (or a user editing
LLM output) and is executed by the server. `backend/app/runner.py` is the single place
this happens, and documents its own reasoning inline. Summary:

**What's in place today:**
- Runs in a **separate subprocess**, not in-process — a crash or hang can't take the API
  server down.
- **Wall-clock timeout** (`subprocess.run(timeout=...)`, default 5s) that kills the process
  if exceeded.
- **POSIX resource limits** via `resource.setrlimit` in a `preexec_fn`: capped address
  space (default 256MB), capped CPU time, capped process count, capped file size —
  best-effort, Linux/macOS only.
- Runs with **`python -I -S`** (isolated mode): ignores `PYTHON*` env vars and doesn't
  auto-import `site`, so a malicious `sitecustomize.py` on the host can't be leveraged.
- **Stripped environment** (`env={}`) — no API keys or application secrets are inherited by
  generated code. Generated code is also statically rejected from importing `os`, `sys`,
  networking/process modules, or reading files.
- **Pre-execution AST validation** rejects imports, dynamic execution (`eval`/`exec`/`compile`),
  filesystem/process/network primitives, dunder access, and unknown global calls before the
  subprocess starts.
- Runs in a throwaway `tempfile.TemporaryDirectory()`, deleted after execution.
- Clear separation, enforced by a small harness script, between "didn't compile", "failed
  static validation", "raised while loading/running", and "ran fine but an assertion was
  false" (see `HARNESS_SOURCE` in `runner.py`).
- **Strict result-contract validation** rejects truthy non-booleans such as `"false"` instead
  of coercing them to `True`.

**What's explicitly NOT in place (by design, given the timebox), and why it matters:**
- No container / gVisor / nsjail / Firecracker / seccomp profile. On a single Linux host,
  code running under rlimits can still, in principle, open arbitrary files it has OS
  permission to read, or make outbound network calls (nothing here blocks sockets). A
  production system should run generated code in a locked-down container or microVM with
  **no filesystem access beyond a scratch dir and no network egress**, rather than relying
  on process-level rlimits alone.
- The AST validator is intentionally a lightweight allow/deny layer, not a complete security
  boundary. It reduces the attack surface before execution, but a production system should
  still move generated code into a locked-down container or microVM with **network egress
  disabled and a read-only filesystem**.
- No per-user/tenant isolation or resource quota across concurrent runs (fine for a
  single-user local tool; would need a queue + worker pool at scale).

## Persistence

Saved tests live in a single SQLite table (`backend/app_data.db`, path overridable via
`INVOICE_DB_PATH`) via plain `sqlite3` — chosen over an ORM because the schema is one table
and it keeps the amount of code between "LLM output" and "what actually decides pass/fail"
as small and auditable as possible. The provided `data/` fixtures are read directly from
disk and are never written to; only user-created tests are persisted.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset | Enables real LLM generation. Unset = mock mode. |
| `INVOICE_LLM_MODEL` | `claude-sonnet-4-5` | Model used for generation. |
| `INVOICE_FORCE_MOCK` | unset | Force mock mode even if a key is set (used by tests). |
| `INVOICE_DATA_DIR` | `./data` | Where case fixtures are read from. |
| `INVOICE_DB_PATH` | `./backend/app_data.db` | SQLite file location. |
| `INVOICE_EXEC_TIMEOUT` | `5` | Wall-clock seconds before a run is killed. |
| `INVOICE_EXEC_MEMORY_MB` | `256` | RLIMIT_AS cap for the child process. |
| `INVOICE_EXEC_CPU_LIMIT` | `5` | RLIMIT_CPU cap (seconds) for the child process. |

## Repository layout

```
backend/
  app/
    main.py       FastAPI routes
    cases.py      Read-only access to data/ fixtures
    llm.py        Mock generator + Anthropic API call
    runner.py     Sandboxed execution of generated code
    db.py         SQLite persistence for saved tests
    config.py     Env-driven configuration
  tests/           pytest suite (57 tests)
  requirements.txt
frontend/
  index.html, app.js, styles.css   static, no build step
data/              the 9 provided fixtures (read-only)
AI_USAGE.md
CHALLENGE.md       the original brief, for reference
```
