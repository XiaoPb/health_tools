# Check 准确度统计与规则化分拣 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `check` 增加 Online/Comp 对金标的准确度统计、主要异常项中文摘要、可配置准确度标定和分拣，并通过 `-r/--rule` 用一份完整 check YAML 配置全部现有及新增参数。

**Architecture:** 新增正式的 `check` 规则类型，由规则加载器和验证器解析为强类型 `CheckRule`，命令行按“显式 CLI > 规则 > 内置默认值”生成 `CheckRequest`。准确度计算复用 `health_tools.utils.accuracy` 的共同有效边界和逐比较计算口径；每文件生成结构化准确度结果和按优先级选出的主要异常项，报告、精简报告和 sort 共用同一套分类函数。

**Tech Stack:** Python 3.9+、Click、pandas、PyYAML、dataclasses、pytest、Black、Ruff、mypy。

---

## 范围与确定的行为

1. `check` 同时计算：
   - `online vs ref`
   - `comp vs ref`
   - 不新增 `online vs comp` 的样本误差统计；“Online 低于 Comp”比较的是两者对同一金标、同一准确度指标的百分比差。
2. 准确度沿用 offline 口径：
   - `ref`、`online`、`comp` 中存在 finite 且非 0 样本的列才启用；
   - 所有启用列共同确定首尾有效边界；
   - 边界内部的 0 保留，`NaN/Inf` 在具体比较时过滤；
   - 全 0 Comp 不参与 `comp vs ref`；
   - 默认方法为 `mae/rmse/correlation/within_5/within_10/within_15`，阈值边界默认严格 `<`，可切换为 `<=`。
3. `check_report.csv` 在 `场景分类` 后新增：
   - `主要异常项`
   - `Online准确度样本数`
   - `Online MAE`
   - `Online RMSE`
   - `Online相关系数`
   - 每个启用 `within_N` 对应 `Online ±NBPM准确度`
   - `Comp准确度样本数`
   - 同构的 Comp 指标列
   - 最后仍为 `文件相对路径`
4. `主要异常项` 只显示一个中文简要描述，按 sort 的同一优先级选择：
   - `帧不完整`
   - `数据范围异常`
   - `ACC异常`
   - `ACC警告`
   - `时间戳异常`
   - `数据未居中`
   - `金标异常`
   - `首帧非0`
   - 按规则顺序命中的准确度标定标签，例如 `Online ±5准确度低`、`Online低于Comp 10个百分点`
   - `Ipd转换异常`
   - 其他扩展检查项的中文检查名
   - 只有总 FAIL 的旧报告显示 `未分类异常`
   - 无异常显示 `正常`
5. 准确度标定分类位于 `frame_warning` 之后、Ipd 和其他低优先级异常之前。每条标定规则声明稳定英文 `category`，sort 输出到 `abnormal/<category>/`。
6. `-r/--rule` 支持用户目录 `~/.ghealth_tools/rules/check/`、包内 `rules/check/` 和绝对路径。
7. YAML 声明可复用的数据解释和检查业务规则：芯片、检查项、阈值、时间戳列、参考列、准确度列、
   场景提取、准确度方法和标定条件。输入路径、输出路径、sort 开关、sort 输出目录、并行数和 verbose
   都是本次运行上下文，必须由 CLI/API 外部输入，不写入 YAML。
8. 配置优先级为显式 CLI > YAML > `CheckRequest` 默认值；其中 `-c/--chip` 显式传入时覆盖 YAML 的 `chip`，
   未传入时使用 YAML 芯片。`-r/--rule` 自身不能出现在 YAML。
   `--sort` 启用时默认读取本次 check 生成的报告：单文件为 `<输入文件父目录>/check_report.csv`，
   目录输入为 `<输入目录>/check_report.csv`；仍可用 CLI `--report` 覆盖已有报告，但该参数不进入 YAML。

## 完整规则声明

创建内置示例 `src/health_tools/rules/check/default.yaml`，并在 `docs/rules.md` 原样给出完整字段：

```yaml
version: "1.0"
description: 默认数据质量、准确度与分拣规则

# YAML 描述芯片、列语义和检查策略，不描述输入/输出和本次运行控制。
chip: gh3036
checks: [range, ipd, frame, center, acc, agc, ref]
tolerance: 50
static_min: 5

ratios:
  range: 1.0
  frame: 1.0
  center: 5.0
  ipd: 1.0
  acc: 1.0

acc_axis: false

timestamp:
  column: null
  ratio: 20.0
  ms: null
  fail_ratio: 1.0
  base_ms: null

reference:
  hr_column: null
  spo2_column: null
  sample_rate: 25.0
  stale_seconds: 5.0
  step_threshold: 8.0

scene_regex: null

accuracy:
  enabled: false
  ref_column: REF_RESULT0
  online_column: ALGO_RESULT0
  comp_column: COMP_RESULT0
  methods: [mae, within_5, within_10, within_15, rmse, correlation]
  thresholds: []
  inclusive: false
  marks:
    - id: online_within_5_low
      comparison: online
      metric: within_5
      min: 80.0
      label: Online ±5准确度低
      category: accuracy_online_low
    - id: comp_within_5_low
      comparison: comp
      metric: within_5
      min: 80.0
      label: Comp ±5准确度低
      category: accuracy_comp_low
    - id: online_below_comp
      comparison: online_below_comp
      metric: within_5
      min_gap: 10.0
      label: Online低于Comp 10个百分点
      category: accuracy_online_below_comp
```

对应 CLI 新增参数：

```text
-r, --rule PATH_OR_NAME
--chip TEXT
--checks TEXT
--tolerance INTEGER
--static-min INTEGER
--range-ratio FLOAT
--frame-ratio FLOAT
--center-ratio FLOAT
--ipd-ratio FLOAT
--acc-ratio FLOAT
--acc-axis/--no-acc-axis
--check-timestamp TEXT
--timestamp-ratio FLOAT
--timestamp-ms FLOAT
--timestamp-fail-ratio FLOAT
--timestamp-base-ms FLOAT
--ref-hr-column TEXT
--ref-spo2-column TEXT
--ref-sample-rate FLOAT
--ref-stale-seconds FLOAT
--ref-step-threshold FLOAT
--scene-regex TEXT
--sort
--report PATH_OR_NAME
--sort-output PATH
--workers INTEGER
-v, --verbose
--accuracy/--no-accuracy
--accuracy-ref-column TEXT
--accuracy-online-column TEXT
--accuracy-comp-column TEXT
--accuracy-thresholds FLOAT[,FLOAT...]
--accuracy-inclusive/--accuracy-strict
--accuracy-min COMPARISON:METRIC:MIN:CATEGORY[:LABEL]
--online-comp-gap METRIC:MIN_GAP:CATEGORY[:LABEL]
```

重复的 `--accuracy-min` 和 `--online-comp-gap` 按 CLI 出现顺序组成 marks，并整体替换规则中的 `accuracy.marks`。示例：

```bash
ghealth_tool check -i data -r default.yaml \
  --accuracy \
  --accuracy-ref-column REF_RESULT0 \
  --accuracy-online-column ALGO_RESULT0 \
  --accuracy-comp-column COMP_RESULT0 \
  --accuracy-min "online:within_5:80:accuracy_online_low:Online ±5准确度低" \
  --online-comp-gap "within_5:10:accuracy_online_below_comp:Online低于Comp 10个百分点"
```

## 文件结构

- Create: `src/health_tools/core/check_accuracy.py`：准确度列准备、两组比较、标定规则匹配和中文摘要。
- Create: `src/health_tools/rules/check/default.yaml`：完整可复制的 check 规则。
- Create: `tests/test_check_accuracy.py`：准确度口径、标定和主要异常单元测试。
- Create: `tests/test_check_rules.py`：规则加载、验证、CLI 合并和帮助文本测试。
- Modify: `src/health_tools/models/rules.py`：新增 `CheckRule`、`CheckAccuracyRule`、`AccuracyMarkRule`；`CheckRule` 只保存业务策略。
- Modify: `src/health_tools/rules/loader.py`：加载 check 规则并保留规则文件基准目录。
- Modify: `src/health_tools/rules/validator.py`：验证完整 check schema。
- Modify: `src/health_tools/api/models.py`：新增 `RuleType.CHECK`、扩展 `CheckRequest` 和每文件准确度模型。
- Modify: `src/health_tools/api/rule_operations.py`：让规则目录管理 API 支持 check。
- Modify: `src/health_tools/commands/check.py`：增加参数、规则合并、帮助和动态 sort 汇总。
- Modify: `src/health_tools/api/check_operation.py`：执行准确度、统一报告列、主要异常和 sort 分类。
- Modify: `src/health_tools/core/checker.py`：只在需要时给 `FileCheckReport` 增加结构化准确度字段，不复制准确度算法。
- Modify: `tests/test_check_sort.py`：准确度标定的排序优先级与目录测试。
- Modify: `tests/test_api_rules.py`、`tests/test_api_contract.py`：公开规则类型契约更新。
- Modify: `tests/test_documentation.py`：确保新增规则和命令文档被导航覆盖。
- Modify: `docs/cmd_check.md`、`docs/rules.md`、`docs/commands.md`：完整参数、报告和规则说明。
- Modify: `.agents/skills/use-ghealth-tool/references/commands.md`、`.agents/skills/use-ghealth-tool/references/workflows.md`、`.agents/skills/use-ghealth-tool/references/rules.md`：同步仓库技能事实来源。

---

### Task 1: 建立 check 规则模型和完整 YAML

**Files:**
- Modify: `src/health_tools/models/rules.py`
- Create: `src/health_tools/rules/check/default.yaml`
- Test: `tests/test_check_rules.py`

- [ ] **Step 1: 写失败测试，固定完整规则对象结构**

```python
def test_load_check_rule_keeps_all_supported_parameters():
    rule = RuleLoader.load_check_rule("default.yaml")

    assert rule.checks == ("range", "ipd", "frame", "center", "acc", "agc", "ref", "accuracy")
    assert rule.ratios.frame == 1.0
    assert rule.timestamp.ratio == 20.0
    assert rule.reference.sample_rate == 25.0
    assert rule.accuracy.ref_column == "REF_RESULT0"
    assert rule.accuracy.methods == ("mae", "within_5", "within_10", "within_15", "rmse", "correlation")
    assert rule.accuracy.marks[0].category == "accuracy_online_low"
```

- [ ] **Step 2: 运行测试确认因 `load_check_rule` 缺失而失败**

Run: `pytest tests/test_check_rules.py::test_load_check_rule_keeps_all_supported_parameters -v`

Expected: FAIL，提示 `RuleLoader` 没有 `load_check_rule`。

- [ ] **Step 3: 增加强类型规则 dataclass**

在 `src/health_tools/models/rules.py` 增加不可变配置对象，字段与完整 YAML 一一对应：

```python
@dataclass(frozen=True)
class AccuracyMarkRule:
    id: str
    comparison: str
    metric: str
    category: str
    label: str
    min: Optional[float] = None
    min_gap: Optional[float] = None


@dataclass(frozen=True)
class CheckAccuracyRule:
    enabled: bool = False
    ref_column: str = "REF_RESULT0"
    online_column: str = "ALGO_RESULT0"
    comp_column: Optional[str] = "COMP_RESULT0"
    methods: Tuple[str, ...] = ("mae", "within_5", "within_10", "within_15", "rmse", "correlation")
    thresholds: Tuple[Dict[str, Any], ...] = ()
    inclusive: bool = False
    marks: Tuple[AccuracyMarkRule, ...] = ()


@dataclass(frozen=True)
class CheckRule:
    version: str = "1.0"
    description: str = ""
    chip: Optional[str] = None
    values: Dict[str, Any] = field(default_factory=dict)
    accuracy: CheckAccuracyRule = field(default_factory=CheckAccuracyRule)
```

`values` 只保存除 `accuracy` 外的业务策略参数：`checks`、各项 ratio、`tolerance`、`static_min`、`acc_axis`、时间戳策略、参考列策略和 `scene_regex`。
不保存 `input/output/sort/report/sort_output/workers/verbose`，但保留 `chip` 以及 timestamp/reference/accuracy 列配置，
避免把数据位置、文件移动动作或展示性能写死，同时保证规则能解释输入列语义。

- [ ] **Step 4: 创建完整内置规则**

将“完整规则声明”章节的 YAML 原样写入 `src/health_tools/rules/check/default.yaml`。

- [ ] **Step 5: 运行模型测试确认当前仅缺加载器**

Run: `pytest tests/test_check_rules.py::test_load_check_rule_keeps_all_supported_parameters -v`

Expected: FAIL，仍只因加载器缺失，不出现 YAML 语法或导入错误。

- [ ] **Step 6: 提交规则模型骨架**

```bash
git add src/health_tools/models/rules.py src/health_tools/rules/check/default.yaml tests/test_check_rules.py
git commit -m "feat: 定义 check 完整规则模型" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 2: 接入规则加载、验证和规则管理 API

**Files:**
- Modify: `src/health_tools/rules/loader.py`
- Modify: `src/health_tools/rules/validator.py`
- Modify: `src/health_tools/api/models.py`
- Modify: `src/health_tools/api/rule_operations.py`
- Modify: `tests/test_check_rules.py`
- Modify: `tests/test_api_rules.py`
- Modify: `tests/test_api_contract.py`

- [ ] **Step 1: 写失败测试覆盖加载和验证错误**

```python
def test_check_rule_rejects_runtime_paths_and_controls():
    errors = RuleValidator.validate(
        {
            "version": "1.0",
            "input": "data",
            "output": "report.csv",
            "sort": True,
            "workers": 8,
            "accuracy": {"enabled": False},
        },
        "check",
    )
    message = " ".join(errors)
    assert "input" in message
    assert "output" in message
    assert "sort" in message
    assert "workers" in message


def test_validate_check_rule_rejects_invalid_accuracy_mark():
    errors = RuleValidator.validate(
        {
            "version": "1.0",
            "accuracy": {
                "enabled": True,
                "ref_column": "REF_RESULT0",
                "online_column": "ALGO_RESULT0",
                "marks": [{"id": "bad", "comparison": "online", "metric": "within_5"}],
            },
        },
        "check",
    )
    assert "marks[0]" in " ".join(errors)
```

- [ ] **Step 2: 运行测试确认 check 类型尚未接入**

Run: `pytest tests/test_check_rules.py tests/test_api_rules.py tests/test_api_contract.py -q`

Expected: FAIL，包含未知规则类型或缺少 `RuleType.CHECK`。

- [ ] **Step 3: 实现 `RuleLoader.load_check_rule`**

加载器必须：

```python
@classmethod
def load_check_rule(cls, rule_file: str) -> CheckRule:
    rule_path = cls._resolve_rule_path(rule_file, "check")
    data = cls._load_yaml(rule_path)
    errors = RuleValidator.validate(data, "check")
    if errors:
        raise ValueError("check 规则无效: " + "；".join(errors))
    normalized = _normalize_check_rule_values(data, rule_path.parent)
    return CheckRule(
        version=str(data.get("version", "1.0")),
        description=str(data.get("description", "")),
        chip=data.get("chip"),
        values=normalized.values,
        accuracy=normalized.accuracy,
    )
```

规则加载器不再解析任何路径字段；`input/output/report/sort_output` 均不属于 check YAML schema。
`--report` 仅作为 CLI 对自动报告路径的显式覆盖，`--sort-output` 仍必须由 CLI/API 提供。

- [ ] **Step 4: 实现 check schema 验证**

验证器需拒绝：未知顶层字段（包括 `input`、`output`、`sort`、`report`、`sort_output`、`workers`、`verbose`），
未知检查项、负 ratio、时间戳/参考数值非法、准确度列为空、未知 method、重复 mark id/category、目录 category 非安全单段、
mark 缺少 `min` 或 `min_gap`、comparison 与字段不匹配。`chip` 必须是非空字符串，并由显式 `-c/--chip` 覆盖。

```python
if comparison in {"online", "comp"}:
    require exactly one finite 0..100 `min`
elif comparison == "online_below_comp":
    require one finite non-negative `min_gap`
else:
    errors.append("comparison 仅支持 online、comp、online_below_comp")
```

- [ ] **Step 5: 新增公开规则类型**

在 `RuleType` 增加 `CHECK = "check"`，让 list/read/save 与 revision 逻辑自动覆盖该目录；更新参数化契约测试的规则样例。

- [ ] **Step 6: 运行规则测试**

Run: `pytest tests/test_check_rules.py tests/test_api_rules.py tests/test_api_contract.py -q`

Expected: PASS。

- [ ] **Step 7: 提交规则基础设施**

```bash
git add src/health_tools/rules/loader.py src/health_tools/rules/validator.py src/health_tools/api/models.py src/health_tools/api/rule_operations.py tests/test_check_rules.py tests/test_api_rules.py tests/test_api_contract.py
git commit -m "feat: 接入 check 规则加载与验证" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 3: 实现 CLI 与规则的确定性合并

**Files:**
- Modify: `src/health_tools/commands/check.py`
- Modify: `src/health_tools/commands/accuracy_options.py`
- Modify: `src/health_tools/api/models.py`
- Test: `tests/test_check_rules.py`
- Test: `tests/test_reference_checker.py`

- [ ] **Step 1: 写失败测试固定参数优先级**

```python
def test_check_cli_explicit_values_override_rule(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr("health_tools.api.run_check", lambda request, context=None: captured.setdefault("request", request) or CheckResult(BatchResult("check")))
    rule = tmp_path / "check.yaml"
    rule.write_text("version: '1.0'\nchip: gh3220\nframe_ratio: 2\naccuracy:\n  enabled: true\n  ref_column: REF\n  online_column: ONLINE\n", encoding="utf-8")

    result = CliRunner().invoke(check_cmd, ["-r", str(rule), "--frame-ratio", "0.5", "--workers", "8"])

    assert result.exit_code == 0, result.output
    assert captured["request"].frame_ratio == 0.5
    assert captured["request"].chip_name == "gh3036"
    assert captured["request"].workers == 8


def test_check_rule_fills_unspecified_policy_values(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr("health_tools.api.run_check", lambda request, context=None: captured.setdefault("request", request) or CheckResult(BatchResult("check")))
    rule = tmp_path / "check.yaml"
    rule.write_text("version: '1.0'\nchip: gh3220\nframe_ratio: 2\naccuracy:\n  enabled: true\n  ref_column: REF\n  online_column: ONLINE\n", encoding="utf-8")

    result = CliRunner().invoke(check_cmd, ["-r", str(rule), "--workers", "8"])

    assert result.exit_code == 0, result.output
    assert captured["request"].frame_ratio == 2.0
    assert captured["request"].chip_name == "gh3220"
    assert captured["request"].workers == 8
```

- [ ] **Step 2: 运行测试确认 `-r` 尚不存在**

Run: `pytest tests/test_check_rules.py -k 'cli or rule_fills' -v`

Expected: FAIL，Click 报告未知选项 `-r`。

- [ ] **Step 3: 增加新 CLI 选项和解析器**

复用 `accuracy_options` 的阈值解析；新增严格解析函数：

```python
def parse_accuracy_min(value: str) -> AccuracyMarkRule:
    comparison, metric, minimum, category, *label = value.split(":", 4)
    return AccuracyMarkRule(
        id=f"{comparison}_{metric}_{len_seen}",
        comparison=comparison,
        metric=metric,
        min=float(minimum),
        category=category,
        label=label[0] if label else _default_mark_label(comparison, metric, float(minimum)),
    )
```

`--accuracy-min`、`--online-comp-gap` 使用 `multiple=True`，非法格式以 `click.BadParameter` 中文说明终止。

- [ ] **Step 4: 用 Click ParameterSource 合并配置**

给 `check_cmd` 增加 `@click.pass_context`，只对 YAML 允许的业务策略参数执行合并；输入/输出、sort、report、sort-output、workers、verbose 不参与规则合并，
`chip` 参与合并且 CLI 显式 `-c/--chip` 优先：

```python
def _effective(ctx, name, cli_value, rule_values, default):
    if ctx.get_parameter_source(name) == click.core.ParameterSource.COMMANDLINE:
        return cli_value
    if name in rule_values:
        return rule_values[name]
    return default
```

布尔双选项同样按 ParameterSource 判断，不能用 truthy 合并。CLI marks 只要出现任意一条，就整体替换规则 marks。

- [ ] **Step 5: 扩展 `CheckRequest`**

```python
rule_file: Optional[str] = None
accuracy_enabled: bool = False
accuracy_ref_column: Optional[str] = None
accuracy_online_column: Optional[str] = None
accuracy_comp_column: Optional[str] = None
accuracy_methods: Tuple[str, ...] = ()
accuracy_thresholds: Optional[Tuple[float, ...]] = None
accuracy_custom_thresholds: Tuple[Mapping[str, Any], ...] = ()
accuracy_inclusive: bool = False
accuracy_marks: Tuple[AccuracyMarkRule, ...] = ()
```

- [ ] **Step 6: 更新帮助和请求透传测试**

断言 `--help` 包含所有新增选项，并检查 `--sort` 模式在未提供 `--report` 时自动推导本次 check 的报告路径，
`--sort-output` 仍必须由 CLI/API 提供，规则不能覆盖这些运行路径。

- [ ] **Step 7: 运行 CLI 相关测试**

Run: `pytest tests/test_check_rules.py tests/test_reference_checker.py tests/test_progress.py -q`

Expected: PASS。

- [ ] **Step 8: 提交 CLI 合并能力**

```bash
git add src/health_tools/commands/check.py src/health_tools/commands/accuracy_options.py src/health_tools/api/models.py tests/test_check_rules.py tests/test_reference_checker.py tests/test_progress.py
git commit -m "feat: 支持 check 规则参数覆盖" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 4: 复用 offline 口径计算 Online/Comp 准确度

**Files:**
- Create: `src/health_tools/core/check_accuracy.py`
- Create: `tests/test_check_accuracy.py`
- Modify: `src/health_tools/api/models.py`

- [ ] **Step 1: 写失败测试固定共同边界和全零 Comp 行为**

```python
def test_check_accuracy_matches_offline_shared_boundary():
    frame = pd.DataFrame({
        "REF": [0, 80, 85, 90, 0],
        "ONLINE": [0, 84, 95, 90, 0],
        "COMP": [0, 82, 85, 100, 0],
    })
    result = calculate_check_accuracy(frame, config())
    assert result.online["samples"] == 3
    assert result.online["within_5"] == 66.67
    assert result.comp["within_5"] == 66.67


def test_check_accuracy_skips_all_zero_comp():
    frame = pd.DataFrame({"REF": [80, 81], "ONLINE": [80, 82], "COMP": [0, 0]})
    result = calculate_check_accuracy(frame, config())
    assert result.online["samples"] == 2
    assert result.comp is None
```

- [ ] **Step 2: 运行测试确认核心模块缺失**

Run: `pytest tests/test_check_accuracy.py -v`

Expected: ERROR/FAIL，无法导入 `health_tools.core.check_accuracy`。

- [ ] **Step 3: 增加结构化结果模型**

```python
@dataclass(frozen=True)
class CheckAccuracyResult:
    online: Optional[Mapping[str, float]] = None
    comp: Optional[Mapping[str, float]] = None
    matched_mark: Optional[AccuracyMarkRule] = None
```

- [ ] **Step 4: 实现准确度计算**

`calculate_check_accuracy` 必须直接调用：

```python
prepared = prepare_accuracy_columns({"ref": ref, "online": online, "comp": comp})
metric_df = pd.DataFrame(prepared.columns)
online = calculate_accuracy(metric_df, "ref", "online", methods, thresholds, inclusive, trim_zero_padding=False)
comp = calculate_accuracy(metric_df, "ref", "comp", methods, thresholds, inclusive, trim_zero_padding=False) if "comp" in active else None
```

缺少 ref/online 列返回明确验证错误；Comp 列未配置、缺失或全零时只跳过 Comp，不跳过文件。

- [ ] **Step 5: 运行准确度单元测试**

Run: `pytest tests/test_check_accuracy.py -q`

Expected: PASS。

- [ ] **Step 6: 与 offline 夹具做等价性回归**

使用相同数组分别调用 `calculate_check_accuracy` 和 `calculate_accuracy`，逐项断言 samples、MAE、RMSE、correlation、within 指标一致。

- [ ] **Step 7: 提交准确度核心**

```bash
git add src/health_tools/core/check_accuracy.py src/health_tools/api/models.py tests/test_check_accuracy.py
git commit -m "feat: 统计 check online 与 comp 准确度" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 5: 实现准确度标定和中文主要异常项

**Files:**
- Modify: `src/health_tools/core/check_accuracy.py`
- Modify: `src/health_tools/api/check_operation.py`
- Modify: `src/health_tools/core/checker.py`
- Modify: `tests/test_check_accuracy.py`
- Modify: `tests/test_acc_checker.py`

- [ ] **Step 1: 写失败测试固定 mark 语义和首条命中**

```python
def test_accuracy_marks_use_rule_order_and_percentage_point_gap():
    result = CheckAccuracyResult(
        online={"within_5": 70.0},
        comp={"within_5": 85.0},
    )
    marks = (
        AccuracyMarkRule("online_low", "online", "within_5", "accuracy_online_low", "Online ±5准确度低", min=80),
        AccuracyMarkRule("online_gap", "online_below_comp", "within_5", "accuracy_online_below_comp", "Online低于Comp 10个百分点", min_gap=10),
    )
    assert match_accuracy_mark(result, marks).id == "online_low"
```

- [ ] **Step 2: 写失败测试固定主要异常优先级**

```python
def test_primary_issue_places_accuracy_after_frame_warning():
    row = {
        "总异常(结果)": "PASS",
        "帧完整性(结果)": "WARNING",
        "准确度标定分类": "accuracy_online_low",
        "准确度标定说明": "Online ±5准确度低",
    }
    assert primary_issue(row) == "首帧非0"


def test_primary_issue_uses_accuracy_before_ipd():
    row = {
        "总异常(结果)": "FAIL",
        "帧完整性(结果)": "PASS",
        "准确度标定分类": "accuracy_online_low",
        "准确度标定说明": "Online ±5准确度低",
        "Ipd转换(结果)": "FAIL",
    }
    assert primary_issue(row) == "Online ±5准确度低"
```

- [ ] **Step 3: 运行测试确认匹配与摘要函数缺失**

Run: `pytest tests/test_check_accuracy.py tests/test_acc_checker.py -k 'mark or primary_issue' -v`

Expected: FAIL，函数未定义。

- [ ] **Step 4: 实现 mark 匹配**

```python
def match_accuracy_mark(result, marks):
    for mark in marks:
        if mark.comparison in {"online", "comp"}:
            metrics = getattr(result, mark.comparison)
            if metrics is not None and mark.metric in metrics and metrics[mark.metric] < mark.min:
                return mark
        elif mark.comparison == "online_below_comp":
            if result.online and result.comp:
                gap = result.comp.get(mark.metric) - result.online.get(mark.metric)
                if gap >= mark.min_gap:
                    return mark
    return None
```

准确度最低值使用严格 `< min`；Online 落后 Comp 使用 `comp - online >= min_gap`，单位为百分点。

- [ ] **Step 5: 建立单一优先级表**

在 `check_operation.py` 定义结构化优先级，不再让 `_sort_category` 与主要异常文案各写一套 if：

```python
PRIMARY_RULES = (
    ("frame", "帧不完整"),
    ("range", "数据范围异常"),
    ("acc_fail", "ACC异常"),
    ("acc_warning", "ACC警告"),
    ("timestamp", "时间戳异常"),
    ("center", "数据未居中"),
    ("reference", "金标异常"),
    ("frame_warning", "首帧非0"),
)
```

准确度分类随后动态插入，再处理 Ipd/扩展/total_fail/normal。

- [ ] **Step 6: 运行主要异常测试**

Run: `pytest tests/test_check_accuracy.py tests/test_acc_checker.py tests/test_check_sort.py -q`

Expected: PASS。

- [ ] **Step 7: 提交标定和摘要能力**

```bash
git add src/health_tools/core/check_accuracy.py src/health_tools/api/check_operation.py src/health_tools/core/checker.py tests/test_check_accuracy.py tests/test_acc_checker.py tests/test_check_sort.py
git commit -m "feat: 标定 check 准确度主要异常" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 6: 扩展主报告和精简报告

**Files:**
- Modify: `src/health_tools/api/check_operation.py`
- Modify: `src/health_tools/commands/check.py`
- Modify: `tests/test_acc_checker.py`
- Modify: `tests/test_reference_checker.py`
- Modify: `tests/test_check_accuracy.py`

- [ ] **Step 1: 写失败测试固定主报告列顺序**

```python
def test_check_report_places_primary_issue_and_accuracy_after_scene(tmp_path):
    header, row = run_report_fixture(tmp_path)
    scene = header.index("场景分类")
    assert header[scene + 1] == "主要异常项"
    assert header[scene + 2:scene + 6] == [
        "Online准确度样本数", "Online MAE", "Online RMSE", "Online相关系数"
    ]
    assert header[-1] == "文件相对路径"
    assert row[header.index("Online ±5BPM准确度")] == "66.67%"
```

- [ ] **Step 2: 写失败测试固定无准确度时的占位值**

未启用准确度时仍保留稳定列集；默认方法生成的列写 `-`，主要异常项仍正常生成。

- [ ] **Step 3: 运行报告测试确认新列缺失**

Run: `pytest tests/test_acc_checker.py tests/test_reference_checker.py tests/test_check_accuracy.py -k report -v`

Expected: FAIL，找不到 `主要异常项` 或 Online/Comp 指标列。

- [ ] **Step 4: 收敛 API/CLI 两套报告代码**

将 `commands/check.py::_save_report_csv` 变为对 `api/check_operation.py::_save_report` 的薄包装或删除未使用副本；报告列构造、百分比格式化和行构造只能有一个实现。

- [ ] **Step 5: 写入准确度列**

使用规则中 resolved methods 决定动态列；字段命名沿用 offline 的 `format_metric_name`，但增加 Online/Comp 中文前缀。`within_N` 格式化为百分比，MAE/RMSE/correlation 保留两位小数，samples 为整数。

- [ ] **Step 6: 扩展 compact 报告**

对命中 mark 的文件增加一行：

```text
检查项=准确度标定
状态=WARNING
通道=online 或 comp
异常占比=<命中的准确度百分比>
说明=<mark label>
```

为 compact header 新增 `说明`、`比较对象`、`准确度指标`、`准确度阈值` 四列。

- [ ] **Step 7: 运行报告测试**

Run: `pytest tests/test_acc_checker.py tests/test_reference_checker.py tests/test_check_accuracy.py -q`

Expected: PASS。

- [ ] **Step 8: 提交报告扩展**

```bash
git add src/health_tools/api/check_operation.py src/health_tools/commands/check.py tests/test_acc_checker.py tests/test_reference_checker.py tests/test_check_accuracy.py
git commit -m "feat: 输出 check 准确度与主要异常" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 7: 将准确度标定接入 sort 优先级

**Files:**
- Modify: `src/health_tools/api/check_operation.py`
- Modify: `src/health_tools/commands/check.py`
- Modify: `tests/test_check_sort.py`

- [ ] **Step 1: 写失败测试固定 sort 顺序**

```python
def test_sort_places_accuracy_after_frame_warning_before_ipd(tmp_path):
    rows = [
        report_row("frame_warning.csv", frame="WARNING", accuracy="accuracy_online_low", ipd="FAIL"),
        report_row("accuracy.csv", frame="PASS", accuracy="accuracy_online_low", ipd="FAIL"),
    ]
    stats = _sort_report(write_report(tmp_path, rows), tmp_path / "sorted")
    assert (tmp_path / "sorted/abnormal/frame_warning/frame_warning.csv").exists()
    assert (tmp_path / "sorted/abnormal/accuracy_online_low/accuracy.csv").exists()
```

- [ ] **Step 2: 运行测试确认当前把准确度列忽略**

Run: `pytest tests/test_check_sort.py -k accuracy -v`

Expected: FAIL，文件落入 ipd 或 normal。

- [ ] **Step 3: 让 `_sort_category` 读取报告标定列**

报告增加隐藏逻辑字段并写入 CSV：

```text
准确度标定分类
准确度标定说明
```

这两列是 sort 的稳定机器接口；`主要异常项` 仅用于展示，不能反向解析中文。

- [ ] **Step 4: 动态显示准确度分类统计**

CLI 固定分类顺序打印到 `frame_warning`，随后按规则 marks 顺序打印实际准确度 category，再打印 `agc/ipd/total_fail/normal`；未知扩展分类仍按名称排序。

- [ ] **Step 5: 运行 sort 测试**

Run: `pytest tests/test_check_sort.py -q`

Expected: PASS。

- [ ] **Step 6: 提交 sort 集成**

```bash
git add src/health_tools/api/check_operation.py src/health_tools/commands/check.py tests/test_check_sort.py
git commit -m "feat: 按准确度标定分拣 check 文件" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 8: 更新命令、规则和技能文档

**Files:**
- Modify: `docs/cmd_check.md`
- Modify: `docs/rules.md`
- Modify: `docs/commands.md`
- Modify: `.agents/skills/use-ghealth-tool/references/commands.md`
- Modify: `.agents/skills/use-ghealth-tool/references/workflows.md`
- Modify: `.agents/skills/use-ghealth-tool/references/rules.md`
- Modify: `tests/test_documentation.py`

- [ ] **Step 1: 写失败文档测试**

```python
def test_check_docs_cover_rule_accuracy_and_primary_issue():
    text = Path("docs/cmd_check.md").read_text(encoding="utf-8")
    for token in ("-r/--rule", "主要异常项", "Online准确度", "Comp准确度", "online_below_comp", "frame_warning"):
        assert token in text
```

- [ ] **Step 2: 运行测试确认文档尚未覆盖**

Run: `pytest tests/test_documentation.py -v`

Expected: FAIL，缺少新增关键词。

- [ ] **Step 3: 更新 `docs/cmd_check.md`**

必须写清：全部新增 CLI、准确度共同边界、每组比较、报告列顺序、主要异常优先级、mark 严格/包含边界、sort 目录、CLI/规则优先级和两个完整命令示例。

- [ ] **Step 4: 更新 `docs/rules.md`**

新增 `check` 规则章节，原样包含完整 YAML，逐字段表格说明 chip、timestamp/reference/accuracy 列和 marks；明确
`input/output/sort/report/sort_output/workers/verbose` 不允许出现在 YAML，规则导航表将 `check` 改为 `-r/--rule`；
芯片可写在 YAML，但显式 `-c/--chip` 或 API 请求值覆盖它，输入/输出和 sort 路径仍只能由外部参数提供。

- [ ] **Step 5: 更新技能参考**

明确执行 `check -r` 前应 `validate`；`check --sort` 会移动文件；准确度必须确认 ref/online/comp 列；Comp 全零会跳过 Comp 比较。

- [ ] **Step 6: 运行文档测试**

Run: `pytest tests/test_documentation.py tests/test_check_rules.py -q`

Expected: PASS。

- [ ] **Step 7: 提交文档**

```bash
git add docs/cmd_check.md docs/rules.md docs/commands.md .agents/skills/use-ghealth-tool/references/commands.md .agents/skills/use-ghealth-tool/references/workflows.md .agents/skills/use-ghealth-tool/references/rules.md tests/test_documentation.py
git commit -m "docs: 补充 check 准确度规则与分拣" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 9: 全量验证和最终提交审计

**Files:**
- Verify only

- [ ] **Step 1: 确认导入当前工作区**

Run: `python -c "import health_tools; print(health_tools.__file__)"`

Expected: 路径位于当前仓库 `src/health_tools/__init__.py`。

- [ ] **Step 2: 验证内置完整规则**

Run: `ghealth_tool validate src/health_tools/rules/check/default.yaml --type check --strict`

Expected: 验证成功，无未知字段。

- [ ] **Step 3: 运行目标测试**

Run: `pytest tests/test_check_accuracy.py tests/test_check_rules.py tests/test_check_sort.py tests/test_acc_checker.py tests/test_reference_checker.py -q`

Expected: PASS。

- [ ] **Step 4: 运行全量质量检查**

```bash
black --check src/ tests/
ruff check src/ tests/
mypy src/
pytest
```

Expected: 全部通过；若出现既有 warning，记录但不把它误报为本功能失败。

- [ ] **Step 5: 审计工作区和提交历史**

```bash
git diff --check
git status --short
git log --oneline -9
```

Expected: 无未提交的本任务文件；提交均含规定的 `Co-Authored-By` trailer。

## 自审结论

- 需求覆盖：报告分类后准确度、主要异常项、Online/Comp 对 Ref、offline 口径、两类标定、sort 优先级、`-r`、完整规则声明均有对应任务。
- 边界明确：准确度低于阈值使用 `<`；Online 落后 Comp 使用百分点差 `>=`；缺失/全零 Comp 不阻断 Online；未知旧报告仍保留 `total_fail`。
- 单一事实来源：准确度算法复用 `utils.accuracy`，异常优先级由同一结构同时驱动主要异常和 sort，报告写入收敛为单实现。
- 无占位项：所有新增字段、目录名、列名、命令和测试期望均已确定。
