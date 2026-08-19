# check 命令

检查 PPG/ACC 数据完整性和正确性，并可按检查报告分拣正常/异常文件。别名：`chk`。

## 用法

```bash
ghealth_tool check -i <input> [options]
ghealth_tool chk -i <input> [options]
ghealth_tool check --sort --sort-output <output_dir> [--report <check_report.csv>]
```

## 参数

| 参数 | 说明 |
|------|------|
| `-i/--input` | 输入 CSV 文件或目录，普通检查模式必需 |
| `-c/--chip` | 芯片型号，不指定则尝试从 CSV info 行自动识别 |
| `--checks` | 指定检查项：`range,ipd,frame,center,acc,agc`，默认全部 |
| `--tolerance` | Ipd 转换误差容忍度，单位 pA，默认 50 |
| `--static-min` | ACC 静止检测最小连续帧数，默认 5 |
| `--range-ratio` | 数据范围异常允许比例，默认 1% |
| `--frame-ratio` | 帧丢失允许比例，默认 1% |
| `--center-ratio` | 数据居中异常允许比例，默认 5% |
| `--ipd-ratio` | Ipd 超差允许比例，默认 1% |
| `--acc-ratio` | ACC 异常帧允许比例，默认 1% |
| `--acc-axis` | 将 ACC 单轴静止或循环异常也计入检查结果；默认只统计 XYZ 联合异常 |
| `--check-timestamp` | 指定时间戳列并检查相邻间隔稳定性 |
| `--timestamp-ratio` | 时间戳间隔百分比容差，默认 20% |
| `--timestamp-ms` | 时间戳间隔固定毫秒容差 |
| `--timestamp-fail-ratio` | 时间戳异常间隔允许比例，默认 1% |
| `-o/--output` | 检查报告 CSV 输出路径，默认 `<path>/check_report.csv` |
| `--sort` | 读取检查报告并分拣正常/异常文件 |
| `--report` | 分拣使用的检查报告路径 |
| `--sort-output` | 分拣输出目录 |
| `-w/--workers` | 并行线程数，默认 4 |
| `-v/--verbose` | 显示失败/跳过文件明细和检查项详情 |

## 输出与异常汇总

- 普通检查模式使用进度条显示并行处理进度。
- 默认先输出“检查处理结果”汇总，按无法识别芯片、规则加载失败、读取失败、空文件、列结构不符合规则等原因统计。
- `-v/--verbose` 会显示跳过文件明细和每个检查项的详情。
- 有可检查文件时生成 `check_report.csv`；如果启用 ACC 且存在 Ipd FAIL，会额外生成 `ipd_detail_<文件名>.csv`。
- 同目录固定生成 `check_report_compact.csv`，仅保留 `WARNING`/`FAIL` 检查项的通道长表，便于后续分析程序直接读取。AGC 证据同时包含变化次数、有效相邻对数和变化占比，避免用 PPG 通道样本数误算调光比例。

数据居中统计先计算 `Rawdata - adc_offset`。低于居中下限或高于居中上限分别统计偏低/偏高占比；其中不高于
`0.05 * adc_full_scale` 记为接近 0，不低于 `0.95 * adc_full_scale` 记为接近满量程。
`AGC_INFO` 检查只统计相邻有效值变化次数，不会单独改变文件总状态。

## 检查结果

每个检查项输出三态：

- `PASS`：无异常。
- `WARNING`：有异常，但异常比例不超过对应 `--*-ratio`。
- `FAIL`：异常比例超过阈值，或缺少必要列导致无法检查。

`总异常(结果)` 只输出 `PASS` 或 `FAIL`，其中 `WARNING` 归为 `PASS`。

## 分拣报告

`--sort` 模式读取 `check_report.csv`，根据 `总异常(结果)` 将源文件移动到：

- `normal/`：总结果为 `PASS`
- `abnormal/`：总结果为 `FAIL`

报告必须包含 `文件相对路径` 列；分拣不会覆盖目标同名文件，并会输出
`normal_files.csv` 和 `abnormal_files.csv` 记录每个文件的处理状态。

## 示例

```bash
# 检查目录下所有 CSV
ghealth_tool check -i data/ -c gh3036

# 仅检查 ACC 和帧完整性
ghealth_tool chk -i data/ -c gh3036 --checks acc,frame

# 调整异常允许比例
ghealth_tool check -i data/ --frame-ratio 0.5 --acc-ratio 2 --center-ratio 5

# 检查时间戳间隔稳定性
ghealth_tool check -i data/ --check-timestamp timestamp --timestamp-ratio 20 --timestamp-ms 5

# 把 ACC 单轴异常也计入结果
ghealth_tool check -i data/ --checks acc --acc-axis

# 按检查报告分拣
ghealth_tool check --sort --report data/check_report.csv --sort-output sorted/
```
