# check Performance Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce redundant per-file work and bound thread scheduling for large `check` batches while preserving check semantics and the `PRIMARY_RULES` anomaly-priority contract.

**Architecture:** Add a file-scoped lazy context around one CSV/DataChecker pair, reuse parsed columns, numeric arrays, timestamp analysis, and sampling positions/results, then replace all-at-once Future submission with a bounded completion-driven scheduler. Keep report construction and priority classification in the main thread.

**Tech Stack:** Python 3.9+, pandas, numpy, `concurrent.futures.ThreadPoolExecutor`, pytest, existing `ExecutionContext` progress/cancellation APIs.

---

### Task 1: Establish regression and instrumentation tests

**Files:**
- Create: `tests/test_check_performance.py`
- Modify: `tests/test_check_sort.py:83-311` only if a focused priority assertion is needed

- [ ] **Step 1: Write baseline tests for priority preservation**

Add tests that call the existing `primary_issue` and `_sort_category` with rows containing multiple failures, asserting the first matching `PRIMARY_RULES` entry wins (for example frame before range, range before ACC, and accuracy mark before AGC/Ipd).

```python
def test_primary_issue_and_sort_category_keep_primary_rules_order():
    row = {
        "帧完整性(结果)": "FAIL",
        "数据范围(结果)": "FAIL",
        "总异常(结果)": "FAIL",
    }
    assert primary_issue(row) == "帧不完整"
    assert _sort_category(row) == "frame"
```

- [ ] **Step 2: Add a deterministic bounded-scheduler test seam**

Create a small test helper or monkeypatchable callback that tracks active calls and maximum active calls. The test must run `run_check` against several small CSV paths with `workers=2`, block each callback briefly, and assert the scheduler never has more than four submitted-but-not-collected tasks. Do not assert wall-clock duration.

- [ ] **Step 3: Add cache-call-count tests**

Monkeypatch the sampling and timestamp helper functions in `health_tools.api.check_operation` and run one file with HR, SpO2, and accuracy enabled. Assert shared sample positions are built once and each distinct `(ref, online, comp, positions)` sample combination is generated once. Add a second case with different reference columns to assert no incorrect cross-column reuse.

- [ ] **Step 4: Run the new tests before implementation**

Run:

```powershell
python -c "import health_tools; print(health_tools.__file__)"
pytest tests/test_check_performance.py tests/test_check_sort.py -q
```

Expected: the priority assertions pass; scheduler/cache assertions fail because the current implementation submits all Futures and repeats sampling.

- [ ] **Step 5: Commit the red tests**

```powershell
git add tests/test_check_performance.py tests/test_check_sort.py
git commit -m "test: cover check caching and bounded concurrency" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 2: Add reusable file-scoped check context

**Files:**
- Modify: `src/health_tools/api/check_operation.py` near `run_check` and its helper imports
- Test: `tests/test_check_performance.py`

- [ ] **Step 1: Define explicit cached data types**

Add private dataclasses/types for a file context and timestamp/sample cache entries. The context must contain `path`, `chip`, `chip_rule`, `frame`, `checker`, resolved data/frame/ACC/IPD/AGC columns, and dictionaries keyed by explicit sampling column/config tuples. Keep these types private to the check operation module.

- [ ] **Step 2: Implement lazy column and numeric accessors**

Move the existing `_rule_mismatch` inputs to context-backed values. Resolve each column family once after CSV loading. Numeric conversion must be lazy and keyed by column tuple; return the same cached pandas/numpy object for subsequent callers in the same file.

- [ ] **Step 3: Route mismatch checks through the context**

Update `_rule_mismatch` or add a context-specific variant that consumes resolved columns. Preserve missing-field order and exact skip reason text. Ensure mismatch returns before any expensive numeric conversion.

- [ ] **Step 4: Route range/frame/center/AGC/IPD/ACC checks through cached inputs**

Add the smallest `DataChecker` interfaces needed to accept pre-resolved columns or arrays. Do not change thresholds, status construction, summaries, or anomaly counting. Keep `PRIMARY_RULES` untouched.

- [ ] **Step 5: Run focused behavior tests**

Run:

```powershell
pytest tests/test_acc_checker.py tests/test_check_accuracy.py tests/test_check_rules.py tests/test_check_performance.py -q
```

Expected: all existing checker semantics pass; only sampling/scheduler tests remain failing.

- [ ] **Step 6: Commit the context refactor**

```powershell
git add src/health_tools/api/check_operation.py src/health_tools/core/checker.py tests/test_check_performance.py
git commit -m "refactor: cache per-file check inputs" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 3: Reuse timestamp analysis and second-sampling results

**Files:**
- Modify: `src/health_tools/api/check_operation.py`
- Modify: `src/health_tools/core/checker.py` only if timestamp parsing needs an exposed analysis result
- Test: `tests/test_check_performance.py`, `tests/test_acc_checker.py`

- [ ] **Step 1: Expose one timestamp analysis result**

Refactor timestamp handling so the context can retain parsed timestamps, interval statistics, status inputs, and predicted sample rate. `check_timestamp_interval` must still return the same `CheckResult`; the context must not parse the timestamp column again when predicting sample rate.

- [ ] **Step 2: Add shared sample-position caching**

Cache `build_sample_positions` by sample rate and online column. Build positions once when reference or accuracy checks need them. Reuse the cached positions for HR, SpO2, accuracy, and evidence generation.

- [ ] **Step 3: Add sample-frame caching with explicit keys**

Cache `sample_check_seconds` by `(ref_column, online_column, comp_column, sample_rate, positions identity/config)`. Return independent frames for different reference columns and reuse only identical column/config combinations.

- [ ] **Step 4: Preserve reference and accuracy result behavior**

Keep HR/SpO2 result names, warning/fail thresholds, abnormal-time metrics, accuracy metrics, and evidence output paths unchanged. Evidence must use an existing compatible sampled frame where possible.

- [ ] **Step 5: Run targeted sampling and report tests**

Run:

```powershell
pytest tests/test_acc_checker.py -q
pytest tests/test_check_accuracy.py tests/test_check_sampling.py tests/test_reference_checker.py tests/test_check_performance.py -q
```

Expected: all tests pass, including call-count assertions.

- [ ] **Step 6: Commit timestamp and sampling reuse**

```powershell
git add src/health_tools/api/check_operation.py src/health_tools/core/checker.py tests/test_check_performance.py
git commit -m "perf: reuse check timestamp and sampling work" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 4: Optimize ACC shared preparation without changing detection semantics

**Files:**
- Modify: `src/health_tools/core/checker.py`
- Modify: `src/health_tools/api/check_operation.py`
- Test: `tests/test_acc_checker.py`, `tests/test_check_performance.py`

- [ ] **Step 1: Add a prepared ACC input path**

Allow `check_acc_anomaly` to receive already-resolved ACC columns, numeric arrays, and display frame IDs from the file context. Keep the existing public call signature compatible by making the prepared input optional.

- [ ] **Step 2: Reuse arrays across all ACC detectors**

Ensure all-zero, static, and cyclic checks consume the same numeric array and frame IDs. Preserve static-before-cyclic masking, single-axis behavior, cycle period bounds, amplitude threshold, XYZ overlap, and deduplicated anomaly indices.

- [ ] **Step 3: Add equivalence tests**

For representative zero, static, cyclic, mixed, short, NaN, and single-axis datasets, compare prepared and unprepared paths field-by-field (`count`, `first_frame`, `max_duration`, `frames`, anomaly ratio, and final status).

- [ ] **Step 4: Run ACC and checker tests**

```powershell
pytest tests/test_acc_checker.py tests/test_check_performance.py -q
```

- [ ] **Step 5: Commit ACC preparation reuse**

```powershell
git add src/health_tools/core/checker.py src/health_tools/api/check_operation.py tests/test_acc_checker.py tests/test_check_performance.py
git commit -m "perf: reuse prepared ACC check inputs" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 5: Replace all-at-once submission with bounded scheduling

**Files:**
- Modify: `src/health_tools/api/check_operation.py`
- Test: `tests/test_check_performance.py`, `tests/test_api_contract.py`

- [ ] **Step 1: Add an effective worker/window calculation**

Validate `request.workers` as today, then derive `effective_workers = min(request.workers, max(1, len(files)))` and `window = max(1, effective_workers * 2)`. Keep empty-file handling and `workers < 1` validation unchanged.

- [ ] **Step 2: Implement incremental Future submission**

Create an iterator over `files`, submit at most `window` paths, consume completed futures with `wait(..., return_when=FIRST_COMPLETED)` or an equivalent completion iterator, and submit one replacement per completed future. Maintain the existing item/report/ACC/IPD/evidence aggregation code in the main thread.

- [ ] **Step 3: Preserve cancellation and exception behavior**

On cancellation or batch-level exception, stop pulling from the iterator, cancel pending futures, and shut down the executor according to the existing policy. A per-file exception must remain an `ItemStatus.FAIL` result and must not prevent replacement submission.

- [ ] **Step 4: Preserve filtering and report order**

Continue applying `_is_failed_check_report` before adding an item/report. Store completed results with their original input index, then sort aggregated items/reports by that index before report generation if the old implementation’s order would otherwise change. Do not alter `PRIMARY_RULES` or report classification.

- [ ] **Step 5: Run concurrency and API tests**

```powershell
pytest tests/test_check_performance.py tests/test_api_contract.py tests/test_cli.py tests/test_check_sort.py -q
```

Expected: bounded-window, cancellation, filtering, output-order, and priority tests pass.

- [ ] **Step 6: Commit bounded scheduling**

```powershell
git add src/health_tools/api/check_operation.py tests/test_check_performance.py tests/test_api_contract.py
git commit -m "perf: bound check thread scheduling" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 6: Document concurrency semantics and add a repeatable benchmark

**Files:**
- Modify: `docs/cmd_check.md`
- Create: `tests/benchmarks/bench_check_performance.py`
- Test: `tests/test_documentation.py` if documentation assertions need extension

- [ ] **Step 1: Document workers behavior**

Explain that `--workers` controls file-level threads, the scheduler keeps a bounded pending window, results and reports remain deterministic, and cancellation stops new submissions. Document that more workers do not guarantee linear speedup for CPU-heavy checks.

- [ ] **Step 2: Add benchmark dataset generation and runner**

Create a script that generates deterministic small CSV files and measures 100, 500, and 1000 file batches for workers 1, 2, 4, and 8. Report elapsed time, peak RSS when available, and monkeypatch/instrumentation counters for CSV reads, timestamp parsing, sample-position creation, second sampling, and ACC preparation. The script must not write into production test fixtures.

- [ ] **Step 3: Add documentation coverage**

Extend `tests/test_documentation.py` to assert the new workers/scheduling statements are present.

- [ ] **Step 4: Run documentation and benchmark smoke checks**

```powershell
pytest tests/test_documentation.py -q
python tests/benchmarks/bench_check_performance.py --files 10 --workers 1,2
```

Expected: documentation tests pass and the smoke benchmark prints measurements without modifying repository fixtures.

- [ ] **Step 5: Commit docs and benchmark**

```powershell
git add docs/cmd_check.md tests/benchmarks/bench_check_performance.py tests/test_documentation.py
git commit -m "docs: describe bounded check concurrency" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 7: Full verification and performance comparison

**Files:**
- Modify only if verification exposes a regression; otherwise no new files

- [ ] **Step 1: Verify local package resolution**

```powershell
python -c "import health_tools; print(health_tools.__file__)"
```

Expected: path points inside `E:\Code\Python\health_tools\src\health_tools`.

- [ ] **Step 2: Run the complete check-related suite**

```powershell
pytest tests/test_acc_checker.py tests/test_check_accuracy.py tests/test_check_rules.py tests/test_check_sampling.py tests/test_check_sort.py tests/test_reference_checker.py tests/test_check_performance.py tests/test_api_contract.py tests/test_cli.py -q
```

Expected: exit code 0 with no failures.

- [ ] **Step 3: Run repository quality checks**

```powershell
black --check src/ tests/
ruff check src/ tests/
mypy src/
```

Expected: all commands exit 0. If pytest auto-loads an unavailable Qt plugin, rerun with `pytest -p no:pytest-qt` and record that environment handling in the final report.

- [ ] **Step 4: Run full tests**

```powershell
pytest -q
```

Expected: exit code 0, or a documented environment-only Qt plugin failure with the prescribed disabled-plugin rerun result.

- [ ] **Step 5: Compare benchmark results**

Run the benchmark on the same generated dataset before and after optimization, record timings and call-count reductions in the task notes, and verify `workers=1` and `workers=4` produce equivalent report rows and priority categories.

- [ ] **Step 6: Commit any final verification-only fixes**

```powershell
git add <explicitly-listed-files>
git commit -m "fix: address check optimization regressions" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

