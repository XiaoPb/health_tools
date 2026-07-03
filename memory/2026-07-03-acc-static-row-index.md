# ACC静止阈值和行号显示排查记录

## 症状

使用 `--static-min 10` 时，ACC汇总表仍出现 `静止检测-XYZ` 的 `最长帧` 为 1、4、5、6 等小于阈值的记录。GH3220 的帧号是 0-255 循环，异常表显示循环帧号也不便于定位原始行。

## 根因

单轴静止段先按 `static_min` 过滤，但三轴静止交集段使用 `min_length=1` 再次取连续段，导致三个单轴静止段的短重叠也被记为 `static_xyz`。

ACC报告展示帧号复用了数据帧号列。对 GH3220 来说，帧号循环重复，展示 `framed_id` 无法唯一定位异常位置。

## 修复

- `static_xyz` 交集段也按 `self.static_min` 过滤。
- ACC异常报告展示位置新增 GH3220 特例：GH3220 使用 0-based 行号展示；其他芯片仍优先使用帧号列。
- 帧完整性检查不变，GH3220 仍按 0-255 循环帧号计算。

## 验证

- `pytest tests/test_acc_checker.py tests/test_check_sort.py tests/test_rule_loader.py -v`：58 passed。
- 使用 `F:\Downloads\DVT血氧专项` 跑 `ghealth_tool check --checks acc --static-min 10 --acc-ratio 5`：
  - 613 个 CSV 中 601 成功，12 个因缺少 ACC 列跳过。
  - 默认 ACC 结果 601 文件全部通过，其中 5 个为 Warning。
  - `静止检测-XYZ` 最小 `最长帧` 为 10。
  - GH3220 异常展示位置为行号，例如 545、888、910。
