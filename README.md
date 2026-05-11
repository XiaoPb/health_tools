# Health Tools

PPG（光电容积脉搏波）数据分析命令行工具库，支持数据转换、可视化、分类等功能。

## 安装

```bash
pip install health-tools
```

或从源码安装：

```bash
git clone https://github.com/yourusername/health_tools.git
cd health_tools
pip install -e .
```

## 快速开始

```bash
# 查看帮助
health_tool --help

# 查看版本
health_tool --version
```

## 命令

### parse - 日志解析

将原始日志文件解析为CSV格式。

```bash
# 使用解析规则文件
health_tool parse -i raw.log -o output.csv -r parse/gh3220.yaml

# 使用芯片规则
health_tool parse -i raw.log -o output.csv --chip gh3220

# 批量处理目录
health_tool parse -i logs/ -o output/ -r parse/default.yaml -v
```

### plot - 数据可视化

绘制PPG数据的时域/频域图。

```bash
# 绘制时域和频域图
health_tool plot -i data.csv -o plots/ --type both --sample-rate 100

# 仅绘制时域图
health_tool plot -i data.csv -o plots/ --type time --channels red,ir

# 指定窗口和重叠率
health_tool plot -i data.csv -o plots/ --window 10 --overlap 0.75
```

### classify - 数据分类

根据规则对数据进行分类保存。

```bash
# 使用分类规则
health_tool classify -i data/ -o classified/ -r classify/default.yaml

# 生成分类报告
health_tool classify -i data/ -o classified/ -r classify/default.yaml --report

# 移动文件而非复制
health_tool classify -i data/ -o classified/ -r classify/default.yaml --move
```

### convert - 格式转换

CSV格式转换（紧凑型↔展开型，芯片特定格式）。

```bash
# 转换为芯片格式
health_tool convert -i input.csv -o output.csv --chip gh3220

# 合并多个文件
health_tool convert -i data/ -o merged.csv --merge

# 按大小分割
health_tool convert -i large.csv -o split/ --split 10000
```

### info - 信息查看

查看数据文件或规则文件信息。

```bash
# 查看CSV文件信息
health_tool info data.csv --stats --preview 20

# 查看规则文件
health_tool info rules/chip/gh3220.yaml --schema
```

### validate - 规则验证

验证YAML规则文件格式和内容。

```bash
# 验证规则文件
health_tool validate rules/chip/gh3220.yaml

# 严格模式验证
health_tool validate rules/parse/gh3220.yaml --strict
```

## 规则文件

### 芯片规则 (rules/chip/*.yaml)

定义CSV文件的格式：

```yaml
version: "1.0"
chip: gh3220

csv:
  header_row: 1          # 列名所在行
  data_start_row: 2      # 数据开始行
  delimiter: ","
  encoding: "utf-8"

columns:
  - timestamp
  - red
  - ir
  - green
```

### 解析规则 (rules/parse/*.yaml)

定义如何解析日志文件：

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

### 分类规则 (rules/classify/*.yaml)

定义数据分类规则：

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
      supine: ["supine", "lie"]
      sit: ["sit", "sitting"]

structure:
  supine: ""
  sit: ""

rules:
  - target: "{motion}"
    use_filename: true
```

### 转换规则 (rules/convert/*.yaml)

定义CSV格式转换，支持列映射、前值填充、频率扩展：

```yaml
version: "1.0"
target_chip: gh3220

csv:
  info_row: 0            # 信息所在行（0=无）
  header_row: 1          # 列名所在行
  data_start_row: 2      # 数据开始行
  delimiter: ","

column_mapping:
  time: TimeStamp
  acc[0]: ACCX           # [] 为字面量列名
  rawdata{0-15}: CH{0-15}  # {} 展开为 rawdata0->CH0, rawdata1->CH1, ...

forward_fill:
  - polar_HR             # 0值用前一个非0值填充

expand_repeat:
  polar_HR: 25           # 每个值重复25次匹配采样率
```

## 列名展开语法

支持两种范围展开语法：

```yaml
# chip/parse 规则中：[] 表示范围展开
columns:
  - ch[0-15]             # 展开为 ch0, ch1, ..., ch15

# convert 规则中：{} 表示范围展开，[] 为字面量
column_mapping:
  rawdata[{0-1}]: Rawdata{0-1}  # rawdata[0]->Rawdata0, rawdata[1]->Rawdata1
  acc[0]: ACCX                   # acc[0] 是字面量列名
```

## 内置芯片规则

| 芯片 | 文件 | 描述 |
|------|------|------|
| GH3220 | `rules/chip/gh3220.yaml` | Goodix PPG传感器 |
| GH3036 | `rules/chip/gh3036.yaml` | Goodix健康传感器 |

## 开发

### 环境设置

```bash
# 克隆仓库
git clone https://github.com/yourusername/health_tools.git
cd health_tools

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
.\venv\Scripts\activate  # Windows

# 安装开发依赖
pip install -e ".[dev]"
```

### 运行测试

```bash
pytest
```

### 代码格式化

```bash
black src/
ruff check src/
```

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
