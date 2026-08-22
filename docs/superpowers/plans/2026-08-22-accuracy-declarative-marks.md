# 准确度声明式判断扩展实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 check 的准确度指标和标定条件都能通过 YAML 声明式扩展，支持新增比较类型、指标和阈值标准，同时保持现有 `online`、`comp`、`online_below_comp` 配置兼容。

**Architecture:** 保留旧版 `AccuracyMarkRule` 输入作为兼容格式，在规则加载后归一化为统一的左值、右值、运算符和阈值条件。校验器负责拒绝无法安全解释的表达式，匹配器只执行白名单运算，不执行 YAML 中的任意 Python 表达式。报告仍按 `marks` 的声明顺序选择首个命中项。

**Tech Stack:** Python 3.9+, dataclasses, PyYAML, pandas, pytest, Ruff, mypy。

---

## 现状评估

`test_data/data_gh3036_offline/check_moto.yaml` 当前包含：

```yaml
comparison: online_below_comp_10
comparison: online_below_comp_5
```

当前校验器只允许 `online`、`comp`、`online_below_comp`，因此该文件会返回：

```text
marks[0].comparison 仅支持 online、comp、online_below_comp
marks[1].comparison 仅支持 online、comp、online_below_comp
```

当前已经支持的扩展边界：

- `accuracy.methods`：`std`、`rmse`、`mae`、`mape`、`bias`、`correlation`、`r2`、`within_N`。
- `accuracy.thresholds`：按固定值或参考值百分比计算自定义命名指标。
- `accuracy.marks`：只能对 Online/Comp 单项指标下限，或 Online 与 Comp 的指标差值进行标定。

因此，新增统计指标大多可以直接通过 YAML 完成；新增比较关系或判定标准目前不能仅靠 YAML 完成，需要扩展规则模型、校验器、加载器和匹配器。

## 目标 YAML 语法

保留旧写法：

```yaml
marks:
  - id: online_below_comp_10
    comparison: online_below_comp
    metric: within_5
    min_gap: 10
    label: Online低于Comp 10个百分点
    category: accuracy_online_below_comp_10
```

新增推荐写法：

```yaml
marks:
  - id: online_below_comp_10
    left: online.within_5
    operator: diff_gte
    right: comp.within_5
    threshold: 10
    label: Online低于Comp 10个百分点
    category: accuracy_online_below_comp_10

  - id: online_mae_high
    left: online.mae
    operator: gte
    threshold: 8
    label: Online MAE不低于8 bpm
    category: accuracy_online_mae_high

  - id: online_vs_comp_ratio
    left: online.within_5
    operator: ratio_lt
    right: comp.within_5
    threshold: 0.9
    label: Online准确度低于Comp的90%
    category: accuracy_online_comp_ratio
```

第一阶段只支持以下白名单运算：

- `lt`、`lte`、`gt`、`gte`：左指标与固定 `threshold` 比较。
- `diff_gte`、`diff_gt`：`right - left` 与固定 `threshold` 比较，兼容 `online_below_comp`。
- `ratio_lt`、`ratio_lte`：`left / right` 与固定 `threshold` 比较，右值为 0 或缺失时不命中。

不支持任意表达式、函数调用、字段下标或跨文件聚合，避免规则文件变成不受控脚本。

### Task 1: 固化当前能力和目标语法的回归测试

**Files:**
- Modify: `tests/test_check_accuracy.py`
- Modify: `tests/test_check_rules.py`
- Test data: `test_data/data_gh3036_offline/check_moto.yaml`

- [ ] **Step 1: 写出现状失败测试**

增加测试，确认 `check_moto.yaml` 当前会被校验器拒绝，并锁定错误信息；同时增加目标语法的解析失败测试，确保实现前测试明确失败。

```python
def test_check_moto_rule_reports_unsupported_comparison():
    errors = RuleValidator.validate(load_yaml("test_data/data_gh3036_offline/check_moto.yaml"), "check")
    assert any("仅支持 online、comp、online_below_comp" in error for error in errors)
```

- [ ] **Step 2: 运行测试确认失败基线**

运行：`pytest tests/test_check_accuracy.py tests/test_check_rules.py -q`

预期：新增目标语法测试失败，现有旧语法测试保持通过。

### Task 2: 扩展准确度标定规则模型和 YAML 加载

**Files:**
- Modify: `src/health_tools/models/rules.py`
- Modify: `src/health_tools/rules/loader.py`
- Modify: `src/health_tools/rules/validator.py`
- Test: `tests/test_check_rules.py`

- [ ] **Step 1: 为 `AccuracyMarkRule` 增加归一化字段**

保留现有字段 `comparison`、`metric`、`min`、`min_gap`，新增可选字段 `left`、`operator`、`right`、`threshold`，并规定旧字段和新字段不能混用。

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
    left: Optional[str] = None
    operator: Optional[str] = None
    right: Optional[str] = None
    threshold: Optional[float] = None
```

- [ ] **Step 2: 严格校验字段组合**

在 `RuleValidator._validate_check_accuracy` 中允许旧格式三种 `comparison`，并允许新格式 `left/operator/right/threshold`。`left`、`right` 使用 `online.<metric>` 或 `comp.<metric>` 格式；二元运算必须有 `right`；运算符只能是 `lt/lte/gt/gte/diff_gte/diff_gt/ratio_lt/ratio_lte`；阈值必须是有限数；禁止未知字段、空路径和新旧字段混用。

- [ ] **Step 3: 加载新旧两种格式为同一模型**

在 `RuleLoader.load_check_rule` 中把旧格式映射为等价条件：

```text
online + min       -> left=online.metric, operator=lt, threshold=min
comp + min         -> left=comp.metric, operator=lt, threshold=min
online_below_comp  -> left=online.metric, operator=diff_gte,
                      right=comp.metric, threshold=min_gap
```

新格式直接构造对应字段，并保留原字段用于报告显示和兼容调用方。

- [ ] **Step 4: 运行规则测试**

运行：`pytest tests/test_check_rules.py -q`

预期：旧格式和新格式均通过校验、加载后字段一致，非法运算符和非法路径被拒绝。

### Task 3: 实现白名单条件匹配器

**Files:**
- Modify: `src/health_tools/core/check_accuracy.py`
- Test: `tests/test_check_accuracy.py`

- [ ] **Step 1: 写匹配器行为测试**

覆盖 `online.mae gte 8`、`comp.within_5 lt 80`、`comp.within_5 - online.within_5 >= 10`、`online.within_5 / comp.within_5 < 0.9`，以及缺失指标、空结果、Comp 为 0 时不命中比例规则；多条规则必须按 YAML 顺序返回第一条命中规则。

- [ ] **Step 2: 实现指标路径解析和运算分派**

新增私有函数：

```python
def _metric_value(result: CheckAccuracyResult, path: str) -> Optional[float]:
    ...

def _matches_declarative_mark(result: CheckAccuracyResult, mark: AccuracyMarkRule) -> bool:
    ...
```

所有值必须来自 `result.online` 或 `result.comp` 的已计算指标；未知路径返回 `None`。运算分派使用显式字典或 `if` 分支，不使用 `eval`。

- [ ] **Step 3: 保留旧匹配行为并统一入口**

让 `match_accuracy_mark()` 统一调用新条件匹配；只含旧字段的对象走兼容转换，确保现有报告、sort 分类和 `marks` 顺序行为不变。

- [ ] **Step 4: 运行准确度测试**

运行：`pytest tests/test_check_accuracy.py -q`

预期：所有新旧匹配测试通过。

### Task 4: 更新示例规则和文档

**Files:**
- Modify: `test_data/data_gh3036_offline/check_moto.yaml`
- Modify: `docs/rules.md`
- Modify: `docs/cmd_check.md`
- Test: `tests/test_check_rules.py`

- [ ] **Step 1: 修正示例 YAML**

将当前不受支持的比较类型改为合法声明式规则：

```yaml
- id: online_below_comp_10
  left: online.within_5
  operator: diff_gte
  right: comp.within_5
  threshold: 10
  label: Online低于Comp 10个百分点
  category: accuracy_online_below_comp_10
```

- [ ] **Step 2: 更新规则文档**

在 `docs/rules.md` 明确区分 `methods`、`thresholds`、`marks` 的职责，记录旧格式兼容范围、新格式字段、白名单运算符、缺失值和除零行为，以及 `marks` 顺序决定优先级。同步删除或修正文档中仍描述已删除 check CLI 准确度参数的段落。

- [ ] **Step 3: 增加完整 YAML 校验测试**

确认示例文件能通过：

```powershell
python -c "from health_tools.rules.loader import RuleLoader; RuleLoader.load_check_rule('test_data/data_gh3036_offline/check_moto.yaml'); print('ok')"
```

### Task 5: 端到端验证和提交

**Files:**
- No new files

- [ ] **Step 1: 运行定向测试**

运行：`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest tests/test_check_accuracy.py tests/test_check_rules.py tests/test_check_sort.py -q`，预期全部通过。

- [ ] **Step 2: 运行静态检查**

运行：`ruff check src/ tests/`、`black --check src/ tests/`、`mypy src/`。预期本次涉及文件无新增问题；全仓已有问题需要单独记录，不修改无关内容。

- [ ] **Step 3: 使用示例数据执行 check**

使用该规则对 `test_data/data_gh3036_offline/fail_category` 执行 check，确认报告中的 `主要异常项`、准确度列和准确度分类目录分别对应命中的第一条 mark。

- [ ] **Step 4: 提交**

```powershell
git add src/health_tools/models/rules.py src/health_tools/rules/loader.py src/health_tools/rules/validator.py src/health_tools/core/check_accuracy.py tests/test_check_accuracy.py tests/test_check_rules.py test_data/data_gh3036_offline/check_moto.yaml docs/rules.md docs/cmd_check.md
git commit -m "feat: 扩展check准确度声明式标定规则" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

## 自审结论

- 已覆盖当前 YAML 中两个不支持的比较类型及修复方式。
- 保留现有 YAML 写法，避免已有规则立即失效。
- 新增规则仅允许白名单字段和运算，未引入任意表达式执行风险。
- `methods`、`thresholds` 和 `marks` 的职责清晰分离，新增统计指标与新增判定关系分别处理。
- 未把输入/输出路径或运行参数放入 YAML，符合当前 check 规则约定。
