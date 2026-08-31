---
name: use-ghealth-tool
description: Use when a task involves ghealth_tool/GHealth Tools, PPG CSV or日志数据、GH3036/GH3220、数据检查/绘图/分类/评估、SNR/CTR/Noise 产测、离线跑库或 chip/parse/check/classify/convert/evaluate/analysis YAML 规则。
---

# 使用 GHealth Tools

把数据目标转换成可验收的 CLI 工作流。命令参数以当前 `ghealth_tool <command> --help` 和仓库
`docs/cmd_<command>.md` 为准；本 skill 的参考文件只补充选择、风险和验收要点。

## 快速路径

1. 确认输入路径、目标输出、芯片/采样率、规则、是否允许移动源文件，以及是否需要 HR/SpO2 金标。
   缺少会改变结果的信息时先询问，不猜测。
2. 在仓库根目录运行：`python .agents/skills/use-ghealth-tool/scripts/inspect_environment.py`。
   若不是当前源码安装，先执行 `pip install -e ".[dev]"`，再确认 `python -c "import health_tools; print(health_tools.__file__)"`。
3. 运行 `ghealth_tool --help` 和目标命令 `--help`；再读取对应的
   `references/commands.md`、`rules.md`、`workflows.md` 或 `troubleshooting.md`。
4. 用 `ghealth_tool info <csv> --schema --preview 5` 预检真实表头；规则任务先 `validate`，批量任务先用一个文件试跑。
5. 使用新输出目录执行最小命令。默认保留源文件：分类用 `--copy`；不要主动使用 `--move`。
6. 验收文件存在且非空、表头/列顺序/行数正确、报告和图片数量合理，并汇总成功、跳过、WARNING、FAIL 及原因。

解析日志必须显式使用 `parse --rule`；`parse --chip` 不能替代解析规则。`parse --dry-run` 只加载规则，
不读取日志，必须再用小日志正式解析验证正则。

## 命令路由

| 目标 | 命令 | 关键提醒 |
|---|---|---|
| 日志转 CSV | `parse` | 显式 `--rule`；规则中的 `target_chip` 决定完整输出 |
| 陌生 CSV 转格式 | `convert` | 先 `info`，用 `--init-rule` 生成模板后编辑 |
| 文件/规则预检 | `info`、`validate` | `validate` 不是业务结果验证 |
| 按列/大小/时间拆分 | `split` | 选择一个 `--by-*`，先确认时间列 |
| 批量复制或按帧处理 | `process` | 输入必须是目录，必要时 `--split` |
| 时域/频域/AC/FFT/STFT/PSD | `plot` | PSD 通常需要目录；保存图片加 `--no-show` |
| 姿态/场景分类 | `classify` | 默认保留源文件；使用 `--copy`，需要时 `--report` |
| 完整性/范围/ACC/金标 | `check` | `--sort` 会分拣源文件；XLSX 不能用于分拣 |
| HR/SpO2 准确度 | `evaluate` | `--type hr|spo2`；列索引是 1-based |
| SNR/CTR/Noise | `factory` | 确认 chip/rule、通道和最短时长 |
| 配置/规则/离线版本 | `config` | `--init`、`--show`、`--add`、`--offline-path` |
| 外部算法多版本跑库 | `offline` | 会调用 exe；普通模式可能移动不合规 CSV |
| 自动诊断报告 | `analyze` | 可复用 check/offline/PNG；核对证据和跳过原因 |

## 安全边界

- 不覆盖已有输出；先检查目标路径，优先使用新的输出目录。
- `classify --move` 会移动源文件；`check --sort` 会按报告分拣源文件。
- `offline` 正常模式会把表头不完全匹配的 CSV 移到同级 `<输入目录名>_mv`；运行前明确说明并确认。
  `offline --no-run` 不调用外部算法，也不执行该输入预检移动。
- `offline` 前确认 `TEE_Algorithm.exe`、版本、`cmd_setting.yaml`、采样率、通道映射和输出目录；不把未经小样本验证的命令用于生产数据。
- `validate` 只做规则结构检查。parse 正则、分类条件、convert 对齐、evaluate 列语义和分析结论都必须用真实小样本验证。
- Windows 遇到 `pytestqt`/Qt DLL 初始化问题时，按仓库 AGENTS.md 禁用 `pytest-qt` 后再判断测试结果。

## 参考文件

- `references/commands.md`：命令选择、别名、互斥参数和高影响选项。
- `references/rules.md`：规则类型、字段不变量和验证限制。
- `references/workflows.md`：可复制的端到端命令序列。
- `references/troubleshooting.md`：安装来源、输入、规则、离线和产物故障排查。

## 完成标准

交付时说明实际命令、规则、输入/输出位置、处理数量、成功/跳过/WARNING/FAIL、移动或未执行的阶段；
没有样本、外部算法或用户授权时，只完成可安全验证部分，并明确剩余条件。
