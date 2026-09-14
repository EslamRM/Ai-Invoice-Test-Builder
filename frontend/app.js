"use strict";

const API = "/api";

const state = {
  cases: [],
  activeCaseFolder: null,
  activeCase: null,       // { folder, expectation, result }
  expectationText: "",
  code: "",
  source: "mock",
  llmAvailable: false,
  useLlm: true,
  lastRunResult: null,
  savedTests: [],
  activeSavedTestId: null,
  codeDirty: false,
};

// ---------------------------------------------------------------------
// fetch helpers
// ---------------------------------------------------------------------
async function api(path, opts) {
  const resp = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(body.detail || `Request failed (${resp.status})`);
  }
  return body;
}

function esc(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.remove("show"), 2400);
}

// ---------------------------------------------------------------------
// bootstrap
// ---------------------------------------------------------------------
async function init() {
  try {
    const health = await api("/health");
    state.llmAvailable = !!health.llm_available;
  } catch (e) {
    state.llmAvailable = false;
  }
  renderModePill();

  try {
    state.cases = await api("/cases");
  } catch (e) {
    document.getElementById("case-list").innerHTML =
      `<div class="saved-empty">Could not reach the API at ${API}. Is the backend running?</div>`;
    return;
  }
  renderSidebar();
  await refreshSavedTests();
}

function renderModePill() {
  const pill = document.getElementById("mode-pill");
  const text = document.getElementById("mode-pill-text");
  if (state.llmAvailable) {
    pill.classList.add("live");
    text.textContent = "LLM connected";
  } else {
    pill.classList.remove("live");
    text.textContent = "Mock mode (no API key)";
  }
}

// ---------------------------------------------------------------------
// sidebar / case list
// ---------------------------------------------------------------------
function renderSidebar() {
  const list = document.getElementById("case-list");
  const count = document.getElementById("case-count");
  if (count) count.textContent = state.cases.length;
  list.innerHTML = state.cases
    .map((c, index) => {
      const active = c.folder === state.activeCaseFolder ? "active" : "";
      const statusOk = c.expected_status === c.final_status;
      const dotClass = statusOk ? "ready" : "review";
      return `
        <button class="case-item ${active}" data-folder="${esc(c.folder)}" aria-current="${active ? "page" : "false"}">
          <div class="case-top">
            <div>
              <div class="case-number">CASE ${String(index + 1).padStart(2, "0")}</div>
              <div class="name">${esc(c.name)}</div>
            </div>
            <span class="status-dot ${dotClass}" title="${esc(c.expected_status)}"></span>
          </div>
          <div class="case-description">${esc(c.expected_status)} · ${esc(c.folder)}</div>
        </button>`;
    })
    .join("");

  list.querySelectorAll(".case-item").forEach((el) => {
    el.addEventListener("click", () => selectCase(el.dataset.folder));
  });
}

async function selectCase(folder) {
  state.activeCaseFolder = folder;
  renderSidebar();
  try {
    state.activeCase = await api(`/cases/${encodeURIComponent(folder)}`);
  } catch (e) {
    showToast(e.message);
    return;
  }
  state.expectationText = state.activeCase.expectation.expectation_criteria || "";
  state.code = "";
  state.source = "mock";
  state.activeSavedTestId = null;
  state.codeDirty = false;
  state.lastRunResult = null;
  renderMain();
}

// ---------------------------------------------------------------------
// main panel
// ---------------------------------------------------------------------
function renderMain() {
  const main = document.getElementById("main");
  if (!state.activeCase) {
    main.innerHTML = `<div class="empty-state">
      <div class="empty-icon">▣</div>
      <div class="big">Select a case to begin</div>
      <div>Choose one of the provided invoice outputs to generate and verify a test.</div>
    </div>`;
    return;
  }

  const { expectation, result } = state.activeCase;
  const header = result.header || {};
  const lineCount = (result.lines || []).length;
  const sourceLabel = state.source === "llm" ? "LLM" : state.source === "mock" ? "Offline mock" : state.source;
  const dirtyLabel = state.codeDirty ? `<span class="editor-dirty">Unsaved changes</span>` : `<span>Ready</span>`;
  const runDisabled = !state.code.trim() ? "disabled" : "";

  main.innerHTML = `
    <div class="case-header">
      <div class="case-title-wrap">
        <div class="section-kicker">Invoice test case</div>
        <h2>${esc(expectation.test_case_name)}</h2>
        <div class="case-meta"><code>${esc(state.activeCaseFolder)}</code> · tags: ${(expectation.tags || []).map(esc).join(", ") || "—"}</div>
      </div>
      <div class="header-actions">
        <button class="btn btn-secondary btn-small" id="btn-copy-json" title="Copy the complete invoice result">Copy JSON</button>
        <button class="btn btn-secondary btn-small" id="btn-reset-code" ${state.code ? "" : "disabled"}>Reset code</button>
      </div>
    </div>

    <div class="summary-grid">
      <div class="summary-cell"><div class="label">Vendor</div><div class="value">${esc(header.party_name || "—")}</div></div>
      <div class="summary-cell"><div class="label">Doc #</div><div class="value">${esc(header.document_number || "—")}</div></div>
      <div class="summary-cell"><div class="label">Final status</div><div class="value">${esc(result.final_status || header.status || "—")}</div></div>
      <div class="summary-cell"><div class="label">Lines</div><div class="value">${lineCount}</div></div>
    </div>

    <details class="raw-json">
      <summary>View raw result.json <span class="summary-hint">Reference data · not editable</span></summary>
      <pre>${esc(JSON.stringify(result, null, 2))}</pre>
    </details>

    <div class="panel">
      <div class="panel-header">
        <div>
          <h3>1 · Expectation</h3>
          <div class="panel-subtitle">Describe what the generated test should prove. Be specific about fields, thresholds, and required outcomes.</div>
        </div>
      </div>
      <textarea id="expectation-input" aria-label="Natural language expectation" placeholder="Example: Every invoice line must have Voyage Code V7X0042 with 100% confidence.">${esc(state.expectationText)}</textarea>
      <div class="toolbar toolbar-main">
        <div class="toolbar-left">
          <button class="btn btn-primary" id="btn-generate">Generate test</button>
          <label class="toggle ${state.llmAvailable ? "" : "toggle-disabled"}" title="${state.llmAvailable ? "Generate using the configured model" : "No API key is configured, so generation uses the offline mock"}">
            <input type="checkbox" id="toggle-llm" ${state.useLlm ? "checked" : ""} ${state.llmAvailable ? "" : "disabled"} />
            Use LLM ${state.llmAvailable ? "" : "· offline mock"}
          </label>
        </div>
        <div class="toolbar-right"><span class="badge badge-neutral">Input: natural language</span></div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-header">
        <div>
          <h3>2 · Review generated Python <span class="source-tag" id="source-tag">${esc(sourceLabel)}</span></h3>
          <div class="panel-subtitle">Review or edit the code before running it. The runner validates and executes it in a timeboxed subprocess.</div>
        </div>
        <div class="panel-actions"><button class="btn btn-small btn-secondary" id="btn-copy-code" ${state.code ? "" : "disabled"}>Copy code</button></div>
      </div>
      <div class="editor-wrap">
        <textarea id="code-editor" spellcheck="false" aria-label="Generated Python code" placeholder="Generate a test or write Python here...">${esc(state.code)}</textarea>
        <div class="editor-meta"><span>${dirtyLabel}</span><span id="code-stats">${codeStats(state.code)}</span></div>
      </div>
      <div class="toolbar toolbar-main">
        <div class="toolbar-left">
          <button class="btn btn-primary" id="btn-run" ${runDisabled}>Run test</button>
          <button class="btn btn-secondary" id="btn-save" ${runDisabled}>Save test</button>
        </div>
        <div class="toolbar-right"><span class="badge badge-neutral">Deterministic replay</span></div>
      </div>
      <div class="hint">Generated code is treated as untrusted input. The runner validates the source, applies resource limits, strips inherited environment variables, and executes it in a separate subprocess. See README for the security boundary.</div>
    </div>

    <div class="panel" id="result-panel" style="${state.lastRunResult ? "" : "display:none"}">
      <div class="panel-header">
        <div>
          <h3>3 · Verification result</h3>
          <div class="panel-subtitle">PASS/FAIL is decided by the executed Python test, not by the LLM.</div>
        </div>
      </div>
      <div id="result-body"></div>
    </div>
  `;

  document.getElementById("btn-generate").addEventListener("click", onGenerate);
  document.getElementById("btn-run").addEventListener("click", onRun);
  document.getElementById("btn-save").addEventListener("click", onSave);
  document.getElementById("btn-copy-code").addEventListener("click", () => copyText(state.code, "Code copied."));
  document.getElementById("btn-copy-json").addEventListener("click", () => copyText(JSON.stringify(result, null, 2), "Invoice JSON copied."));
  document.getElementById("btn-reset-code").addEventListener("click", resetCode);
  document.getElementById("toggle-llm").addEventListener("change", (e) => { state.useLlm = e.target.checked; });
  document.getElementById("expectation-input").addEventListener("input", (e) => { state.expectationText = e.target.value; });
  document.getElementById("code-editor").addEventListener("input", (e) => {
    state.code = e.target.value;
    state.codeDirty = true;
    updateEditorState();
  });

  if (state.lastRunResult) renderResult(state.lastRunResult);
}

function codeStats(code) {
  const lines = code ? code.split("\n").length : 0;
  const chars = code ? code.length : 0;
  return `${lines} lines · ${chars} chars`;
}

function updateEditorState() {
  const stats = document.getElementById("code-stats");
  const save = document.getElementById("btn-save");
  const run = document.getElementById("btn-run");
  const copy = document.getElementById("btn-copy-code");
  if (stats) stats.textContent = codeStats(state.code);
  if (save) save.disabled = !state.code.trim();
  if (run) run.disabled = !state.code.trim();
  if (copy) copy.disabled = !state.code.trim();
  const dirty = document.querySelector(".editor-dirty");
  if (dirty) dirty.textContent = state.codeDirty ? "Unsaved changes" : "Ready";
}

async function copyText(text, successMessage) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    showToast(successMessage);
  } catch (e) {
    showToast("Copy failed. Select and copy manually.");
  }
}

function resetCode() {
  if (!state.code || !state.activeCase) return;
  if (!window.confirm("Reset the editor to the latest generated/saved code?")) return;
  const sourceTest = state.activeSavedTestId ? state.savedTests.find((t) => t.id === state.activeSavedTestId) : null;
  if (sourceTest) {
    state.code = sourceTest.code;
    state.source = sourceTest.source || "saved";
  } else {
    state.code = "";
    state.source = "mock";
  }
  state.codeDirty = false;
  state.lastRunResult = null;
  renderMain();
}

function renderResult(result) {
  const panel = document.getElementById("result-panel");
  const body = document.getElementById("result-body");
  panel.style.display = "";

  const statusLabels = {
    passed: "Passed",
    failed: "Failed — assertion(s) did not hold",
    syntax_error: "Syntax error — code did not compile",
    runtime_error: "Runtime error — code raised an exception",
    timeout: "Timed out — execution exceeded the limit",
  };
  const passedChecks = (result.checks || []).filter(c => c.passed).length;
  const totalChecks = (result.checks || []).length;

  let html = `<div class="result-banner ${esc(result.status)}">
    <span>${esc(statusLabels[result.status] || result.status)}</span>
    ${result.duration_ms != null ? `<span style="margin-left:auto;font-weight:500;font-size:11.5px;">${esc(result.duration_ms)} ms</span>` : ""}
  </div>`;
  html += `<div class="result-summary">
    <span>${totalChecks ? `${passedChecks}/${totalChecks} checks passed` : "No structured checks returned"}</span>
    ${result.error_type ? `<span class="sep">·</span><span>Error: ${esc(result.error_type)}</span>` : ""}
  </div>`;

  if (result.checks && result.checks.length) {
    html += result.checks.map((c) => `<div class="check-row ${c.passed ? "pass" : "fail"}">
      <span class="icon">${c.passed ? "✓" : "✕"}</span>
      <div><div class="name">${esc(c.name)}</div><div class="detail">${esc(c.detail || "")}</div></div>
    </div>`).join("");
  } else if (!result.error) {
    html += `<div class="result-empty">The test returned no checks.</div>`;
  }

  if (result.error) {
    html += `<div class="error-block">${esc(result.error)}${result.traceback ? "\n\n" + esc(result.traceback) : ""}</div>`;
  }
  body.innerHTML = html;
}

// ---------------------------------------------------------------------
// actions
// ---------------------------------------------------------------------
async function onGenerate() {
  const btn = document.getElementById("btn-generate");
  btn.disabled = true;
  btn.textContent = "Generating…";
  try {
    const resp = await api("/generate", {
      method: "POST",
      body: JSON.stringify({
        case_folder: state.activeCaseFolder,
        expectation_text: state.expectationText,
        use_llm: state.useLlm,
      }),
    });
    state.code = resp.code;
    state.source = resp.source;
    state.codeDirty = false;
    state.activeSavedTestId = null;
    state.lastRunResult = null;
    renderMain();
    showToast(`Generated with ${resp.source === "llm" ? "the LLM" : "the offline mock generator"}.`);
  } catch (e) {
    showToast("Generate failed: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate test";
  }
}

async function onRun() {
  const btn = document.getElementById("btn-run");
  btn.disabled = true;
  btn.textContent = "Running…";
  try {
    const result = await api("/run", {
      method: "POST",
      body: JSON.stringify({ case_folder: state.activeCaseFolder, code: state.code }),
    });
    state.lastRunResult = result;
    renderResult(result);
    document.getElementById("result-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) {
    showToast("Run failed: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Run test";
  }
}

async function onSave() {
  if (!state.code.trim()) {
    showToast("Generate or write some code first.");
    return;
  }
  const defaultName = state.activeCase.expectation.test_case_name || state.activeCaseFolder;
  const name = window.prompt("Name this saved test:", defaultName);
  if (!name) return;
  try {
    await api("/tests", {
      method: "POST",
      body: JSON.stringify({
        case_folder: state.activeCaseFolder,
        name,
        expectation_text: state.expectationText,
        code: state.code,
        source: state.source,
      }),
    });
    state.codeDirty = false;
    showToast("Test saved.");
    await refreshSavedTests();
  } catch (e) {
    showToast("Save failed: " + e.message);
  }
}

async function refreshSavedTests() {
  try {
    state.savedTests = await api("/tests");
  } catch (e) {
    state.savedTests = [];
  }
  renderSavedList();
}

function renderSavedList() {
  const list = document.getElementById("saved-list");
  const count = document.getElementById("saved-count");
  if (count) count.textContent = state.savedTests.length;
  if (!state.savedTests.length) {
    list.innerHTML = `<div class="saved-empty">No saved tests yet. Generate one, run it, then hit "Save test case".</div>`;
    return;
  }
  list.innerHTML = state.savedTests
    .map((t) => {
      const badge = t.last_run_status
        ? `<span class="badge badge-${t.last_run_status}">${esc(t.last_run_status)}</span>`
        : `<span class="badge badge-neutral">not run</span>`;
      return `
        <div class="saved-test-card ${state.activeSavedTestId === t.id ? "selected" : ""}" data-id="${esc(t.id)}">
          <div class="card-top"><div class="title">${esc(t.name)}</div>${badge}</div>
          <div class="case">${esc(t.case_folder)}</div>
          <div class="row">
            <button class="btn btn-ghost btn-open" data-id="${esc(t.id)}">Open</button>
            <button class="btn btn-ghost btn-rerun" data-id="${esc(t.id)}">Rerun</button>
            <button class="btn btn-ghost btn-danger btn-delete" data-id="${esc(t.id)}">Delete</button>
          </div>
        </div>`;
    })
    .join("");

  list.querySelectorAll(".btn-open").forEach((b) =>
    b.addEventListener("click", () => openSavedTest(b.dataset.id))
  );
  list.querySelectorAll(".btn-rerun").forEach((b) =>
    b.addEventListener("click", () => rerunSavedTest(b.dataset.id))
  );
  list.querySelectorAll(".btn-delete").forEach((b) =>
    b.addEventListener("click", () => deleteSavedTest(b.dataset.id))
  );
}

async function openSavedTest(id) {
  const test = state.savedTests.find((t) => t.id === id);
  if (!test) return;
  if (test.case_folder !== state.activeCaseFolder) {
    await selectCase(test.case_folder);
  }
  state.expectationText = test.expectation_text;
  state.code = test.code;
  state.source = test.source || "saved";
  state.activeSavedTestId = test.id;
  state.codeDirty = false;
  state.lastRunResult = test.last_run_result || null;
  renderMain();
}

async function rerunSavedTest(id) {
  try {
    const result = await api(`/tests/${id}/run`, { method: "POST" });
    showToast(`Rerun: ${result.status}`);
    await refreshSavedTests();
    const test = state.savedTests.find((t) => t.id === id);
    if (test && test.case_folder === state.activeCaseFolder) {
      state.lastRunResult = result;
      state.codeDirty = false;
      renderResult(result);
      document.getElementById("result-panel").style.display = "";
    }
  } catch (e) {
    showToast("Rerun failed: " + e.message);
  }
}

async function deleteSavedTest(id) {
  if (!window.confirm("Delete this saved test?")) return;
  try {
    await api(`/tests/${id}`, { method: "DELETE" });
    await refreshSavedTests();
  } catch (e) {
    showToast("Delete failed: " + e.message);
  }
}

init();
