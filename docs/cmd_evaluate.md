# evaluate 命令

批量评估心率或血氧结果，输出文件明细、异常列表和准确度汇总。别名：`eval`。

## 用法

```bash
ghealth_tool evaluate -i <input_dir> -o <output_dir> [options]
ghealth_tool eval -i <input_dir> -o <output_dir> [options]
```

## 参数

| 参数 | 说明 |
|------|------|
| `-i/--input` | 输入目录 |
| `-o/--output` | 输出目录 |
| `--type` | 评估类型：`hr` 或 `spo2`，默认 `hr` |
| `--ref-column` | 参考列名，覆盖规则配置 |
| `--pred-column` | 预测列名，覆盖规则配置 |
| `--ref-column-col` | 参考列索引，1-based，优先于列名 |
| `--pred-column-col` | 预测列索引，1-based，优先于列名 |
| `--chip` | 芯片型号，用于按芯片规则读取 CSV |
| `--rule` | 评估规则文件，默认随 `--type` 使用 `evaluate_hr.yaml` 或 `evaluate_spo2.yaml` |
| `--diff-threshold` | 参考值差分异常阈值 |
| `--stale-minutes` | 参考值长时间不变异常阈值（分钟） |
| `--filter` | 仅处理文件名包含指定字符的 CSV |
| `--accuracy-thresholds` | 固定准确度阈值，逗号分隔；未指定时由规则 `methods` 决定，无规则配置时默认 `5,10,15` |
| `--accuracy-inclusive/--accuracy-strict` | 阈值边界包含/严格模式；默认 strict，即 `abs(error) < threshold` |
| `-v/--verbose` | 显示失败/跳过文件明细 |

## 准确度统计口径

- 默认使用 strict 模式，固定阈值和规则中的命名阈值都按
  `abs(error) < threshold` 计入；指定 `--accuracy-inclusive` 后改为
  `abs(error) <= threshold`。`--accuracy-strict` 可显式恢复默认行为。
- evaluate 规则显式声明 `methods` 时使用规则方法，否则使用含 `5/10/15` 的默认方法；
  `thresholds` 始终作为额外的自定义命名指标。因此内置 SpO2 规则继续使用 `within_3`、
  `within_6`、`within_9`。显式 `--accuracy-thresholds` 只替换 `methods` 中固定数值形式的
  `within_N`；其他方法以及 `thresholds` 中自定义命名的固定阈值、百分比阈值均保留。
- 参考列或预测列如果没有任意一个 finite 且非 `0` 的值，则整列禁用，不参与有效边界、
  比较或汇总。剩余全部启用列共同确定首尾共享边界：从首个到最后一个“所有启用列均为
  finite 且非 `0`”的行截取同一切片。切片中间的 `0` 保留并参与正常误差计算，
  `NaN`/`Inf` 仅在每一对参考值与预测值计算时成对过滤。

## 输出文件

成功找到有效数据后会在输出目录生成：

| 文件 | 说明 |
|------|------|
| `file_details.csv` | 每个文件的分类、异常数量、样本数和准确度指标 |
| `anomaly_list.csv` | 仅包含检测到参考值异常的文件 |
| `accuracy_summary.csv` | 全量数据按分类聚合后的准确度指标 |
| `accuracy_filtered.csv` | 去除参考值异常后的准确度指标 |

## 输出与异常汇总

- 目录处理使用进度条显示进度。
- 默认输出“评估结果”汇总，成功文件不逐条打印。
- 空文件、读取失败、缺少参考列/预测列等会统计为跳过或失败。
- 使用 `-v/--verbose` 时显示文件明细和简短原因。

## 示例

```bash
# 心率评估
ghealth_tool evaluate -i ./result/ -o ./eval_out/ --type hr --chip gh3036

# 血氧评估，按列索引指定参考列和预测列
ghealth_tool eval -i ./result/ -o ./eval_out/ --type spo2 --ref-column-col 3 --pred-column-col 8

# 覆盖异常检测阈值
ghealth_tool evaluate -i ./result/ -o ./eval_out/ --diff-threshold 20 --stale-minutes 1.5

# 使用自定义固定阈值，并把等于阈值的误差计入
ghealth_tool evaluate -i ./result/ -o ./eval_out/ --accuracy-thresholds 3,6,9 --accuracy-inclusive
```
