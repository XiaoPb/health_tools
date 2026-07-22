# 规则文件格式

GHealth Tools 使用 YAML 描述 CSV、日志解析、转换、分类、评估和分析行为。规则把设备差异和
项目配置从 Python 代码中分离出来，便于复用和审查。

## 规则目录与查找顺序

内置规则随 Python 包安装：

```text
src/health_tools/rules/
├── chip/      # gh3036.yaml、gh3036_evk.yaml、gh3220.yaml
├── parse/     # default.yaml、gh3220.yaml
├── classify/  # default.yaml、posture_patterns.yaml、spo2_posture.yaml
├── convert/   # standard.yaml、template.yaml
├── evaluate/  # evaluate_hr.yaml、evaluate_spo2.yaml
└── analysis/  # analysis_hr.yaml、analysis_spo2.yaml
```

运行 `ghealth_tool config --init` 后，可在 `~/.ghealth_tools/rules/` 中放置同样的目录。相对规则名按 **用户目录 → 内置目录** 顺序解析，用户规则可覆盖同名内置规则；绝对路径直接使用。

各命令引用规则的方式：

| 命令 | 选项 | 说明 |
|---|---|---|
| `parse` | `-r/--rule` | parse 规则文件名或路径 |
| `convert` | `-r/--rule` | convert 规则；`--init-rule` 可生成模板 |
| `classify` | `-r/--rule` | classify 规则；`--extend` 追加 patterns |
| `evaluate` | `--rule` | evaluate 规则，默认随 `--type` 选内置 |
| `analyze` | `--rule` | analysis 规则；`--type other` 时必填 |
| `check`/`factory`/`offline` | `-c/--chip` | 通过 `chip/<chip>.yaml` 加载芯片规则 |

## 通用约定

- YAML 使用 UTF-8 编码。
- 行号从 1 开始；`info_row: 0` 表示没有信息行。
- 列范围统一使用 `{start-end}` 花括号语法：`CH{0-3}` → `CH0`、`CH1`、`CH2`、`CH3`。多个花括号从左到右嵌套展开，例如 `ALGO{0-1}_CH{0-2}` → `ALGO0_CH0`、`ALGO0_CH1`、`ALGO0_CH2`、`ALGO1_CH0`、…。
- `[]` 是字面量，不参与展开：`rawdata[{0-1}]` 只展开花括号，得到字面列名 `rawdata[0]`、`rawdata[1]`；`acc[0]`、`CH16-31` 这类不含花括号的名称原样保留。**注意** `CH16-31` 是一个名为 “CH16-31” 的列，不是 16~31 的范围；要表示范围请写 `CH{16-31}`。
- 修改规则后先运行 `validate`（适用时），再用一个小文件执行目标命令。

## chip 规则

路径：`rules/chip/<chip>.yaml`。chip 规则定义标准 CSV 的读取方式、完整列顺序，以及检查、产测、离线算法和评估所需的芯片信息。`check`/`factory`/`offline` 通过 `-c/--chip` 加载，`evaluate`/`analyze` 通过 `--chip` 加载；`parse`/`convert` 通过 `target_chip` 间接引用。

```yaml
version: "1.0"
chip: gh3220

csv:
  info_row: 1                 # 信息所在行，0 表示无
  header_row: 2               # 列名所在行
  data_start_row: 3           # 数据开始行
  delimiter: ","              # 分隔符
  encoding: utf-8             # 编码
  info: "Version: GH3220"     # 可选，写入输出 CSV 信息行的固定文本

columns:                       # 完整列顺序（支持 {start-end} 展开）
  - TimeStamp
  - FRAME_ID
  - ACCX
  - ACCY
  - ACCZ
  - CH{0-15}

frame_column: FRAME_ID        # 帧号列；未配置时检查器尝试自动识别
acc_columns:                   # X/Y/Z 三轴列；未配置时检查器尝试自动识别
  x: ACCX
  y: ACCY
  z: ACCZ

check_columns:                 # 检查专用列组
  data: [CH{0-15}]             # 原始数据列，覆盖基于列名的自动识别
  agc: [AGC_INFO_CH{0-15}]     # AGC 列，供 check 解析位段

factory_columns: [CH{0-15}]    # 参与 SNR/CTR/Noise 计算的列（自动过滤全零列）

factory_config:                # 采样率与三个产测指标的截取时长
  sample_rate: 100
  snr:  {skip_head_seconds: 10, skip_tail_seconds: 10, min_duration_seconds: 90}
  ctr:  {skip_head_seconds: 1,  skip_tail_seconds: 0,  min_duration_seconds: 2}
  noise: {skip_head_seconds: 2, skip_tail_seconds: 0,  min_duration_seconds: 4}

chip_info:                     # ADC 与物理量解析参数，见下文
  adc_full_scale: 8388608
  adc_offset: 8388608
  adc_vref: 1.8
  tia_ratio: 2
  gain:
    source: "AGC_INFO_CH{0-15}"
    bits: "[3:0]"
    type: "int"
    unit: ""
    desc: "增益等级"

gain_tia_map:                  # 增益等级到 TIA 电阻的映射，见下文
  unit: "KΩ"
  map:
    0: 10
    1: 25

hr_ref_column:                 # 心率参考列（列名: 1-based 列索引）
  REF_RESULT0: 30
spo_ref_column:                # 血氧参考列（列名: 1-based 列索引）
  REF_RESULT5: 35
```

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `version` | string | 规则版本，`validate` 要求存在 |
| `chip` | string | 芯片标识，`-c/--chip` 即取此名 |
| `csv` | object | CSV 行号、分隔符、编码与可选 `info` 文本 |
| `csv.info_row` | int | 信息所在行，`0` 表示无信息行 |
| `csv.header_row` | int | 列名所在行 |
| `csv.data_start_row` | int | 数据开始行 |
| `csv.delimiter` | string | 字段分隔符 |
| `csv.encoding` | string | 文件编码 |
| `csv.info` | string | 可选；写入输出 CSV 信息行的固定文本 |
| `columns` | list | 完整列顺序；转换输出、离线预检和 parse 的 `target_chip` 输出都按此顺序 |
| `frame_column` | string | 帧号列；未配置时 `check` 尝试自动识别 |
| `acc_columns` | object | `x`/`y`/`z` 三轴列；未配置时 `check` 尝试自动识别 |
| `check_columns` | object | `data`、`agc` 等检查专用列组，覆盖自动识别 |
| `factory_columns` | list | 参与 SNR/CTR/Noise 计算的列 |
| `factory_config` | object | 采样率与三个指标的截取时长 |
| `chip_info` | object | ADC 参数与按位段解析的物理量，见下 |
| `gain_tia_map` | object | 增益等级到 TIA 电阻的映射，见下 |
| `hr_ref_column` | object | 心率参考列 `{列名: 1-based 索引}`，evaluate 列名找不到时回退使用 |
| `spo_ref_column` | object | 血氧参考列 `{列名: 1-based 索引}`，同上 |

`check_columns.data` 会覆盖基于常见列名的自动识别。离线输入预检要求文件表头与展开后的 `columns` 数量、名称和顺序完全相同。

### chip_info 结构

`chip_info` 顶层是 ADC 全局参数，其余每个命名条目描述一个从 AGC/LED/physics 列按位段解析的物理量：

```yaml
chip_info:
  adc_full_scale: 8388608   # ADC 满量程
  adc_offset: 0             # ADC 偏置；CH*/Rawdata* 计算 PI 前减去该值，Ipd* 不减
  adc_vref: 1.8             # ADC 参考电压 (V)
  tia_ratio: 2              # TIA 比率

  gain:                     # 任意命名条目，名称即物理量名
    source: "AGC_INFO_CH{0-31}"  # 来源列（支持 {} 展开）
    bits: "[3:0]"           # 位段 [high:low]；null 表示整列直接使用
    type: "int"             # int 或 float
    unit: ""                # 单位字符串，仅用于展示
    desc: "增益等级"         # 说明文字
  led_current_sum:
    source: "AGC_INFO_CH{0-31}"
    bits: "[29:16]"
    type: "int"
    unit: "0.1mA"
    desc: "LED总电流"
  led_current_drv3:
    optional: true          # 标记可选；芯片不支持该量时缺省
  ipd_pA:
    source: "Ipd{0-31}"
    bits: null              # 整列直接使用
    type: "float"
    unit: "pA"
    desc: "光电流值"
```

内置条目常见名称：`gain`、`bg_cancel_level`、`dc_cancel_level`、`dc_cancel_code`、`led_current_sum`、`led_current_drv0/1/3/4`、`ipd_pA`。物理量换算关系（`check` 与 `analyze` 据此解释光学列）：

```text
rawdata_uv = (rawdata_value - adc_offset) / adc_full_scale * adc_vref * 1_000_000
ipd_pA     = rawdata_uv / (tia_ratio * gain_tia_map.map[gain]) * 1000
ctr        = ipd_pA * 1000 / led_current_sum      # 单位 nA/mA
```

### gain_tia_map 结构

```yaml
gain_tia_map:
  unit: "KΩ"   # 电阻单位，仅用于展示
  map:          # 增益等级 -> TIA 电阻值
    0: 10
    1: 25
    2: 50
    3: 100
    4: 250
    5: 500
    6: 1000
```

### hr_ref_column / spo_ref_column

`evaluate` 解析参考列与预测列时优先级为：命令行 `--ref-column-col/--pred-column-col` > 规则 `ref_column/pred_column` 列名 > chip 规则的 `hr_ref_column`/`spo_ref_column`（按 `type` 选择）中同名列的 1-based 索引。因此即使输出 CSV 改了列顺序，只要索引正确，evaluate 仍能定位参考列。

## parse 规则

路径：`rules/parse/<name>.yaml`。把日志行用正则转换为一组列，输出 CSV。

### 单 pattern 规则

```yaml
version: "1.0"
description: GH3220 日志
chip: gh3220            # 等价于 target_chip；指定后输出完整芯片列格式
regex: '^\[(.+?)\]\s+GH3220:\s*(\d+),(\d+),(\d+),(\d+)$'
columns: [timestamp, red, ir, green, aux]
separator: ','          # 默认逗号
```

`regex` 捕获组数量可以等于展开后的 `columns` 数量（逐列映射）；也可以只用一个捕获组，再按 `separator` 拆分为多列。`chip` 与 `target_chip` 互为兼容字段，给解析命令提供默认目标芯片。

指定 `chip`/`target_chip` 后，输出按目标芯片 `columns` 的完整列顺序，未匹配列填 0，并写入 info 行 + header 行（与 chip 规则一致）。命令行 `-c/--chip` 不会覆盖规则里的 `chip/target_chip`。

### 多 pattern 规则

同一日志分别生成多组 CSV：

```yaml
version: "1.0"
description: 同时解析 PPG 和算法输出
target_chip: gh3036
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

多 pattern 模式以 pattern 名区分输出，每个 pattern 输出文件名为 `{原文件名}_{pattern名}.csv`。每个 pattern 都支持捕获组逐列映射或单捕获组按 `separator` 拆列。`validate` 和规则保存 API 会逐项检查捕获组与列数是否匹配。

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `version` | string | 规则版本 |
| `description` | string | 说明；`--strict` 要求存在 |
| `regex` | string | 单 pattern 的正则 |
| `columns` | list | 单 pattern 的输出列名（支持 `{start-end}` 展开） |
| `separator` | string | 单捕获组拆分多列的分隔符，默认 `,` |
| `chip` / `target_chip` | string | 目标芯片；指定后输出完整芯片列格式 |
| `patterns` | dict | 多 pattern 配置，键为 pattern 名 |
| `patterns.<name>.regex` | string | 该 pattern 的正则 |
| `patterns.<name>.columns` | list | 该 pattern 的输出列名 |
| `patterns.<name>.separator` | string | 该 pattern 的分隔符，默认 `,` |

## classify 规则

路径：`rules/classify/<name>.yaml`。分类支持两套结构：简单的 `filename/data_columns/structure/rules`，以及功能更完整的 `extract/classify` 流程。两套可共存于同一规则文件；存在 `classify` 时独占执行（`rules` 被跳过，未命中返回 `default`），否则使用简单 `rules`。

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
  posture: "sit|stand|walk"   # posture/ 及其下 sit/stand/walk 子目录（| 分隔多个子目录）

rules:
  - target: '{motion}'
    use_filename: true
  - target: 'posture/{level}'   # {level} 必须出现在 target 中，conditions 才会求值
    conditions:
      level:
        normal: "spo2_median >= 95"
        low: "spo2_median < 95"

default: unclassified
```

`conditions` 的键（如 `level`）是占位符名，必须出现在对应 `target` 中（如 `{level}`）才会求值；条件表达式引用 `extract` 或 `data_columns` 提取的变量（上例 `spo2_median` 见下文提取示例）。

### 提取与条件分类

```yaml
version: "1.0"
extends: posture_patterns.yaml   # 递归合并基础规则
target_chip: gh3036              # 可选，指定芯片规则以决定 CSV 读取格式（info_row/header_row/delimiter/columns）

extract:                          # 提取变量供 classify 条件使用
  - name: spo2_median
    function: calculate_median
    params:
      column: REF_RESULT5
      column_col: 50             # 列名找不到时回退的 0-based 位置索引
      samples: 50
  - name: posture
    function: extract_from_path
    params:
      patterns:
        sit: [静坐]
        supine: [平躺]

classify:                         # 按条件匹配，命中即返回 target；存在时 rules 被跳过
  - target: '{posture}/normalSpO2'
    condition: 'spo2_median >= 95'
  - target: '{posture}/lowspo2'
    condition: 'spo2_median < 95'

accuracy:                         # 可选；启用 --accuracy 时计算准确度
  ref_column: REF_RESULT5         # 参考列名（classify 仅按列名读取）
  pred_column: ALGO_RESULT0       # 预测列名
  methods: [std, rmse, mae, within_3, correlation]
  thresholds:
    - { name: within_0.5, value: 0.5 }
    - { name: within_10_percent, percent: 10 }

default: unclassified
```

`extends` 递归合并基础规则；命令行 `--extend <patterns.yaml>` 可多次追加 patterns 到 `extract` 中含 `params.patterns` 的项。分类 `target` 是相对于输出目录的路径，`{变量名}` 会被提取值替换。`--copy`（默认）、`--move`、`--symlink` 决定文件落盘方式。

classify 的准确度按列名读取 `ref_column`/`pred_column`；如参考列名不在 CSV 中，请用命令行 `--ref-column`/`--pred-column` 指定，或改用 evaluate 规则（其 chip 规则的 `hr_ref_column`/`spo_ref_column` 支持按 1-based 索引回退）。

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `version` | string | 规则版本 |
| `extends` | string | 基础规则文件名，递归合并 |
| `target_chip` | string | 可选，指定芯片规则以决定 CSV 读取格式 |
| `filename` | object | 文件名正则与字段 |
| `filename.regex` | string | 文件名正则 |
| `filename.fields` | list | 捕获组对应的字段名 |
| `data_columns` | list | 数据列定义，见下 |
| `structure` | object | 目录结构；值为 `""` 或 `|` 分隔的子目录名 |
| `rules` | list | 简单分类规则（存在 `classify` 时被跳过） |
| `rules[].target` | string | 分类目标路径，支持 `{变量}` |
| `rules[].use_filename` | bool | 使用文件名字段 |
| `rules[].conditions` | object | 条件占位符，键须出现在 target 中 |
| `extract` | list | 提取变量定义 |
| `extract[].name` | string | 变量名 |
| `extract[].function` | string | 提取函数名，见下表 |
| `extract[].params` | object | 函数参数 |
| `classify` | list | 条件分类规则（存在时独占执行） |
| `classify[].target` | string | 分类目标路径 |
| `classify[].condition` | string | 条件表达式 |
| `accuracy` | object | 准确度配置，见下 |
| `default` | string | 未匹配时的目录名 |

### data_columns 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 变量名，供 target/condition 引用 |
| `source` | string | `filename` / `parent_dir` / `data`（默认 `data`） |
| `type` | string | `string`（默认）或 `int`（int 会转数值再统计） |
| `column` | string | `source=data` 时读取的列名 |
| `column_index` | int | 或 0-based 列索引，与 `column` 二选一 |
| `match` | object | 关键词匹配 → 类别名 `{类别: [关键词]}` |
| `regex` | string | 正则提取 |
| `group` | int | 捕获组序号（1-based） |
| `ranges` | object | 按列均值落入区间分类 `{类别: [最小, 最大]}` |
| `values` | list | 按列众数是否在列表中判定 |
| `compute` | string | 计算表达式（保留字段） |

### extract 函数

`CLASSIFY_FUNCTIONS` 注册的全部函数：

| function | 签名 | 说明 |
|---|---|---|
| `calculate_median` | `(df, column, samples=50)` | 指定列最后 N 个值的中位数 |
| `calculate_mean` | `(df, column)` | 指定列均值 |
| `calculate_std` | `(df, column)` | 指定列标准差 |
| `calculate_percentile` | `(df, column, percentile=50)` | 指定列百分位数 |
| `get_column_value` | `(df, column, row=-1)` | 指定列某行值 |
| `count_values` | `(df, column)` | 指定列值计数字典 |
| `extract_from_path` | `(file_path, patterns)` | 按路径关键词匹配类别，未匹配返回 `other` |
| `classify_by_range` | `(value, ranges)` | 按范围分类（一般不直接用作 extract） |

调用约定（`classifier._extract_values` 的分发逻辑）：

- `params` 含 `patterns` → 调用 `extract_from_path(file_path, patterns)`。
- `params` 含 `column` → 先按列名取列；列名不存在时用 `column_col`（0-based 位置索引）回退；随后以 `func(df, column, params.get("samples", 50))` 调用。该第三参数仅与 `calculate_median` 的 `samples` 形参匹配，因此：
  - `calculate_median` 正常工作（`samples` 默认 50）。
  - `calculate_percentile` 的第三参数落到 `percentile`（恒 50，显式 `percentile` 不生效）。
  - `get_column_value` 的第三参数落到 `row`（恒 50，显式 `row` 不生效）。
  - `calculate_mean`、`calculate_std`、`count_values` 不接收第三参数，column 分支会抛错并被跳过，当前不可用。
- 否则 → `func(df, **params)` 透传。

### accuracy 块

`--accuracy` 启用时按列名读取参考列与预测列计算准确度。`methods` 与 `thresholds` 的可用取值与 evaluate 规则完全一致（见 [evaluate 规则](#evaluate-规则)）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `ref_column` | string | 参考列名 |
| `pred_column` | string | 预测列名 |
| `methods` | list | 准确度方法列表 |
| `thresholds` | list | 自定义阈值指标 |

### 条件表达式语法

`classify[].condition` 与 `rules[].conditions` 中的条件使用安全 AST 求值器（非 `eval`，禁止代码注入）：

- 比较：`< <= > >= == !=`，支持链式 `a < b < c`
- 逻辑：`and` `or`（可组合）
- 算术：`+ - * / // % **`
- 常量：`True` `False` `None`
- 变量：`extract` 与 `data_columns` 提取的值

不支持函数调用、下标、属性访问；未定义变量求值失败记 warning 并判 `False`。示例：`spo2_median >= 90 and spo2_median < 95`。

## convert 规则

路径：`rules/convert/<name>.yaml`。转换顺序为：读取输入 → 合并 `extra_source` → 映射列 → 计算 `computed` 列 → `expand_repeat` 频率扩展 → `forward_fill` 前值填充 → 按目标芯片列补 0 并排序。

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
  acc[0]: ACCX          # [] 是字面量，acc[0] 即源列名
  acc[1]: ACCY
  acc[2]: ACCZ
  rawdata[{0-1}]: Rawdata{0-1}   # 仅展开花括号，得 rawdata[0] -> Rawdata0
  polar_hr: REF_RESULT0

computed:
  FLAG0: 'status * 1'
  TEMP: 'raw_temp / 100'

expand_repeat:
  polar_hr: 25          # 每个值重复 25 次对齐高采样率列

forward_fill:
  - polar_hr
```

也可用等长的 `source_columns` 和 `target_columns` 代替 `column_mapping`。映射后缺失的目标芯片列补 0，多余列被丢弃。

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `version` | string | 规则版本 |
| `description` | string | 说明 |
| `target_chip` | string | 目标芯片，输出按其 `columns` 排序与补列 |
| `csv` | object | 输入 CSV 解析配置（`info_row`/`header_row`/`data_start_row`/`delimiter`/`encoding`） |
| `column_mapping` | object | 源列 → 目标列映射（支持 `{start-end}` 展开） |
| `source_columns` / `target_columns` | list | 等长列表，与 `column_mapping` 二选一 |
| `computed` | object | 计算列，见下 |
| `expand_repeat` | object | 列重复扩展 `{列: 次数}` |
| `forward_fill` | list | 前值填充列 |
| `extra_source` | object/list | 外部参考文件合并，见下 |

### computed 公式

公式按空白与 `+ - * /` 切分为 token：列名取该列数值，数字字面量取字面值，**无法识别的 token 按 0**，除零时把除数的 0 替换为 1。**不支持括号、函数或 `**`**。例如 `'raw_temp / 100'`、`'status * 1'`。解析失败整列填 0 并记 warning。

### extra_source

`extra_source` 可为单个对象或对象列表，把同目录下的金标等外部 CSV 按键左连接到主文件：

```yaml
extra_source:
  - name: spo2_ref            # 名称，用于对齐错误报告（缺省时回退到 description）
    pattern: '*.csv'           # glob 匹配（与 suffix/path 三选一）
    required_columns: [时间]   # 候选文件必须包含全部列
    any_required_columns: [SpO2, O2 饱和度]  # 至少命中其中一列
    csv:
      header_row: 1
      data_start_row: 2
      delimiter: ','
      encoding: utf-8
    align:
      left_on: time           # 主文件对齐列
      right_on: 时间          # 外部文件对齐列
      right_extract: '(\d{2}:\d{2}:\d{2})'  # 用第一个捕获组归一化右侧键
    column_mapping:
      SpO2: ref_spo2          # 外部列 -> 合并后中间列
```

| 字段 | 说明 |
|---|---|
| `name` | 来源名称，用于对齐错误报告 |
| `description` | `name` 缺省时回退使用 |
| `path` | 固定文件；相对路径以主文件目录为基准，优先级高于 `suffix`/`pattern` |
| `suffix` | 在主文件同目录匹配文件名后缀 |
| `pattern` | 在主文件同目录使用 glob 匹配 |
| `required_columns` | 候选文件必须包含全部列 |
| `any_required_columns` | 候选文件至少包含其中一列 |
| `csv` | 外部文件的表头、数据行、分隔符和编码 |
| `align.left_on` / `right_on` | 主文件与外部文件的对齐列（必须同时提供） |
| `align.left_extract` / `right_extract` | 可选正则；用第一个捕获组归一化对齐键 |
| `column_mapping` | 外部列到合并后中间列的映射 |

解析时排除主文件自身，按排序后的第一个合规候选文件合并；外部键重复时保留最后一行。没有匹配的数据补 0。如果找到外部文件但所有映射列均无有效数据，`convert` 会写出 `extra_source_align_errors.csv`，记录原始文件、对比文件、来源名和失败原因。

## evaluate 规则

路径：`rules/evaluate/<name>.yaml`。评估规则定义参考列、预测列、异常阈值、场景分类和准确度方法。`--type` 默认随 `hr`/`spo2` 选内置 `evaluate_hr.yaml`/`evaluate_spo2.yaml`，可用 `--rule` 覆盖。

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

methods: [mae, within_5, within_10, within_15, std, rmse, correlation]
thresholds:
  - { name: within_0.5, value: 0.5 }
  - { name: within_10_percent, percent: 10 }

first_output_time: true
default_category: other
```

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `description` | string | 说明；`--strict` 要求存在 |
| `type` | string | `hr` 或 `spo2` |
| `ref_column` / `pred_column` | string | 默认参考列和预测列；CLI `--ref-column/--pred-column` 可覆盖 |
| `anomaly` | object | 参考值异常检测阈值，见下 |
| `classify` | object | 按目录和文件名关键词分类，见下 |
| `classify_rule` | string | 保留字段，当前 evaluate 不会读取；场景分类请用 `by_directory`/`by_filename` |
| `methods` | list | 准确度方法，见下 |
| `thresholds` | list | 自定义阈值指标，见下 |
| `first_output_time` | bool | 是否统计首次有效输出时间 |
| `default_category` | string | 未匹配场景分类，默认 `other` |

### anomaly 字段与默认值

参考列与预测列解析优先级：CLI `--ref-column-col/--pred-column-col` > 规则列名 > chip 规则 `hr_ref_column`/`spo_ref_column`（按 `type` 选择：先取同名列的 1-based 索引；列名不在映射中时取第一个有效索引）。

| 字段 | hr 默认 | spo2 默认 | 说明 |
|---|---:|---:|---|
| `diff_threshold` | 30 | 5 | 相邻结果差分异常阈值 |
| `stale_minutes` | 2 | 2 | 结果长时间不变的判定时长（分钟） |
| `sample_rate` | 25 | 25 | 异常时长换算使用的采样率 |

### classify 匹配规则

`classify` 配置 `by_directory` 与 `by_filename` 两个关键词映射（`{类别: [关键词]}`）。`by_directory` 按父目录名（转小写）子串匹配；未命中再按 `by_filename`（文件名 stem 转小写）子串匹配；仍未命中用 `default_category`。

### methods 可用取值

| method | 说明 |
|---|---|
| `std` | 误差标准差 |
| `rmse` | 均方根误差 |
| `mae` | 平均绝对误差 |
| `mape` | 平均绝对百分比误差（%） |
| `bias` | 偏差（平均误差） |
| `correlation` | 相关系数 |
| `r2` | 决定系数 R² |
| `within_N` | 误差 `|ref-pred| <= N` 的样本占比（%），如 `within_5`、`within_10` |

未指定 `methods` 时默认 `[mae, rmse, std]`。

### thresholds 自定义指标

`thresholds` 是列表，每项至少含 `name`，并二选一提供阈值来源：

```yaml
thresholds:
  - { name: within_0.5, value: 0.5 }          # 固定阈值：|ref-pred| <= value 的占比(%)
  - { name: within_10_percent, percent: 10 }   # 百分比阈值：|ref-pred| <= |ref|*percent/100 的占比(%)
```

## analysis 规则

路径：`rules/analysis/<name>.yaml`。分析规则声明功能类型、输入列、启用的内置检测器、阈值和结构化原因条件。

```yaml
version: "1.0"
type: hr
columns:
  reference: REF_RESULT0
  prediction: ALGO_RESULT0
detectors: [integrity, raw_signal, reference, accuracy, motion, hr_psd]
thresholds: {error: 10}
causes:
  - id: example
    title: 原始数据示例
    origin: raw
    when: {feature: data_complete, op: eq, value: false}
    actions: [检查采集链路并重新采集]
```

`origin` 只能是 `raw`、`reference` 或 `algorithm`。算法原因不能声明 `actions`；条件只支持 `all`、`any`、`not` 和 `eq/ne/lt/le/gt/ge/in/not_in/between/exists`，不会执行任意表达式。`type=other` 必须通过 `--rule` 指定分析规则。

`detectors` 决定允许使用的证据类型。`hr_psd` 只适用于心率；SpO2 或未声明该检测器的自定义功能不会执行心率锁频、牵引和谐波判断。SpO2 内置规则把 `motion_rms` 超限作为静止测试条件不满足，优先于准确度异常归因，并以 `pi_low` 检查静止双波长数据的最低通道 PI。

光学列的数据语义固定如下：`CH*` 默认视为 Rawdata，和 `Rawdata*` 一样在计算 PI 前减去 chip 规则的 `chip_info.adc_offset`；`Ipd*` 单位是 pA，不能再减 ADC 偏置。内置规则会识别这三类列，结构化结果通过 `pi_by_channel` 和 `pi_units` 保留逐通道值与单位。

心率 Polar 参考检查使用 `ref_min/ref_max`、`ref_valid_ratio`、`ref_stale_seconds` 和 `ref_jump_per_second`。局部越界或跳变样本从准确度中隔离，仅产生人工复审警告；它不会覆盖原始/PSD 原因、结论或证据图。只有有效比例低于 `ref_valid_ratio` 或全局无有效值时，才停止参考归因。

`thresholds` 控制诊断敏感度。完整默认值、调高/调低的影响和判断流程见 [analyze 命令](cmd_analyze.md#配置判断阈值)。修改后应使用正常与异常小样本验证，不能把阈值变化解释为算法优化。

## 验证能力与限制

```bash
ghealth_tool validate path/to/rules/convert/custom.yaml
ghealth_tool validate path/to/rules/parse/custom.yaml --strict
```

当前验证器根据路径中是否包含 `chip`、`parse`、`classify`、`convert`、`evaluate`、`analysis` 判断类型，因此建议
自定义文件也保留类型目录。它执行基础结构检查，但不会证明表达式在真实数据上有结果。

已知限制：

- `evaluate` 和 `analysis` 支持结构验证，但仍需使用目标命令对小样本验证列和阈值。
- `classify` 的条件表达式、提取函数和扩展 patterns 需要实际分类运行验证。
- `computed` 公式和 `extra_source` 对齐是否正确只能通过实际转换与输出报告确认。
- `--strict` 当前只额外要求单 pattern parse 规则包含 `description`。

验证通过后仍应检查输出列顺序、文件数量、报告中的跳过原因和少量数据值。
