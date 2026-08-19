# 命令选择与参数边界

先运行 `ghealth_tool <命令> --help` 核对当前版本。仓库中的完整说明位于
`docs/cmd_<命令>.md`，本文只保留 AI 选择命令时需要的差异与风险。

## 命令矩阵

| 命令 | 输入 | 输出 | 关键选择 |
|---|---|---|---|
| `parse` (`p`) | 日志文件/目录 | CSV | 必须用 `--rule` 解析；芯片输出由规则内 `chip/target_chip` 决定 |
| `plot` (`pl`) | CSV 或离线目录 | 图片 | `--type time|freq|stft|psd|both`；PSD 输入必须是目录 |
| `classify` (`cls`) | CSV 文件/目录 | 分类目录 | 默认 `--copy`；`--move`、`--symlink` 改变落盘方式 |
| `convert` (`cv`) | CSV 文件/目录 | CSV | 正常转换需 `--rule`；`--init-rule` 生成模板；可 `--merge`、`--split` |
| `info` (`i`) | CSV/YAML | 终端信息 | 用 `--stats`、`--schema`、`--preview` 预检输入 |
| `validate` (`val`) | YAML | 验证状态 | 类型由路径推断；不等同于真实数据验证 |
| `split` | CSV 文件/目录 | 多个 CSV | 按列值、行数或时间三种方式 |
| `process` | CSV 目录 | 处理后 CSV | `--split` 按帧拆分，否则批量复制/处理 |
| `factory` (`snr`, `fac`) | CSV 文件/目录 | 指标表/CSV | chip/rule 提供列和 ADC 参数，CLI 可覆盖增益、电流、时长 |
| `config` (`cfg`) | 配置选项 | 用户配置 | 初始化规则、扫描离线版本、设置默认版本 |
| `evaluate` (`eval`) | 结果目录 | 评估报告 | `--type hr|spo2`；列索引为 1-based 且优先于列名 |
| `offline` | 芯片 CSV 目录 | 版本结果、PSD、准确度 | 会调用 exe 并移动不合规输入；支持多版本和 `--no-run` |
| `check` (`chk`) | CSV/目录或报告 | 检查报告/分拣目录 | 普通检查需 `-i`；`--sort` 需 `--sort-output` |
| `analyze` (`ana`) | CSV/目录或 offline 结果 | 诊断报告和证据图 | `--focus` 强制深度分析；`--report` 选择 Markdown/PPT |

## 高影响参数

- `parse --chip`：当前不能提供解析正则，也不会覆盖 `--rule` 内的目标芯片；不要单独使用。
- `parse --dry-run`：只加载和打印规则，不读取日志或证明正则能匹配。
- `classify --move`：移动源文件。默认使用 `--copy`。
- `check --sort`：根据报告移动源文件到正常/异常目录。
- `offline --version`、`--versions`、`--all-versions`：互斥。
- `offline --no-run`：只处理已有结果，不运行输入预检和外部算法。
- `offline --no-plot`、`--no-accuracy`：分别跳过耗时阶段。
- `convert --merge`：把目录输入合并为一个输出；先确认输出路径为文件。
- `plot --type psd`：普通绘图参数多数不生效，使用 `--psd-acc axis|rms` 选择 ACC 图组。
- `check --acc-axis`：把单轴静止/循环异常也计入结果，可能提高失败数量。

## 参数优先级

CLI 显式参数通常覆盖规则或配置默认值。芯片结构来自 `--chip`，转换/绘图也可通过
`--rule` 指定格式。无法确认优先级时读取命令实现和对应文档，不组合两个来源猜测结果。
### analyze 快速复用

`analyze` 支持 `--check-report`、`--offline-result` 和可重复的 `--figure-dir`，用于在
CSV 与跑库目录分离时直接生成报告；`--resume` 复用 `analysis_state.json` 中的完成阶段，
`--restart` 清理分析工作区后重跑。
