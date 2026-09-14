# Full-Stack Engineering Challenge — AI-Assisted Invoice Test Builder

## Purpose

This exercise evaluates your ability to use modern AI development tools to design and
deliver a working full-stack feature quickly.

You are encouraged to use coding agents and generative AI throughout the assignment. We
are interested not only in the final code, but also in how you direct, validate and
improve AI-generated work.

## Deadline

Please submit the completed assignment within a maximum of **5 working days** of receiving it.

We do not expect a production-ready solution. Prioritise a coherent end-to-end workflow,
sound technical decisions and a usable result.

## Scenario

Our platform processes supplier invoices automatically: it extracts the document, matches
lines against purchase orders or a product catalog, validates prices and quantities
against tolerances, classifies lines into accounting dimensions, and decides whether the
invoice is ready for posting or needs human review.

To test that pipeline, QA engineers write an **expectation** for each sample invoice in
natural language. Your task is to build the tool that turns such an expectation into a
**deterministic, executable test**.

Build an application that lets a user:

1. Load an invoice-processing output (`result.json` — provided, see *Provided data*).
2. Write the expected result in natural language.
3. Use an LLM to generate **Python code** that evaluates the expectation against the output.

The generated Python code — **not the LLM** — must decide whether the test passes or
fails. Once generated, a test must be reproducible and re-runnable with no model call.

### Example expectation

> We expect the invoice to be Ready to Post. Both lines should match PO B202607-31195.
> The BANANA PREPARATION line should match exactly with no warnings. The PINEAPPLE line
> over-consumes the remaining PO quantity (23.29 vs 20 KG) and should produce a
> non-blocking quantity warning, but must stay matched and must not be flagged for a
> price mismatch.

(This is essentially `case-01-over-supply-within-tolerance/expectation.json` — every
provided case comes with a real expectation you can use.)

## Provided data

The `data/` directory contains **9 anonymised test cases** exported from the invoice
processing system. Each case is a folder:

```
data/
  index.json                      # list of all cases with expected/actual status
  case-01-over-supply-within-tolerance/
    expectation.json              # the natural-language expected result
    result.json                   # the invoice-processing output to test against
  case-02-rooftop-data-capture-and-classification/
  ...
```

### `expectation.json`

| Field | Meaning |
|-------|---------|
| `test_case_name` | Human-readable name of the scenario |
| `expected_status` | Expected final document status (e.g. `Ready to Post`, `Needs Verification`) |
| `expectation_criteria` | The natural-language expectation — the input for your code generator |
| `tags` | Scenario category (e.g. `PO Matching`, `Data Capture`) |

### `result.json` — the invoice-processing output

The fields your generated tests will typically assert on:

| Field | Meaning |
|-------|---------|
| `final_status`, `header.status` | Final document status |
| `header` | Invoice header: vendor (`party_name`), organisation, `document_number`, totals, currency, dates |
| `lines[]` | Invoice lines: `description`, `quantity`, `unit_price`, `net_amount`, and PO-match fields (`matched_po_number`, `matched_po_quantity`, `matched_po_quantity_to_deduct`) |
| `validation[]` | Policy validation results: `severity` (`WARN` / `BLOCK`), `outcome_status`, and `tolerance_outcome` with per-line `matches[]` (`price_difference`, `price_within_tolerance`, `po_remaining_quantity`, `quantity_to_deduct`) and `quantity_overages[]` (`tier`: `ok` / `review` / `block`, `overage_pct`, `reason`) |
| `warnings[]`, `failures[]` | Human-readable warning / failure messages |
| `po_matching` | PO matching audit: `validation_rows`, `review_reasons` |
| `classification[]` | Per-line dimension/GL classification decisions (`dimension_name`, `dimension_value_name`, `dimension_confidence`, `decision`) |
| `catalog_matching` | Per-line catalog match info (`catalog_node_name`, `catalog_node_path`), where catalog matching applies |
| `pending_review`, `review_queue` | Whether the document is held for human review |

The 9 cases intentionally cover different assertion styles: exact PO matches, quantity
over-supply within/outside tolerance, price differences under/over a €0.01 tolerance,
catalog matching, unit conversions, dimension classification, and data capture
(IBAN / voyage-number extraction). All names, numbers and identifiers are fictional;
amounts, tolerances and statuses are real system behaviour.

## Required workflow

The user should be able to:

1. Select or load an invoice-processing output.
2. Enter the expected result in natural language.
3. Generate a Python test from the expectation.
4. Review and edit the generated Python code.
5. Execute the code against the invoice output.
6. See whether the test passed or failed.
7. Distinguish **assertion failures**, **syntax errors** and **runtime errors**.
8. Save and rerun a test case.

The generated code should expose a documented entry point, for example:

```python
def run_test(invoice: dict) -> dict:
    """Evaluate the expectation against an invoice-processing output.

    Args:
        invoice: parsed content of a result.json file.

    Returns:
        e.g. {"passed": bool, "checks": [{"name": str, "passed": bool, "detail": str}]}
    """
```

You may define the exact contract and result format — document whatever you choose.

## Technical expectations

Your solution should include:

- A frontend interface
- A backend API
- Persistence for test cases
- LLM-based Python generation
- Deterministic Python execution
- Basic execution timeout or isolation
- Automated tests for the core execution flow
- A **mock mode** that works without an external model API key

Generated Python must be treated as **untrusted input**. A production-grade sandbox is
not required within the timebox, but your implementation and documentation should
demonstrate that you understand the risks and where the trust boundaries are.

## Use of AI tools

You are explicitly encouraged to use tools such as Claude Code, Codex, Cursor, Copilot
or equivalent systems.

Include an `AI_USAGE.md` file explaining:

- Which AI tools and models you used
- How you structured your prompts or agent instructions
- Which parts of the implementation were AI-generated
- Examples where the generated output was incorrect or incomplete
- How you validated and corrected generated work
- Decisions that required your own engineering judgement
- What you would improve with additional time

Do not include credentials, personal conversations or unrelated chat history.

## Deliverables

Submit exactly two things:

1. **The code solution** (with setup instructions, tests and `AI_USAGE.md`).
2. **A video with you on camera** explaining what you implemented, what alternatives you considered, and how it could be improved.

## Evaluation

We will evaluate:

- Completeness of the end-to-end workflow
- Effective and responsible use of AI development tools
- Speed and prioritisation
- Code quality and architecture
- Verification of AI-generated code
- Usability
- Testing and documentation

A smaller working solution is preferable to a broad incomplete one. As a benchmark:
generating a test from `case-01`'s expectation, running it against `case-01/result.json`
and seeing it pass — then editing the code to assert something false and seeing a clear
assertion failure — should demonstrate most of the required workflow.
