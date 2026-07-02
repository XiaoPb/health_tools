# Command Performance Help Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化所有 CLI 命令的启动/help 性能，并修复大数据量下最明显的转换与分割慢路径。

**Architecture:** 先让顶层 `--help` 使用静态命令摘要，避免为了显示短说明导入 pandas/matplotlib/scipy 等重依赖。再把子命令模块的重依赖延迟到真实执行路径中，并对转换、分割中的逐行循环改为 pandas/numpy 向量化实现。

**Tech Stack:** Click、pandas、numpy、pytest、PowerShell `Measure-Command`。

---

### Task 1: 静态化顶层 help

**Files:**
- Modify: `src/health_tools/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: 写 help 别名断言**

```python
def test_cli_help_lists_aliases_without_loading_commands():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "parse (p)" in result.output
    assert "convert (cv)" in result.output
```

- [ ] **Step 2: 修改 `LazyGroup.format_commands` 使用静态短说明**

```python
COMMAND_HELP = {
    "parse": "log解析转CSV命令",
    "plot": "数据绘图命令",
    "classify": "数据分类命令",
    "convert": "CSV格式转换",
    "info": "查看规则和文件信息",
    "validate": "验证规则文件",
    "split": "数据分割命令",
    "process": "批量处理命令",
    "factory": "工厂测试数据分析",
    "config": "配置管理",
    "evaluate": "评估指标命令",
    "offline": "离线评估流程",
    "check": "数据质量检查",
    "ui": "启动图形界面",
}
```

- [ ] **Step 3: 验证**

Run: `pytest tests/test_cli.py -q`
Expected: 全部通过。

### Task 2: 延迟子命令重依赖

**Files:**
- Modify: `src/health_tools/commands/parse.py`
- Modify: `src/health_tools/commands/split.py`
- Modify: `src/health_tools/commands/convert.py`
- Modify: `src/health_tools/commands/classify.py`
- Modify: `src/health_tools/commands/factory.py`
- Modify: `src/health_tools/commands/info.py`
- Modify: `src/health_tools/commands/process.py`
- Modify: `src/health_tools/commands/evaluate.py`
- Modify: `src/health_tools/commands/config.py`
- Modify: `src/health_tools/commands/offline.py`

- [ ] **Step 1: 将仅执行时需要的 core/pandas 导入移动到命令函数或 helper 内**

```python
def split_cmd(...):
    from health_tools.core.splitter import DataSplitter
    from health_tools.rules.loader import RuleLoader
    ...
```

- [ ] **Step 2: 对类型注解使用 `from __future__ import annotations` 或局部导入**

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
```

- [ ] **Step 3: 验证子命令 help**

Run: `pytest tests/test_cli.py -q`
Expected: `parse --help`、`convert --help`、`classify --help`、`split --help` 均通过。

### Task 3: 转换命令大数据优化

**Files:**
- Modify: `src/health_tools/core/converter.py`
- Test: `tests/test_convert.py`

- [ ] **Step 1: 增加 forward_fill 行为测试**

```python
def test_forward_fill_uses_previous_nonzero_value():
    import pandas as pd

    rule = ConvertRule(column_mapping={"frame": "FRAME_ID"}, forward_fill=["FRAME_ID"])
    converter = DataConverter(rule)
    df = pd.DataFrame({"frame": [0, 10, 0, 0, 13]})

    result = converter.convert(df)

    assert list(result["FRAME_ID"]) == [0, 10, 10, 10, 13]
```

- [ ] **Step 2: 用向量化替换 `_apply_forward_fill` 的 Python 行循环**

```python
series = pd.to_numeric(df[resolved], errors="coerce")
mask = series.ne(0) & series.notna()
if not mask.any():
    continue
df[resolved] = series.where(mask).ffill().fillna(series).astype(df[resolved].dtype, copy=False)
```

- [ ] **Step 3: 用批量判断降低 `_ensure_int64` 的列循环成本**

```python
float_cols = list(df.select_dtypes(include=["float"]).columns)
for col in float_cols:
    ...
```

- [ ] **Step 4: 验证**

Run: `pytest tests/test_convert.py -q`
Expected: 全部通过。

### Task 4: 分割命令大数据优化

**Files:**
- Modify: `src/health_tools/core/splitter.py`

- [ ] **Step 1: `split_by_column_value` 避免 `index.get_loc` 逐个查找**

```python
positions = np.flatnonzero(col_data.to_numpy() == value)
```

- [ ] **Step 2: `split_by_time` 使用向量化累计分组**

```python
elapsed = (times - times.iloc[0]).dt.total_seconds()
group_ids = np.floor(elapsed / seconds).astype(int)
```

- [ ] **Step 3: 验证**

Run: `pytest tests/test_check_sort.py tests/test_cli.py -q`
Expected: 全部通过。

### Task 5: 性能与质量回归

**Files:**
- No code changes.

- [ ] **Step 1: 运行测试**

Run: `pytest -q`
Expected: 全部通过。

- [ ] **Step 2: 测量 help 冷启动**

Run: `Measure-Command { python -m health_tools --help | Out-Null }`
Expected: 明显低于优化前约 800ms。

- [ ] **Step 3: 提交**

```bash
git add src/health_tools tests docs/superpowers/plans/2026-07-02-command-performance-help.md
git commit -m "fix: optimize command startup and data processing" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

## Self-Review

Spec coverage: 覆盖全部命令 help 路径、典型子命令 help、转换和分割两个大数据热点。

Placeholder scan: 无 TBD/TODO/implement later。

Type consistency: `DataConverter`、`ConvertRule`、`split_by_column_value`、`split_by_time` 名称与现有代码一致。
