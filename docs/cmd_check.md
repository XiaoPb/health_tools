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
| `-r/--rule` | check 规则文件路径或内置规则名；支持用户规则目录、包内规则和绝对路径 |
| `-c/--chip` | 芯片型号，不指定则尝试从 CSV info 行自动识别 |
| `--checks` | 指定检查项：`range,ipd,frame,center,acc,agc,ref`。不指定规则文件时默认执行 `range,ipd,frame,center,acc,agc`；`ref` 仅在显式指定且提供金标列时执行。使用 `-r` 时按规则文件中的 `checks` 声明执行 |
| `--tolerance` | Ipd 转换误差容忍度，单位 pA，默认 50 |
| `--static-min` | ACC 静止检测最小连续帧数，默认 5 |
| `--range-ratio` | 数据范围异常允许比例，默认 1% |
| `--frame-ratio` | 帧丢失允许比例，默认 1% |
| `--center-ratio` | 数据居中异常允许比例，默认 5% |
| `--ipd-ratio` | Ipd 超差允许比例，默认 1% |
| `--acc-ratio` | ACC 异常帧允许比例，默认 1% |
| `--acc-axis/--no-acc-axis` | 将 ACC 单轴静止或循环异常也计入检查结果；默认只统计 XYZ 联合异常 |
| `--check-timestamp` | 指定时间戳列并检查相邻间隔稳定性 |
| `--timestamp-ratio` | 时间戳间隔百分比容差，默认 20% |
| `--timestamp-ms` | 时间戳间隔固定毫秒容差 |
| `--timestamp-fail-ratio` | 时间戳异常间隔允许比例，默认 1% |
| `--timestamp-base-ms` | 指定期望相邻时间戳间隔（毫秒）；统计基准相对它偏差超过 20% 时为 FAIL |
| `--ref-hr-column` | 指定心率金标列名；指定后启用心率金标检查 |
| `--ref-spo2-column` | 指定血氧金标列名；指定后启用血氧金标检查 |
| `--ref-sample-rate` | 金标采样率（Hz），默认 25 |
| `--ref-stale-seconds` | 金标连续不变判定时长（秒），默认 5 |
| `--ref-step-threshold` | 金标相邻值阶跃阈值，默认 8；绝对变化严格大于该值判定阶跃 |
| `--ref-warning-seconds` | 金标异常起始警告窗口（秒），默认 10；窗口内异常为 WARNING，窗口外异常为 FAIL |
| `--reference-detail-output` | 输出金标异常文件的秒采样 `time,ref,online,comp` 证据 CSV 目录 |
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
- 同目录生成精简报告，文件名在完整报告主名后追加 `_compact`（例如 `custom.csv` 对应 `custom_compact.csv`），仅保留 `WARNING`/`FAIL` 检查项的通道长表，便于后续分析程序直接读取。所有占比统一按百分比显示并保留两位小数（如 `16.00%`）；ACC 行同时包含异常帧数和总帧数。AGC 证据同时包含变化次数、有效相邻对数和变化占比，避免用 PPG 通道样本数误算调光比例。
- 完整报告中的 ACC 异常帧列表以文本形式写入（前置 `'`），避免 Excel 自动识别为货币或科学计数格式；金标异常时间戳使用普通整数文本显示。
- 完整报告、对应的 `_compact` 精简报告以及分拣清单均包含 `场景分类` 列；未指定正则或未匹配时显示 `default`。
- 主报告在 `总异常(结果)` 后依次追加 `场景分类`、`主要异常项`，以及 Online/Comp 对 Ref 的准确度样本数、MAE、RMSE、相关系数和各个 `within_N` 百分比列。准确度列缺失时输出 `-`；配置已启用但没有有效样本时样本数为 `0`、指标为 `-`，不把缺列误报为 0%。
- Online/Comp 准确度沿用 offline 的共同有效边界规则：三列共同确定首尾边界，边界内 0 保留，NaN/Inf 在比较时过滤；全 0 Comp 不参与 Comp vs Ref。
- 准确度是否启用、列名、指标、阈值、边界和标定优先级全部由 `-r/--rule` 的 `accuracy` 块声明；CLI 不再提供准确度策略参数。未加载规则文件时不执行准确度统计。

`accuracy.marks` 统一使用声明式条件：`left`/`right` 为 `online.<metric>` 或
`comp.<metric>`，`operator` 支持 `lt/lte/gt/gte`、`diff_gte/diff_gt`、
`ratio_lt/ratio_lte`，并用有限数 `threshold` 判定。差值按 `right - left` 计算，比例按
`left / right` 计算；二元运算必须提供 `right`，指标缺失或比例除数为 0 时不命中。
mark 引用的指标必须由 `accuracy.methods` 或非空 `accuracy.thresholds` 项声明；旧的
`comparison/metric/min/min_gap` 格式不兼容，校验时会直接报错。多条 mark 按 YAML 顺序匹配，
第一条命中项决定主要异常说明和分拣目录。

启用准确度时，`check_report.csv` 的列顺序固定为：文件名、芯片、总异常结果、场景分类、主要异常项；随后为每个
`checks` 检查项的“状态/摘要”列，以及 ACC 证据列（启用 ACC 时）；最后部分的核心列顺序为：

```text
Online准确度样本数, Online MAE, Online RMSE, Online相关系数, Online ±5准确度, Online ±10准确度, Online ±15准确度,
Comp准确度样本数, Comp MAE, Comp RMSE, Comp相关系数, Comp ±5准确度, Comp ±10准确度, Comp ±15准确度,
准确度标定分类, 准确度标定说明,
文件相对路径
```

实际启用的 `within_N` 方法会按规则顺序替换对应的 `±N` 列；未启用的方法不生成列。`主要异常项`
只保留一个按异常优先级选出的中文摘要，例如 `帧不完整`、`首帧非0`、`Online ±5准确度低` 或
`Online低于Comp 10个百分点`。`accuracy.comp_column` 可以省略；省略时不生成 Comp 指标，
即使提供了 Comp 列但其有效样本全为 0，也会跳过 Comp vs Ref 统计。

## 各检查项判断逻辑

### 数据范围（`range`）

读取芯片规则中的数据列，逐个数值化后检查是否落在芯片允许范围内（边界值算正常）。全 0 的预留通道会跳过，不计入异常分母；缺少数据列时文件会被跳过，并在检查处理结果中记录列结构原因。

异常比例为所有有效数据单元格中超范围单元格的比例，默认 `--range-ratio 1%`：

- 无超范围值：`PASS`
- 异常比例 `≤ 1%`：`WARNING`
- 异常比例 `> 1%`：`FAIL`

### 帧完整性（`frame`）

读取 `FRAME_ID`（或芯片规则指定的帧列）并统计丢失帧数：首帧期望为 `0`；GH3220
按 `0~255` 循环帧号检查，其他芯片按递增帧号检查。丢失率计算为：

```text
丢失帧数 / (实际帧数 + 丢失帧数) × 100%
```

默认 `--frame-ratio 1%`，后续丢帧按异常比例三态判断。第一帧不是 `0`、但后续帧完全连续时，
结果固定为 `WARNING`，且不把开头缺失的帧计入丢帧率；如果后续同时存在丢帧，则仍按丢帧率
决定 `WARNING` 或 `FAIL`。缺少帧列时文件会被跳过并记录列结构原因；帧列存在但没有有效数值时记为 `FAIL`。

### 数据居中（`center`）

先计算 `Rawdata - adc_offset`，再按 ADC 满量程判断：低于 `0.30 * full_scale` 或高于 `0.85 * full_scale` 的点属于偏离居中；边界值算正常。另行统计不高于 `0.05 * full_scale` 的接近 0 点，以及不低于 `0.95 * full_scale` 的接近满量程点。

全 0 预留通道跳过。异常比例为偏离居中的有效点占比，默认 `--center-ratio 5%`：异常比例 `≤ 5%` 为 `WARNING`，超过 `5%` 为 `FAIL`；没有异常为 `PASS`。缺少数据列时文件会被跳过，并记录列结构原因。

### Ipd 转换（`ipd`）

按行使用 `Rawdata`、AGC 增益和芯片参数计算期望 `Ipd_pA`，检查实际值与期望值的绝对误差。误差不超过 `--tolerance`（默认 `±50 pA`）算正常；全 0 预留通道跳过。

超差点比例默认允许 `1%`（`--ipd-ratio`）：无超差为 `PASS`，比例不超过阈值为 `WARNING`，超过阈值为 `FAIL`。缺少 Ipd/Rawdata 列时文件会被跳过，并记录列结构原因；所有通道都是全 0 预留通道时为 `PASS` 并说明已跳过。

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

指定 `--timestamp-base-ms` 时，还会比较统计基准与期望基准；相对偏差严格大于 `20%` 直接 `FAIL`，等于 `20%` 不失败。缺少指定时间戳列时文件会被跳过并记录列结构原因；时间戳无法解析、倒退或有效点不足时记为 `FAIL`。

### 金标数据（`--ref-hr-column`、`--ref-spo2-column`）

只有显式指定对应列名时才会启动金标检查。指定 `--checks` 时使用 `ref` 检查项；未指定
`--checks` 时，只要指定金标列名也会自动检查。

心率金标有效范围为 `30-240`，血氧金标有效范围为 `70-100`，边界值正常。`0` 表示当前
时间没有金标数据，不参与范围、阶跃和静止判断；非零样本占比低于 `70%` 时金标异常。

阶跃和静止是两种独立异常：

- 阶跃：相邻有效金标值的绝对变化严格大于 `--ref-step-threshold`，默认 `8`。
- 静止：原始高频数据先从 Online 首个有限非零值开始按采样率取每秒第一帧，再按秒样本判断；
  连续相同有效值超过 `--ref-stale-seconds` 秒即异常。`TimeStamp`、Ref、Online、Comp
  始终取同一原始行。该秒采样也用于 Online/Comp 准确度，逐帧完整性、范围、ACC 等检查不降采样。
  若时间戳检查为 FAIL，则使用时间戳有效间隔中位数预测实际采样率进行抽样；时间戳正常时使用
  指定的 `--ref-sample-rate`（默认 25 Hz）。

任一条件异常都会使对应的“心率金标”或“血氧金标”检查项产生 `WARNING` 或 `FAIL`：异常发生在
起始 `--ref-warning-seconds` 秒内时为 `WARNING`，只要有异常发生在窗口外则为 `FAIL`。主报告摘要会写明
范围异常数、非零占比、阶跃次数和最长静止秒数；`check_report_compact.csv` 也会同步写入这些
指标及阈值列。缺少指定金标列时文件会被跳过并记录列结构原因；金标列存在但没有有效数值时记为 `FAIL`。

启用 `--reference-detail-output` 后，对金标检查为 `WARNING` 或 `FAIL` 的文件输出四列证据 CSV，目录
结构镜像输入目录；已有目标文件不会覆盖。Online 没有有效非零起点时金标明确失败，并输出表头。

## 检查结果

每个检查项输出三态：

- `PASS`：无异常。
- `WARNING`：有异常，但异常比例不超过对应 `--*-ratio`；WARNING 仍表示文件存在数据问题。
- `FAIL`：异常比例超过阈值，或缺少必要列、数据无法解析、时间戳倒退/基准偏差超限等硬性条件触发失败。

比例阈值采用“**小于等于阈值为 WARNING，严格超过阈值为 FAIL**”。`总异常(结果)` 只输出 `PASS` 或 `FAIL`：单项全部为 PASS/WARNING 时总结果为 `PASS`，任意单项为 FAIL 时总结果为 `FAIL`。因此未被专门分拣规则捕获的 WARNING 文件（例如数据范围、时间戳、数据居中、金标或 Ipd WARNING）在默认 `--sort` 中会进入 `normal/`，需要重点关注精简报告中的 WARNING 行。

## 分拣报告

`--sort` 模式读取 `check_report.csv`，按异常优先级为每个文件选择**唯一**分类；文件命中一个分类后只移动一次，并保留原始 `文件相对路径`：

1. `帧完整性(结果)=FAIL` → `abnormal/frame/`
2. `数据范围(结果)=FAIL` → `abnormal/range/`
3. `ACC异常(结果)=FAIL` → `abnormal/acc_fail/`
4. `ACC异常(结果)=WARNING` → `abnormal/acc_warning/`
5. `时间戳间隔(结果)=FAIL` → `abnormal/timestamp/`
6. `数据居中(结果)=FAIL` → `abnormal/center/`
7. `心率金标(结果)=FAIL` 或 `血氧金标(结果)=FAIL` → `abnormal/reference/`
8. `帧完整性(结果)=WARNING` → `abnormal/frame_warning/`
9. 准确度标定命中按规则声明顺序进入 `abnormal/<category>/`，例如
   `accuracy_online_low`、`accuracy_online_below_comp`；其优先级低于帧警告，高于 Ipd 和其他扩展检查项。
10. 低优先级检查项分别进入自身目录，例如 `Ipd转换(结果)=FAIL` → `abnormal/ipd/`；扩展
   报告中的未知检查项使用检查项名称作为目录名。
11. 旧报告只有 `总异常(结果)=FAIL`、没有失败单项时 → `abnormal/total_fail/`
12. 其余文件（包括只有数据范围、时间戳、数据居中、金标或 Ipd WARNING 的文件）→ `normal/`

例如 `sub/a.csv` 被判定为帧不完整时，目标路径为 `abnormal/frame/sub/a.csv`。如果同一文件同时有
多项异常，只按上面的第一项分类；因此明确的 FAIL 分类优先于首帧警告，首帧警告优先于 Ipd
等原低优先级检查项。

报告必须包含 `文件相对路径` 列；旧报告缺少具体检查项列时，会按可识别的列分类，只有总异常
结果时进入 `abnormal/total_fail/`。分拣不会覆盖目标同名文件，源文件不存在、路径非法或目标
已存在时记录为跳过。

正常文件生成 `normal_files.csv`，异常文件统一生成一个 `abnormal_files.csv`。异常清单新增 `分类`
列，常见值包括 `frame`、`range`、`acc_fail`、`acc_warning`、`timestamp`、`center`、
`reference`、`frame_warning`、`ipd` 和 `total_fail`；扩展检查项使用检查项名称。两个清单都
包含文件名、相对路径、目标路径、移动状态、原因和场景分类，不再生成 `other` 分类目录。

```text
abnormal_files.csv
normal_files.csv
```

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

# 检查心率和血氧金标
ghealth_tool check -i data/ --ref-hr-column REF_HR --ref-spo2-column REF_SPO2

# 使用 50 Hz 数据和可配置阶跃阈值
ghealth_tool check -i data/ --ref-hr-column hr_ref --ref-sample-rate 50 --ref-step-threshold 6

# 读取既有 check 报告分拣（目录输入仅用于推导 data/check_report.csv，不会在同一次调用中重新检查）
ghealth_tool check -i data/ --sort --sort-output sorted/
# 也可显式覆盖报告路径
ghealth_tool check --sort --report data/check_report.csv --sort-output sorted/
# 输出示例：sorted/abnormal/frame/<原相对路径>

# 使用完整 check 规则，规则中的 chip/列名/准确度策略可复用
ghealth_tool check -i data/ -r default.yaml
```
