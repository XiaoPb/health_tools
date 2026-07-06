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

# 仅整理已有结果
ghealth_tool offline -i data/ -c gh3220 --no-run

# 跳过绘图和准确度统计
ghealth_tool offline -i data/ -c gh3036 --no-plot --no-accuracy
```
