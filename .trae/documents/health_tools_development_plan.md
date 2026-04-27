# health_tools Python库开发计划

## 一、项目概述

开发一个用于PPG（光电容积脉搏波）数据分析的Python命令行工具库，支持数据转换、可视化、分类等功能。

---

## 二、命令设计（完善版）

### 2.1 主命令结构

```
health_tool <command> [options]
```

### 2.2 子命令设计

| 命令 | 功能描述 | 别名 |
|------|----------|------|
| `parse` | 日志解析转CSV | `p` |
| `plot` | 数据可视化（时频图等） | `pl` |
| `classify` | 数据分类保存 | `cls` |
| `convert` | CSV格式转换 | `cv` |
| `info` | 查看数据/规则信息 | `i` |
| `validate` | 验证规则文件 | `val` |

### 2.3 详细命令参数设计

#### 2.3.1 `parse` - 日志解析命令

```bash
health_tool parse [OPTIONS]

功能：将原始日志文件解析为CSV格式

参数：
  -i, --input <PATH>      输入文件或目录（必需）
  -o, --output <PATH>     输出文件或目录（默认：当前目录）
  -r, --rule <FILE>       解析规则文件（YAML格式）
  -c, --chip <NAME>       芯片类型（如: max30102, afe4400等）
      --compact           生成紧凑型CSV（默认）
      --expand            生成展开型CSV（每列一个字段）
      --delimiter <CHAR>  字段分隔符（默认: 逗号）
      --timestamp <FORMAT> 时间戳格式（如: %Y-%m-%d %H:%M:%S）
      --encoding <ENC>    输入文件编码（默认: utf-8）
  -v, --verbose           详细输出模式
      --dry-run           仅验证规则，不生成文件
```

#### 2.3.2 `plot` - 数据可视化命令

```bash
health_tool plot [OPTIONS]

功能：绘制PPG数据的时域/频域图

参数：
  -i, --input <PATH>      输入CSV文件或目录（必需）
  -o, --output <PATH>     输出图片目录（默认：当前目录）
      --type <TYPE>       图表类型: time|freq|both（默认: both）
      --channels <LIST>   指定绘制的通道（如: red,ir,green）
      --sample-rate <HZ>  采样率（Hz）
      --window <SEC>      时间窗口大小（秒）
      --overlap <RATIO>   窗口重叠率（0-1，默认: 0.5）
      --format <FMT>      图片格式: png|svg|pdf（默认: png）
      --dpi <NUM>         图片DPI（默认: 150）
      --no-show           不显示图片，仅保存
  -v, --verbose           详细输出模式
```

#### 2.3.3 `classify` - 数据分类命令

```bash
health_tool classify [OPTIONS]

功能：根据规则对数据进行分类保存

参数：
  -i, --input <PATH>      输入CSV文件或目录（必需）
  -o, --output <PATH>     输出目录（必需）
  -r, --rule <FILE>       分类规则文件（YAML格式，必需）
      --copy              复制文件到分类目录（默认）
      --move              移动文件到分类目录
      --symlink           创建符号链接
      --report            生成分类报告
      --unknown <DIR>     未匹配文件的存放目录
  -v, --verbose           详细输出模式
```

#### 2.3.4 `convert` - 格式转换命令

```bash
health_tool convert [OPTIONS]

功能：CSV格式转换（紧凑型↔展开型，芯片特定格式）

参数：
  -i, --input <PATH>      输入CSV文件或目录（必需）
  -o, --output <PATH>     输出文件或目录（必需）
  -r, --rule <FILE>       转换规则文件（YAML格式）
  -c, --chip <NAME>       目标芯片格式
      --from <FORMAT>     源格式: compact|expand|chip
      --to <FORMAT>       目标格式: compact|expand|chip
      --merge             合并多个文件
      --split <SIZE>      按大小分割文件（行数）
  -v, --verbose           详细输出模式
```

#### 2.3.5 `info` - 信息查看命令

```bash
health_tool info [OPTIONS] <TARGET>

功能：查看数据文件或规则文件信息

参数：
  <TARGET>                目标文件路径
      --stats             显示统计信息
      --schema            显示数据结构
      --preview <N>       预览前N行（默认: 10）
```

#### 2.3.6 `validate` - 规则验证命令

```bash
health_tool validate <RULE_FILE>

功能：验证YAML规则文件格式和内容

参数：
  <RULE_FILE>             规则文件路径
      --strict            严格模式验证
```

---

## 三、全局选项

```bash
health_tool [GLOBAL_OPTIONS] <command>

全局选项：
  --config <FILE>         指定配置文件
  --log-level <LEVEL>     日志级别: debug|info|warning|error
  --version               显示版本信息
  --help                  显示帮助信息
```

---

## 四、YAML规则文件格式设计

### 4.1 规则文件目录结构

```
rules/
├── chip/                    # 芯片CSV格式规则
│   ├── gh3220.yaml
│   ├── max30102.yaml
│   └── afe4400.yaml
├── parse/                   # 日志解析规则
│   ├── default.yaml
│   └── custom.yaml
├── classify/                # 分类规则
│   └── default.yaml
└── convert/                 # 转换规则
    └── standard.yaml
```

---

### 4.2 芯片规则文件 (rules/chip/*.yaml)

定义CSV文件的格式，用于读取或生成特定芯片格式的CSV。

```yaml
version: "1.0"
chip: gh3220

csv:
  header_row: 1          # 列名所在行（0表示无列名）
  data_start_row: 2      # 数据开始行
  delimiter: ","         # 分隔符
  encoding: "utf-8"      # 编码

columns:                 # 列定义（按顺序）
  - timestamp
  - red
  - ir
  - green
  - aux
```

**通道简写语法**：

支持使用 `name[start-end]` 格式表示连续通道：

```yaml
# 以下两种写法等价

# 方式1：完整写法
columns:
  - timestamp
  - ch0
  - ch1
  - ch2
  - ch3
  - ch4
  - ch5
  - ch6
  - ch7

# 方式2：简写
columns:
  - timestamp
  - ch[0-7]        # 展开为 ch0, ch1, ch2, ch3, ch4, ch5, ch6, ch7
```

**更多简写示例**：

```yaml
# 16通道数据
columns:
  - timestamp
  - ch[0-15]       # 展开为 ch0~ch15

# 多个范围
columns:
  - timestamp
  - led[1-4]       # 展开为 led1, led2, led3, led4
  - aux[0-2]       # 展开为 aux0, aux1, aux2

# 混合写法
columns:
  - timestamp
  - red
  - ir
  - ch[0-3]        # 展开为 ch0, ch1, ch2, ch3
```

**示例：带信息头的CSV格式**

```yaml
version: "1.0"
chip: gh3220_custom

csv:
  header_row: 2          # 第2行是列名
  data_start_row: 3      # 第3行开始是数据
  delimiter: ","
  encoding: "utf-8"

columns:
  - TIME
  - RED
  - IR
  - GREEN
```

对应CSV文件：
```csv
# GH3220 PPG Data Export
TIME,RED,IR,GREEN
2024-01-01 12:00:00.000,123456,234567,345678
2024-01-01 12:00:00.010,123460,234570,345680
```

---

### 4.3 解析规则文件 (rules/parse/*.yaml)

定义如何用正则表达式解析日志文件。

```yaml
version: "1.0"
description: "GH3220日志解析规则"

regex: '^\[(.+?)\]\s+GH3220:\s*(\d+),(\d+),(\d+),(\d+)$'

columns:           # 按正则捕获组顺序定义列名
  - timestamp
  - red
  - ir
  - green
  - aux
```

**通道简写语法**：

与芯片规则相同，支持 `name[start-end]` 格式：

```yaml
# 16通道数据解析
regex: '^\[(.+?)\]\s*(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(\d+),(\d+)$'

columns:
  - timestamp
  - ch[0-15]       # 展开为 ch0~ch15，对应捕获组2-17
```

**示例：MAX30102解析规则**

```yaml
version: "1.0"
description: "MAX30102日志解析规则"

regex: '^\[(.+?)\]\s*(\d+),(\d+)$'

columns:
  - timestamp
  - red
  - ir
```

**示例：简单空格分隔**

```yaml
version: "1.0"
description: "空格分隔数据"

regex: '^(\S+)\s+(\d+)\s+(\d+)\s+(\d+)$'

columns:
  - timestamp
  - ch1
  - ch2
  - ch3
```

---

### 4.4 分类规则文件 (rules/classify/*.yaml)

定义数据分类规则，支持从文件名和数据列进行目录分类。

```yaml
version: "1.0"
description: "PPG数据分类规则"

# 从文件名提取信息
filename:
  regex: '(\d{8})_(\w+)_(\w+)_(\w+)_(\d+Hz)'
  fields:
    - date        # 日期
    - chip        # 芯片型号
    - company     # 公司名称
    - project     # 项目代号
    - sample_rate # 采样频率

# 从数据列提取信息
data_columns:
  - name: spo2
    type: int
    ranges:
      normalSpO2: [95, 100]
      lowspo2: [0, 95]
  - name: motion
    type: string
    values: [supine, sit, stand, walk, run]

# 分类目录结构
structure:
  # 格式: 目录名: 子目录列表（用|分隔）
  supine: "normalSpO2|lowspo2"
  supine/lowspo2: "75-80|80-85|85-90|90-95"
  sit: "normalSpO2|lowspo2"
  sit/lowspo2: "75-80|80-85|85-90|90-95"
  stand: "normalSpO2|lowspo2"
  stand/lowspo2: "75-80|80-85|85-90|90-95"
  lowTemperature: "normalSpO2|lowspo2"
  lowTemperature/lowspo2: "75-80|80-85|85-90|90-95"
  highToLow: ""

# 分类匹配规则
rules:
  # 根据数据列值匹配目录
  - target: "{motion}/{spo2_level}/{spo2_range}"
    conditions:
      spo2_level:
        normalSpO2: "spo2 >= 95"
        lowspo2: "spo2 < 95"
      spo2_range:
        "75-80": "spo2 >= 75 and spo2 < 80"
        "80-85": "spo2 >= 80 and spo2 < 85"
        "85-90": "spo2 >= 85 and spo2 < 90"
        "90-95": "spo2 >= 90 and spo2 < 95"

  # 特殊情况
  - target: "highToLow"
    condition: "motion == 'supine' and spo2_trend == 'decreasing'"

# 默认分类
default: unclassified
```

---

### 4.5 分类规则详解

#### 4.5.1 文件名解析

从文件名提取元数据用于分类：

```yaml
filename:
  regex: '(\d{8})_(\w+)_(\w+)_(\w+)_(\d+Hz)\.csv'
  fields:
    - date        # 20251210
    - chip        # gh3020
    - company     # XXX
    - project     # T1-SmartWatch
    - sample_rate # 25Hz
```

示例文件名：`20251210_gh3020_XXX_T1-SmartWatch_25Hz.csv`

提取结果：
- `date`: `20251210`
- `chip`: `gh3020`
- `company`: `XXX`
- `project`: `T1-SmartWatch`
- `sample_rate`: `25Hz`

#### 4.5.2 数据列分类

根据数据列的值进行分类：

```yaml
data_columns:
  # 数值范围分类 - 指定列名
  - name: spo2
    column: spo2          # 列名
    type: int
    ranges:
      normalSpO2: [95, 100]
      lowspo2: [0, 95]
  
  # 数值范围分类 - 指定列索引（从0开始）
  - name: hr
    column_index: 2       # 第3列
    type: int
    ranges:
      normal: [60, 100]
      high: [100, 200]
  
  # 枚举值分类 - 数据列
  - name: motion
    column: motion_type
    type: string
    values: [supine, sit, stand, walk, run]
  
  # 从文件名获取 - 字符串匹配
  - name: motion
    source: filename      # 来源：filename 或 parent_dir
    type: string
    match:
      supine: ["supine", "lie", "lying"]    # 文件名包含这些字符串
      sit: ["sit", "sitting"]
      stand: ["stand", "standing"]
      walk: ["walk", "walking"]
      run: ["run", "running"]
  
  # 从父目录名获取
  - name: subject
    source: parent_dir
    type: string
    match:
      subject1: ["S001", "subject1"]
      subject2: ["S002", "subject2"]
  
  # 从文件名正则提取
  - name: chip
    source: filename
    type: string
    regex: '_(\w+)_\d+Hz'
    group: 1              # 正则捕获组
  
  # 计算列
  - name: hr
    type: int
    compute: "calculate_hr(red, ir)"
```

**字段说明**：

| 字段 | 说明 | 可选值 |
|------|------|--------|
| `column` | 数据列名 | 列名字符串 |
| `column_index` | 数据列索引 | 整数（从0开始） |
| `source` | 数据来源 | `data`（默认）, `filename`, `parent_dir` |
| `match` | 字符串匹配规则 | `{值: [匹配字符串列表]}` |
| `regex` | 正则提取 | 正则表达式 |
| `group` | 正则捕获组 | 整数（从1开始） |

#### 4.5.3 目录结构定义

定义分类后的目录结构：

```yaml
structure:
  # 单层目录
  highToLow: ""
  
  # 两层目录
  supine: "normalSpO2|lowspo2"
  sit: "normalSpO2|lowspo2"
  
  # 三层目录
  supine/lowspo2: "75-80|80-85|85-90|90-95"
  sit/lowspo2: "75-80|80-85|85-90|90-95"
```

生成的目录结构：
```
parent_dir/
├── highToLow/
├── supine/
│   ├── normalSpO2/
│   └── lowspo2/
│       ├── 75-80/
│       ├── 80-85/
│       ├── 85-90/
│       └── 90-95/
├── sit/
│   ├── normalSpO2/
│   └── lowspo2/
│       ├── 75-80/
│       ├── 80-85/
│       ├── 85-90/
│       └── 90-95/
└── ...
```

#### 4.5.4 分类匹配规则

定义如何将文件/数据匹配到目录：

```yaml
rules:
  # 使用变量匹配
  - target: "{motion}/{spo2_level}"
    conditions:
      spo2_level:
        normalSpO2: "spo2 >= 95"
        lowspo2: "spo2 < 95"
  
  # 使用文件名字段
  - target: "{chip}/{project}"
    use_filename: true
  
  # 条件匹配
  - target: "highToLow"
    condition: "spo2_start >= 95 and spo2_end < 85"
```

---

### 4.6 分类规则示例

#### 示例1：简单文件名分类

```yaml
version: "1.0"

filename:
  regex: '(\w+)_(\w+)_(\d+)\.csv'
  fields:
    - subject
    - motion
    - trial

structure:
  supine: ""
  sit: ""
  stand: ""

rules:
  - target: "{motion}"
    use_filename: true
```

#### 示例2：数据列值分类

```yaml
version: "1.0"

data_columns:
  - name: spo2
    type: int
    ranges:
      normal: [95, 100]
      low: [0, 95]

structure:
  normal: ""
  low: ""

rules:
  - target: "{spo2_level}"
    conditions:
      spo2_level:
        normal: "mean(spo2) >= 95"
        low: "mean(spo2) < 95"
```

#### 示例3：复合分类（文件名+数据列）

```yaml
version: "1.0"

filename:
  regex: '(\d{8})_(\w+)_(\w+)\.csv'
  fields:
    - date
    - subject
    - motion

data_columns:
  - name: spo2
    type: int

structure:
  "{motion}": "normal|low"
  "{motion}/low": "75-85|85-95"

rules:
  - target: "{motion}/{spo2_level}"
    conditions:
      spo2_level:
        normal: "mean(spo2) >= 95"
        low: "mean(spo2) < 95"
  
  - target: "{motion}/low/{spo2_range}"
    conditions:
      spo2_range:
        "75-85": "mean(spo2) >= 75 and mean(spo2) < 85"
        "85-95": "mean(spo2) >= 85 and mean(spo2) < 95"
```

---

### 4.5 转换规则文件 (rules/convert/*.yaml)

定义CSV格式转换映射。

```yaml
version: "1.0"
description: "紧凑格式转GH3220格式"

source_columns:          # 源CSV列名
  - timestamp
  - red
  - ir
  - green

target_columns:          # 目标CSV列名（按顺序映射）
  - TIME
  - RED
  - IR
  - GREEN
```

**示例：添加计算列**

```yaml
version: "1.0"
description: "添加校验和列"

source_columns:
  - timestamp
  - red
  - ir

target_columns:
  - TIME
  - RED
  - IR
  - SUM

computed:                # 计算列
  SUM: "red + ir"
```

---

### 4.6 规则使用示例

```bash
# 解析日志（使用内置解析规则）
health_tool parse -i raw.log -o output.csv -r parse/default.yaml

# 解析日志并输出为GH3220格式
health_tool parse -i raw.log -o output.csv -r parse/default.yaml --chip gh3220

# 转换CSV格式
health_tool convert -i input.csv -o output.csv --chip gh3220

# 分类数据
health_tool classify -i data/ -o classified/ -r classify/default.yaml
```

---

### 4.7 内置芯片规则

#### GH3220 (rules/chip/gh3220.yaml)

```yaml
version: "1.0"
chip: gh3220

csv:
  header_row: 1
  data_start_row: 2
  delimiter: ","
  encoding: "utf-8"

columns:
  - timestamp
  - red
  - ir
  - green
  - aux
```

#### MAX30102 (rules/chip/max30102.yaml)

```yaml
version: "1.0"
chip: max30102

csv:
  header_row: 1
  data_start_row: 2
  delimiter: ","
  encoding: "utf-8"

columns:
  - timestamp
  - red
  - ir
```

#### AFE4400 (rules/chip/afe4400.yaml)

```yaml
version: "1.0"
chip: afe4400

csv:
  header_row: 1
  data_start_row: 2
  delimiter: ","
  encoding: "utf-8"

columns:
  - timestamp
  - led1
  - led2
  - led3
```

---

## 五、项目结构

```
health_tools/
├── pyproject.toml           # 项目配置（PEP 517/518）
├── README.md                # 项目说明
├── LICENSE                  # 许可证
├── .gitignore               # Git忽略配置
├── src/
│   └── health_tools/
│       ├── __init__.py      # 包初始化
│       ├── __main__.py      # 入口点
│       ├── cli.py           # CLI主模块
│       ├── commands/        # 命令实现
│       │   ├── __init__.py
│       │   ├── parse.py     # parse命令
│       │   ├── plot.py      # plot命令
│       │   ├── classify.py  # classify命令
│       │   ├── convert.py   # convert命令
│       │   ├── info.py      # info命令
│       │   └── validate.py  # validate命令
│       ├── core/            # 核心功能
│       │   ├── __init__.py
│       │   ├── parser.py    # 日志解析器
│       │   ├── plotter.py   # 数据绘图
│       │   ├── classifier.py # 数据分类
│       │   └── converter.py  # 格式转换
│       ├── models/          # 数据模型
│       │   ├── __init__.py
│       │   ├── config.py    # 配置模型
│       │   └── data.py      # 数据模型
│       ├── rules/           # 规则处理
│       │   ├── __init__.py
│       │   ├── loader.py    # 规则加载
│       │   └── validator.py # 规则验证
│       └── utils/           # 工具函数
│           ├── __init__.py
│           ├── file.py      # 文件操作
│           └── logger.py    # 日志工具
├── tests/                   # 测试目录
│   ├── __init__.py
│   ├── conftest.py          # pytest配置
│   ├── test_cli.py
│   ├── test_parser.py
│   ├── test_plotter.py
│   ├── test_classifier.py
│   └── test_converter.py
├── rules/                   # 内置规则文件
│   ├── chip/                # 芯片规则
│   │   ├── gh3220.yaml      # GH3220芯片规则
│   │   ├── max30102.yaml    # MAX30102芯片规则
│   │   └── afe4400.yaml     # AFE4400芯片规则
│   ├── classify/            # 分类规则
│   │   ├── default.yaml
│   │   └── signal_quality.yaml
│   └── convert/             # 转换规则
│       └── standard.yaml
└── docs/                    # 文档目录
    └── usage.md
```

---

## 六、依赖库

```toml
[project]
dependencies = [
    "click>=8.1.0",           # CLI框架
    "pandas>=2.0.0",          # 数据处理
    "numpy>=1.24.0",          # 数值计算
    "pyyaml>=6.0",            # YAML解析
    "matplotlib>=3.7.0",      # 绑图
    "scipy>=1.10.0",          # 信号处理
    "rich>=13.0.0",           # 终端美化输出
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "black>=23.0.0",
    "ruff>=0.1.0",
    "mypy>=1.0.0",
]
```

---

## 七、推荐扩展功能

| 功能 | 命令 | 描述 |
|------|------|------|
| 数据过滤 | `health_tool filter` | 按条件过滤数据 |
| 数据合并 | `health_tool merge` | 合并多个CSV文件 |
| 数据重采样 | `health_tool resample` | 重采样数据 |
| 信号质量评估 | `health_tool assess` | 评估信号质量 |
| 特征提取 | `health_tool extract` | 提取PPG特征（HR, HRV, SpO2等） |
| 批量处理 | `health_tool batch` | 批量执行多个命令 |
| 配置管理 | `health_tool config` | 管理配置文件 |

---

## 八、开发步骤

### 阶段一：项目初始化
1. 创建项目结构
2. 配置 pyproject.toml
3. 设置开发环境

### 阶段二：核心功能开发
1. 实现CLI框架（使用Click）
2. 实现规则加载器
3. 实现日志解析器
4. 实现数据绘图功能
5. 实现数据分类功能
6. 实现格式转换功能

### 阶段三：测试与文档
1. 编写单元测试
2. 编写集成测试
3. 编写使用文档
4. 创建示例规则文件

### 阶段四：发布准备
1. 代码质量检查
2. 版本号管理
3. 打包发布

---

## 九、使用示例

### 9.1 日志解析

```bash
# 使用GH3220芯片规则解析日志（自动查找内置规则）
health_tool parse -i raw_data.log -o output.csv --chip gh3220

# 使用自定义规则文件
health_tool parse -i raw_data.log -o output.csv -r custom_rule.yaml

# 指定输出格式
health_tool parse -i raw_data.log -o output.csv --chip gh3220 --format chip_specific

# 批量处理目录
health_tool parse -i logs/ -o output/ --chip gh3220 --verbose
```

### 9.2 数据可视化

```bash
# 绘制时域和频域图
health_tool plot -i output.csv -o plots/ --type both --sample-rate 100

# 仅绘制时域图
health_tool plot -i output.csv -o plots/ --type time --channels red,ir

# 指定窗口和重叠率
health_tool plot -i output.csv -o plots/ --window 10 --overlap 0.75
```

### 9.3 数据分类

```bash
# 使用默认分类规则
health_tool classify -i data/ -o classified/ -r rules/classify/default.yaml

# 生成分类报告
health_tool classify -i data/ -o classified/ -r rules/classify/default.yaml --report

# 移动文件而非复制
health_tool classify -i data/ -o classified/ -r rules/classify/default.yaml --move
```

### 9.4 格式转换

```bash
# 紧凑型转展开型
health_tool convert -i compact.csv -o expand.csv --from compact --to expand

# 转换为GH3220特定格式
health_tool convert -i input.csv -o output.csv --chip gh3220 --to chip_specific

# 合并多个文件
health_tool convert -i data/*.csv -o merged.csv --merge
```

### 9.5 信息查看

```bash
# 查看数据文件信息
health_tool info data.csv --stats --preview 20

# 查看规则文件结构
health_tool info rules/chip/gh3220.yaml --schema
```

### 9.6 规则验证

```bash
# 验证规则文件
health_tool validate rules/chip/gh3220.yaml

# 严格模式验证
health_tool validate rules/chip/gh3220.yaml --strict
```

---

## 十、数据流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                        health_tool 工作流程                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐    parse     ┌──────────┐    plot     ┌────────┐ │
│  │ 原始日志  │ ──────────→ │ CSV数据   │ ──────────→ │ 时频图  │ │
│  │  .log    │             │  .csv    │             │  .png  │ │
│  └──────────┘             └──────────┘             └────────┘ │
│       │                        │                               │
│       │                        │ classify                      │
│       │                        ↓                               │
│       │                  ┌──────────┐                          │
│       │                  │ 分类数据  │                          │
│       │                  │  /分类目录 │                          │
│       │                  └──────────┘                          │
│       │                        │                               │
│       │                        │ convert                       │
│       │                        ↓                               │
│       │                  ┌──────────┐                          │
│       └─────────────────→│ 芯片格式  │                          │
│                          │ CSV      │                          │
│                          └──────────┘                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 十一、规则文件快速参考

### 通道简写语法

| 格式 | 说明 | 展开结果 |
|------|------|----------|
| `ch[0-7]` | 连续数字范围 | `ch0, ch1, ch2, ch3, ch4, ch5, ch6, ch7` |
| `led[1-4]` | 从1开始的范围 | `led1, led2, led3, led4` |
| `ch[0-15]` | 16通道 | `ch0~ch15` |

### 芯片规则 (chip/*.yaml)

| 字段 | 说明 | 示例 |
|------|------|------|
| `version` | 规则版本 | `"1.0"` |
| `chip` | 芯片名称 | `gh3220` |
| `csv.header_row` | 列名所在行 | `1` |
| `csv.data_start_row` | 数据开始行 | `2` |
| `csv.delimiter` | 分隔符 | `","` |
| `columns` | 列名列表（支持简写） | `[timestamp, ch[0-7]]` |

### 解析规则 (parse/*.yaml)

| 字段 | 说明 | 示例 |
|------|------|------|
| `version` | 规则版本 | `"1.0"` |
| `regex` | 正则表达式 | `'^\[(.+?)\]\s*(\d+),(\d+)$'` |
| `columns` | 捕获组对应列名（支持简写） | `[timestamp, ch[0-7]]` |

### 分类规则 (classify/*.yaml)

| 字段 | 说明 | 示例 |
|------|------|------|
| `version` | 规则版本 | `"1.0"` |
| `filename.regex` | 文件名正则 | `'(\d{8})_(\w+)\.csv'` |
| `filename.fields` | 文件名字段 | `[date, chip]` |
| `data_columns` | 数据列定义 | `[{name: spo2, ranges: {...}}]` |
| `structure` | 目录结构 | `{supine: "normal\|low"}` |
| `rules` | 分类匹配规则 | `[{target, conditions}]` |
| `default` | 默认分类 | `unknown` |

### 转换规则 (convert/*.yaml)

| 字段 | 说明 | 示例 |
|------|------|------|
| `version` | 规则版本 | `"1.0"` |
| `source_columns` | 源列名（支持简写） | `[timestamp, ch[0-7]]` |
| `target_columns` | 目标列名（支持简写） | `[TIME, CH[0-7]]` |
| `computed` | 计算列 | `{SUM: "red + ir"}` |
