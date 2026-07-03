# 鱼跃血氧 CSV 检查跳过排查记录

## 症状

使用 `gh3220_yuyue_spo2` 规则检查 `F:\Downloads\DVT血氧专项` 时，611 个 CSV 全部跳过，提示“列结构不符合规则，缺少 数据列、帧号列”。

## 根因

CSV 表头使用 `framed_id`、`ppg_ch0-23`、`acc_x/y/z`。检查器默认只会把 `CH0`、`Rawdata0`、`ch0` 这类列识别为原始数据列，因此需要在规则中显式配置 `check_columns.data`。

同时 `ChipRule` 已经定义了 `frame_column` 和 `acc_columns` 字段，但 `RuleLoader.load_chip_rule()` 构造 `ChipRule` 时没有传入这两个 YAML 字段，导致规则里写了 `frame_column: framed_id` 也不会生效。

## 修复

- `src/health_tools/rules/loader.py`：加载芯片规则时传入 `acc_columns` 和 `frame_column`。
- `C:\Users\lzh17\.ghealth_tools\rules\chip\gh3220_yuyue_spo2.yaml`：新增 `acc_columns` 与 `check_columns.data/agc`，显式指定鱼跃血氧数据列。
- `tests/test_rule_loader.py`：新增回归测试，确保加载器保留检查相关列配置。

## 验证

- `pytest tests/test_rule_loader.py tests/test_acc_checker.py -v`：46 passed。
- 单个 PPG+ACC 样例文件：从跳过变为成功进入检查，输出数据范围、帧完整性、数据居中和 ACC 异常结果。
- `LowSpo2\90-85\偏紧\坐姿` 抽样目录：5 个 CSV 全部进入检查，0 跳过。

## 后续注意

样例文件进入检查后，`数据范围` 仍显示 24/24 列超范围。原因是当前 GH3220 范围检查使用 `[2^23, 2^24]`，而这些 `ppg_ch` 数据虽大于 `2^23`，但仍被当前结果判为超范围，需要另行确认范围检查边界或显示文本语义。
