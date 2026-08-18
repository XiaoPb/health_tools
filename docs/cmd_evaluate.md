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
| `--accuracy-thresholds` | 准确度阈值，逗号分隔；默认采用规则或 `5,10,15` |
| `--accuracy-inclusive/--accuracy-strict` | 阈值使用 `<=` 或 `<`；默认 strict |
| `-v/--verbose` | 显示失败/跳过文件明细 |

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
```
