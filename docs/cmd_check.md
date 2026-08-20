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
| `--timestamp-base-ms` | 指定期望相邻时间戳间隔（毫秒）；统计基准相对它偏差超过 20% 时为 FAIL |
| `--scene-regex` | 按文件相对路径提取场景；正则需包含 `(?P<scene>...)`，未匹配时为 `default` |
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
- 同目录固定生成 `check_report_compact.csv`，仅保留 `WARNING`/`FAIL` 检查项的通道长表，便于后续分析程序直接读取。所有占比统一按百分比显示并保留两位小数（如 `16.00%`）；ACC 行同时包含异常帧数和总帧数。AGC 证据同时包含变化次数、有效相邻对数和变化占比，避免用 PPG 通道样本数误算调光比例。
- `check_report.csv`、`check_report_compact.csv` 以及分拣清单均包含 `场景分类` 列；未指定正则或未匹配时显示 `default`。

## 各检查项判断逻辑

### 数据范围（`range`）

读取芯片规则中的数据列，逐个数值化后检查是否落在芯片允许范围内（边界值算正常）。全 0 的预留通道会跳过，不计入异常分母；没有可检查的数据列直接 `FAIL`。

异常比例为所有有效数据单元格中超范围单元格的比例，默认 `--range-ratio 1%`：

- 无超范围值：`PASS`
- 异常比例 `≤ 1%`：`WARNING`
- 异常比例 `> 1%`：`FAIL`

### 帧完整性（`frame`）

读取 `FRAME_ID`（或芯片规则指定的帧列）并统计丢失帧数：GH3220 按 `0~255` 循环帧号检查，其他芯片按递增帧号检查。丢失率计算为：

```text
丢失帧数 / (实际帧数 + 丢失帧数) × 100%
```

默认 `--frame-ratio 1%`，按异常比例三态判断。缺少帧列、帧列没有有效数值时直接 `FAIL`。

### 数据居中（`center`）

先计算 `Rawdata - adc_offset`，再按 ADC 满量程判断：低于 `0.30 * full_scale` 或高于 `0.85 * full_scale` 的点属于偏离居中；边界值算正常。另行统计不高于 `0.05 * full_scale` 的接近 0 点，以及不低于 `0.95 * full_scale` 的接近满量程点。

全 0 预留通道跳过。异常比例为偏离居中的有效点占比，默认 `--center-ratio 5%`：异常比例 `≤ 5%` 为 `WARNING`，超过 `5%` 为 `FAIL`；没有异常为 `PASS`。缺少数据列直接 `FAIL`。

### Ipd 转换（`ipd`）

按行使用 `Rawdata`、AGC 增益和芯片参数计算期望 `Ipd_pA`，检查实际值与期望值的绝对误差。误差不超过 `--tolerance`（默认 `±50 pA`）算正常；全 0 预留通道跳过。

超差点比例默认允许 `1%`（`--ipd-ratio`）：无超差为 `PASS`，比例不超过阈值为 `WARNING`，超过阈值为 `FAIL`。缺少 Ipd/Rawdata 列直接 `FAIL`；所有通道都是全 0 预留通道时为 `PASS` 并说明已跳过。

### ACC 异常（`acc`）

检测三类异常：

- 全零：XYZ 同一帧全部为 0；
- 静止：数值连续不变，默认使用 `--static-min 5` 检测最小连续段；
- 循环：固定序列至少重复两个完整周期，周期长度为 2~50，且序列幅度至少 20。

默认只将 XYZ 同时异常计入结果；`--acc-axis` 会把单轴静止/循环也计入。异常帧按索引去重后计算：

```text
异常帧数 / 总帧数 × 100%
```

默认 `--acc-ratio 1%`：无异常为 `PASS`，异常比例不超过阈值为 `WARNING`，超过阈值为 `FAIL`。缺少 ACC 列时无法检查，文件会被跳过并记录原因。

### AGC 调光（`agc`）

只统计每个 AGC 列相邻有效值的变化次数、有效相邻对数和变化比例，不把 AGC 变化单独计入文件总结果，也不会产生 `WARNING/FAIL`。缺失 AGC 列时按当前检查流程跳过该项。

### 时间戳间隔（`--check-timestamp`）

指定时间戳列后，先解析为毫秒并计算相邻间隔。任意负间隔直接 `FAIL`（时间戳倒退）；有效时间戳不足、无法解析或基准间隔无效也直接 `FAIL`。

其余间隔以中位数作为统计基准，单个间隔偏离基准超过 `--timestamp-ratio`（默认 `±20%`），或超过 `--timestamp-ms` 固定毫秒容差，就计为异常间隔。异常间隔比例默认允许 `1%`（`--timestamp-fail-ratio`），按 `PASS/WARNING/FAIL` 三态判断。

指定 `--timestamp-base-ms` 时，还会比较统计基准与期望基准；相对偏差严格大于 `20%` 直接 `FAIL`，等于 `20%` 不失败。

## 检查结果

每个检查项输出三态：

- `PASS`：无异常。
- `WARNING`：有异常，但异常比例不超过对应 `--*-ratio`；WARNING 仍表示文件存在数据问题。
- `FAIL`：异常比例超过阈值，或缺少必要列、数据无法解析、时间戳倒退/基准偏差超限等硬性条件触发失败。

比例阈值采用“**小于等于阈值为 WARNING，严格超过阈值为 FAIL**”。`总异常(结果)` 只输出 `PASS` 或 `FAIL`：单项全部为 PASS/WARNING 时总结果为 `PASS`，任意单项为 FAIL 时总结果为 `FAIL`。因此 WARNING 文件在默认 `--sort` 中会进入 `normal/`，需要重点关注精简报告中的 WARNING 行。

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

# 指定期望时间基准；实际间隔中位数偏离 40ms 超过20%时 FAIL
ghealth_tool check -i data/ --check-timestamp timestamp --timestamp-base-ms 40

# 从相对路径提取场景
ghealth_tool check -i data/ --scene-regex "subject\\d+_(?P<scene>rest|motion)_"

# 把 ACC 单轴异常也计入结果
ghealth_tool check -i data/ --checks acc --acc-axis

# 按检查报告分拣
ghealth_tool check --sort --report data/check_report.csv --sort-output sorted/
```
