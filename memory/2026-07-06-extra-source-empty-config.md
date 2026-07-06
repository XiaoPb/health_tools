# 2026-07-06 extra_source 空配置误查找

## Symptom

convert 规则未配置 `extra_source` 时，转换过程中仍输出 `未找到 extra_source 文件` 日志。

## Root cause

`ConvertRule.extra_source` 默认值是空字典 `{}`，`DataConverter._extra_source_configs()` 将空字典当作有效配置返回 `[{}]`。后续查找逻辑拿到空配置后找不到 `path/suffix/pattern`，因此误报未找到 extra_source 文件。

## Fix

`_extra_source_configs()` 过滤空字典；列表形式的 `extra_source` 中空字典也安静跳过。

## Evidence

- `pytest tests/test_convert.py`：16 passed
- `ruff check src/ tests/`：passed
- `black --check src/ tests/`：passed
- `pytest`：125 passed

