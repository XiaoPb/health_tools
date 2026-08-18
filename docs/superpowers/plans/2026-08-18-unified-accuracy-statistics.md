# 统一准确度统计口径 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 evaluate、classify、offline、PSD plot 和 analyze 的准确度统计共享同一套阈值比较、全零列禁用、首尾零填充裁剪与加权汇总规则。

**Architecture:** 在 `utils/accuracy.py` 建立唯一的准确度预处理与阈值计算入口：先禁用没有有限非零值的列，再以“所有启用列均为有限非零值”的首个和最后一个行为共享边界，统一裁剪所有列；区间内部的 `0` 保留。所有命令通过统一的 API 字段和 Click 选项传递阈值及 strict/inclusive 模式，各业务模块只负责选择比较对象和组织报告，不再自行实现 `within_N`。

**Tech Stack:** Python 3.9+、NumPy、pandas、Click、pytest、Black、Ruff、mypy

---

## 已确认统计口径

1. 未被规则显式配置且命令行未覆盖时，固定阈值默认使用 `(5, 10, 15)`。
2. 默认严格比较：`abs(reference - prediction) < threshold`；传入 inclusive 参数后使用 `<=`。
3. `within_N`、规则中 `{name, value}` 的绝对阈值和 `{name, percent}` 的百分比阈值都遵循同一个 strict/inclusive 开关。
4. 一列没有任何 `isfinite(value) and value != 0` 的样本时视为禁用列。禁用列不参与边界计算、不产生比较结果，也不进入分类或总计。
5. 对剩余启用列构造全局边界：

```python
ready = np.logical_and.reduce(
    [np.isfinite(values[name]) & (values[name] != 0) for name in active_columns]
)
start = np.flatnonzero(ready)[0]
end = np.flatnonzero(ready)[-1] + 1
```

   所有列统一切片到 `[start:end]`。这等价于删除“任意启用列仍为 `0`/非有限值”的连续首段和尾段。
6. 共享区间内部的 `0` 是正常样本，必须保留并参与误差统计；只对当前比较双方的 `NaN/Inf` 做成对过滤。
7. offline/PSD 中 Polar 启用时，分别统计 Offline、Online、Comp 与 Polar；某算法列禁用时只省略该比较。Polar 禁用时，仅在 Online 和 Offline 都启用时回退到 `Online vs Offline`。
8. 每个文件先独立裁剪。分类平均、版本汇总和 TOTAL 必须使用各比较自己的有效样本数加权，不能用 Offline 的样本数替代 Online/Comp 的权重。
9. 规则已显式声明的阈值保持兼容：HR evaluate 继续默认 `5/10/15`，SpO2 evaluate 继续默认 `3/6/9`，`spo2_posture.yaml` 的 `within_0.5`、`within_10_percent` 等自定义项继续存在。只有显式传入 `--accuracy-thresholds` 时才替换规则 `methods` 中的固定 `within_N` 集合，非 `within_N` 指标及命名自定义阈值保留。

## 公共参数

五个 request 都增加：

```python
accuracy_thresholds: Optional[Tuple[float, ...]] = None
accuracy_inclusive: bool = False
```

`None` 表示“采用规则显式阈值；规则未声明时采用 `5/10/15`”。CLI 统一增加：

```text
--accuracy-thresholds TEXT
    逗号分隔的正数阈值，例如 3,5,10；省略时采用规则或 5,10,15
--accuracy-inclusive/--accuracy-strict
    inclusive 使用 <=，strict 使用 <；默认 strict
```

阈值必须有限、严格大于 `0`、不重复，并按输入顺序输出。CLI 非法值使用 `click.BadParameter`；直接调用 API 的非法 tuple 使用 `RequestValidationError`。

## 文件结构

- Create: `tests/test_accuracy.py`：共享边界、strict/inclusive、自定义阈值和累计器单元测试。
- Create: `src/health_tools/commands/accuracy_options.py`：五个命令共用的 Click 选项与字符串解析。
- Modify: `src/health_tools/utils/accuracy.py`：共享配置解析、全局边界和全部准确度计算。
- Modify: `src/health_tools/api/models.py`：扩展五个 accuracy request。
- Modify: `src/health_tools/api/operations.py`：evaluate 参数传递与 API 校验。
- Modify: `src/health_tools/api/file_operations.py`：classify、plot 参数传递。
- Modify: `src/health_tools/api/offline_operation.py`：offline 的 PSD 图与 CSV 报告参数传递。
- Modify: `src/health_tools/api/analysis_operation.py`：analyze 参数传递和动态指标收集。
- Modify: `src/health_tools/core/evaluator.py`：evaluate 统一预处理和规则阈值兼容。
- Modify: `src/health_tools/core/psd_plotter.py`：PSD 文本指标使用共享工具。
- Modify: `src/health_tools/core/offline.py`：多列全局边界、动态阈值和逐比较加权。
- Modify: `src/health_tools/core/analysis/raw.py`：原始数据准确度和异常分段共享同一裁剪区间。
- Modify: `src/health_tools/core/analysis/psd.py`：PSD 分析比较共享同一裁剪区间。
- Modify: `src/health_tools/core/analysis/reporting.py`：CSV、Markdown、PPT 动态渲染阈值列。
- Modify: `src/health_tools/commands/evaluate.py`、`classify.py`、`offline.py`、`plot.py`、`analyze.py`：接入统一 CLI 参数。
- Modify: `tests/test_classify.py`、`tests/test_offline.py`、`tests/test_analysis.py`、`tests/test_progress.py`、`tests/test_api_contract.py`：业务入口和参数传递回归。
- Modify: `docs/cmd_evaluate.md`、`docs/cmd_classify.md`、`docs/cmd_offline.md`、`docs/cmd_plot.md`、`docs/cmd_analyze.md`、`docs/rules.md`：记录统一统计口径和参数优先级。

### Task 1: 建立共享预处理和阈值计算契约

**Files:**
- Create: `tests/test_accuracy.py`
- Modify: `src/health_tools/utils/accuracy.py`
- Modify: `src/health_tools/utils/__init__.py`

- [ ] **Step 1: 写 strict/inclusive 与默认阈值失败测试**

```python
def test_within_threshold_defaults_to_strict_and_supports_inclusive():
    diff = np.array([4.9, 5.0, 5.1])

    assert calculate_within_threshold(diff, 5) == pytest.approx(100 / 3)
    assert calculate_within_threshold(diff, 5, inclusive=True) == pytest.approx(200 / 3)


def test_resolve_accuracy_methods_uses_defaults_without_overriding_rule_methods():
    assert resolve_accuracy_methods([], None) == [
        "std", "rmse", "mae", "within_5", "within_10", "within_15"
    ]
    assert resolve_accuracy_methods(["mae", "within_3", "within_6", "within_9"], None) == [
        "mae", "within_3", "within_6", "within_9"
    ]
    assert resolve_accuracy_methods(
        ["mae", "within_3", "within_6", "correlation"], (5.0, 10.0)
    ) == ["mae", "within_5", "within_10", "correlation"]
```

- [ ] **Step 2: 写全零列与全局零填充边界失败测试**

使用不同起止位置证明边界必须取所有启用列的交集，而不是任一列有值的并集：

```python
def test_prepare_accuracy_columns_uses_shared_ready_boundary_and_keeps_middle_zero():
    columns = {
        "polar": np.array([80, 81, 82, 0, 84, 85, 86], dtype=float),
        "online": np.array([0, 81, 82, 0, 84, 85, 0], dtype=float),
        "offline": np.array([0, 0, 82, 0, 84, 0, 0], dtype=float),
        "comp": np.zeros(7, dtype=float),
    }

    prepared = prepare_accuracy_columns(columns)

    assert prepared.active_columns == ("polar", "online", "offline")
    assert (prepared.start, prepared.end) == (2, 5)
    assert prepared.columns["polar"].tolist() == [82, 0, 84]
    assert prepared.columns["online"].tolist() == [82, 0, 84]
    assert prepared.columns["offline"].tolist() == [82, 0, 84]
```

再覆盖全 `NaN`、全 `Inf`、空输入、所有列禁用，以及边界内一方为 `NaN` 时仅该比较样本被成对过滤。

- [ ] **Step 3: 实现共享数据结构和校验函数**

在 `accuracy.py` 增加：

```python
DEFAULT_ACCURACY_THRESHOLDS = (5.0, 10.0, 15.0)
DEFAULT_ACCURACY_METHODS = (
    "std", "rmse", "mae", "within_5", "within_10", "within_15"
)


@dataclass(frozen=True)
class PreparedAccuracyColumns:
    columns: Dict[str, np.ndarray]
    active_columns: Tuple[str, ...]
    start: int
    end: int


def normalize_accuracy_thresholds(
    thresholds: Optional[Sequence[float]],
) -> Optional[Tuple[float, ...]]:
    if thresholds is None:
        return None
    values = tuple(float(value) for value in thresholds)
    if not values or any(not np.isfinite(value) or value <= 0 for value in values):
        raise ValueError("准确度阈值必须是有限正数")
    if len(set(values)) != len(values):
        raise ValueError("准确度阈值不能重复")
    return values


def prepare_accuracy_columns(columns: Mapping[str, Sequence[float]]) -> PreparedAccuracyColumns:
    numeric = {name: np.asarray(values, dtype=float) for name, values in columns.items()}
    lengths = {len(values) for values in numeric.values()}
    if len(lengths) > 1:
        raise ValueError("准确度列长度必须一致")
    active = tuple(
        name for name, values in numeric.items()
        if np.any(np.isfinite(values) & (values != 0))
    )
    if not active:
        return PreparedAccuracyColumns(
            {name: values[:0] for name, values in numeric.items()}, (), 0, 0
        )
    ready = np.logical_and.reduce(
        [np.isfinite(numeric[name]) & (numeric[name] != 0) for name in active]
    )
    indices = np.flatnonzero(ready)
    if not len(indices):
        return PreparedAccuracyColumns(
            {name: values[:0] for name, values in numeric.items()}, active, 0, 0
        )
    start, end = int(indices[0]), int(indices[-1]) + 1
    return PreparedAccuracyColumns(
        {name: values[start:end] for name, values in numeric.items()}, active, start, end
    )
```

- [ ] **Step 4: 让所有 within 计算使用同一个 inclusive 开关**

将 `calculate_within_threshold`、`calculate_within_percent` 和 `calculate_accuracy` 默认改为 strict：

```python
def calculate_within_threshold(
    diff: np.ndarray, threshold: float, *, inclusive: bool = False
) -> float:
    errors = np.abs(diff)
    passed = errors <= threshold if inclusive else errors < threshold
    return float(np.mean(passed) * 100) if len(errors) else 0.0
```

`calculate_accuracy(..., inclusive=False, trim_zero_padding=True)` 在计算前调用 `prepare_accuracy_columns({"ref": ref, "pred": pred})`；任一列禁用或没有共同边界时只返回 `{"samples": 0}`。未传 methods 时使用 `DEFAULT_ACCURACY_METHODS`，即保留 STD/RMSE/MAE，并把旧的默认 `1/2/3` 改为 `5/10/15`。区间内只过滤双方非有限值，不过滤 `0`。百分比阈值同样根据 `inclusive` 选择 `<` 或 `<=`。

- [ ] **Step 5: 修正 AccuracyCalculator 的累计数据对齐**

`AccuracyCalculator` 保存 `inclusive`，每个文件先用共享工具获得成对对齐后的 ref/pred，再把同一个 finite mask 处理后的数组加入 total；不得再分别 `dropna()` 后按最短长度拼接。类别和 total 只累计 `samples > 0` 的比较，确保全零列文件不会影响加权分母。

- [ ] **Step 6: 运行单元测试并提交**

```bash
pytest tests/test_accuracy.py -v
git add src/health_tools/utils/accuracy.py src/health_tools/utils/__init__.py tests/test_accuracy.py
git commit -m "refactor: 统一准确度统计基础逻辑" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

Expected: 边界值、全局裁剪、中间零、全零列、NaN 对齐和累计加权测试全部通过。

### Task 2: 贯通统一 request 和 CLI 参数

**Files:**
- Create: `src/health_tools/commands/accuracy_options.py`
- Modify: `src/health_tools/api/models.py`
- Modify: `src/health_tools/commands/evaluate.py`
- Modify: `src/health_tools/commands/classify.py`
- Modify: `src/health_tools/commands/offline.py`
- Modify: `src/health_tools/commands/plot.py`
- Modify: `src/health_tools/commands/analyze.py`
- Modify: `tests/test_api_contract.py`

- [ ] **Step 1: 写五个 request 默认值和 CLI help 失败测试**

断言 `PlotRequest`、`ClassifyRequest`、`EvaluateRequest`、`OfflineRequest`、`AnalyzeRequest` 均为 `accuracy_thresholds is None`、`accuracy_inclusive is False`；五个命令的 `--help` 都包含两个 accuracy 选项。

- [ ] **Step 2: 写阈值参数校验失败测试**

使用 `CliRunner` 覆盖 `5,10,15`、`3.5,6`，以及空串、`5,0`、`5,-1`、`5,5`、`5,nan`、`5,inf`。合法值传入 tuple，非法值退出码非零且错误信息包含“有限正数”或“不能重复”。直接构造 request 传非法 tuple 时，API operation 必须抛 `RequestValidationError`。

- [ ] **Step 3: 实现公共 Click 选项**

`commands/accuracy_options.py` 提供 `parse_accuracy_thresholds()` 和可复用装饰器：

```python
def accuracy_options(command):
    command = click.option(
        "--accuracy-inclusive/--accuracy-strict",
        default=False,
        help="阈值命中使用 <=；默认严格使用 <",
    )(command)
    return click.option(
        "--accuracy-thresholds",
        callback=parse_accuracy_thresholds,
        help="逗号分隔的准确度阈值；默认采用规则或 5,10,15",
    )(command)
```

解析函数调用 `normalize_accuracy_thresholds`，把 `ValueError` 转换为 `click.BadParameter`。

- [ ] **Step 4: 扩展 request 并接入五个命令**

在五个 dataclass 尾部增加公共字段，命令函数参数与构造 request 时使用同名字段。保持字段有默认值，避免现有 API 调用和测试构造失效。

- [ ] **Step 5: 运行契约测试并提交**

```bash
pytest tests/test_api_contract.py -k "accuracy_thresholds or accuracy_inclusive" -v
git add src/health_tools/commands/accuracy_options.py src/health_tools/api/models.py src/health_tools/commands/evaluate.py src/health_tools/commands/classify.py src/health_tools/commands/offline.py src/health_tools/commands/plot.py src/health_tools/commands/analyze.py tests/test_api_contract.py
git commit -m "feat: 增加统一准确度统计参数" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 3: 更新 evaluate 与 classify 准确度入口

**Files:**
- Modify: `src/health_tools/api/operations.py`
- Modify: `src/health_tools/api/file_operations.py`
- Modify: `src/health_tools/core/evaluator.py`
- Modify: `tests/test_classify.py`
- Modify: `tests/test_progress.py`
- Create: `tests/test_evaluator.py`

- [ ] **Step 1: 写 evaluate 规则优先级和边界失败测试**

测试 HR 未覆盖时仍输出 `within_5/10/15`，SpO2 未覆盖时仍输出 `within_3/6/9`；显式 `accuracy_thresholds=(5, 10)` 时只替换固定 `within_N`，保留 `mae/std/correlation`。构造误差恰好等于阈值的行，验证默认不命中、inclusive 时命中。

- [ ] **Step 2: 写 evaluate 共享边界失败测试**

用 ref/pred 起止零填充不同、区间中间包含 `0` 的 DataFrame，断言 `metrics_all` 和 `metrics_filtered` 使用同一原始共享边界；异常行过滤只减少对应样本，不重新寻找更窄的零填充边界。

- [ ] **Step 3: 实现 BatchEvaluator 参数与预处理**

`BatchEvaluator.__init__` 接收 `accuracy_thresholds`、`accuracy_inclusive`。`_evaluate_file` 先解析数值列并执行一次 `prepare_accuracy_columns`，再在该切片内计算 Polar 异常 mask、all metrics 和 filtered metrics。后续 `calculate_accuracy` 调用必须传 `trim_zero_padding=False`，避免 filtered 数据因异常行被删除而重新寻找边界。`resolve_accuracy_methods(rule.methods, accuracy_thresholds)` 负责阈值集合；`rule.thresholds` 中命名自定义阈值原样传给 `calculate_accuracy`。

- [ ] **Step 4: 写 classify 自定义阈值兼容和累计失败测试**

加载 `spo2_posture.yaml`，断言未覆盖时 `within_1/2/3/5`、`within_0.5`、`within_10_percent` 均存在；显式 `5,10,15` 时固定集合变为 `5/10/15`，但两个命名自定义阈值保留。加入一个全零预测文件，断言它不增加 category/TOTAL 的 `samples`；加入内部零样本，断言其误差参与统计。

- [ ] **Step 5: 贯通 API operation**

`run_evaluate` 和 `run_classify` 调用 `normalize_accuracy_thresholds` 做 API 校验并传递参数。`AccuracyCalculator` 的 methods 通过 `resolve_accuracy_methods` 生成，inclusive 同时传给固定阈值和规则自定义阈值。

- [ ] **Step 6: 运行回归测试并提交**

```bash
pytest tests/test_evaluator.py tests/test_classify.py tests/test_progress.py -k "accuracy or evaluate or classify" -v
git add src/health_tools/api/operations.py src/health_tools/api/file_operations.py src/health_tools/core/evaluator.py tests/test_evaluator.py tests/test_classify.py tests/test_progress.py
git commit -m "feat: 统一评估与分类准确度统计" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 4: 更新 offline 与 PSD plot 多列统计

**Files:**
- Modify: `src/health_tools/core/psd_plotter.py`
- Modify: `src/health_tools/core/offline.py`
- Modify: `src/health_tools/api/offline_operation.py`
- Modify: `src/health_tools/api/file_operations.py`
- Modify: `src/health_tools/commands/offline.py`
- Modify: `tests/test_offline.py`
- Modify: `tests/test_progress.py`

- [ ] **Step 1: 写四列全局边界失败测试**

构造 Polar、Online、Offline 起止出值位置不同，Comp 全零的 `_result.vshb`：Comp 必须被禁用；边界由 Polar/Online/Offline 三列全部非零的首末行决定。再构造 Comp 非全零但起始更晚、结束更早的样本，断言所有三组 Polar 比较共享 Comp 约束后的同一边界。

- [ ] **Step 2: 写回退与内部零失败测试**

覆盖：Polar 全零时生成 `Online vs Offline`；Polar、Online 或 Offline 任一必要列禁用时不生成该比较；共享区间中间某列的 `0` 不删除该行，并按正常绝对误差进入 `samples`、MAE 和 `within_N`。

- [ ] **Step 3: 重构 PSD 图指标文本**

`_metric_text_rows` 先对 `polar/offline/online/comp` 一次性调用 `prepare_accuracy_columns`，再根据 active columns 选择比较。`_calc_metrics` 调用共享 `calculate_accuracy`，`_format_metric_line` 按有序阈值动态生成 `±Nbpm`，不再硬编码 5/10/15。`PsdPlotter.plot` 接收 request 的两个参数。

- [ ] **Step 4: 重构离线 CSV 报告和加权汇总**

`calculate_offline_accuracy` 使用与 PSD 文本完全相同的比较选择。完成四列全局裁剪后，逐对调用 `calculate_accuracy(..., trim_zero_padding=False)`，不得退化为各比较自行裁剪。每个比较保留自己的 `samples(<comparison>)`，分类平均和 TOTAL 的每个指标使用对应 samples 加权；顶层 `samples` 保留为主比较样本数以兼容现有读取方。全零列的指标列和 samples 列均不生成。

- [ ] **Step 5: 贯通 plot/offline API**

`run_plot` 仅在 PSD 目录绘图路径传递 accuracy 参数；普通 time/freq 图接受参数但不使用。`run_offline` 向 `PsdPlotter.plot` 和 `calculate_offline_accuracy` 传递完全相同的阈值与 inclusive，保证图片和 CSV 报告一致。更新 mock 函数签名，避免 `tests/test_progress.py` 因新增 kwargs 失败。

- [ ] **Step 6: 运行离线回归并提交**

```bash
pytest tests/test_offline.py tests/test_progress.py -k "psd or offline_accuracy or accuracy" -v
git add src/health_tools/core/psd_plotter.py src/health_tools/core/offline.py src/health_tools/api/offline_operation.py src/health_tools/api/file_operations.py src/health_tools/commands/offline.py tests/test_offline.py tests/test_progress.py
git commit -m "feat: 统一离线与 PSD 准确度统计" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 5: 更新 analyze 原始/PSD 分析和动态报告

**Files:**
- Modify: `src/health_tools/core/analysis/raw.py`
- Modify: `src/health_tools/core/analysis/psd.py`
- Modify: `src/health_tools/core/analysis/reporting.py`
- Modify: `src/health_tools/api/analysis_operation.py`
- Modify: `tests/test_analysis.py`

- [ ] **Step 1: 写 raw/PSD 统一统计失败测试**

对原始 CSV 和 `_result.vshb` 分别复用误差恰好 `5/10/15`、首尾错位零填充、中间零、全零 Comp 数据。断言两条分析路径与 evaluate/offline 得到相同 `samples`、MAE 和 within 比例。`error_ratio`/异常分段仍使用 analysis 规则的 `thresholds.error` 与 `>`，不受 accuracy inclusive 影响。

- [ ] **Step 2: 替换 raw.py 的硬编码 within 统计**

`_error_segments` 接收 `accuracy_thresholds`、`accuracy_inclusive` 和已经裁剪好的 ref/pred；误差分段逻辑保持不变，准确度字段调用共享函数生成。`analyze_raw_file` 在 reference 分析前确定共享边界，并同步切片 reference mask、时间轴和错误分段输入。

- [ ] **Step 3: 替换 psd.py 的硬编码比较**

`_accuracy_features` 对四列只执行一次全局预处理，根据 active columns 生成 `offline/online/comp` 或 `online_vs_offline` comparisons。`_comparison_metrics` 使用动态 methods、inclusive 和 `trim_zero_padding=False`，不再直接写 `errors <= 5/10/15`，也不允许各比较重新计算边界。

- [ ] **Step 4: 让 CSV、Markdown 和 PPT 动态渲染阈值**

`analysis_operation._offline_records` 不再固定提取 `within_5/10/15`，而是从 comparisons/metrics 中收集所有 `within_` 键。`reporting._accuracy_rows` 按 request 阈值顺序聚合，并使用每个 comparison 自己的 samples 加权。`file_diagnosis.csv` fieldnames、Markdown 表头和 PPT 表格列数均由阈值列表生成；默认输出仍保持 5/10/15 三列。

- [ ] **Step 5: 贯通 AnalyzeRequest**

`run_analyze` 校验 request 阈值并传给 raw/PSD 分析和 reporting。直接分析已有 PSD、自动 offline 升级后分析、Markdown 和 PPT 四条路径都必须携带同一配置。

- [ ] **Step 6: 运行分析回归并提交**

```bash
pytest tests/test_analysis.py -k "accuracy or psd or report or threshold" -v
git add src/health_tools/core/analysis/raw.py src/health_tools/core/analysis/psd.py src/health_tools/core/analysis/reporting.py src/health_tools/api/analysis_operation.py tests/test_analysis.py
git commit -m "feat: 统一分析报告准确度统计" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 6: 更新文档并完成全量验证

**Files:**
- Modify: `docs/cmd_evaluate.md`
- Modify: `docs/cmd_classify.md`
- Modify: `docs/cmd_offline.md`
- Modify: `docs/cmd_plot.md`
- Modify: `docs/cmd_analyze.md`
- Modify: `docs/rules.md`

- [ ] **Step 1: 更新五个命令页**

每页增加两个 CLI 参数，并明确默认 strict `<`、inclusive `<=`、默认/规则阈值优先级、全零列禁用、全部启用列共享首尾边界、中间零保留。offline/plot 文档额外说明 Polar 回退和逐比较样本数。

- [ ] **Step 2: 更新规则文档**

把 `within_N` 和命名 threshold 的定义从 `<=` 改为默认 `<`，说明命令行 inclusive 可以切换为 `<=`。保留 `evaluate_spo2.yaml` 的 `3/6/9` 和 `spo2_posture.yaml` 自定义阈值示例，说明显式 `--accuracy-thresholds` 只替换 methods 中固定 `within_N`。

- [ ] **Step 3: 校验源码导入位置和 CLI help**

```bash
python -c "import health_tools; print(health_tools.__file__)"
ghealth_tool evaluate --help
ghealth_tool classify --help
ghealth_tool offline --help
ghealth_tool plot --help
ghealth_tool analyze --help
```

Expected: 导入路径位于当前工作区 `E:\\Code\\Python\\health_tools\\src`，五个 help 都显示统一参数。

- [ ] **Step 4: 运行全量测试和质量检查**

```bash
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:MPLBACKEND='Agg'; pytest
black --check src/ tests/
ruff check src/ tests/
mypy src/
git diff --check
```

Expected: pytest、Black、Ruff、mypy 和 diff check 全部通过。若发现仓库既有失败，记录完整命令、文件和错误，并确认本次定向测试仍通过；不修改无关代码。

- [ ] **Step 5: 提交文档并核对提交范围**

```bash
git add docs/cmd_evaluate.md docs/cmd_classify.md docs/cmd_offline.md docs/cmd_plot.md docs/cmd_analyze.md docs/rules.md
git commit -m "docs: 说明统一准确度统计规则" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
git status --short
git log -6 --oneline
```

Expected: 工作区无未提交文件；提交只包含本计划列出的源码、测试和文档。
