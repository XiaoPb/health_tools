# GHealth Tools

GHealth Tools 是面向 PPG（光电容积脉搏波）传感器数据的命令行工具，覆盖日志解析、
CSV 格式转换、质量检查、绘图、分类、指标评估、产测计算和离线算法跑库。

## 安装

```bash
# 安装稳定版本
pip install ghealth-tools

# 源码开发安装
pip install -e ".[dev]"
```

安装后先确认当前终端使用的是预期版本：

```bash
ghealth_tool --version
python -c "import health_tools; print(health_tools.__file__)"
```

源码开发时，第二条命令应指向当前仓库的 `src/health_tools/__init__.py`。如果仍指向
`site-packages` 中的旧副本，请重新执行可编辑安装。

## 快速开始

以下流程把 GH3220 示例日志解析为普通 CSV，再查看内容并生成图像：

```bash
# 1. 先验证规则
ghealth_tool validate src/health_tools/rules/parse/gh3220.yaml

# 2. 解析日志；-r 决定如何提取字段
ghealth_tool parse -i raw.log -o parsed.csv -r gh3220.yaml

# 3. 查看解析列和样本值
ghealth_tool info parsed.csv --schema --preview 5

# 4. 按真实采样率生成时域和频域图
ghealth_tool plot -i parsed.csv -o plots/ --type both --channels red,ir \
  --sample-rate 25 --no-show
```

如果输出必须是完整 chip CSV，parse 规则需设置 `chip` 或 `target_chip`，且解析列名必须与
chip 规则列名一致；未匹配列会补 0。当前 `parse --chip` 不能替代解析正则，始终应显式
提供 `--rule`。标准化后再运行 `check -c <chip>`。

处理真实数据前，运行 `ghealth_tool <命令> --help` 核对当前安装版本的参数。

## 命令导航

| 命令 | 别名 | 用途 | 详细说明 |
|---|---|---|---|
| `parse` | `p` | 按 parse 规则将原始日志解析为 CSV | [parse](docs/cmd_parse.md) |
| `plot` | `pl` | 绘制时域、频域、STFT 或 PSD 图 | [plot](docs/cmd_plot.md) |
| `classify` | `cls` | 按文件名或数据内容分类 | [classify](docs/cmd_classify.md) |
| `convert` | `cv` | 转换、合并或分割 CSV 格式 | [convert](docs/cmd_convert.md) |
| `info` | `i` | 查看 CSV 或规则信息 | [info](docs/cmd_info.md) |
| `validate` | `val` | 验证 YAML 规则 | [validate](docs/cmd_validate.md) |
| `split` | 无 | 按列值、行数或时间分割数据 | [split](docs/cmd_split.md) |
| `process` | 无 | 批量复制或按帧处理 CSV | [process](docs/cmd_process.md) |
| `factory` | `snr`, `fac` | 计算 SNR、CTR 和 Noise | [factory](docs/cmd_factory.md) |
| `config` | `cfg` | 管理用户规则和离线工具配置 | [config](docs/cmd_config.md) |
| `evaluate` | `eval` | 批量评估心率或血氧指标 | [evaluate](docs/cmd_evaluate.md) |
| `offline` | 无 | 调用离线算法、整理结果并评估 | [offline](docs/cmd_offline.md) |
| `check` | `chk` | 检查范围、帧、居中、Ipd、ACC 和时间戳 | [check](docs/cmd_check.md) |
完整命令索引见 [命令说明](docs/commands.md)。

Python 项目可直接调用稳定的 `health_tools.api`，无需模拟命令行。接口覆盖 CLI、规则管理、
可视化配置替换和离线资源发现；进度、取消与 UI 集成示例见
[Python API 使用指南](docs/api_usage.md)。

## 常见工作流

### 转换陌生 CSV

```bash
# 根据输入表头和目标芯片生成转换规则模板
ghealth_tool convert --init-rule -i input.csv -c gh3036 -o custom_rules/convert/vendor.yaml

# 编辑映射后先验证，再转换
ghealth_tool validate custom_rules/convert/vendor.yaml
ghealth_tool convert -i input.csv -o output.csv -r custom_rules/convert/vendor.yaml -v
```

### 检查并分拣文件

```bash
ghealth_tool check -i data/ -c gh3036 -o data/check_report.csv
ghealth_tool check --sort --report data/check_report.csv --sort-output sorted/
```

### 离线多版本评估

```bash
ghealth_tool cfg --offline-path /path/to/offline_algorithm_tools
ghealth_tool offline --list --chip gh3220
ghealth_tool offline -i data/ -c gh3220 --versions version_a,version_b
```

离线工具只在 Windows 下调用 `TEE_Algorithm.exe`；`--no-run` 可对已有结果执行整理、绘图
和准确度统计。

## 规则系统

内置规则位于 `src/health_tools/rules/`，用户规则默认位于
`~/.ghealth_tools/rules/`。相对规则名优先查找用户目录，再查找内置目录；绝对路径直接使用。

| 规则类型 | 用途 |
|---|---|
| `chip` | CSV 行号、编码、列顺序、检查列和芯片参数 |
| `parse` | 日志正则、字段列和多 pattern 输出 |
| `classify` | 文件名/数据提取、目录分类和准确度配置 |
| `convert` | 列映射、计算列、前值填充、频率扩展和外部数据合并 |
| `evaluate` | 心率/血氧列、异常阈值、分类和准确度方法 |

格式、字段和示例见 [规则文件说明](docs/rules.md)。修改规则后使用 `validate` 验证，再用
小样本运行目标命令。

## 配置目录

运行 `ghealth_tool config --init` 会创建：

```text
~/.ghealth_tools/
├── config.yaml
├── rules/
└── offline_algorithm_tools/
```

使用 `ghealth_tool config --show` 查看当前生效配置。详细优先级和离线版本配置见
[config 命令](docs/cmd_config.md)。

## 文档

- [命令索引](docs/commands.md)
- [规则文件格式](docs/rules.md)
- [架构说明](docs/architecture.md)
- [Python API 使用指南](docs/api_usage.md)
- [Python API 架构](docs/api_architecture.md)
- [变更记录](CHANGELOG.md)

## 开发

```bash
pip install -e ".[dev]"
pytest
pytest --cov=health_tools
ruff check src/ tests/
black --check src/ tests/
mypy src/
```

项目支持 Python 3.9+，Black 和 Ruff 行宽均为 100。面向用户的文本、注释和文档使用中文。

## 许可证

[MIT License](LICENSE)
