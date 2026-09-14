# AI Usage

This task explicitly encourages AI-assisted development. AI was used as an engineering
accelerator, but generated output was treated as untrusted until it had been reviewed,
executed, tested, and corrected.

## Tools and models

- **Claude Sonnet** was used for the initial agentic implementation pass: backend, frontend,
  persistence, LLM integration, execution runner, and the first automated-test suite.
- **ChatGPT (GPT-5.6 Luna)** was used during the review/hardening pass to inspect the
  implementation against the brief, identify gaps, improve security boundaries, expand
  verification, review the documentation, and prepare the submission for final QA.
- No credentials or personal conversations were supplied to the AI tools.

The exact model name used by the application is configurable through `INVOICE_LLM_MODEL`;
the default in this submission is `claude-sonnet-4-5`.

## How the AI-assisted workflow was structured

The implementation was developed in small, reviewable stages rather than asking an agent
to build an unconstrained application in one pass:

1. Inspect the brief and the actual nine fixture schemas before designing the data contract.
2. Define the generated-test contract first: `run_test(invoice) -> {passed, checks}`.
3. Build the fixture loader, persistence layer, execution boundary, generation layer, API,
   frontend, and tests incrementally.
4. Run the code after each major stage and use failures as feedback rather than assuming the
   generated implementation was correct.
5. Add business-case verification and mutation tests so a generated test must fail when a
   relevant invoice field is changed.
6. Audit the README and this file against the actual implementation before submission.

## What was AI-generated

AI assistance produced substantial portions of the implementation, including:

- FastAPI routes and Pydantic request/response models.
- SQLite persistence using Python's standard `sqlite3` module.
- The generated-test execution harness and static AST validation.
- The Anthropic API integration and offline mock generator.
- The static HTML/CSS/JavaScript frontend.
- Automated tests and fixture-specific verification.

The important engineering step was not treating that output as automatically correct.
The generated implementation was repeatedly run and corrected, and the final design reflects
those verification results.

## Examples of incorrect or incomplete AI-generated output

### 1. Unsafe result coercion

An early runner version effectively treated the `passed` value as truthy/falsy. That would
make a value such as `"false"` truthy in Python and could incorrectly produce a passing result.

**Correction:** the execution contract now requires `passed` to be a real boolean, and every
check must contain a string `name`, boolean `passed`, and string `detail`.

### 2. Contract violations were not surfaced cleanly

An early version assumed the generated function would always return a dictionary. A malformed
return value could therefore cause an internal exception instead of a useful test result.

**Correction:** the runner validates the result shape explicitly and reports contract
violations separately from normal assertion failures.

### 3. Test lifecycle assumptions in FastAPI

The API tests initially relied on startup behavior that is not guaranteed when `TestClient`
is instantiated without its lifespan context.

**Correction:** the application uses FastAPI's lifespan mechanism and the test suite initializes
the small test database explicitly as an additional safeguard.

### 4. Overly strict environment testing

An early test expected the child process environment to contain literally no variables. Python
can provide incidental locale information even when the application passes an empty environment.

**Correction:** the security test focuses on the property that matters: application credentials
and secret-like variables are not inherited by generated code.

### 5. Mock generation that could imply unsupported coverage

A first mock approach could produce a generic passing/reminder check for requirements it did
not actually understand. That creates a dangerous false sense of coverage.

**Correction:** the mock generator now implements only tested, high-confidence expectation
patterns and fails closed when it cannot safely translate the intent. The real LLM receives the
full invoice result plus the natural-language expectation.

## Security decisions and trust boundary

Generated Python is untrusted input because it can originate from an LLM or be edited by a
user in the browser.

The current implementation therefore combines:

- AST validation before execution.
- Rejection of imports, dynamic execution, filesystem/process/network primitives, dunder
  access, and unknown global calls.
- Execution in a separate subprocess.
- Wall-clock timeout.
- POSIX CPU, memory, process-count, and file-size limits where supported.
- Python isolated mode (`-I -S`).
- A stripped environment so application credentials are not inherited.
- A temporary working directory.
- Strict validation of the returned test-result contract.

This is intentionally **not described as a production-grade sandbox**. There is no container,
gVisor, nsjail, Firecracker, seccomp profile, or OS-level network namespace in this exercise.
A production deployment should execute generated code inside a stronger isolation boundary,
with network egress disabled and filesystem access restricted to an isolated scratch area.

## Why the LLM does not decide PASS/FAIL

The LLM is only a code generator. The generated Python source is reviewed and then executed
against the supplied invoice result. The execution result is the source of truth for PASS/FAIL.
Saved tests can therefore be rerun later without another model call.

This distinction is also why the system uses mutation testing: passing the original fixture is
not enough; the same test should fail when a business-relevant field is deliberately changed.

## Verification performed

The final suite contains **57 automated tests**, including:

- fixture loading and path-traversal protection;
- generation and mock-mode behavior;
- syntax/runtime/timeout/contract handling;
- execution-boundary checks;
- the complete generate → run → save → rerun → edit → rerun API workflow;
- business-specific checks for all nine supplied invoice cases;
- one mutation benchmark for each supplied case.

The mutation benchmark is especially important: it helps detect vacuous tests that only check
`final_status` while ignoring the actual expectation.

## What I would improve with more time

1. Replace the lightweight execution boundary with a locked-down container or microVM using
   no network egress and a read-only filesystem plus an isolated scratch directory.
2. Add more mutation operators and score generated-test quality automatically.
3. Use a real code editor such as CodeMirror or Monaco for syntax highlighting and line-level
   validation feedback.
4. Add run-history diffing so changes in invoice-processing output are visible over time.
5. Add authentication/authorization and per-user resource quotas if this becomes a multi-user
   production service.
