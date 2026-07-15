# 规则文件格式

GHealth Tools 使用 YAML 描述 CSV、日志解析、转换、分类和评估行为。规则把设备差异和
项目配置从 Python 代码中分离出来，便于复用和审查。

## 规则目录与查找顺序

内置规则随 Python 包安装：

```text
src/health_tools/rules/
├── chip/
├── parse/
├── classify/
├── convert/
└── evaluate/
```

运行 `ghealth_tool config --init` 后，可在 `~/.ghealth_tools/rules/` 中放置同样的目录。
相对规则名按用户目录、内置目录、当前工作目录顺序解析；用户规则可覆盖同名内置规则。
绝对路径直接使用。

芯片通过 `--chip gh3220` 加载时会自动查找 `chip/gh3220.yaml`。其他规则通常通过
`--rule` 指定文件名或路径。

## 通用约定

- YAML 使用 UTF-8 编码。
- 行号从 1 开始；`info_row: 0` 表示没有信息行。
- `{start-end}` 展开数字范围，例如 `CH{0-3}` -> `CH0`、`CH1`、`CH2`、`CH3`。
- `rawdata[{0-1}]` 只展开花括号，结果为字面列名 `rawdata[0]`、`rawdata[1]`。
- 旧规则中的 `CH[0-3]` 仍可由通用列展开函数兼容，但新规则应使用花括号。
- 修改规则后先运行 `validate`（适用时），再用一个小文件执行目标命令。

## chip 规则

路径：`rules/chip/<chip>.yaml`。chip 规则定义标准 CSV 的读取方式、完整列顺序，以及
检查、产测和离线算法所需的芯片信息。

```yaml
version: "1.0"
chip: gh3220

csv:
  info_row: 1
  header_row: 2
  data_start_row: 3
  delimiter: ","
  encoding: utf-8

columns:
  - TimeStamp
  - FRAME_ID
  - ACCX
  - ACCY
  - ACCZ
  - CH{0-15}

frame_column: FRAME_ID
acc_columns:
  x: ACCX
  y: ACCY
  z: ACCZ

check_columns:
  data:
    - CH{0-15}
  agc:
    - AGC_INFO_CH{0-15}

factory_columns:
  - CH{0-15}

factory_config:
  sample_rate: 100
  snr: {skip_head_seconds: 10, skip_tail_seconds: 10, min_duration_seconds: 90}
  ctr: {skip_head_seconds: 1, skip_tail_seconds: 0, min_duration_seconds: 2}
  noise: {skip_head_seconds: 2, skip_tail_seconds: 0, min_duration_seconds: 4}

chip_info:
  adc_full_scale: 8388608
  adc_offset: 8388608
  adc_vref: 1.8
  tia_ratio: 2

hr_ref_column:
  default: 18
spo_ref_column:
  default: 18
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `version` | string | 规则版本，`validate` 要求存在 |
| `chip` | string | 芯片标识 |
| `csv` | object | CSV 行号、分隔符和编码 |
| `columns` | list | 完整列顺序；转换输出和离线预检会使用 |
| `frame_column` | string | 帧号列；未配置时检查器尝试自动识别 |
| `acc_columns` | object | X/Y/Z 三轴列；未配置时检查器尝试自动识别 |
| `check_columns` | object | `data`、`agc` 等检查专用列组 |
| `factory_columns` | list | 参与 SNR/CTR/Noise 计算的列 |
| `factory_config` | object | 采样率和三个指标的截取时长 |
| `chip_info` | object | ADC、TIA、增益和 LED 电流解释参数 |
| `gain_tia_map` | object | 增益等级到 TIA 电阻的映射 |
| `hr_ref_column` | object | 心率离线跑库参考列索引配置 |
| `spo_ref_column` | object | 血氧离线跑库参考列索引配置 |

`check_columns.data` 会覆盖基于常见列名的自动识别。离线输入预检要求文件表头与展开后的
`columns` 数量、名称和顺序完全相同。

## parse 规则

路径：`rules/parse/<name>.yaml`。单 pattern 规则用一个正则把日志行转换为一组列：

```yaml
version: "1.0"
description: GH3220 日志
chip: gh3220
regex: '^\[(.+?)\]\s+GH3220:\s*(\d+),(\d+),(\d+),(\d+)$'
columns: [timestamp, red, ir, green, aux]
separator: ','
```

`regex` 的捕获组数量必须等于展开后的 `columns` 数量。`chip` 或兼容字段 `target_chip`
可给解析命令提供默认目标芯片。

多 pattern 规则可从同一日志分别生成多组 CSV：

```yaml
version: "1.0"
description: 同时解析 PPG 和算法输出
patterns:
  ppg:
    regex: '^PPG:(\d+),(\d+)$'
    columns: [red, ir]
    separator: ','
  result:
    regex: '^RESULT:(\d+),(\d+)$'
    columns: [ref, pred]
    separator: ','
```

多 pattern 模式以 pattern 名区分输出。每个 pattern 的捕获组仍须与自己的列一一对应。

## classify 规则

路径：`rules/classify/<name>.yaml`。分类支持两套兼容结构：简单的
`filename/data_columns/structure/rules`，以及功能更完整的 `extract/classify` 流程。

### 简单分类

```yaml
version: "1.0"
filename:
  regex: '(\d{8})_(\w+)_(\w+)\.csv'
  fields: [date, subject, motion]

data_columns:
  - name: motion
    source: filename
    type: string
    match:
      sit: [sit, sitting]
      walk: [walk, walking]

structure:
  sit: ''
  walk: ''

rules:
  - target: '{motion}'
    use_filename: true

default: unclassified
```

### 提取与条件分类

```yaml
version: "1.0"
extends: posture_patterns.yaml
target_chip: gh3036

extract:
  - name: spo2_median
    function: calculate_median
    params:
      column: REF_RESULT5
      column_col: 51
      samples: 50
  - name: posture
    function: extract_from_path
    params:
      patterns:
        sit: [静坐]
        supine: [平躺]

classify:
  - target: '{posture}/normalSpO2'
    condition: 'spo2_median >= 95'
  - target: '{posture}/lowspo2'
    condition: 'spo2_median < 95'

accuracy:
  ref_column: REF_RESULT5
  pred_column: ALGO_RESULT0
  methods: [rmse, mae, correlation]

default: unclassified
```

`extends` 递归合并基础规则；命令行可多次使用 `--extend` 扩展 patterns。分类目标是相对于
输出目录的路径。`--copy`、`--move`、`--symlink` 决定文件落盘方式。

## convert 规则

路径：`rules/convert/<name>.yaml`。转换顺序为：读取输入、合并 `extra_source`、映射列、
计算列、频率扩展、前值填充、补齐并按目标芯片列排序。

```yaml
version: "1.0"
description: 第三方 CSV 转 GH3036
target_chip: gh3036

csv:
  info_row: 0
  header_row: 1
  data_start_row: 2
  delimiter: ','
  encoding: utf-8

column_mapping:
  time: TimeStamp
  frame: FRAME_ID
  acc[0]: ACCX
  acc[1]: ACCY
  acc[2]: ACCZ
  rawdata[{0-1}]: Rawdata{0-1}
  polar_hr: REF_RESULT0

computed:
  FLAG0: 'status * 1'
  TEMP: 'raw_temp / 100'

expand_repeat:
  polar_hr: 25

forward_fill:
  - polar_hr
```

也可使用等长的 `source_columns` 和 `target_columns` 代替 `column_mapping`。公式只支持按
空白/运算符拆分的列、数字与 `+ - * /`；无法解析的 token 按 0 处理。映射后缺失的目标
芯片列补 0，多余列被丢弃。

### extra_source

`extra_source` 可为一个对象或对象列表，用于把同目录下的金标等外部 CSV 按键左连接到
主文件：

```yaml
extra_source:
  - name: spo2_ref
    pattern: '*.csv'
    required_columns: [时间]
    any_required_columns: [SpO2, O2 饱和度]
    csv:
      header_row: 1
      data_start_row: 2
      delimiter: ','
      encoding: utf-8
    align:
      left_on: time
      right_on: 时间
      right_extract: '(\d{2}:\d{2}:\d{2})'
    column_mapping:
      SpO2: ref_spo2
      O2 饱和度: ref_spo2
```

| 字段 | 说明 |
|---|---|
| `path` | 固定文件；相对路径以主文件目录为基准 |
| `suffix` | 在主文件同目录匹配文件名后缀 |
| `pattern` | 在主文件同目录使用 glob 匹配 |
| `required_columns` | 候选文件必须包含全部列 |
| `any_required_columns` | 候选文件至少包含其中一列 |
| `csv` | 外部文件的表头、数据行、分隔符和编码 |
| `align.left_on/right_on` | 主文件与外部文件的对齐列 |
| `align.left_extract/right_extract` | 可选正则；用第一个捕获组归一化键 |
| `column_mapping` | 外部列到合并后中间列的映射 |

解析时排除主文件自身，按排序后的第一个合规候选文件合并；外部键重复时保留最后一行。
没有匹配的数据补 0。如果找到外部文件但所有映射列均无有效数据，`convert` 会写出
`extra_source_align_errors.csv`。

## evaluate 规则

路径：`rules/evaluate/<name>.yaml`。评估规则定义参考列、预测列、异常阈值、场景分类和
准确度方法。

```yaml
description: 心率准确度评估
type: hr
ref_column: REF_RESULT0
pred_column: ALGO_RESULT0

anomaly:
  diff_threshold: 30
  stale_minutes: 2
  sample_rate: 25

classify:
  by_directory:
    walk: [walk, walking, 步行]
    sit: [sit, sitting, 静坐]
  by_filename:
    run: [run, 跑步]

methods: [mae, within_5, within_10, std, rmse, correlation]
first_output_time: true
default_category: other
```

| 字段 | 说明 |
|---|---|
| `type` | `hr` 或 `spo2` |
| `ref_column` / `pred_column` | 默认参考列和预测列；CLI 可覆盖 |
| `anomaly.diff_threshold` | 相邻结果差分异常阈值 |
| `anomaly.stale_minutes` | 结果长时间不变的判定时长 |
| `anomaly.sample_rate` | 异常时长换算使用的采样率 |
| `classify` | 按目录和文件名关键词分类 |
| `classify_rule` | 可选的 classify 规则名 |
| `methods` | 输出的准确度方法 |
| `thresholds` | 自定义固定值或百分比阈值 |
| `first_output_time` | 是否统计首次有效输出时间 |
| `default_category` | 未匹配场景分类 |

## 验证能力与限制

```bash
ghealth_tool validate path/to/rules/convert/custom.yaml
ghealth_tool validate path/to/rules/parse/custom.yaml --strict
```

当前验证器根据路径中是否包含 `chip`、`parse`、`classify`、`convert` 判断类型，因此建议
自定义文件也保留类型目录。它执行基础结构检查，但不会证明表达式在真实数据上有结果。

已知限制：

- `evaluate` 尚无专用结构验证；使用 `ghealth_tool evaluate --rule ...` 对小样本验证。
- 多 pattern parse 的旧验证路径仍期待顶层 `regex` 和 `columns`；使用
  `ghealth_tool parse --dry-run` 并用小日志验证各 pattern。
- `classify` 的条件表达式、提取函数和扩展 patterns 需要实际分类运行验证。
- `computed` 公式和 `extra_source` 对齐是否正确只能通过实际转换与输出报告确认。
- `--strict` 当前只额外要求单 pattern parse 规则包含 `description`。

验证通过后仍应检查输出列顺序、文件数量、报告中的跳过原因和少量数据值。
