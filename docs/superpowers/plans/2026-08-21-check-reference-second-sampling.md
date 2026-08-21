# Check 金标秒采样与异常证据 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `check` 对原始高频 CSV 的准确度计算和金标异常检查统一按采样率抽取每秒第一帧，并可把金标异常文件导出为 `time,ref,online,comp` 四列证据 CSV。

**Architecture:** 在 `core/check_sampling.py` 建立唯一的原始数据秒采样位置计算和列抽取函数：从 Online 首个有限非零值所在行开始，按整数采样率步进生成位置；HR、SpO2、准确度和证据列都使用同一组位置，但各自传入对应的 Ref 列。`run_check` 每个原始 CSV 只计算一次位置，再分别构造金标、准确度和证据视图；offline/evaluate 不接入该函数，保持已按秒整理的数据口径。证据输出目录是运行上下文，仅由 CLI/API 指定，不进入 YAML。

**Tech Stack:** Python 3.9+、Click、pandas、dataclasses、pytest、Black、Ruff、mypy。

---

## 已确认行为

1. 原始 `check` 数据按 `reference.sample_rate` / `--ref-sample-rate` 抽取：25 Hz 时步长为 25 行。
2. 起点是 Online 列首个 **finite 且非 0** 值所在行；抽样索引为 `start, start + rate, start + 2 * rate, ...`。
3. TimeStamp、Ref、Online、Comp 必须取相同原始行，不允许各列独立找起点或填充。
4. `time` 使用原始 `TimeStamp` 值，不换算成 `0,1,2...` 秒序号。
5. 秒采样后的数据同时用于：
   - HR/SpO2 金标范围、非零占比、阶跃和连续静止检查；
   - Online vs Ref、Comp vs Ref 准确度；
   - 准确度标定和主要异常项。
6. 金标检查收到的已是 1 Hz 数据，因此连续静止阈值直接使用 `stale_seconds` 个样本；摘要和 compact report 中的阈值仍表达为秒。
7. offline 跑库准确度不调用秒采样函数，现有 `calculate_offline_accuracy` 行为不变。
8. 只有启用 `--reference-detail-output` 时才生成证据文件；该路径不写入 YAML。
9. 对任一 `心率金标(结果)=FAIL` 或 `血氧金标(结果)=FAIL` 的文件，输出秒采样后的四列 CSV：`time,ref,online,comp`。
10. 输出目录镜像输入相对目录，文件名保持原名；例如 `场景/a.csv` 输出到 `<detail>/场景/a.csv`，避免同名文件互相覆盖。
11. `comp_column` 未配置或原文件缺少 Comp 列时仍生成 `comp` 列，值为空；TimeStamp、Ref 或 Online 缺列时沿用 check 的列结构校验并跳过该文件。
12. Online 没有 finite 非零值时，秒采样结果为空：准确度样本数为 0，金标检查返回明确 FAIL“Online 列没有有效非零起点”，启用证据输出时写出只有表头的 CSV。
13. `sample_rate` 表示每秒帧数，秒采样要求为正整数；`25.0` 合法，`25.5` 在 CLI/API/规则验证阶段拒绝，避免静默取整导致错位。

## CLI 与 API

新增 CLI：

```text
--reference-detail-output PATH  输出金标异常文件的秒采样四列证据 CSV
```

新增 API 字段：

```python
@dataclass(frozen=True)
class CheckRequest:
    reference_detail_output: Optional[Path] = None
```

新增结果字段，便于调用方发现生成物：

```python
@dataclass(frozen=True)
class CheckResult:
    reference_detail_paths: Tuple[Path, ...] = ()
```

`reference_detail_output` 是本次执行路径，与 `input/output/sort/report/workers` 一样禁止写入 check YAML。

## 文件结构

- Create: `src/health_tools/core/check_sampling.py`：原始 check 数据的秒采样位置、按位置抽取和四列证据构建。
- Create: `tests/test_check_sampling.py`：起点、步长、同一行对齐、缺 Comp、空 Online 和采样率验证。
- Modify: `src/health_tools/core/checker.py`：金标检查支持已秒采样数据，并保持指标单位清晰。
- Modify: `src/health_tools/core/check_accuracy.py`：只消费调用方传入的秒采样 DataFrame，不自行再次抽样。
- Modify: `src/health_tools/api/models.py`：增加证据输出请求路径和结果路径。
- Modify: `src/health_tools/api/check_operation.py`：每文件只采样一次，复用于金标、准确度和证据导出。
- Modify: `src/health_tools/commands/check.py`：增加 CLI 参数并传入 `CheckRequest`。
- Modify: `src/health_tools/rules/validator.py`：`reference.sample_rate` 收紧为正整数数值。
- Modify: `tests/test_reference_checker.py`：1 Hz 金标检查和端到端证据输出测试。
- Modify: `tests/test_check_accuracy.py`：准确度使用秒采样数据的集成测试。
- Modify: `tests/test_check_rules.py`、`tests/test_api_contract.py`：规则/API 契约测试。
- Modify: `docs/cmd_check.md`、`docs/rules.md`、`.agents/skills/use-ghealth-tool/references/commands.md`、`.agents/skills/use-ghealth-tool/references/workflows.md`：同步用户文档和技能事实来源。

---

### Task 1: 建立唯一秒采样函数

**Files:**
- Create: `src/health_tools/core/check_sampling.py`
- Create: `tests/test_check_sampling.py`

- [ ] **Step 1: 写失败测试，固定 Online 起点、25 帧步长和同行对齐**

```python
import pandas as pd

from health_tools.core.check_sampling import build_sample_positions, sample_check_seconds


def test_sample_check_seconds_starts_at_first_nonzero_online_and_keeps_rows_aligned():
    frame = pd.DataFrame(
        {
            "TimeStamp": range(1000, 1060),
            "REF": range(2000, 2060),
            "ONLINE": [0, 0, 0, 80] + list(range(81, 137)),
            "COMP": range(3000, 3060),
        }
    )

    positions = build_sample_positions(frame, sample_rate=25, online_column="ONLINE")
    sampled = sample_check_seconds(
        frame,
        positions=positions,
        timestamp_column="TimeStamp",
        ref_column="REF",
        online_column="ONLINE",
        comp_column="COMP",
    )

    assert sampled.index.tolist() == [3, 28, 53]
    assert sampled["time"].tolist() == [1003, 1028, 1053]
    assert sampled["ref"].tolist() == [2003, 2028, 2053]
    assert sampled["online"].tolist() == [80, 105, 130]
    assert sampled["comp"].tolist() == [3003, 3028, 3053]
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `pytest tests/test_check_sampling.py::test_sample_check_seconds_starts_at_first_nonzero_online_and_keeps_rows_aligned -q`

Expected: FAIL，`health_tools.core.check_sampling` 不存在。

- [ ] **Step 3: 实现最小秒采样 API**

```python
"""check 原始数据按秒抽样。"""

from typing import Optional

import numpy as np
import pandas as pd


def normalize_frame_rate(sample_rate: float) -> int:
    value = float(sample_rate)
    if not np.isfinite(value) or value <= 0 or not value.is_integer():
        raise ValueError("sample_rate 必须是正整数")
    return int(value)


def build_sample_positions(
    frame: pd.DataFrame,
    *,
    sample_rate: float,
    online_column: str,
) -> np.ndarray:
    """返回从首个有效非零 Online 行开始的原始位置。"""
    rate = normalize_frame_rate(sample_rate)
    if online_column not in frame.columns:
        raise ValueError("缺少秒采样列: " + online_column)
    online = pd.to_numeric(frame[online_column], errors="coerce")
    ready = np.isfinite(online.to_numpy(dtype=float, na_value=np.nan)) & online.ne(0).to_numpy()
    starts = np.flatnonzero(ready)
    if starts.size == 0:
        return np.empty(0, dtype=np.int64)
    return np.arange(starts[0], len(frame), rate, dtype=np.int64)


def sample_check_seconds(
    frame: pd.DataFrame,
    *,
    positions: np.ndarray,
    timestamp_column: str,
    ref_column: str,
    online_column: str,
    comp_column: Optional[str],
) -> pd.DataFrame:
    required = (timestamp_column, ref_column, online_column)
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError("缺少秒采样列: " + ", ".join(missing))

    columns = {
        "time": frame[timestamp_column],
        "ref": frame[ref_column],
        "online": frame[online_column],
        "comp": (
            frame[comp_column]
            if comp_column and comp_column in frame.columns
            else pd.Series(pd.NA, index=frame.index, dtype="object")
        ),
    }
    evidence = pd.DataFrame(columns, index=frame.index)
    if positions.size == 0:
        return evidence.iloc[:0]
    return evidence.iloc[positions]
```

- [ ] **Step 4: 补充缺 Comp、首个 Online 为 NaN/Inf/0、Online 全无效测试**

```python
def test_sample_check_seconds_keeps_empty_comp_column_when_unconfigured():
    frame = pd.DataFrame({"TimeStamp": [0, 40], "REF": [80, 81], "ONLINE": [80, 81]})
    positions = build_sample_positions(frame, sample_rate=1, online_column="ONLINE")
    sampled = sample_check_seconds(
        frame,
        positions=positions,
        timestamp_column="TimeStamp",
        ref_column="REF",
        online_column="ONLINE",
        comp_column=None,
    )
    assert sampled.columns.tolist() == ["time", "ref", "online", "comp"]
    assert sampled["comp"].isna().all()


def test_sample_check_seconds_returns_header_only_without_nonzero_online():
    frame = pd.DataFrame(
        {"TimeStamp": [0, 40, 80], "REF": [80, 81, 82], "ONLINE": [0, float("nan"), 0]}
    )
    positions = build_sample_positions(frame, sample_rate=25, online_column="ONLINE")
    sampled = sample_check_seconds(
        frame,
        positions=positions,
        timestamp_column="TimeStamp",
        ref_column="REF",
        online_column="ONLINE",
        comp_column=None,
    )
    assert sampled.empty
    assert sampled.columns.tolist() == ["time", "ref", "online", "comp"]
```

- [ ] **Step 5: 补充采样率严格校验测试**

```python
import pytest

from health_tools.core.check_sampling import normalize_frame_rate


@pytest.mark.parametrize("value", [0, -1, 25.5, float("nan"), float("inf")])
def test_normalize_frame_rate_rejects_non_positive_or_fractional_values(value):
    with pytest.raises(ValueError, match="正整数"):
        normalize_frame_rate(value)


def test_normalize_frame_rate_accepts_integer_float():
    assert normalize_frame_rate(25.0) == 25
```

- [ ] **Step 6: 运行 Task 1 测试**

Run: `pytest tests/test_check_sampling.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add src/health_tools/core/check_sampling.py tests/test_check_sampling.py
git commit -m "feat: 增加 check 原始数据秒采样" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 2: 让金标检查消费 1 Hz 数据

**Files:**
- Modify: `src/health_tools/core/checker.py`
- Modify: `tests/test_reference_checker.py`

- [ ] **Step 1: 写失败测试，证明 25 帧重复只代表 1 秒**

```python
def test_reference_check_uses_second_samples_for_stale_seconds():
    second_frame = pd.DataFrame({"REF_HR": [80, 80, 80, 80, 80, 81]})

    result = _checker().check_reference_data(
        second_frame,
        "REF_HR",
        "hr",
        sample_rate=1,
        stale_seconds=5,
    )

    assert result.status == "PASS"

    result = _checker().check_reference_data(
        pd.DataFrame({"REF_HR": [80] * 6 + [81]}),
        "REF_HR",
        "hr",
        sample_rate=1,
        stale_seconds=5,
    )
    assert result.status == "FAIL"
    assert "最长静止 6 秒" in result.summary
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `pytest tests/test_reference_checker.py::test_reference_check_uses_second_samples_for_stale_seconds -q`

Expected: FAIL，现有摘要仍使用“帧”，metrics 阈值仍暴露为帧数。

- [ ] **Step 3: 将金标检查的静止指标改为秒样本语义**

`check_reference_data()` 保留 `sample_rate` 参数以兼容其他调用方，但 `run_check` 传入秒采样数据时必须传 `sample_rate=1.0`。调整摘要和 metrics：

```python
stale_limit = sample_rate * stale_seconds
stale = longest_run > stale_limit

metrics = {
    column: {
        # 既有字段保留，避免 compact report/API 破坏
        "longest_static_frames": float(longest_run),
        "static_frame_threshold": float(stale_limit),
        # 新字段明确真实单位
        "longest_static_seconds": float(longest_run / sample_rate),
        "static_second_threshold": float(stale_seconds),
    }
}

if stale:
    reasons.append(
        f"最长静止 {longest_run / sample_rate:g} 秒，超过 {stale_seconds:g} 秒"
    )
```

- [ ] **Step 4: 写测试确认 0 不参与范围、阶跃和连续静止**

```python
def test_reference_check_zeros_only_affect_nonzero_ratio():
    result = _checker().check_reference_data(
        pd.DataFrame({"REF_HR": [80, 80, 0, 80, 80, 81]}),
        "REF_HR",
        "hr",
        sample_rate=1,
        stale_seconds=2,
    )
    assert result.status == "PASS"
    metric = result.channel_metrics["REF_HR"]
    assert metric["longest_static_seconds"] == 2
    assert metric["step_count"] == 0
```

- [ ] **Step 5: 运行金标检查测试**

Run: `pytest tests/test_reference_checker.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add src/health_tools/core/checker.py tests/test_reference_checker.py
git commit -m "fix: 按秒确认 check 金标异常" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 3: 在 run_check 中共享秒采样数据

**Files:**
- Modify: `src/health_tools/api/check_operation.py`
- Modify: `src/health_tools/core/check_accuracy.py`
- Modify: `tests/test_check_accuracy.py`
- Modify: `tests/test_reference_checker.py`

- [ ] **Step 1: 写失败集成测试，固定金标与准确度使用相同秒点**

```python
def test_check_reference_and_accuracy_share_online_aligned_second_samples(tmp_path):
    frame = pd.DataFrame(
        {
            "TimeStamp": range(60),
            "REF": [80] * 60,
            "ONLINE": [0, 0, 0] + [80] * 57,
            "COMP": [0, 0, 0] + [81] * 57,
        }
    )
    source = tmp_path / "input" / "sample.csv"
    source.parent.mkdir()
    frame.to_csv(source, index=False)
    result = run_check(
        CheckRequest(
            input_path=source.parent,
            checks="ref,accuracy",
            timestamp_column="TimeStamp",
            ref_hr_column="REF",
            ref_sample_rate=25,
            ref_stale_seconds=5,
            accuracy_enabled=True,
            accuracy_ref_column="REF",
            accuracy_online_column="ONLINE",
            accuracy_comp_column="COMP",
        )
    )

    report = result.reports[0]
    assert report.accuracy.online["samples"] == 3
    assert report.accuracy.comp["samples"] == 3
    assert report.reference.channel_metrics["REF"]["total_count"] == 3
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `pytest tests/test_check_accuracy.py::test_check_reference_and_accuracy_share_online_aligned_second_samples -q`

Expected: FAIL，`run_check` 尚未建立共享预处理路径。

- [ ] **Step 3: 在 `check_one()` 中只计算一次秒采样位置**

在 CSV 读取和 `_rule_mismatch()` 通过后，根据金标或准确度是否启用决定是否采样：

```python
reference_enabled = (request.checks is None or "ref" in checks) and bool(
    request.ref_hr_column or request.ref_spo2_column
)
sampling_needed = reference_enabled or request.accuracy_enabled
sample_positions = None
if sampling_needed:
    sample_positions = build_sample_positions(
        frame,
        sample_rate=request.ref_sample_rate,
        online_column=request.accuracy_online_column or "ALGO_RESULT0",
    )
```

不要修改 `frame`；range/frame/center/agc/ipd/acc/timestamp 继续使用原始逐帧数据。

- [ ] **Step 4: 金标和准确度使用共享位置构造各自视图**

```python
reference_frame = sample_check_seconds(
    frame,
    positions=sample_positions,
    timestamp_column=request.timestamp_column or "TimeStamp",
    ref_column=request.ref_hr_column,
    online_column=request.accuracy_online_column or "ALGO_RESULT0",
    comp_column=request.accuracy_comp_column,
)
reference_frame = reference_frame.rename(columns={"ref": request.ref_hr_column})
checker.check_reference_data(
    reference_frame,
    request.ref_hr_column,
    "hr",
    sample_rate=1.0,
    stale_seconds=request.ref_stale_seconds,
    step_threshold=request.ref_step_threshold,
)

accuracy_frame = sample_check_seconds(
    frame,
    positions=sample_positions,
    timestamp_column=request.timestamp_column or "TimeStamp",
    ref_column=accuracy_rule.ref_column,
    online_column=accuracy_rule.online_column,
    comp_column=accuracy_rule.comp_column,
)
accuracy_frame = accuracy_frame.rename(
    columns={
        "ref": accuracy_rule.ref_column,
        "online": accuracy_rule.online_column,
        "comp": accuracy_rule.comp_column or "__unused_comp__",
    }
)
calculate_check_accuracy(accuracy_frame, accuracy_rule)
```

实现时用小型 helper 构造映射，避免 `None` 成为列名；不能在 `calculate_check_accuracy()` 内再次抽样。

- [ ] **Step 5: 明确 Online 无非零起点行为**

在金标检查前检测 `sample_positions.size == 0`（各列视图都为空）：

```python
if sample_positions.size == 0:
    reference_result = CheckItemResult(
        "心率金标",
        False,
        "Online 列没有有效非零起点，无法按秒检查金标",
        status="FAIL",
    )
else:
    reference_result = checker.check_reference_data(...)
```

准确度继续由 `calculate_check_accuracy()` 返回 `online={"samples": 0}`、`comp=None`，不得用原始全帧数据兜底。

- [ ] **Step 6: 增加端到端测试，证明其他逐帧检查未被降采样**

构造 50 帧 CSV，其中帧号在非采样行丢失；运行 `run_check()` 后断言：

```python
assert report_accuracy_samples == 2
assert report_row["帧完整性(结果)"] == "FAIL"
```

这证明只有 reference/accuracy 使用秒采样，frame 等检查仍读取原始数据。

- [ ] **Step 7: 运行目标测试**

Run: `pytest tests/test_check_sampling.py tests/test_check_accuracy.py tests/test_reference_checker.py tests/test_check_sort.py -q`

Expected: PASS。

- [ ] **Step 8: 提交**

```powershell
git add src/health_tools/api/check_operation.py src/health_tools/core/check_accuracy.py tests/test_check_accuracy.py tests/test_reference_checker.py
git commit -m "feat: 统一 check 金标与准确度秒采样" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 4: 增加金标异常四列证据输出

**Files:**
- Modify: `src/health_tools/api/models.py`
- Modify: `src/health_tools/api/check_operation.py`
- Modify: `src/health_tools/commands/check.py`
- Modify: `tests/test_reference_checker.py`
- Modify: `tests/test_api_contract.py`

- [ ] **Step 1: 写失败 API 测试，固定目录结构和四列格式**

```python
def test_run_check_writes_reference_failure_evidence_with_relative_directory(tmp_path):
    input_dir = tmp_path / "input"
    source = input_dir / "walk" / "same.csv"
    write_raw_check_csv(source, ref=[80] * 151, online=[80] * 151, comp=[81] * 151)
    detail_dir = tmp_path / "reference_details"

    result = run_check(
        CheckRequest(
            input_path=input_dir,
            checks="ref",
            timestamp_column="TimeStamp",
            ref_hr_column="REF",
            ref_sample_rate=25,
            ref_stale_seconds=5,
            accuracy_enabled=True,
            accuracy_ref_column="REF",
            accuracy_online_column="ONLINE",
            accuracy_comp_column="COMP",
            reference_detail_output=detail_dir,
        )
    )

    evidence = detail_dir / "walk" / "same.csv"
    assert evidence in result.reference_detail_paths
    assert pd.read_csv(evidence).columns.tolist() == ["time", "ref", "online", "comp"]
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `pytest tests/test_reference_checker.py::test_run_check_writes_reference_failure_evidence_with_relative_directory -q`

Expected: FAIL，`CheckRequest` 不接受 `reference_detail_output`。

- [ ] **Step 3: 扩展请求和结果模型**

```python
@dataclass(frozen=True)
class CheckRequest:
    reference_detail_output: Optional[Path] = None


@dataclass(frozen=True)
class CheckResult:
    reference_detail_paths: Tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reference_detail_paths",
            tuple(Path(path) for path in self.reference_detail_paths),
        )
```

- [ ] **Step 4: 在单文件结果中暂存证据 DataFrame**

扩展 `check_one()` 返回值为包含 `reference_evidence` 的内部结果对象或第五项 tuple。仅当 reference 检查结果中至少一个 `status == "FAIL"` 时保留按共享位置抽取的四列证据；WARNING/PASS 不导出。

```python
reference_failed = any(
    result.name in {"心率金标", "血氧金标"} and result.status == "FAIL"
    for result in report.results
)
reference_evidence = evidence_frame if reference_failed else None
```

- [ ] **Step 5: 在并行处理结束后集中写文件**

主线程按输入相对路径写出，避免多个 worker 创建同一目录：

```python
detail_paths = []
if request.reference_detail_output is not None:
    for source, evidence in reference_details.items():
        relative = Path(_relative_path(source, base))
        destination = request.reference_detail_output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        evidence.to_csv(destination, index=False, encoding="utf-8-sig")
        detail_paths.append(destination)
        artifacts.append(destination)
```

输出目录存在时允许复用，但单个目标文件已存在必须抛出 `RequestValidationError`，不得静默覆盖用户文件。

- [ ] **Step 6: 增加边界测试**

覆盖：

```python
def test_reference_detail_is_not_written_for_passed_reference(...): ...
def test_reference_detail_keeps_blank_comp_column_when_comp_is_missing(...): ...
def test_reference_detail_writes_header_only_when_online_has_no_nonzero_start(...): ...
def test_reference_detail_does_not_overwrite_existing_file(...): ...
def test_reference_detail_mirrors_relative_paths_for_duplicate_names(...): ...
```

- [ ] **Step 7: 增加 CLI 参数并验证透传**

```python
@click.option(
    "--reference-detail-output",
    type=click.Path(path_type=Path),
    help="输出金标异常文件的秒采样 time/ref/online/comp CSV",
)
```

CLI 测试 monkeypatch `run_check`，断言：

```python
assert captured["request"].reference_detail_output == tmp_path / "details"
```

- [ ] **Step 8: 运行 API/CLI 测试**

Run: `pytest tests/test_reference_checker.py tests/test_api_contract.py tests/test_check_rules.py -q`

Expected: PASS。

- [ ] **Step 9: 提交**

```powershell
git add src/health_tools/api/models.py src/health_tools/api/check_operation.py src/health_tools/commands/check.py tests/test_reference_checker.py tests/test_api_contract.py tests/test_check_rules.py
git commit -m "feat: 导出 check 金标异常对比数据" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 5: 收紧规则验证且保持 offline 不变

**Files:**
- Modify: `src/health_tools/rules/validator.py`
- Modify: `tests/test_check_rules.py`
- Modify: `tests/test_offline.py`
- Modify: `tests/test_evaluate.py`

- [ ] **Step 1: 写失败规则测试，拒绝小数帧率**

```python
def test_check_rule_reference_sample_rate_must_be_positive_integer():
    errors = RuleValidator.validate(
        {
            "version": "1.0",
            "reference": {"sample_rate": 25.5},
            "accuracy": {"enabled": False},
        },
        "check",
    )
    assert "reference.sample_rate 必须是正整数" in errors
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `pytest tests/test_check_rules.py::test_check_rule_reference_sample_rate_must_be_positive_integer -q`

Expected: FAIL，现有 validator 接受任意非负有限数。

- [ ] **Step 3: 仅收紧 check reference.sample_rate**

增加专用 helper，不能修改 evaluate/offline 的通用规则：

```python
@staticmethod
def _validate_positive_integer(config: dict, key: str, label: str) -> List[str]:
    value = config.get(key)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) <= 0
        or not float(value).is_integer()
    ):
        return [f"{label} 必须是正整数"]
    return []
```

- [ ] **Step 4: 添加 offline/evaluate 防回归测试**

测试必须证明：

```python
def test_offline_accuracy_does_not_call_check_second_sampler(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "health_tools.core.check_sampling.sample_check_seconds",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("offline 不应秒采样")),
    )
    assert calculate_offline_accuracy(build_offline_result(tmp_path)) is not None
```

evaluate 同样运行现有准确度用例，确认输出样本数未被除以采样率。

- [ ] **Step 5: 运行规则和防回归测试**

Run: `pytest tests/test_check_rules.py tests/test_offline.py tests/test_evaluate.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add src/health_tools/rules/validator.py tests/test_check_rules.py tests/test_offline.py tests/test_evaluate.py
git commit -m "fix: 校验 check 秒采样频率" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 6: 更新文档、示例规则和技能参考

**Files:**
- Modify: `docs/cmd_check.md`
- Modify: `docs/rules.md`
- Modify: `.agents/skills/use-ghealth-tool/references/commands.md`
- Modify: `.agents/skills/use-ghealth-tool/references/workflows.md`
- Modify: `tests/test_documentation.py`

- [ ] **Step 1: 写失败文档测试**

```python
def test_check_docs_cover_second_sampling_and_reference_evidence():
    command = Path("docs/cmd_check.md").read_text(encoding="utf-8")
    workflow = Path(
        ".agents/skills/use-ghealth-tool/references/workflows.md"
    ).read_text(encoding="utf-8")
    for token in (
        "--reference-detail-output",
        "Online 首个有限非零值",
        "每 25 帧第一帧",
        "time,ref,online,comp",
        "offline 不重复抽样",
    ):
        assert token in command + workflow
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `pytest tests/test_documentation.py::test_check_docs_cover_second_sampling_and_reference_evidence -q`

Expected: FAIL，缺少新增行为说明。

- [ ] **Step 3: 更新 `docs/cmd_check.md`**

写清：

- `--reference-detail-output` 是运行路径，不进入 YAML；
- 25 Hz 示例索引为 Online 首个非零行、`+25`、`+50`；
- TimeStamp/Ref/Online/Comp 同行抽取；
- 秒采样只影响 reference/accuracy，逐帧质量检查不变；
- 金标异常证据目录结构、四列格式和不覆盖规则；
- Online 无有效非零起点时的 FAIL/空证据行为。

- [ ] **Step 4: 更新 `docs/rules.md`**

把 `reference.sample_rate` 定义改为“原始 check CSV 每秒帧数，必须为正整数”；明确它同时驱动金标与准确度秒采样。完整 YAML 不新增证据目录字段。

- [ ] **Step 5: 更新技能参考**

命令参考增加参数；工作流增加：

```bash
ghealth_tool check -i data -r check.yaml \
  --reference-detail-output reference_details
```

并提醒 offline 结果已经按秒整理，不应再应用原始 check 抽样。

- [ ] **Step 6: 运行文档测试**

Run: `pytest tests/test_documentation.py tests/test_check_rules.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add docs/cmd_check.md docs/rules.md .agents/skills/use-ghealth-tool/references/commands.md .agents/skills/use-ghealth-tool/references/workflows.md tests/test_documentation.py
git commit -m "docs: 说明 check 金标秒采样与证据输出" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 7: 用真实 GH3036 样本验证并全量审计

**Files:**
- Verify only

- [ ] **Step 1: 确认工作区导入**

Run: `python -c "import health_tools; print(health_tools.__file__)"`

Expected: 当前仓库 `src/health_tools/__init__.py`。

- [ ] **Step 2: 验证 check 规则**

由于 `validate` 从路径推断类型，自定义规则应放在 `rules/check/` 语义路径或通过 Python API 显式指定类型：

```powershell
@'
from pathlib import Path
import yaml
from health_tools.rules.validator import RuleValidator

path = Path(r"test_data/data_gh3036_offline/check_moto.yaml")
errors = RuleValidator.validate(yaml.safe_load(path.read_text(encoding="utf-8")), "check")
assert not errors, errors
'@ | python -
```

Expected: 无错误。

- [ ] **Step 3: 用复制数据运行真实 check**

不得对 `fail_category` 原目录直接递归执行，因为里面包含旧报告和 `analysis_*` 派生 CSV。使用当前已复制的纯输入目录或重新复制 77 个源文件：

```powershell
ghealth_tool check \
  -i test_data/data_gh3036_offline/fail_category_check_input_20260821 \
  -r test_data/data_gh3036_offline/check_moto.yaml \
  -o test_data/data_gh3036_offline/fail_category_check_report_seconds.csv \
  --reference-detail-output test_data/data_gh3036_offline/reference_details_seconds
```

Expected:

- 77 个文件处理成功；
- Online/Comp 准确度样本数约为原来的 `1/25`；
- 正常的每秒 25 帧重复不再直接触发 5 秒静止 FAIL；
- 所有金标 FAIL 文件都有对应四列证据 CSV；
- 证据 CSV 的第一行等于 Online 首个非零原始行，后续原始行号相差 25。

- [ ] **Step 4: 运行目标测试**

Run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
pytest tests/test_check_sampling.py tests/test_check_accuracy.py tests/test_reference_checker.py tests/test_check_rules.py tests/test_api_contract.py -q
```

Expected: PASS。

- [ ] **Step 5: 运行全量质量检查**

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
pytest -q
black --check src/ tests/
ruff check src/ tests/
mypy src/
git diff --check
```

Expected: 全部通过；既有 NumPy correlation warning 可记录，不视为本功能失败。

- [ ] **Step 6: 审计提交和工作区**

```powershell
git status --short
git log --oneline -7
```

Expected: 无未提交源码/文档；测试数据报告保持未跟踪或按仓库约定处理，不混入功能提交；每个提交均含规定的 `Co-Authored-By` trailer。

## 自审结论

- 需求覆盖：Online 起点、按采样率取每组第一帧、原始 TimeStamp、同一行四列、金标检查、准确度、异常证据目录和 offline 不处理均有明确任务。
- 边界明确：Comp 缺失、Online 无起点、非整数采样率、同名文件、已有目标文件和逐帧检查不降采样均有测试。
- 单一事实来源：秒采样集中在 `core/check_sampling.py`，`run_check` 每文件只调用一次，reference/accuracy/evidence 共享结果。
- YAML 边界不变：只保存 `reference.sample_rate` 业务语义，证据输出路径仍由 CLI/API 外部输入。
