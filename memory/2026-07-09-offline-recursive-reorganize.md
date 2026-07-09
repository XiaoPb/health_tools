# offline 多版本准确度汇总找不到 vshb

## Symptom

多版本 offline 输出目录形如 `GH3036_RES/<version>/数据整理/`，目录中实际存在 `_result.vshb`，但命令提示：

- `WARN 未找到有效的 .vshb 结果文件`
- `WARN 未生成多版本准确度汇总`

## Root Cause

`calculate_offline_accuracy()` 本身会递归查找 `_result.vshb`，问题发生在更前面的整理阶段。
`reorganize_output()` 只遍历 `output_dir.iterdir()` 第一层文件；如果结果文件已经位于子目录
或已有 `数据整理/` 下，整理阶段不会收集这些文件，随后命令只对空的 `数据整理/` 做准确度统计。

## Fix

`reorganize_output()` 改为递归扫描 `output_dir.rglob("*")`，同时跳过目标 `数据整理/` 目录内
已有文件，避免重复搬动已整理结果。

## Verification

新增命令层回归测试覆盖 `GH3036_RES/<version>/数据整理/` 结构下，多版本 `--no-run`
可生成总准确度 CSV。

`pytest tests/test_offline.py tests/test_progress.py` 和 `pytest` 均通过。
