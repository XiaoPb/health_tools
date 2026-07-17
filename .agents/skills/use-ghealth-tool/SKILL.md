---
name: use-ghealth-tool
description: 使用 GHealth Tools 完成 PPG 传感器数据任务，包括日志解析、CSV 转换与分割、数据质量检查、时域/频域/STFT/PSD 绘图、文件分类、心率或血氧评估、SNR/CTR/Noise 产测、离线算法多版本跑库，以及 chip/parse/classify/convert/evaluate YAML 规则编写与排错。用户提到 ghealth_tool、GHealth Tools、PPG CSV、GH3036、GH3220、规则文件、离线跑库、数据检查或上述工作流时使用此 Skill。
---

# 使用 GHealth Tools

把用户的数据目标转换为可验证的 GHealth Tools 工作流。先确认运行环境和输入结构，再选择
命令与规则；执行后检查文件、报告和跳过原因，不以退出码为唯一成功标准。

## 执行流程

1. 明确目标、输入路径、芯片、期望输出和是否允许移动原文件。缺少会改变结果的字段时先
   询问，不猜测芯片、采样率、参考列或算法版本。
2. 从本 Skill 目录运行 `python scripts/inspect_environment.py`。在源码仓库中出现非零状态
   时先修复安装来源；通常执行 `pip install -e ".[dev]"`。
3. 按任务读取一份或多份参考：
   - 选择命令或核对互斥参数：读取 `references/commands.md`。
   - 新建、修改或排查 YAML：读取 `references/rules.md`。
   - 组合多个命令：读取 `references/workflows.md`。
   - 命令失败、输出为空或版本错位：读取 `references/troubleshooting.md`。
4. 运行 `ghealth_tool <command> --help` 核对当前版本。把 `--help` 和仓库
   `docs/cmd_<command>.md` 作为参数事实来源，不凭记忆补选项。
5. 检查输入：用 `ghealth_tool info` 查看 CSV/YAML；适用时运行 `validate`；批量任务先用
   一个代表性文件验证列、规则和输出目录。
6. 执行最小命令。默认保留源数据：分类使用 `--copy`，不主动使用 `--move`；报告分拣和
   离线输入预检会移动文件，执行前明确说明影响。
7. 验证输出：确认文件存在且非空、CSV 列顺序符合目标 chip 规则、图片数量合理、报告中
   没有被忽略的 FAIL/WARN，并向用户汇总成功、跳过和失败数量。

解析日志时始终显式提供 `--rule`。不要用 `parse --chip` 代替解析规则；完整芯片输出由
parse 规则中的 `chip/target_chip` 决定。`parse --dry-run` 只加载并打印规则，不读取输入，
所以必须再用小日志正式解析才能证明正则有效。

## 任务路由

| 用户目标 | 首选命令 | 必读参考 |
|---|---|---|
| 日志转 CSV | `parse` | commands、rules |
| 第三方 CSV 转标准格式 | `convert` | rules、workflows |
| 范围/帧/ACC/时间戳检查 | `check` | commands、workflows |
| 时域、频域、STFT、PSD | `plot` | commands |
| 姿态/场景分类 | `classify` | rules |
| 心率/血氧准确度 | `evaluate` | rules、workflows |
| 离线算法跑库 | `config` + `offline` | commands、workflows、troubleshooting |
| SNR/CTR/Noise | `factory` | commands |
| 自动数据诊断与报告 | `analyze` | commands、workflows、troubleshooting |
| 编写或修正规则 | `validate` + 目标命令 | rules |

## 安全边界

- 不覆盖用户已有输出；先检查目标路径，优先使用新目录或明确的文件名。
- `classify --move` 会移动源文件；除非用户明确要求，否则使用默认 `--copy`。
- `check --sort` 会把报告中的源文件移动到 `normal/`、`abnormal/`。
- `offline` 正常跑库前会把表头不完全匹配的 CSV 移到同级 `<输入目录名>_mv`。先向用户
  说明并确认输入目录适合整理；`offline --no-run` 不执行此预检。
- `offline` 调用外部 `TEE_Algorithm.exe`。确认版本、参数模板和输出目录后再运行，不把
  未验证的命令用于生产数据。
- 规则验证只检查部分结构。即使 `validate` 通过，也必须用小样本验证业务结果。

## 完成标准

交付时说明实际执行的命令、使用的规则、输出位置、处理文件数、警告/失败原因以及未执行的
可选阶段。若缺少样本、外部算法或用户授权，只完成可安全验证的部分并明确剩余条件。
