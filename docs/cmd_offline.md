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
| `--timeout` | 外部工具超时时间，默认 300 秒 |
| `-v/--verbose` | 详细输出 |

当前没有 `offline` 的短别名。

## 输出流程

1. 跑库：调用配置目录中的 `TEE_Algorithm.exe`。
2. 整理：将离线输出整理到结果目录。
3. PSD：默认生成 PSD 时频图，使用 `--no-plot` 可跳过。
4. 准确度：默认生成 `accuracy_report.csv`，使用 `--no-accuracy` 可跳过。

整理、PSD 和准确度统计阶段使用进度条；未找到 PSD 或 `.vshb` 有效结果时输出 WARN，不中断后续流程。
算法等级为 `medium`/`med` 或 `basic` 时，PSD 默认绘制 `PPG + ACCRMS`；其他等级默认绘制
`PPG + ACCX/ACCY/ACCZ`。

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

不同版本的参数顺序可在用户配置 `offline_cmd` 中按 `芯片 + 算法版本` 配置。
`accx`、`ppg_ch0`、`polar` 等列号变量会从 `rules/chip/<chip>.yaml` 自动推导。

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
