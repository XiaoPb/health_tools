# 命令详细说明

## parse - 日志解析

将原始日志文件按正则规则解析为CSV格式。

```bash
ghealth_tool parse -i <输入> -o <输出> [-r <规则文件>] [-c <芯片>] [--delimiter <分隔符>]
```

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入日志文件或目录（必需） |
| `-o, --output` | 输出CSV文件或目录（必需） |
| `-r, --rule` | 解析规则文件（YAML） |
| `-c, --chip` | 芯片名称（使用内置芯片规则） |
| `--delimiter` | 字段分隔符（默认逗号） |

### 示例

```bash
# 单文件解析
ghealth_tool parse -i raw.log -o output.csv -r parse/gh3220.yaml

# 目录批量解析
ghealth_tool parse -i logs/ -o output/ -c gh3220

# 使用别名
ghealth_tool p -i raw.log -o output.csv -c gh3220
```

### 工作原理

1. 加载解析规则（正则表达式 + 列名定义）
2. 逐行匹配日志，提取字段
3. 按芯片规则写入CSV（含信息行、表头）

---

## plot - 数据可视化

绘制PPG数据的时域图、频域图或时频图（STFT）。

```bash
ghealth_tool plot -i <输入> -o <输出目录> [--type <类型>] [--sample-rate <采样率>]
```

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入CSV文件（必需） |
| `-o, --output` | 输出目录（必需） |
| `--type` | 图表类型：time / freq / both / stft |
| `--sample-rate` | 采样率（Hz） |
| `--channels` | 指定绘制的通道（逗号分隔） |
| `--window` | 窗口大小（秒） |
| `--overlap` | 窗口重叠率（0-1） |

### 示例

```bash
# 时域+频域
ghealth_tool plot -i data.csv -o plots/ --type both --sample-rate 100

# 仅时域，指定通道
ghealth_tool plot -i data.csv -o plots/ --type time --channels red,ir

# STFT时频图
ghealth_tool plot -i data.csv -o plots/ --type stft --sample-rate 100 --window 10
```

---

## classify - 数据分类

根据文件名模式和规则将CSV文件分类到目录结构中。

```bash
ghealth_tool classify -i <输入目录> -o <输出目录> [-r <规则>] [--accuracy] [--move]
```

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入CSV文件或目录（必需） |
| `-o, --output` | 输出目录（必需） |
| `-r, --rule` | 分类规则文件（默认 spo2_posture.yaml） |
| `--extend` | 扩展patterns文件（可多次使用） |
| `--accuracy` | 启用准确率计算 |

### 示例

```bash
# 基本分类
ghealth_tool classify -i data/ -o classified/ -r classify/spo2_posture.yaml

# 使用别名 + 准确率
ghealth_tool cls -i data/ -o classified/ --accuracy
```

---

## convert - 格式转换

CSV格式转换，支持列映射、前值填充、频率扩展、合并和分割。

```bash
ghealth_tool convert -i <输入> -o <输出> -r <规则> [--merge] [--split <行数>]
```

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入CSV文件或目录（必需） |
| `-o, --output` | 输出文件或目录（必需） |
| `-r, --rule` | 转换规则文件（必需） |
| `-c, --chip` | 目标芯片格式（仅用于 --init-rule） |
| `--merge` | 合并目录中所有CSV |
| `--split` | 按行数分割输出 |
| `--init-rule` | 生成转换规则模板 |
| `-v, --verbose` | 详细输出 |

### 示例

```bash
# 使用转换规则
ghealth_tool cv -i input.csv -o output.csv -r convert/my_rule.yaml -v

# 合并目录并分割
ghealth_tool cv -i data/ -o merged.csv -r convert/rule.yaml --merge --split 5000

# 生成规则模板
ghealth_tool convert --init-rule -c gh3220 -o my_convert_rule.yaml

# 从输入文件自动匹配列名生成模板
ghealth_tool convert --init-rule -c gh3220 -i input.csv -o my_convert_rule.yaml
```

### 转换流程

1. 按 convert rule 的 `csv` 配置读取输入文件
2. 执行列映射（`column_mapping`）
3. 执行计算列（`computed`）
4. 执行频率扩展（`expand_repeat`）
5. 执行前值填充（`forward_fill`）
6. 补齐目标芯片缺失列（填0）
7. 按芯片列顺序排列
8. 保持Int64整数类型
9. 按芯片规则的CSV格式写入输出

### 前值填充 (forward_fill)

在首个非0值出现后，将后续的0值替换为前一个非0值：

```
输入: [0, 0, 3, 0, 0, 4, 0, 0, 5]
输出: [0, 0, 3, 3, 3, 4, 4, 4, 5]
```

规则中使用源列名（映射前的名称）。

### 频率扩展 (expand_repeat)

当某列采样率低于其他列时，将每个值重复N次以对齐行数：

```yaml
expand_repeat:
  polar_HR: 25    # 1Hz -> 25Hz，每个值重复25次
```

---

## split - 数据分割

按行数分割大型CSV文件。

```bash
ghealth_tool split -i <输入> -o <输出目录> -n <行数>
```

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入CSV文件（必需） |
| `-o, --output` | 输出目录（必需） |
| `-n, --rows` | 每个分片的行数 |

---

## info - 信息查看

查看CSV数据文件或规则文件的基本信息。

```bash
ghealth_tool info <文件路径> [--stats] [--preview <行数>] [--schema]
```

| 参数 | 说明 |
|---|---|
| `文件路径` | 要查看的文件 |
| `--stats` | 显示统计信息 |
| `--preview` | 预览前N行数据 |
| `--schema` | 显示规则文件结构 |

### 示例

```bash
# 查看CSV信息和统计
ghealth_tool info data.csv --stats --preview 10

# 查看规则文件结构
ghealth_tool info rules/chip/gh3220.yaml --schema

# 使用别名
ghealth_tool i data.csv --stats
```

---

## validate - 规则验证

验证YAML规则文件的格式和内容是否正确。

```bash
ghealth_tool validate <规则文件> [--strict]
```

| 参数 | 说明 |
|---|---|
| `规则文件` | 要验证的YAML文件 |
| `--strict` | 严格模式（检查列名是否存在于芯片定义中） |

---

## process - 批量处理

执行批量数据处理流水线。

```bash
ghealth_tool process -i <输入目录> -o <输出目录> [选项]
```

---

## factory - 产测计算

计算 SNR/CTR/Noise，支持芯片规则自动提取增益和灯电流。别名：`fac`。

```bash
ghealth_tool factory -i <输入> -c <芯片> [选项]
ghealth_tool fac -i <输入> -c <芯片> [选项]
```

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入 CSV 文件或目录（必需） |
| `-c, --chip` | 芯片类型 |
| `-r, --rule` | 转换规则文件 |
| `--gain` | 增益参数（KΩ），覆盖自动提取 |
| `--current` | 灯电流（mA），覆盖自动提取 |
| `--sample-rate` | 采样率 Hz |
| `--snr-cfg` | SNR 配置：skip_head,skip_tail,min_duration |
| `--ctr-cfg` | CTR 配置：skip_head,skip_tail,min_duration |
| `--noise-cfg` | Noise 配置：skip_head,skip_tail,min_duration |
| `--channels` | 指定计算通道（逗号分隔） |
| `-o, --output` | 输出结果 CSV 文件或目录 |
| `-v, --verbose` | 详细输出 |

### 示例

```bash
# 单文件计算
ghealth_tool fac -i data.csv -c gh3036_evk

# 目录批量（不匹配文件自动跳过）
ghealth_tool fac -i data_dir/ -c gh3036_evk -v

# 覆盖时长配置
ghealth_tool fac -i data.csv -c gh3036_evk --snr-cfg "5,5,60"

# 指定增益和电流
ghealth_tool fac -i data.csv -c gh3036 --gain 10 --current 25.0 -o results.csv
```

### 工作原理

1. 加载芯片规则，读取 `factory_columns` 和 `factory_config`
2. 从 `chip_info` 获取 ADC 参数（adc_full_scale, adc_offset, adc_vref, tia_ratio）
3. 自动从数据中提取每通道的增益和灯电流（source 列全为 0 时跳过 CTR）
4. 各指标独立判断数据时长：满足哪个算哪个，全不满足才跳过
5. 输出 chip_info 面板和计算结果表

---

## check - 数据检查

检查PPG/ACC数据完整性和正确性。别名：`chk`。

```bash
ghealth_tool check <路径> [-c <芯片>] [--checks <检查项>] [--tolerance <pA>] [-o <输出>] [-v]
```

| 参数 | 说明 |
|---|---|
| `路径` | 输入CSV文件或目录（必需） |
| `-c, --chip` | 芯片型号，不指定则自动识别 |
| `--checks` | 指定检查项（逗号分隔: range,ipd,frame,center,acc），默认全部 |
| `--tolerance` | Ipd转换误差容忍度（pA，默认50） |
| `-o, --output` | 检查报告CSV输出路径（默认: `<path>/check_report.csv`） |
| `-v, --verbose` | 显示详细信息 |

### 检查项

| 检查项 | 说明 |
|---|---|
| `range` | 检查原始数据是否在ADC正常范围内 |
| `frame` | 检查FRAME_ID完整性（丢包检测） |
| `center` | 检查数据去除基线后是否居中 |
| `ipd` | 检查Ipd_pA与Rawdata转换一致性（仅GH3036） |
| `acc` | ACC加速度计异常检测（全零/静止/循环） |

### ACC异常检测

检测三种加速度计数据异常：

1. **全零异常**: ACCX、ACCY、ACCZ同时为0的连续段
2. **静止异常**: 单通道或多通道连续不变超过3个点，区分XYZ全部卡死或部分通道卡死
3. **循环异常**: 固定序列重复≥2个完整周期（周期长度2~50点），排除静止段避免重复计数

输出汇总表格（每文件一行）和统一CSV报告文件。CSV包含全部检查项的结果（PASS/FAIL + 说明）以及ACC异常详细字段（次数、通道、首帧FRAME_ID、最长持续帧数）。

### 列名解析

ACC和帧号列名支持规则文件指定或自动检测：

| 字段 | 规则文件配置 | 自动检测规则 |
|---|---|---|
| ACC XYZ | `acc_columns: {x: "列名", y: "列名", z: "列名"}` | 匹配含acc+x/y/z的列名（大小写不敏感）；其次匹配纯x/y/z |
| 帧号 | `frame_column: "列名"` | 匹配frame_id/frame/fid（大小写不敏感）；无匹配时回退行索引 |

### 示例

```bash
# 检查目录下所有CSV
ghealth_tool check data/ -v

# 仅检查ACC异常
ghealth_tool check data/ --checks acc

# 指定报告输出路径
ghealth_tool check data/ -o report/check_result.csv

# 仅检查数据范围和帧完整性
ghealth_tool check data.csv --checks range,frame

# 使用别名
ghealth_tool chk data/ -c gh3036 --checks acc,frame
```

### CSV报告格式

统一输出一个CSV文件，每文件一行，列结构：

```
文件名, 芯片, 数据范围(结果), 数据范围(说明), 帧完整性(结果), 帧完整性(说明), ..., ACC全零次数, ACC全零通道, ACC全零首帧, ACC全零最长帧, ACC静止次数, ACC静止通道, ACC静止首帧, ACC静止最长帧, ACC循环次数, ACC循环通道, ACC循环首帧, ACC循环最长帧
```

检查项列动态生成，只包含实际运行的检查项。未运行的检查项不会出现在CSV中。

---

## offline - 离线跑库

调用离线算法工具（TEE_Algorithm.exe）进行心率计算，支持准确度统计和PSD时频图。别名：`ol`。

```bash
ghealth_tool offline -i <输入目录> -c <芯片> [选项]
```

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入数据目录（必需） |
| `-o, --output` | 输出结果目录（默认: `<input>_offline_result`） |
| `-c, --chip` | 芯片型号（如 gh3036, gh3220） |
| `--version` | 算法版本（覆盖默认版本） |
| `--hba-fs` | 采样率（默认25） |
| `--scene-en` | 场景适配 0=关 1=开（默认0） |
| `--ch-num` | 有效PPG通道数（默认2） |
| `--ref-col` | 源CSV中金标列索引（1-based，覆盖芯片配置） |
| `--no-accuracy` | 跳过准确度统计 |
| `--no-plot` | 跳过PSD时频图绘制 |
| `--no-run` | 跳过跑库，直接整理/统计/绘图 |
| `--list` | 列出可用芯片和版本 |
| `--timeout` | 超时时间（秒，默认300） |
| `-v, --verbose` | 详细输出 |

### 算法版本管理

离线工具按芯片和等级分类存放，等级包括：exclusive、premium、medium、basic。

```bash
# 查看可用版本
ghealth_tool offline --list

# 设置离线工具路径
ghealth_tool cfg --offline-path /path/to/offline_algorithm_tools

# 扫描版本
ghealth_tool cfg --offline-scan

# 设置默认版本
ghealth_tool cfg --offline-default gh3220=V4300_GH_HR_exc_pv_v2.0.3.0
```

### 示例

```bash
# 基本跑库
ghealth_tool offline -i data/ -c gh3220

# 指定版本
ghealth_tool offline -i data/ -c gh3220 --version V4200_GH_HR_exc_pv_v1.0.1.0

# 仅整理已有结果（跳过跑库）
ghealth_tool offline -i data/ -c gh3220 --no-run

# 跳过绘图
ghealth_tool offline -i data/ -c gh3036 --no-plot
```
