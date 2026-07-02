# 命令详细说明

## 批量命令输出约定

`parse`、`plot`、`classify`、`convert`、`split`、`process`、`factory`、`evaluate`
和 `check` 在目录模式下默认使用进度条，并在结束时输出汇总统计。成功文件默认不逐条打印；
空文件、格式不对、读取失败、列缺失、规则不匹配、无有效数据等情况会按原因聚合展示。
需要查看具体文件明细时使用 `-v/--verbose`。

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

绘制PPG数据的时域图、频域图、时频图（STFT）或离线结果 PSD 时频图。

```bash
ghealth_tool plot -i <输入> -o <输出目录> [--type <类型>] [--sample-rate <采样率>]
```

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入CSV文件；PSD 模式为离线结果目录（必需） |
| `-o, --output` | 输出目录（必需） |
| `--type` | 图表类型：time / freq / both / stft / psd |
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

# 离线结果目录生成PSD时频图，输出目录不存在时会自动创建
ghealth_tool plot -i offline_result/reorganized -o psd_plots/ --type psd
```

`--type psd` 复用 `offline` 命令的 PSD 绘图方式，读取离线结果目录中的
`*_result.vshb`、`.prepsd`、`.accxpsd`、`.accypsd`、`.acczpsd` 文件并生成 PNG。
普通绘图参数（如 `--channels`、`--sample-rate`、`--format`）不影响 PSD 输出。

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

按列值、行数或时间分割CSV文件。

```bash
ghealth_tool split -i <输入> -o <输出目录> [--by-column <列名>] [--by-size <行数>] [--by-time <秒> --time-column <列名>]
```

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入CSV文件或目录（必需） |
| `-o, --output` | 输出目录（必需） |
| `-c, --chip` | 芯片类型（决定CSV格式） |
| `--by-column` | 按指定列值分割（默认 FRAME_ID） |
| `--column-value` | 分割值（默认 0） |
| `--by-size` | 每个分片的行数 |
| `--by-time` | 按时间分割（秒） |
| `--time-column` | 时间列名 |
| `--filter` | 目录模式下仅处理文件名包含指定字符的CSV |
| `-v, --verbose` | 显示失败/跳过明细 |

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

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入目录（必需） |
| `-o, --output` | 输出目录（必需） |
| `-c, --chip` | 芯片类型 |
| `--split` | 按FRAME_ID分割数据 |
| `--frame-column` | 帧ID列名（默认 FRAME_ID） |
| `--workers` | 并行线程数（默认4） |
| `--pattern` | 文件匹配模式（默认 *.csv） |
| `--filter` | 仅处理文件名包含指定字符的CSV |
| `-v, --verbose` | 显示失败/跳过明细 |

默认输出“处理结果”汇总，失败文件按原因聚合统计。

---

## evaluate - 评估指标

批量评估心率或血氧结果，输出文件明细、异常列表和准确度汇总。别名：`eval`。

```bash
ghealth_tool evaluate -i <输入目录> -o <输出目录> [--type hr|spo2] [选项]
```

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入目录（必需） |
| `-o, --output` | 输出目录（必需） |
| `--type` | 评估类型：hr 或 spo2，默认 hr |
| `--ref-column` | 参考列名，覆盖规则配置 |
| `--pred-column` | 预测列名，覆盖规则配置 |
| `--ref-column-col` | 参考列索引，1-based，优先于列名 |
| `--pred-column-col` | 预测列索引，1-based，优先于列名 |
| `--chip` | 芯片型号 |
| `--rule` | 评估规则文件 |
| `--diff-threshold` | 参考值差分异常阈值 |
| `--stale-minutes` | 参考值长时间不变异常阈值（分钟） |
| `--filter` | 仅处理文件名包含指定字符的CSV |
| `-v, --verbose` | 显示失败/跳过明细 |

输出文件包括 `file_details.csv`、`anomaly_list.csv`、`accuracy_summary.csv` 和
`accuracy_filtered.csv`。默认输出“评估结果”汇总，空文件、缺少参考列/预测列等会进入跳过/失败统计。

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

# 目录批量（无有效通道、读取失败等会进入汇总统计）
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
ghealth_tool check -i <路径> [-c <芯片>] [--checks <检查项>] [--tolerance <pA>] [--static-min <帧>] [--*-ratio <百分比>] [-w <线程数>] [-o <输出>] [-v]
```

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入CSV文件或目录（必需，递归扫描子目录） |
| `-c, --chip` | 芯片型号，不指定则自动识别 |
| `--checks` | 指定检查项（逗号分隔: range,ipd,frame,center,acc），默认全部 |
| `--tolerance` | Ipd转换误差容忍度（pA，默认50） |
| `--static-min` | ACC静止检测最小连续帧数（默认5） |
| `--range-ratio` | 数据范围异常允许比例（%，默认1） |
| `--frame-ratio` | 帧丢失允许比例（%，默认1） |
| `--center-ratio` | 数据居中异常允许比例（%，默认5） |
| `--ipd-ratio` | Ipd超差允许比例（%，默认1） |
| `--acc-ratio` | ACC异常帧允许比例（%，默认1） |
| `-w, --workers` | 并行线程数（默认4） |
| `-o, --output` | 检查报告CSV输出路径（默认: `<path>/check_report.csv`） |
| `-v, --verbose` | 显示详细信息 |

### 检查项

| 检查项 | 说明 |
|---|---|
| `range` | 检查原始数据是否在ADC正常范围内 |
| `frame` | 检查帧号完整性（丢包检测，支持frame_cnt/FRAME_ID等） |
| `center` | 检查数据去除基线后是否居中 |
| `ipd` | 检查Ipd_pA与Rawdata转换一致性（仅GH3036） |
| `acc` | ACC加速度计异常检测（全零/静止/循环） |

### 结果状态

每个检查项输出三态结果：

- `PASS`: 无异常。
- `WARNING`: 有异常，但异常比例不超过该检查项的 `--*-ratio` 阈值。
- `FAIL`: 异常比例超过阈值，或缺少必要列导致无法检查。

比例参数使用百分数数字，例如 `--frame-ratio 0.5` 表示允许丢包率不超过0.5%。除 `--center-ratio` 默认5%外，其他比例默认1%。CSV报告额外提供 `总异常(结果)`，只输出 `PASS` 或 `FAIL`；`WARNING` 在总异常判断中归为 `PASS`。

### 列名解析

数据列名按以下优先级解析：

1. **check_columns 显式配置**（最高优先级）：在chip rule YAML中直接指定
2. **columns 自动匹配**：从chip rule的columns字段展开后正则匹配
3. **硬编码 fallback**：按芯片型号使用默认列名

```yaml
# chip rule YAML 示例
frame_column: frame_cnt

# 可选：显式指定checker使用的数据通道（列名支持展开语法）
check_columns:
  data:
    - rawdata{0-1}      # 原始数据列
  ipd:
    - ipd_pa{0-1}       # Ipd转换列
  agc:
    - agc_info{0-1}     # AGC信息列
```

| 字段 | 规则文件配置 | 自动检测规则 |
|---|---|---|
| 帧号 | `frame_column: "列名"` | 匹配frame_id/frame_cnt/frame/fid（大小写不敏感）；无匹配时回退行索引 |
| 数据列 | `check_columns.data` | 匹配rawdata*/ch*模式 |
| Ipd列 | `check_columns.ipd` | 匹配ipd_pa*/ipd*模式 |
| AGC列 | `check_columns.agc` | 匹配agc_info*模式 |
| ACC XYZ | `acc_columns: {x: "列名", y: "列名", z: "列名"}` | 匹配含acc+x/y/z的列名；其次匹配纯x/y/z |

### ACC异常检测

检测三种加速度计数据异常，按通道分类报告：

1. **全零异常**: ACCX、ACCY、ACCZ同时为0的连续段
2. **静止异常**: 连续不变超过N帧（默认5，`--static-min`可配置）
3. **循环异常**: 固定序列重复≥2个完整周期（周期长度2~50点，振幅≥20）

**通道归类规则**: 三通道都检出同类异常→归入XYZ同时；否则归入对应单通道(X/Y/Z)。

终端按通道拆表显示（如 静止检测-XYZ、循环检测-Z），仅展示有异常的子表。循环检测使用本通道静止掩码排除，不会被其他通道静止误遮蔽。

ACC状态按异常覆盖帧去重后计算异常比例：任一异常覆盖到的帧只计一次，异常帧数 / 总帧数不超过 `--acc-ratio` 时为 `WARNING`，超过时为 `FAIL`。

### Ipd转换检查

逐行从 `agc_info` 提取 gain code 映射 kΩ，按实际增益计算期望 Ipd_pA，与实际值比较误差。中途 AGC 切换时每行独立计算，不会因增益变化导致误报。

检查结果为 `FAIL` 时自动生成超差详情文件 `ipd_detail_<文件名>.csv`（与 `check_report.csv` 同目录），仅包含超差行；`WARNING` 不生成详情文件。

```
frame, rawdata0, ipd_pa0, agc_info0, expected_ipd0, diff0, exceed0, rawdata1, ...
```

| 列 | 说明 |
|---|---|
| `frame` | 帧号 |
| `rawdata*` | 原始数据值 |
| `ipd_pa*` | 实际Ipd值 |
| `agc_info*` | AGC信息（含gain code） |
| `expected_ipd*` | 根据rawdata和agc计算的期望Ipd |
| `diff*` | \|实际 - 期望\| 差值 |
| `exceed*` | 1=超差, 0=正常 |

### 示例

```bash
# 检查目录下所有CSV（递归）
ghealth_tool check -i data/ -v

# 仅检查ACC异常
ghealth_tool check -i data/ --checks acc

# 指定芯片型号和报告输出路径
ghealth_tool check -i data/ -c gh3036_moto_hr -o report/check_result.csv

# 8线程并行处理
ghealth_tool check -i data/ -c gh3036_moto_hr -w 8

# 仅检查数据范围和帧完整性
ghealth_tool check -i data.csv --checks range,frame

# 按检查项配置异常允许比例
ghealth_tool check -i data/ --range-ratio 0.5 --frame-ratio 0.2 --acc-ratio 2

# 使用别名
ghealth_tool chk -i data/ -c gh3036 --checks acc,frame
```

### CSV报告格式

统一输出一个CSV文件，每文件一行，列结构：

```
文件名, 芯片, 总异常(结果), 数据范围(结果), 数据范围(说明), 帧完整性(结果), 帧完整性(说明), ...,
ACC全零次数, ACC全零最长帧, ACC全零前10帧,
ACC静止XYZ次数, ACC静止XYZ最长帧, ACC静止XYZ前10帧,
ACC循环XYZ次数, ACC循环XYZ最长帧, ACC循环XYZ前10帧,
ACC静止X次数, ACC静止X最长帧, ACC静止X前10帧,
ACC静止Y次数, ACC静止Y最长帧, ACC静止Y前10帧,
ACC静止Z次数, ACC静止Z最长帧, ACC静止Z前10帧,
ACC循环X次数, ACC循环X最长帧, ACC循环X前10帧,
ACC循环Y次数, ACC循环Y最长帧, ACC循环Y前10帧,
ACC循环Z次数, ACC循环Z最长帧, ACC循环Z前10帧,
文件相对路径
```

每个检查项结果列为 `PASS` / `WARNING` / `FAIL`。`总异常(结果)` 只输出 `PASS` / `FAIL`，其中 `WARNING` 归为 `PASS`。每种ACC异常每通道三列：次数、最长持续帧数、前10次异常起始帧号（逗号分隔）。XYZ同时的判定取三通道交集（静止）或去重合并（循环）。

---

## offline - 离线跑库

调用离线算法工具（TEE_Algorithm.exe）进行心率计算，支持准确度统计和PSD时频图。

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

### 算法参数模板

不同算法版本的 `TEE_Algorithm.exe` 参数数量和顺序可能不同，可在
`C:\Users\lzh17\.ghealth_tools\config.yaml` 中按 `芯片 + 算法版本` 配置：

```yaml
offline_cmd:
  gh3036:
    GH_HR_exc_keep-B6lite_v1.0.1.2:
      cmd_arg:
        - start_idx
        - end_idx
        - input_dir
        - output_dir
        - csv
        - hba_fs
        - scene_en
        - datatype
        - ch_num
        - accx
        - accy
        - accz
        - ppg_ch0
        - ppg_ch1
        - ppg_ch2
        - ppg_ch3
        - polar
        - mcu_out
        - comp_out
      cmd_default:
        start_idx: 0
        end_idx: -1
        datatype: 0
        scene_en: 0
```

`cmd_arg` 决定最终传参顺序和数量，删除某个变量后该参数不会传入。`cmd_default`
未配置且内置变量表不存在的名称会按字面量传给 exe。列号变量
`accx`、`ppg_ch0`、`polar` 等由 `rules/chip/<chip>.yaml` 自动推导，不需要写具体索引值。
未配置 `offline_cmd` 的版本继续使用内置默认命令格式。执行 `cfg --offline-scan` 会保留
仍然有效的默认版本和手写的 `offline_cmd` 配置。

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
