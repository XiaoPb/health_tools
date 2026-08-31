# 故障排查

按环境、输入、规则、执行、输出的顺序定位问题。不要在输入结构尚未确认时反复调整业务
参数。

## 运行了错误安装

症状：源码中已有模块或选项，但导入失败或 `--help` 不显示。

```bash
python scripts/inspect_environment.py --json
python -c "import health_tools; print(health_tools.__file__)"
ghealth_tool --version
```

在仓库根目录执行 `pip install -e ".[dev]"`，再确认模块路径指向 `src/health_tools`。

如果 `ghealth_tool <command> --help` 与本文或旧脚本不一致，以当前 help 为准；先检查
`ghealth_tool --version`、`python -c "import health_tools; print(health_tools.__file__)"`，不要
通过添加未知选项“试出”参数。当前 `check` 的准确度策略来自 YAML `accuracy` 块，不支持旧的
`--accuracy`、`--accuracy-min`、`--online-comp-gap` 选项。

## 找不到规则

- 运行 `ghealth_tool config --show` 查看用户规则目录。
- 相对名称应放在正确的类型子目录，例如 `rules/chip/custom.yaml`。
- 临时排查使用绝对路径，排除当前工作目录和同名规则覆盖问题。
- chip 参数只写名称，不写类型目录：`--chip custom`。

## CSV 为空、列缺失或格式不对

```bash
ghealth_tool info input.csv --schema --preview 10
```

核对编码、分隔符、`header_row`、`data_start_row`、列名空格和大小写。目录任务加 `-v` 查看
具体跳过原因。convert 至少匹配一个源列才会产生结果。

## parse 没有匹配记录

用少量原始行测试正则，确认捕获组与列数相同。多 pattern 逐个测试；`validate` 对多
pattern 支持有限，`parse --dry-run` 也不读取日志，两者都不能替代小样本正式解析。不要
单独使用 `parse --chip`，解析必须提供 `--rule`。

## extra_source 没有合并数据

检查候选文件是否被 `required_columns`、`any_required_columns` 选中，对齐列是否存在，
`left_extract/right_extract` 是否提取相同格式。读取
`extra_source_align_errors.csv` 中的主文件、外部文件和映射列。

## check 跳过全部文件

显式提供 `--chip` 排除自动识别失败；检查 chip 规则的 `columns`、`check_columns`、
`frame_column`、`acc_columns`。`WARNING` 在总结果中算通过，`FAIL` 才进入异常分类。

## offline 未启动或无结果

1. 用 `config --show` 和 `offline --list --chip <chip>` 确认路径、等级、版本和默认版本。
2. 检查输入是否被移动到同级 `<input>_mv`；表头必须与 chip `columns` 完全一致。
3. 检查版本目录中的 `cmd_setting.yaml`，本地配置会整份替换全局模板。
4. 超时可显式增加 `--timeout`；异常返回后用 `--settle-timeout` 调整等待稳定时间。
5. 已有完整结果使用 `--no-run` 重做整理、PSD 和准确度。

## 图片或报告缺失

- PSD 需要目录和配套 `.prepsd`/ACC PSD 文件；普通 CSV 不能直接使用 `--type psd`。
- `--no-plot`、`--no-accuracy` 会主动跳过对应离线产物。
- 检查输出目录权限、文件名过滤器和汇总中的 WARN/跳过原因。
- 不只看命令退出码；统计产物数量并打开少量 CSV/图片确认内容。

## 命令执行成功但结果不对

- 先保留完整命令、版本、规则绝对路径和输入样本，避免在不同安装来源之间比较。
- 对目录任务去掉 `--workers`、`--filter` 等批量选项，用一个 CSV 重跑，区分输入/规则问题和并行问题。
- `plot` 保存图片时使用 `--no-show`；`analyze` 可用 `--fast-report` 或复用已有
  `--check-report`、`--offline-result`、`--figure-dir`，但仍要检查 `analysis_summary.json` 和报告证据。
- 报告显示跳过时使用 `-v` 查看逐文件原因；不要把“没有生成输出”直接当作成功。
