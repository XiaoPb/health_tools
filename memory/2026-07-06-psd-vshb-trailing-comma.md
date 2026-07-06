# PSD折线错位：vshb行尾逗号导致表头列错位

## Symptom

`test_data/Data0625-Parsed-Counts-50Hz_gh3220_med_res` 绘制 PSD 图时，心率折线位置不对。

## Root Cause

该目录的 `_result.vshb` 有表头，但数据行末尾多一个逗号。`pandas.read_csv` 默认会把第一列推断为索引，导致列整体左移：`second` 被读成 `polar`，`algo_hr` 等列也跟着错位。PSD 绘图叠加折线时直接使用错位后的 `time` 列，因此折线横轴变成心率值范围。

## Fix

`src/health_tools/core/vshb.py` 的表头读取改为 `pd.read_csv(path, index_col=False)`，禁止自动索引推断，保留真实表头列。

## Evidence

修复后抽样首条记录恢复为 `time=20, offline=75, ref=71, online=0`，PSD 矩阵横轴为 `1..3600`，折线时间范围为 `20..3600`。

## Regression Test

`tests/test_offline.py::test_vshb_parser_keeps_header_columns_with_trailing_commas`

## Status

DONE
