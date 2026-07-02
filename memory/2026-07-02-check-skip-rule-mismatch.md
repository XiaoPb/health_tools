# check 跳过规则不匹配文件调试记录

## Symptom

`check` 对列结构不符合芯片规则的 CSV 继续执行各项检查，输出多个 `Fail`，例如“未找到数据列”“未找到帧号列”“未找到 Ipd 或 Rawdata 列”。

## Root Cause

`health_tools.commands.check` 只在无法识别芯片、规则加载失败、读取失败或空文件时跳过。只要芯片规则能加载，就会进入所有检查项；列结构是否符合该芯片规则由每个检查项单独失败返回，导致规则不匹配文件被报告为异常文件。

## Fix

在 `_process_file` 读取 CSV 后、创建 `FileCheckReport` 前增加 `_check_rule_mismatch` 预检。预检按本次启用的检查项验证必需列，缺少时返回跳过原因，不生成报告。

默认检查以 PPG 主结构列为匹配依据：数据列、帧号列、GH3036 的 Ipd/Rawdata 列。ACC 仅在用户显式指定 `--checks acc` 时作为必需列，避免没有 ACC 的合法数据被默认跳过。

## Evidence

新增测试 `test_check_skips_csv_when_columns_do_not_match_rule` 覆盖 `gh3036` 规则读取 `foo,bar` CSV 时跳过，不生成 `check_report.csv`。

验证命令：

```powershell
$env:PYTHONPATH='src'; pytest -q
black --check src tests
ruff check src tests
```

结果：85 passed，格式检查和 lint 均通过。
