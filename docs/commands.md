# 命令索引

本文按任务选择命令。完整参数、默认值、输入输出和失败条件以各命令页及当前版本
`ghealth_tool <命令> --help` 为准。

## 全局选项

```bash
ghealth_tool --version
ghealth_tool --log-level debug <命令> ...
ghealth_tool --help
```

`--log-level` 支持 `debug`、`info`、`warning`、`error`。

## 按任务选择

| 任务 | 首选命令 | 后续常用命令 |
|---|---|---|
| 从设备日志生成标准 CSV | [`parse`](cmd_parse.md) | `validate`、`check` |
| 把第三方 CSV 转为芯片格式 | [`convert`](cmd_convert.md) | `validate`、`check` |
| 检查文件结构和信号质量 | [`check`](cmd_check.md) | `plot`、`split` |
| 绘制时域、频域或时频图 | [`plot`](cmd_plot.md) | `check` |
| 按姿态、场景或文件名分类 | [`classify`](cmd_classify.md) | `evaluate` |
| 评估心率或血氧准确度 | [`evaluate`](cmd_evaluate.md) | `classify` |
| 运行离线算法并比较结果 | [`offline`](cmd_offline.md) | `config`、`plot` |
| 计算产测指标 | [`factory`](cmd_factory.md) | `info` |
| 分割大文件或不同帧段 | [`split`](cmd_split.md) | `process` |
| 批量复制或按帧预处理 | [`process`](cmd_process.md) | `split` |
| 查看 CSV/规则结构 | [`info`](cmd_info.md) | `validate` |
| 验证规则格式 | [`validate`](cmd_validate.md) | 对应业务命令 |
| 管理用户规则和离线版本 | [`config`](cmd_config.md) | `offline` |
| 自动定位数据或算法异常原因 | [`analyze`](cmd_analyze.md) | `check`、`evaluate`、`offline` |

## 全部命令

| 命令 | 别名 | 输入 | 主要输出 |
|---|---|---|---|
| [`parse`](cmd_parse.md) | `p` | 日志文件或目录 | CSV 文件 |
| [`plot`](cmd_plot.md) | `pl` | CSV 或离线结果目录 | PNG/SVG/PDF 图片 |
| [`classify`](cmd_classify.md) | `cls` | CSV 文件或目录 | 分类目录、可选报告 |
| [`convert`](cmd_convert.md) | `cv` | CSV 文件或目录 | 目标格式 CSV、可选对齐错误报告 |
| [`info`](cmd_info.md) | `i` | CSV 或 YAML | 终端信息 |
| [`validate`](cmd_validate.md) | `val` | YAML 规则 | 验证结果 |
| [`split`](cmd_split.md) | 无 | CSV 文件或目录 | 分割后的 CSV |
| [`process`](cmd_process.md) | 无 | CSV 目录 | 复制或按帧拆分的 CSV |
| [`factory`](cmd_factory.md) | `snr`, `fac` | CSV 文件或目录 | 指标表、可选 CSV |
| [`config`](cmd_config.md) | `cfg` | 配置参数 | 用户配置文件 |
| [`evaluate`](cmd_evaluate.md) | `eval` | 结果目录 | 明细、异常和准确度汇总 |
| [`offline`](cmd_offline.md) | 无 | 芯片 CSV 目录 | 版本目录、PSD、准确度报告 |
| [`check`](cmd_check.md) | `chk` | CSV 或检查报告 | `check_report.csv`、`check_report_compact.csv` 或分拣目录 |
| [`analyze`](cmd_analyze.md) | `ana` | CSV/数据目录，可分离 check、跑库、PNG 目录 | JSON/CSV、证据图、Markdown/PPT |

## 批量命令约定

- 目录模式默认递归或按命令定义的匹配模式处理文件，并显示 Rich 进度条。
- 默认只汇总成功数量和失败原因；使用 `-v/--verbose` 查看文件级明细。
- `--filter` 按文件名包含关系筛选，不是正则表达式。
- 批处理前先用一个小文件确认规则、列名、输出目录和覆盖行为。

## 规则与配置

- 六类 YAML 规则及查找顺序见 [规则文件格式](rules.md)。
- 用户目录、离线算法版本和参数模板见 [config 命令](cmd_config.md)。
- 模块职责和数据流见 [架构说明](architecture.md)。
