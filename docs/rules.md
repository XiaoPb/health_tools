# 规则文件格式说明

所有规则文件使用YAML格式，存放在 `rules/` 目录下。

## 芯片规则 (chip)

路径：`rules/chip/<chip_name>.yaml`

定义特定芯片的CSV文件格式，包括列名、编码、分隔符等。

```yaml
version: "1.0"
chip: gh3220

csv:
  info_row: 1            # 信息行位置（0=无信息行）
  header_row: 2          # 列名所在行
  data_start_row: 3      # 数据开始行
  delimiter: ","         # 分隔符
  encoding: "utf-8"      # 文件编码

columns:
  - TimeStamp
  - FRAME_ID
  - ACCX
  - ACCY
  - ACCZ
  - CH{0-15}             # 展开为 CH0, CH1, ..., CH15

factory_columns:         # 产测计算列（自动过滤全零列）
  - CH{0-15}

factory_config:          # 产测计算参数（各指标独立配置）
  sample_rate: 100
  snr:
    skip_head_seconds: 10
    skip_tail_seconds: 10
    min_duration_seconds: 90
  ctr:
    skip_head_seconds: 1
    skip_tail_seconds: 0
    min_duration_seconds: 2
  noise:
    skip_head_seconds: 2
    skip_tail_seconds: 0
    min_duration_seconds: 4

gain_tia_map:            # 增益等级 → TIA电阻映射
  unit: "KΩ"
  map:
    0: 10
    1: 25
    2: 50
    3: 100
    4: 250
    5: 500
    6: 1000

chip_info:               # 芯片参数（用于 CTR/Noise 计算）
  adc_full_scale: 8388608
  adc_offset: 8388608
  adc_vref: 1.8
  tia_ratio: 2

  gain:
    source: "AGC_INFO_CH{0-15}"
    bits: "[3:0]"
    type: "int"
    desc: "增益等级"

  led_current_sum:
    source: "AGC_INFO_CH{0-15}"
    bits: "[29:16]"
    type: "int"
    unit: "0.1mA"
    desc: "LED总电流"
```

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `version` | string | 规则版本 |
| `chip` | string | 芯片标识名 |
| `csv.info_row` | int | 信息行位置，0表示无信息行 |
| `csv.header_row` | int | 列名行位置 |
| `csv.data_start_row` | int | 数据起始行 |
| `csv.delimiter` | string | 字段分隔符 |
| `csv.encoding` | string | 文件编码 |
| `columns` | list | 列名列表，支持 `{start-end}` 展开 |
| `factory_columns` | list | 产测计算列，支持 `{start-end}` 展开 |
| `factory_config` | dict | 产测参数：顶层 sample_rate，子级 snr/ctr/noise 各有独立 skip/duration |
| `gain_tia_map` | dict | 增益等级到 TIA 电阻（KΩ）的映射 |
| `chip_info` | dict | 芯片参数（adc_full_scale, adc_offset, adc_vref, tia_ratio, gain, led_current 等） |

### chip_info 字段

| 字段 | 说明 |
|---|---|
| `adc_full_scale` | ADC 满量程值 |
| `adc_offset` | ADC 偏移量 |
| `adc_vref` | ADC 参考电压（V） |
| `tia_ratio` | TIA 比率系数 |
| `gain` | 增益配置：source（数据来源列）、bits（位段）、type |
| `led_current_sum` | LED 总电流配置，设 `optional: true` 时自动累加各 drv 通道 |
| `led_current_drv*` | 各 LED 驱动通道电流，支持 `mA/LSB` 单位 |

---

## 解析规则 (parse)

路径：`rules/parse/<name>.yaml`

定义如何从日志文件中提取数据。

```yaml
version: "1.0"
description: "GH3220日志解析规则"

regex: '^\[(.+?)\]\s+GH3220:\s*(\d+),(\d+),(\d+),(\d+)$'

columns:
  - timestamp
  - red
  - ir
  - green
  - aux
```

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `version` | string | 规则版本 |
| `description` | string | 规则描述 |
| `regex` | string | 匹配日志行的正则表达式，每个捕获组对应一列 |
| `columns` | list | 列名列表，与正则捕获组一一对应 |

---

## 分类规则 (classify)

路径：`rules/classify/<name>.yaml`

定义如何根据文件名模式将文件分类到目录结构。

```yaml
version: "1.0"

filename:
  regex: '(\d{8})_(\w+)_(\w+)\.csv'
  fields:
    - date
    - subject
    - motion

data_columns:
  - name: motion
    source: filename
    match:
      supine: ["supine", "lie", "lying"]
      sit: ["sit", "sitting"]
      walk: ["walk", "walking"]

structure:
  supine: ""
  sit: ""
  walk: ""

rules:
  - target: "{motion}"
    use_filename: true
```

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `filename.regex` | string | 匹配文件名的正则 |
| `filename.fields` | list | 正则捕获组对应的字段名 |
| `data_columns` | list | 数据列定义（用于分类判断） |
| `structure` | dict | 输出目录结构 |
| `rules` | list | 分类规则列表 |

---

## 转换规则 (convert)

路径：`rules/convert/<name>.yaml`

定义CSV格式转换的完整流程。

```yaml
version: "1.0"
description: "转换规则说明"

target_chip: gh3036

csv:
  info_row: 0            # 输入文件信息行（0=无）
  header_row: 1          # 输入文件列名行
  data_start_row: 2      # 输入文件数据起始行
  delimiter: ","         # 输入文件分隔符

column_mapping:
  time: TimeStamp
  frame_cnt: FRAME_ID
  acc[0]: ACCX
  acc[1]: ACCY
  acc[2]: ACCZ
  rawdata[{0-1}]: Rawdata{0-1}
  ipd_pa[{0-1}]: Ipd{0-1}
  polar_HR: REF_RESULT0
  hba_out: ALGO_RESULT0
  agc_info[{0-1}]: AGC_INFO_CH{0-1}

forward_fill:
  - hba_out

expand_repeat:
  polar_HR: 25

computed:
  FLAG0: "status * 1"
  TEMP: "raw_temp / 100"
```

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `version` | string | 规则版本 |
| `description` | string | 规则描述 |
| `target_chip` | string | 目标芯片名（对应 chip 规则） |
| `csv` | dict | 输入文件CSV格式配置 |
| `column_mapping` | dict | 源列名 → 目标列名映射 |
| `forward_fill` | list | 需要前值填充的列（使用源列名） |
| `expand_repeat` | dict | 需要频率扩展的列及重复次数 |
| `computed` | dict | 计算列（列名 → 公式） |

### csv 配置

控制如何读取输入文件：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `info_row` | 0 | 信息行位置，0表示无信息行 |
| `header_row` | 1 | 列名行位置，0表示无列名 |
| `data_start_row` | 2 | 数据起始行 |
| `delimiter` | "," | 字段分隔符 |
| `encoding` | "utf-8" | 文件编码 |

### 列名展开语法

所有规则文件统一使用 `{}` 进行范围展开，`[]` 保留为字面量：

| 写法 | 展开结果 |
|---|---|
| `rawdata{0-15}` | rawdata0, rawdata1, ..., rawdata15 |
| `CH{0-15}` | CH0, CH1, ..., CH15 |
| `acc[0]` | acc[0]（字面量，不展开） |
| `rawdata[{0-1}]` | rawdata[0], rawdata[1] |
| `Rawdata{0-1}` | Rawdata0, Rawdata1 |

`column_mapping` 中源和目标同时展开时，按位置一一对应：
- `rawdata{0-15}: CH{0-15}` → rawdata0→CH0, rawdata1→CH1, ..., rawdata15→CH15

### forward_fill 说明

在首个非0值出现后，将后续的0值替换为前一个非0值。适用于低频信号（如心率）在高频数据中的稀疏表示。

```
原始: [0, 0, 3, 0, 0, 4, 0, 0, 5]
填充: [0, 0, 3, 3, 3, 4, 4, 4, 5]
```

列名使用源列名（映射前），系统会自动解析到目标列名。

### expand_repeat 说明

将低采样率列的每个值重复N次，对齐到高采样率列的行数。

例如主数据25Hz（每秒25行），心率1Hz（每秒1行），设置 `polar_HR: 25` 后每个心率值重复25次。

### computed 说明

通过简单公式生成新列，支持 `+`, `-`, `*`, `/` 运算：

```yaml
computed:
  FLAG0: "status * 1"       # 引用源DataFrame中的列
  TEMP: "raw_temp / 100"    # 除以常数
  DIFF: "ch0 - ch1"        # 列间运算
```

---

## 规则查找顺序

`RuleLoader` 按以下顺序查找规则文件：

1. 内置路径：`<package>/rules/<type>/<name>.yaml`
2. 绝对路径：直接使用指定路径
3. 相对路径：相对于当前工作目录

芯片规则通过 `--chip <name>` 参数加载时，自动查找 `rules/chip/<name>.yaml`。
