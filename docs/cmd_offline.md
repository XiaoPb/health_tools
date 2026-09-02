# offline 命令

调用离线算法工具 `TEE_Algorithm.exe` 跑库，并可整理结果、生成 PSD 时频图、统计在线/离线准确度。

## 用法

```bash
ghealth_tool offline -i <input_dir> -c <chip> [options]
ghealth_tool offline --list [--chip <chip>]
```

## 参数

| 参数 | 说明 |
|------|------|
| `-i/--input` | 输入数据目录 |
| `-o/--output` | 输出结果目录，默认 `<input>_offline_result` |
| `-c/--chip` | 芯片型号，如 `gh3036`、`gh3220` |
| `--version` | 算法版本，覆盖配置中的默认版本 |
| `--versions` | 多个算法版本，逗号分隔，如 `v1,v2` |
| `--all-versions` | 运行当前芯片已配置的全部版本 |
| `--hba-fs` | 采样率，默认由算法或规则决定 |
| `--scene-en` | 场景适配开关，`0=关`、`1=开` |
| `--ch-num` | 有效 PPG 通道数 |
| `--ref-col` | 源 CSV 中金标列索引，1-based，覆盖芯片配置 |
| `--ppg-offset` | PPG 自动识别通道的固定偏移，非负整数，默认 `0` |
| `--ppg-map` | 覆盖已声明 PPG 通道，可重复使用，格式为 `ppg_chN=列名或0-based索引` |
| `--no-accuracy` | 跳过准确度统计 |
| `--accuracy-thresholds` | 固定准确度阈值，逗号分隔，默认 `5,10,15` |
| `--accuracy-inclusive/--accuracy-strict` | 阈值边界包含/严格模式；默认 strict，即 `abs(error) < threshold` |
| `--no-plot` | 跳过 PSD 时频图绘制 |
| `--no-run` | 跳过跑库，直接整理/统计/绘图已有结果 |
| `--list` | 列出可用芯片和版本 |
| `--timeout` | 外部工具超时时间；显式设置时固定使用该值 |
| `--settle-timeout` | 外部工具异常返回后等待输出稳定的时间，默认 10 秒 |
| `--workers` | 并行线程数，最多 8，范围 1-8，默认 8 |
| `-v/--verbose` | 详细输出 |

当前没有 `offline` 的短别名。

未显式指定 `--timeout` 时，50 个及以下合规输入文件使用 300 秒；超过 50 个后，每增加
一个文件增加 20 秒。显式 `--timeout` 不参与自动扩展。

## 并行调度

输入目录存在一级子目录时，每个递归包含 CSV 的一级子目录作为一个独立跑库任务；此时只
调度这些一级子目录，忽略输入根目录 CSV。一级子目录超过并行数时，多余任务进入队列，
有运行中的任务完成后再补位。`--workers` 默认 8，最多 8 个 `TEE_Algorithm.exe` 同时运行。

输入目录没有任何一级子目录时，主目录作为唯一任务单线程运行，即使指定大于 1 的
`--workers` 也不会拆分主目录中的 CSV。设置 `--workers 1` 时，含子目录的任务按稳定顺序
逐个运行，但仍使用与并行模式相同的输出隔离和合并流程。存在一级子目录但其中都没有可
处理 CSV 时会停止，不会回退处理根目录 CSV。

为避免外部工具同时清理或覆盖同一个输出目录，每个任务先写入版本目录下的内部隔离层：

```text
<版本输出>/.offline_tasks/<task-id>/raw
```

任务 ID 保留 Unicode 文字；空格、`&`、括号等连续的不适合作为任务目录名的标点会压缩为
一个 `_`。极长任务名会按 Windows 单路径组件限制安全截断，并追加稳定的短哈希，避免组件
超限，也避免不同长名称在截断后发生碰撞。

跑库完成后再单线程整理和合并到最终的 `数据整理/`。所有任务和合并都成功时删除
`.offline_tasks`；任何任务失败或最终目标文件冲突时保留该目录，供排查原始输出。删除
`.offline_tasks` 不会删除同级的 `offline_logs`。

## 输出流程

1. 输入预检：按芯片规则严格校验 CSV 表头，并备份不合规文件。
2. 跑库：调用配置目录中的 `TEE_Algorithm.exe`。
3. 整理：将离线输出整理到结果目录。
4. PSD：默认生成 PSD 时频图，使用 `--no-plot` 可跳过。
5. 准确度：默认生成 `accuracy_report.csv`，使用 `--no-accuracy` 可跳过。

外部算法使用参数列表直接启动，不经过 Windows Shell。因此，通过现有路径支持检查的合法
路径即使包含 `&`，也不会被解释为命令分隔符；中文、空格和特殊字符会作为完整的路径参数
传递。外部老旧 EXE 是否能处理超出系统代码页的字符仍取决于其自身能力；现有的 `mbcs`
路径支持检查仍会跳过系统代码页无法编码的输入路径。

每个任务在对应版本输出目录下写入独立日志：

```text
<版本输出>/offline_logs/<task-id>.log
```

日志使用 UTF-8 编码，记录输入目录、输出目录、可读命令，以及带 `[stdout]`、`[stderr]`
来源标记的外部工具输出。同一任务隔离失败 CSV 后重试时，继续追加到同一个日志文件，并以
“尝试 N”分隔各次执行。日志创建失败、进程启动失败等明确错误会保留在任务失败原因中；
终端失败信息同时给出该任务的日志路径。

终端不会逐行转发外部工具的 stdout/stderr，只显示整体进度、任务状态、错误和日志路径；
任务摘要也不显示外部命令或 `log_tail`。完整子进程输出应到上述日志中查看。

再次在同一版本输出目录启动新一轮跑库时，会先清理上一轮的 `offline_logs`，避免混入旧日志；
`--no-run` 跳过外部算法，也不执行本轮日志清理。成功合并后的日志会继续保留。

### 输入预检

实际跑库前会递归扫描输入目录中的 `.csv` 文件（扩展名不区分大小写），每个文件只读取
前三行。CSV 表头的列名、数量和顺序必须与 `rules/chip/<chip>.yaml` 展开后的列定义完全
一致；仅允许首列表头带 UTF-8 BOM，不会忽略大小写或额外空格。

表头不一致、文件行数不足、编码错误或表头无法解析的文件会移动到输入目录同级的
`<输入目录名>_mv`，并保留原相对目录。例如：

```text
test1/lzh/sample/sample.csv -> test1_mv/lzh/sample/sample.csv
```

备份位置已有同名文件时会追加 `_1`、`_2` 等序号，不会覆盖已有文件。移动失败或过滤后
没有合规 CSV 时不会启动离线工具。多版本跑库只预检一次；`--no-run` 不执行预检，也不会
改变输入目录。

整理、PSD 和准确度统计阶段使用进度条；未找到 PSD 或 `.vshb` 有效结果时输出 WARN，不中断后续流程。
算法等级为 `medium`/`med` 或 `basic` 时，PSD 默认绘制 `PPG + ACCRMS`；其他等级默认绘制
`PPG + ACCX/ACCY/ACCZ`。

准确度阈值默认使用 `5,10,15`。默认 strict 模式按 `abs(error) < threshold` 计入；指定
`--accuracy-inclusive` 后按 `abs(error) <= threshold` 计入。该配置同时作用于
`accuracy_report.csv` 和 PSD 图顶部指标。

每个 VSHB 的 `polar`、`offline`、`online`、`comp` 列按同一口径预处理：没有任意一个
finite 且非 `0` 值的列被禁用，不参与边界、比较、分类汇总或 `TOTAL`。剩余全部启用列共同
确定首尾共享边界，即首个和最后一个“所有启用列均为 finite 且非 `0`”的行；所有列使用
同一切片。切片中间的 `0` 保留并参与正常误差计算，`NaN`/`Inf` 仅在各比较对象成对计算
时过滤。

Polar 启用时，分别为所有启用的 Offline、Online、Comp 计算 `vs Polar`；Polar 禁用时，
只有 Online 和 Offline 均启用才回退为 `Online vs Offline`，不再生成其他比较。每个比较
对象使用自己的 `samples` 对分类平均、`TOTAL` 和报告指标加权，缺失的比较不会以零值补入。
报告在 Polar 启用时写入 `reference=polar`，回退时写入 `reference=offline`。带表头的
`.vshb` 依次识别 `comp_hr`、`cmp_hr`、`comp` 列；无表头旧格式使用 `polar` 后一列。

PSD 图顶部按相同条件显示 `Offline vs Polar`、`Online vs Polar`、`Comp vs Polar`，或回退
后的 `Online vs Offline`，并按指标行数动态增加标题留白。Comp 启用时，PPG 子图使用亮青色
`#00E5FF` 虚线叠加 comp 曲线；该曲线不依赖 Polar 是否启用。图例固定在 PPG 子图右上角，
允许遮挡部分曲线或 PSD 内容。

## 多版本跑库

只要命令能解析出算法版本，结果都会写入 `<output>/<version>/` 子目录；单版本和多版本使用
相同目录格式，避免不同算法结果互相覆盖。每个版本子目录内仍会生成自己的 `数据整理/`、
`psd_bmpfile/` 和 `accuracy_report.csv`。

offline 绘制每个 VSHB 时只渲染一次，并保存两份相同 PNG：一份集中写入
`<版本输出>/psd_bmpfile/`，另一份写入对应 VSHB 所在的 `数据整理/` 子目录。例如：

```text
<版本输出>/psd_bmpfile/sample.png
<版本输出>/数据整理/场景A/sample.png
```

多版本准确度会额外汇总到：

```text
<output>/accuracy_report_all_versions.csv
```

汇总表在每个单版本准确度报告前插入 `version` 列，只拼接各版本的明细、分类平均和 `TOTAL`
行，不额外计算跨版本平均。

`--version`、`--versions`、`--all-versions` 互斥。多版本 `--no-run` 会要求
`<output>/<version>/` 已存在，然后分别整理、绘图和统计已有结果。未指定芯片的单版本
`--no-run` 无法解析算法版本，仍直接使用 `-o/--output` 目录。

## 版本与参数配置

离线工具路径通过 `config/cfg` 命令管理：

```bash
ghealth_tool cfg --offline-path /path/to/offline_algorithm_tools
ghealth_tool cfg --offline-scan
ghealth_tool cfg --offline-default gh3220=V4300_GH_HR_exc_pv_v2.0.3.0
```

不同版本的参数顺序可在用户配置 `offline_cmd` 中按 `芯片 + 算法版本` 配置，也可在
`TEE_Algorithm.exe` 同目录放置 `cmd_setting.yaml`：

```yaml
cmd_arg:
  - start_idx
  - end_idx
  - input_dir
  - output_dir
  - csv
  - hba_fs
  - scene_en
  - ch_num
cmd_default:
  start_idx: 0
  end_idx: -1
  csv: csv
  scene_en: 0
```

本地文件存在时会整份替换该版本的全局参数配置，而不是逐字段合并。文件无法解析、
`cmd_arg` 不是非空列表或 `cmd_default` 不是对象时立即停止跑库。配置优先级为：本地
`cmd_setting.yaml`、全局版本配置、芯片级配置、内置命令格式；命令行显式参数始终覆盖
配置中的默认值。
`accx`、`ppg_ch0`、`polar` 等列号变量会从 `rules/chip/<chip>.yaml` 自动推导。

### PPG 通道映射

offline 最多支持 `ppg_ch0` 到 `ppg_ch31`。只有当前算法版本最终生效的 `cmd_arg` 中明确
写出的 PPG 变量才参与映射；`{ppg_ch0}` 与 `ppg_ch0` 等价，`cmd_default` 中的同名字段
不构成声明。最终模板仍遵循本地 `cmd_setting.yaml`、全局版本配置、芯片级配置的现有
优先级。

默认情况下，已声明通道与自动识别出的原始 PPG 通道一一对应：

```text
ppg_chN = detected_channels[N]
```

使用 `--ppg-offset 4` 后，所有已声明通道统一后移：

```text
ppg_chN = detected_channels[N + 4]
```

稀疏声明仍按通道编号计算。例如模板只声明 `ppg_ch0` 和 `ppg_ch4`，偏移为 `2` 时，
两者分别使用识别通道 `2` 和 `6`。偏移后找不到对应通道会在输入预检前停止，CSV 不会
因此被移动。

`--ppg-map` 可以覆盖单个已声明通道，右侧既可写芯片规则展开后的精确列名，也可写源
CSV 的 0-based 绝对列索引。单通道覆盖在固定偏移之后生效；同一通道重复设置时，最后
一次生效：

```bash
ghealth_tool offline -i data/ -c gh3220 --ppg-offset 4 \
  --ppg-map ppg_ch0=CH4 --ppg-map ppg_ch3=12
```

如果 `cmd_arg` 没有声明 `ppg_ch3`，上例中的第二个设置会被忽略并输出 WARN，右侧内容
不会继续解析。多版本跑库按每个版本最终生效的 `cmd_arg` 分别处理，因此同一设置可能
只在部分版本生效。没有有效 `cmd_arg` 的旧内置 GH3036 命令继续使用原有四通道参数；
新映射参数对它不生效并输出 WARN。`--ch-num` 不决定声明集合，`--no-run` 不解析这些
跑库参数。

## 失败与恢复

- `--version`、`--versions`、`--all-versions` 互斥；组合使用会立即退出。
- 找不到算法版本、可执行文件或合规输入 CSV 时不会启动外部工具。
- 外部工具返回非零状态但结果文件完整时，命令等待输出稳定后以警告继续整理；没有完整
  结果时记录失败。
- 结果不完整时，从最后日志定位导致失败的 CSV，将它移动到同级
  `<输入目录名>_mv` 并保留相对路径，然后把该子目录任务重新放到队列尾部。连续遇到
  不同失败文件时可继续隔离和重试；再次定位到同一个失败文件、日志无法定位 CSV、文件
  已不存在或隔离后没有剩余 CSV 时停止重试该任务。其他子目录任务仍会继续执行。
- 超时后可增加 `--timeout` 重试；已有完整结果可使用 `--no-run` 跳过外部工具。
- 本地 `cmd_setting.yaml` 结构错误会停止对应版本，避免用错误参数调用算法。

## 示例

```bash
# 查看可用版本
ghealth_tool offline --list

# 基本跑库
ghealth_tool offline -i data/ -c gh3220

# 指定版本并覆盖金标列
ghealth_tool offline -i data/ -c gh3220 --version V4200_GH_HR_exc_pv_v1.0.1.0 --ref-col 18

# 指定多个版本并生成汇总准确度
ghealth_tool offline -i data/ -c gh3300 --versions GH_HR_exc_pv_v1.1.4.0,GH_HR_med_pv_v1.0.2.0_final

# 已声明PPG通道统一偏移，并单独覆盖一个通道
ghealth_tool offline -i data/ -c gh3220 --ppg-offset 4 --ppg-map ppg_ch0=CH4

# 运行当前芯片已配置的全部版本
ghealth_tool offline -i data/ -c gh3300 --all-versions

# 仅整理已有结果
ghealth_tool offline -i data/ -c gh3220 --no-run

# 跳过绘图和准确度统计
ghealth_tool offline -i data/ -c gh3036 --no-plot --no-accuracy
```
