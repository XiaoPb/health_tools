# GHealth Tools

PPG（光电容积脉搏波）数据分析命令行工具库，支持数据转换、可视化、分类等功能。

## 安装

```bash
pip install ghealth-tools
```

或从源码安装：

```bash
git clone https://github.com/XiaoPb/health_tools.git
cd health_tools
pip install -e .
```

## 快速开始

```bash
# 查看帮助
ghealth_tool --help

# 查看版本
ghealth_tool --version
```

## 命令

批量命令默认使用进度条并在结束时输出汇总统计。成功文件不会逐条刷屏；
空文件、格式不对、读取失败、列缺失、规则不匹配、无有效数据等会按原因聚合。
需要查看文件级明细时加 `-v/--verbose`。

### parse - 日志解析

将原始日志文件解析为CSV格式。

```bash
# 使用解析规则文件
ghealth_tool parse -i raw.log -o output.csv -r parse/gh3220.yaml

# 使用芯片规则
ghealth_tool parse -i raw.log -o output.csv --chip gh3220

# 批量处理目录
ghealth_tool parse -i logs/ -o output/ -r parse/default.yaml -v
```

### plot - 数据可视化

绘制PPG数据的时域/频域图，也支持 STFT 和离线结果 PSD 时频图。

```bash
# 绘制时域和频域图
ghealth_tool plot -i data.csv -o plots/ --type both --sample-rate 100

# 仅绘制时域图
ghealth_tool plot -i data.csv -o plots/ --type time --channels red,ir

# 指定窗口和重叠率
ghealth_tool plot -i data.csv -o plots/ --window 10 --overlap 0.75

# 离线结果目录生成PSD时频图，输出目录不存在时会自动创建
ghealth_tool plot -i offline_result/reorganized -o psd_plots/ --type psd
```

### classify - 数据分类

根据规则对数据进行分类保存。

```bash
# 使用分类规则
ghealth_tool classify -i data/ -o classified/ -r classify/default.yaml

# 生成分类报告
ghealth_tool classify -i data/ -o classified/ -r classify/default.yaml --report

# 移动文件而非复制
ghealth_tool classify -i data/ -o classified/ -r classify/default.yaml --move
```

### convert - 格式转换

CSV格式转换（紧凑型↔展开型，芯片特定格式）。

```bash
# 使用转换规则
ghealth_tool cv -i input.csv -o output.csv -r convert/my_rule.yaml

# 合并多个文件
ghealth_tool cv -i data/ -o merged.csv -r convert/rule.yaml --merge

# 按大小分割
ghealth_tool cv -i large.csv -o split/ -r convert/rule.yaml --split 10000

# 生成规则模板
ghealth_tool convert --init-rule -c gh3220 -o my_convert_rule.yaml
```

### factory - 产测计算

计算 SNR/CTR/Noise，支持芯片规则自动提取增益和灯电流。

```bash
# 单文件计算
ghealth_tool fac -i data.csv -c gh3036_evk

# 目录批量计算
ghealth_tool fac -i data_dir/ -c gh3036_evk -v

# 指定增益和电流
ghealth_tool fac -i data.csv -c gh3036 --gain 10 --current 25.0

# 覆盖默认时长配置
ghealth_tool fac -i data.csv -c gh3036_evk --snr-cfg "5,5,60" --ctr-cfg "1,0,2"
```

### info - 信息查看

查看数据文件或规则文件信息。

```bash
# 查看CSV文件信息
ghealth_tool info data.csv --stats --preview 20

# 查看规则文件
ghealth_tool info rules/chip/gh3220.yaml --schema
```

### check - 数据检查

检查PPG/ACC数据完整性和正确性。

```bash
# 检查目录下所有CSV（默认运行全部检查项）
ghealth_tool check -i data/ -v

# 仅检查ACC异常
ghealth_tool check -i data/ --checks acc

# 指定报告输出路径
ghealth_tool check -i data/ -o report/check_result.csv

# 仅检查数据范围和帧完整性
ghealth_tool check -i data.csv --checks range,frame

# 允许帧丢失不超过0.5%、ACC异常帧不超过2%
ghealth_tool check -i data/ --frame-ratio 0.5 --acc-ratio 2

# 检查指定时间戳列的相邻间隔稳定性
ghealth_tool check -i data/ --check-timestamp=timestamp

# 时间戳间隔允许0.2%波动，同时允许5ms固定偏差
ghealth_tool check -i data/ --check-timestamp=timestamp --timestamp-ratio 0.2 --timestamp-ms 5

# 按检查报告分拣正常/异常文件（默认读取当前目录 check_report.csv）
ghealth_tool check --sort --sort-output sorted/

# 指定检查报告分拣
ghealth_tool check --sort --report data/check_report.csv --sort-output sorted/

# 使用别名
ghealth_tool chk -i data/ -c gh3036
```

支持的检查项：`range`（数据范围）、`frame`（帧完整性）、`center`（数据居中）、`ipd`（Ipd转换）、`acc`（ACC异常检测）。

各单项检查输出 `PASS` / `WARNING` / `FAIL` 三态：无异常为 `PASS`，异常比例不超过对应 `--*-ratio` 参数为 `WARNING`，超过则为 `FAIL`。比例参数使用百分数数字，除 `--center-ratio` 默认5%外，其他比例默认1%。`WARNING` 在总异常判断中归为通过，CSV报告的 `总异常(结果)` 只输出 `PASS` 或 `FAIL`。

ACC异常检测识别三种异常：全零（XYZ同时为0）、静止（连续不变≥5帧，`--static-min`可配置）、循环（固定序列重复≥2周期）。支持规则文件指定ACC列名和帧号列名，或自动检测。ACC按异常覆盖帧去重后计算异常比例。`--check-timestamp=列名` 可额外检查时间戳间隔稳定性，`--timestamp-ratio` 使用百分数数字（如 `0.2` 表示0.2%）。`-o` 输出统一CSV报告，包含全部检查项结果、ACC异常详情和文件相对路径。`--sort` 读取报告后移动文件到 `normal/` / `abnormal/` 并生成对应列表CSV，不覆盖目标同名文件。

### evaluate - 指标评估

批量评估心率或血氧结果，生成文件明细、异常列表和准确度汇总。

```bash
# 心率评估
ghealth_tool evaluate -i result/ -o eval_out/ --type hr --chip gh3036

# 血氧评估，按列索引指定参考列和预测列
ghealth_tool eval -i result/ -o eval_out/ --type spo2 --ref-column-col 3 --pred-column-col 8
```

### validate - 规则验证

验证YAML规则文件格式和内容。

```bash
# 验证规则文件
ghealth_tool validate rules/chip/gh3220.yaml

# 严格模式验证
ghealth_tool validate rules/parse/gh3220.yaml --strict
```

## 规则文件

### 芯片规则 (rules/chip/*.yaml)

定义CSV文件的格式和产测计算参数：

```yaml
version: "1.0"
chip: gh3220

csv:
  info_row: 1
  header_row: 2
  data_start_row: 3
  delimiter: ","
  encoding: "utf-8"

columns:
  - TimeStamp
  - FRAME_ID
  - CH{0-15}

# ACC列名指定（可选，不指定则自动检测）
acc_columns:
  x: ACCX
  y: ACCY
  z: ACCZ

# 帧号列名指定（可选，不指定则自动检测）
frame_column: FRAME_ID

factory_columns:         # 产测计算列
  - CH{0-15}

factory_config:          # 各指标独立时长配置
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

chip_info:
  adc_full_scale: 8388608
  adc_offset: 8388608
  adc_vref: 1.8
  tia_ratio: 2
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

使用 `{start-end}` 进行范围展开，`[]` 保留为字面量：

```yaml
columns:
  - CH{0-15}             # 展开为 CH0, CH1, ..., CH15
  - ALGO{0-1}_CH{0-2}   # 多段展开: ALGO0_CH0, ALGO0_CH1, ..., ALGO1_CH2

column_mapping:
  rawdata[{0-1}]: Rawdata{0-1}  # rawdata[0]->Rawdata0, rawdata[1]->Rawdata1
  acc[0]: ACCX                   # acc[0] 是字面量列名
```

## 内置芯片规则

| 芯片 | 文件 | 描述 |
|------|------|------|
| GH3220 | `rules/chip/gh3220.yaml` | Goodix PPG传感器 |
| GH3036 | `rules/chip/gh3036.yaml` | Goodix健康传感器 |
| GH3036_EVK | `rules/chip/gh3036_evk.yaml` | GH3036 评估板 |

## 开发

### 环境设置

```bash
# 克隆仓库
git clone https://github.com/XiaoPb/health_tools.git
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
