# VSHB Comp 与 Polar 准确度统计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 所有直接读取 VSHB 的准确度流程在 comp 有效时同步统计 comp vs polar，并在 comp 全为 0 或缺失时跳过。

**Architecture:** 在 `core/vshb.py` 的统一输出中加入可选 `comp` 标准列，表头按别名识别，无表头固定读取 polar 后一列。离线报告与 PSD 摘要只消费标准列并各自判断 comp 是否含正值，复用现有准确度计算和加权汇总逻辑。

**Tech Stack:** Python 3.9+、pandas、NumPy、pytest、Black、Ruff、mypy

---

### Task 1: 扩展 VSHB 标准解析结果

**Files:**
- Modify: `src/health_tools/core/vshb.py`
- Test: `tests/test_offline.py`

- [ ] **Step 1: 写入失败测试**

更新现有表头解析断言，使 `comp_hr` 和 `cmp_hr` 分别得到 `"comp": 72` 与
`"comp": 82`；新增 `comp` 别名测试。更新无表头解析断言，使索引 3 的值出现在
`"comp"`。

```python
assert df.iloc[0].to_dict() == {
    "time": 1,
    "offline": 73,
    "ref": 70,
    "online": 71,
    "comp": 72,
}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_offline.py -k "vshb_parser or vshb_reader" -v`

Expected: 新断言因结果缺少 `comp` 而失败。

- [ ] **Step 3: 实现最小解析改动**

将标准列扩为 `time, offline, ref, online, comp`。必需表头仍为现有四列，comp 从
`("comp_hr", "cmp_hr", "comp")` 中选择首个存在项，缺失时填充 `NaN`。位置读取固定使用
索引 3；不足 4 列时填充 `NaN`，不使原本有效的 VSHB 整体失败。

```python
VSHB_COLUMNS = ["time", "offline", "ref", "online", "comp"]
VSHB_COMP_HEADER_ALIASES = ("comp_hr", "cmp_hr", "comp")
VSHB_POSITIONAL_COMP_COLUMN = 3
```

- [ ] **Step 4: 运行解析测试确认通过**

Run: `pytest tests/test_offline.py -k "vshb_parser or vshb_reader" -v`

Expected: 所有选中测试通过。

### Task 2: 离线报告增加 Comp vs Polar

**Files:**
- Modify: `src/health_tools/core/offline.py`
- Modify: `src/health_tools/commands/offline.py`
- Test: `tests/test_offline.py`
- Test: `tests/test_progress.py`

- [ ] **Step 1: 写入失败测试**

构造一个带有效 polar 和 comp 的 VSHB，断言文件行包含 `MAE(comp)` 等指标；再构造 comp
全为 0 的文件，断言该文件不产生 comp 指标。混合文件的 `TOTAL` 断言 comp 汇总仅按有效
comp 文件的样本数加权。

```python
assert first["MAE(comp)"] == 2.0
assert pd.isna(zero_comp_row["MAE(comp)"])
assert total["MAE(comp)"] == 2.0
```

补充终端表测试，确认 `(comp)` 列归入“在线/离线准确度”表。

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_offline.py tests/test_progress.py -k "accuracy and (comp or tables)" -v`

Expected: 报告尚无 `(comp)` 指标，测试失败。

- [ ] **Step 3: 实现按文件判断与指标输出**

在 `core/offline.py` 新增正值判断函数。仅当 polar 有效且 comp 含正值时调用现有
`calculate_accuracy(metric_df, "ref", "comp", ACCURACY_METHODS)`，再通过
`_add_metric_columns(row, comp_metrics, "(comp)")` 写入。终端表的 polar 指标列筛选加入
`"(comp)"`。

```python
def _has_valid_comp(df: pd.DataFrame) -> bool:
    comp = pd.to_numeric(df["comp"], errors="coerce")
    return bool((comp > 0).any())
```

- [ ] **Step 4: 运行离线准确度测试确认通过**

Run: `pytest tests/test_offline.py tests/test_progress.py -k "accuracy or vshb" -v`

Expected: 所有选中测试通过，现有 polar 缺失降级逻辑不回归。

### Task 3: PSD 摘要增加 Comp vs Polar

**Files:**
- Modify: `src/health_tools/core/psd_plotter.py`
- Test: `tests/test_offline.py`

- [ ] **Step 1: 写入失败测试**

更新 overlay 断言包含 `comp`。调用 `_metric_text_rows` 时传入 comp 数组，断言有效 comp
追加第三行 `Comp vs Polar`，全 0 comp 保持两行，polar 无效时仍只有
`Online vs Offline`。

```python
assert rows[2].startswith("Comp vs Polar:")
assert len(zero_comp_rows) == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_offline.py -k "psd and (overlay or metric)" -v`

Expected: overlay 缺少 comp 或 `_metric_text_rows` 参数不匹配。

- [ ] **Step 3: 实现 PSD 数据流与条件摘要**

空 overlay、VSHB overlay 和绘图局部变量均加入 comp。`_metric_text_rows` 接受 comp 数组，
仅在 polar 与 comp 都含正值时追加 `_format_metric_line("Comp vs Polar", ...)`。不绘制 comp
折线，不改变图例。

- [ ] **Step 4: 运行 PSD 测试确认通过**

Run: `pytest tests/test_offline.py -k "psd" -v`

Expected: 所有 PSD 测试通过。

### Task 4: 文档、全量验证与提交

**Files:**
- Modify: `docs/cmd_offline.md`
- Modify: `docs/superpowers/plans/2026-07-16-vshb-comp-polar-accuracy.md`

- [ ] **Step 1: 更新命令文档**

说明报告在 polar 有效且 comp 非全 0 时增加 `(comp)` 指标；表头别名为 `comp_hr`、
`cmp_hr`、`comp`，无表头旧格式使用 polar 后一列；comp 全 0 或缺失时跳过。

- [ ] **Step 2: 运行格式和静态检查**

Run: `black --check src/ tests/`

Expected: 通过。

Run: `ruff check src/ tests/`

Expected: 通过。

Run: `mypy src/`

Expected: 通过。

- [ ] **Step 3: 确认导入来源并运行全量测试**

Run: `python -c "import health_tools; print(health_tools.__file__)"`

Expected: 路径位于当前工作区 `src/health_tools`。

Run: `pytest`

Expected: 全量测试通过。

- [ ] **Step 4: 检查差异并提交**

Run: `git diff --check`

Expected: 无空白错误。

明确暂存计划、实现、测试和命令文档文件，提交信息：

```text
feat: 统计 VSHB comp 与 polar 准确度

Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>
```
