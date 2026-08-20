# check 命令金标数据检查实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `check` 命令增加可选的心率/血氧金标数据质量检查，并按默认或指定采样率分别检测范围、非零占比、可配置阈值的阶跃异常和超过 5 秒不变的静止异常。

**Architecture:** CLI 将显式金标列名、采样率、静止秒数和阶跃阈值写入冻结的 `CheckRequest`；API 编排层仅在对应列名被指定时追加检查，并在指定列缺失时沿用现有跳过机制。`DataChecker` 提供一个参数化金标检查方法，返回现有 `CheckResult`，报告层无需新增专用格式。

**Tech Stack:** Python 3.9+, Click, pandas, NumPy, pytest, 现有 `CheckResult`/`FileCheckReport` 报告流水线。

---

### Task 1: 扩展请求参数和 CLI 入口

**Files:**
- Modify: `src/health_tools/api/models.py:492-515`
- Modify: `src/health_tools/commands/check.py:19-130`
- Test: `tests/test_check_sort.py` 或新增 `tests/test_reference_checker.py`

- [ ] **Step 1: Write the failing API/CLI tests**

```python
from pathlib import Path

from click.testing import CliRunner

from health_tools.api.models import CheckRequest
from health_tools.commands.check import check_cmd


def test_check_request_keeps_reference_options():
    request = CheckRequest(
        input_path=Path("data.csv"),
        ref_hr_column="REF_HR",
        ref_spo2_column="REF_SPO2",
        ref_sample_rate=50,
        ref_stale_seconds=3,
        ref_step_threshold=6,
    )
    assert request.ref_hr_column == "REF_HR"
    assert request.ref_spo2_column == "REF_SPO2"
    assert request.ref_sample_rate == 50
    assert request.ref_stale_seconds == 3
    assert request.ref_step_threshold == 6


def test_check_help_lists_reference_options():
    result = CliRunner().invoke(check_cmd, ["--help"])
    assert result.exit_code == 0
    assert "--ref-hr-column" in result.output
    assert "--ref-spo2-column" in result.output
    assert "--ref-sample-rate" in result.output
    assert "--ref-stale-seconds" in result.output
    assert "--ref-step-threshold" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reference_checker.py -q` (or the file containing the tests above)

Expected: FAIL because `CheckRequest` and `check_cmd` do not yet expose the five reference options.

- [ ] **Step 3: Add frozen request fields and Click options**

Add these fields after `timestamp_base_ms` in `CheckRequest`:

```python
ref_hr_column: Optional[str] = None
ref_spo2_column: Optional[str] = None
ref_sample_rate: float = 25.0
ref_stale_seconds: float = 5.0
ref_step_threshold: float = 8.0
```

Add Click options before `--scene-regex` in `commands/check.py`:

```python
@click.option("--ref-hr-column", help="心率金标列名；指定后启用心率金标检查")
@click.option("--ref-spo2-column", help="血氧金标列名；指定后启用血氧金标检查")
@click.option("--ref-sample-rate", type=float, default=25.0, show_default=True, help="金标采样率（Hz）")
@click.option(
    "--ref-stale-seconds",
    type=float,
    default=5.0,
    show_default=True,
    help="金标连续不变判定时长（秒）",
)
@click.option(
    "--ref-step-threshold",
    type=float,
    default=8.0,
    show_default=True,
    help="金标阶跃相邻变化阈值",
)
```

Extend `check_cmd` parameters and pass all five values into `CheckRequest`. Validate positive sample rate/stale seconds and non-negative step threshold in `run_check` so API callers receive the same `RequestValidationError` as CLI callers.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_reference_checker.py -q`

Expected: PASS for request construction and help output.

- [ ] **Step 5: Commit**

```bash
git add src/health_tools/api/models.py src/health_tools/commands/check.py tests/test_reference_checker.py
git commit -m "feat: add reference check options" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 2: 实现金标检测核心算法

**Files:**
- Modify: `src/health_tools/core/checker.py` after `check_agc_changes`
- Test: `tests/test_reference_checker.py`

- [ ] **Step 1: Write failing core tests**

```python
import pandas as pd

from health_tools.core.checker import DataChecker
from health_tools.models.rules import ChipRule


def _checker():
    return DataChecker(ChipRule(chip="gh3036", csv={}, columns=[]))


def test_hr_reference_accepts_inclusive_range_and_nonzero_boundary():
    values = [30] * 70 + [0] * 30
    result = _checker().check_reference_data(
        pd.DataFrame({"REF_HR": values}), "REF_HR", "hr", sample_rate=25, stale_seconds=5
    )
    assert result.name == "心率金标"
    assert result.status == "PASS"


def test_hr_reference_rejects_out_of_range_and_low_nonzero_ratio():
    values = [29, 241] + [0] * 98
    result = _checker().check_reference_data(
        pd.DataFrame({"REF_HR": values}), "REF_HR", "hr", sample_rate=25, stale_seconds=5
    )
    assert result.status == "FAIL"
    assert "范围" in result.summary or "非零" in result.summary


def test_reference_step_and_stale_are_independent():
    values = [80] * 125 + [81] * 10
    result = _checker().check_reference_data(
        pd.DataFrame({"REF_SPO2": values}), "REF_SPO2", "spo2", sample_rate=25, stale_seconds=5, step_threshold=8
    )
    assert result.status == "PASS"

    values = [80] * 126 + [81] * 10
    result = _checker().check_reference_data(
        pd.DataFrame({"REF_SPO2": values}), "REF_SPO2", "spo2", sample_rate=25, stale_seconds=5, step_threshold=8
    )
    assert result.status == "FAIL"

    result = _checker().check_reference_data(
        pd.DataFrame({"REF_SPO2": [80, 89, 90]}), "REF_SPO2", "spo2", step_threshold=8
    )
    assert result.status == "FAIL"


def test_reference_non_numeric_and_missing_column_fail():
    checker = _checker()
    assert checker.check_reference_data(
        pd.DataFrame({"REF_HR": ["bad", 80]}), "REF_HR", "hr"
    ).status == "FAIL"
    assert checker.check_reference_data(pd.DataFrame(), "REF_HR", "hr").status == "FAIL"


def test_reference_step_threshold_is_configurable():
    result = _checker().check_reference_data(
        pd.DataFrame({"REF_HR": [80, 86, 87]}), "REF_HR", "hr", step_threshold=5
    )
    assert result.status == "FAIL"
    result = _checker().check_reference_data(
        pd.DataFrame({"REF_HR": [80, 86, 87]}), "REF_HR", "hr", step_threshold=6
    )
    assert result.status == "PASS"
```

- [ ] **Step 2: Run the core tests to verify failure**

Run: `pytest tests/test_reference_checker.py -q`

Expected: FAIL with missing `DataChecker.check_reference_data`.

- [ ] **Step 3: Implement the minimal detector**

Add a method with this contract:

```python
def check_reference_data(
    self,
    df: pd.DataFrame,
    column: str,
    reference_type: str,
    sample_rate: float = 25.0,
    stale_seconds: float = 5.0,
    step_threshold: float = 8.0,
) -> CheckResult:
```

Use ranges `{"hr": (30.0, 240.0), "spo2": (70.0, 100.0)}`. Convert with `pd.to_numeric(..., errors="coerce")`; count NaN and finite out-of-range values as abnormal. Count zero values separately and require `(total - zero_count) / total * 100 >= 70`. Count adjacent valid pairs whose absolute difference is strictly greater than `step_threshold` as step anomalies. Find the longest consecutive run of equal numeric values with `series.ne(series.shift()).cumsum()`; mark stale when `longest_run > sample_rate * stale_seconds` (strictly greater than 5 seconds). Treat non-finite sample rate/seconds or negative step threshold as a failed result rather than raising from the core method. Return `CheckResult(name="心率金标" if reference_type == "hr" else "血氧金标", passed=not anomalies, status="PASS"/"FAIL", summary=..., details=..., channel_metrics={column: {...}})`.

- [ ] **Step 4: Run core tests and formatting**

Run: `pytest tests/test_reference_checker.py -q` and `black --check src/health_tools/core/checker.py tests/test_reference_checker.py`.

Expected: all focused tests PASS and Black reports no changes.

- [ ] **Step 5: Commit**

```bash
git add src/health_tools/core/checker.py tests/test_reference_checker.py
git commit -m "feat: detect reference data anomalies" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 3: 接入 API 编排、列校验和报告

**Files:**
- Modify: `src/health_tools/api/check_operation.py:39-55,360-480`
- Modify: `src/health_tools/commands/check.py` criteria text and check list help
- Test: `tests/test_reference_checker.py`

- [ ] **Step 1: Write failing integration tests**

```python
def test_run_check_adds_only_explicit_reference_results(tmp_path):
    import pandas as pd
    import pytest
    from health_tools.api.check_operation import run_check
    from health_tools.api.models import CheckRequest
    from health_tools.models.rules import ChipRule

    source = tmp_path / "sample.csv"
    pd.DataFrame({"REF_HR": [80, 81], "REF_SPO2": [98, 99]}).to_csv(source, index=False)
    rule = ChipRule(chip="gh3036", csv={}, columns=[])
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(
            "health_tools.rules.loader.RuleLoader.load_chip_rule", staticmethod(lambda _: rule)
        )
        monkeypatch.setattr(
            "health_tools.utils.csv_handler.CSVHandler.read",
            lambda self, _: (None, pd.read_csv(source)),
        )
        output = tmp_path / "check_report.csv"
        run_check(
            CheckRequest(
                input_path=source,
                chip_name="gh3036",
                checks="ref",
                ref_hr_column="REF_HR",
                ref_spo2_column="REF_SPO2",
                output_path=output,
            )
        )
        report = output.read_text(encoding="utf-8-sig")
        assert "心率金标(结果)" in report
        assert "血氧金标(结果)" in report
    finally:
        monkeypatch.undo()
```

- [ ] **Step 2: Run integration test to verify failure**

Run: `pytest tests/test_reference_checker.py::test_run_check_adds_only_explicit_reference_results -q`

Expected: FAIL because `run_check` rejects `ref` as an unknown check and never calls the detector.

- [ ] **Step 3: Wire the checks**

In `run_check`:

```python
checks = set(value.strip() for value in request.checks.split(",") if value.strip()) if request.checks else {
    "range", "ipd", "frame", "center", "acc", "agc"
}
unknown = checks - {"range", "ipd", "frame", "center", "acc", "agc", "ref"}
```

Validate `request.ref_sample_rate > 0`, `request.ref_stale_seconds > 0`, and `request.ref_step_threshold >= 0`. Extend `_rule_mismatch`/`_check_rule_mismatch` with `ref_hr_column` and `ref_spo2_column`; only require a column when its corresponding option is non-empty. Append results after timestamp checks:

```python
if request.ref_hr_column:
    report.results.append(
        checker.check_reference_data(
            frame,
            request.ref_hr_column,
            "hr",
            request.ref_sample_rate,
            request.ref_stale_seconds,
            request.ref_step_threshold,
        )
    )
if request.ref_spo2_column:
    report.results.append(
        checker.check_reference_data(
            frame,
            request.ref_spo2_column,
            "spo2",
            request.ref_sample_rate,
            request.ref_stale_seconds,
            request.ref_step_threshold,
        )
    )
```

Use a dedicated `ref` check token only to select the family when `--checks` is supplied; explicit reference columns should also activate their checks when `--checks` is omitted. Preserve old default check set and existing report serialization.

- [ ] **Step 4: Verify report and skip behavior**

Run: `pytest tests/test_reference_checker.py -q tests/test_check_sort.py -q`.

Expected: new report columns are present, omitted columns do not create results, missing explicitly requested columns produce `SKIP`, and existing sort tests remain green.

- [ ] **Step 5: Commit**

```bash
git add src/health_tools/api/check_operation.py src/health_tools/commands/check.py tests/test_reference_checker.py
git commit -m "feat: wire reference checks into check command" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 4: 同步命令文档和完整验证

**Files:**
- Modify: `docs/cmd_check.md`
- Modify: `docs/commands.md` only if the check option summary needs navigation text
- Test: `tests/test_documentation.py` if CLI/documentation consistency assertions require updates

- [ ] **Step 1: Update command documentation**

Add the five options to the parameter table, document that explicit column names are required to enable checks, describe HR ranges `30-240`, SpO2 ranges `70-100`, nonzero ratio threshold `70%`, step condition `abs(current - previous) > ref_step_threshold` with default `8`, strict stale condition `run_length > sample_rate * stale_seconds`, defaults `25 Hz` and `5 s`, and add examples:

```bash
ghealth_tool check -i data/ --ref-hr-column REF_HR --ref-spo2-column REF_SPO2
ghealth_tool check -i data/ --ref-hr-column hr_ref --ref-sample-rate 50 --ref-stale-seconds 5
```

- [ ] **Step 2: Run focused and repository checks**

Run:

```bash
python -c "import health_tools; print(health_tools.__file__)"
pytest tests/test_reference_checker.py tests/test_check_sort.py -q
black --check src/ tests/
ruff check src/ tests/
```

Expected: import path points into this workspace; focused tests pass; Black and Ruff report no violations.

- [ ] **Step 3: Run the full test suite**

Run: `pytest`

Expected: PASS with no regressions. If the suite exposes a report-header or API fixture that assumes the old check set, update only that fixture to account for optional reference columns, preserving old behavior when options are absent.

- [ ] **Step 4: Commit documentation and final changes**

```bash
git add docs/cmd_check.md docs/commands.md tests/test_documentation.py
git commit -m "docs: document reference data checks" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

- [ ] **Step 5: Final verification**

Run: `git status --short` and `git log -4 --oneline`.

Expected: working tree clean, with the design and implementation commits visible in history.
