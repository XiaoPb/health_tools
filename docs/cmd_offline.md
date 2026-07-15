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
| `--no-accuracy` | 跳过准确度统计 |
| `--no-plot` | 跳过 PSD 时频图绘制 |
| `--no-run` | 跳过跑库，直接整理/统计/绘图已有结果 |
| `--list` | 列出可用芯片和版本 |
| `--timeout` | 外部工具超时时间；显式设置时固定使用该值 |
| `--settle-timeout` | 外部工具异常返回后等待输出稳定的时间，默认 10 秒 |
| `-v/--verbose` | 详细输出 |

当前没有 `offline` 的短别名。

未显式指定 `--timeout` 时，50 个及以下合规输入文件使用 300 秒；超过 50 个后，每增加
一个文件增加 20 秒。显式 `--timeout` 不参与自动扩展。

## 输出流程

1. 输入预检：按芯片规则严格校验 CSV 表头，并备份不合规文件。
2. 跑库：调用配置目录中的 `TEE_Algorithm.exe`。
3. 整理：将离线输出整理到结果目录。
4. PSD：默认生成 PSD 时频图，使用 `--no-plot` 可跳过。
5. 准确度：默认生成 `accuracy_report.csv`，使用 `--no-accuracy` 可跳过。

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

准确度默认以 `polar` 金标为参考，报告中 `reference=polar`，同时统计离线和在线相对金标的
指标。如果 `.vshb` 中 `polar` 列全为 `0`，表示未提供金标；此时报告改为
`reference=offline`，只统计 `online_vs_offline` 指标。PSD 图顶部也只显示
`Online vs Offline` 的准确度说明。

## 多版本跑库

只要命令能解析出算法版本，结果都会写入 `<output>/<version>/` 子目录；单版本和多版本使用
相同目录格式，避免不同算法结果互相覆盖。每个版本子目录内仍会生成自己的 `数据整理/`、
`psd_bmpfile/` 和 `accuracy_report.csv`。

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

## 失败与恢复

- `--version`、`--versions`、`--all-versions` 互斥；组合使用会立即退出。
- 找不到算法版本、可执行文件或合规输入 CSV 时不会启动外部工具。
- 外部工具返回非零状态但结果文件完整时，命令等待输出稳定后以警告继续整理；没有完整
  结果时记录失败。
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

# 运行当前芯片已配置的全部版本
ghealth_tool offline -i data/ -c gh3300 --all-versions

# 仅整理已有结果
ghealth_tool offline -i data/ -c gh3220 --no-run

# 跳过绘图和准确度统计
ghealth_tool offline -i data/ -c gh3036 --no-plot --no-accuracy
```
