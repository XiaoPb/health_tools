# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- PI 按光学列语义计算：CH/Rawdata 扣除 ADC 偏置，Ipd 保持 pA；SpO2 静止分析增加最低通道 PI 门槛
- Polar 局部异常样本从准确度中隔离并单独警告，保留全局分析原结论与关键图；仅全局不可用时停止参考归因

## [0.5.0] - 2026-07-17

### Added
- 新增 `analyze` 命令与公共 API，支持原始数据/PSD 证据归因、强制文件 glob 和 Markdown/PPT 报告
- 新增 `analysis` 规则类型及内置心率、血氧分析规则
- 新增基于利尔达模板的品牌化分析 PPT，包含异常归类、准确度对比和逐文件关键证据页

### Changed
- 分析流程复用 `check`、`evaluate`、`plot` 和 `offline`，关键图优先使用现有 plot 产物
- 心率准确度按 Online/Offline/可选 Comp 对比 Polar，显示 ±5/±10/±15 bpm 占比
- SpO2 限制为静止测试，运动幅度超限时报告具体原因和重新采集措施
- ACC 异常结论包含异常次数、最长连续帧和前 10 个异常帧位置
- 离线准确度报告新增 `±15BPM` 指标，Comp 缺失或全零时不显示 Comp 指标

## [0.4.58] - 2026-07-17

### Fixed
- 规则验证与保存 API 支持多 Pattern Parse、单捕获组分隔多列和纯 Classify 关键词库
- Classify 验证兼容 `extract/classify` 条件分类流程，不再错误要求 legacy `structure`

## [0.4.57] - 2026-07-17

### Fixed
- 修复 `offline_tools_path: .` 随进程工作目录漂移并导致离线版本目录为空的问题
- 修复多分类扫描时默认版本与默认分类不匹配的问题
- 设置离线工具目录时统一保存展开后的绝对路径

## [0.4.56] - 2026-07-17

### Added
- 新增稳定规则目录、读取和保存 API，支持用户覆盖、来源变体和 SHA-256 revision 冲突检测
- 新增配置 YAML 原文替换 API，以及芯片、分类、版本和 EXE 可用性离线资源目录 API

### Changed
- 配置与规则保存使用同目录临时文件和原子替换，配置写入后同步刷新进程内缓存
- 公共规则调用不再加载 Click 或 Rich，评估规则纳入统一结构校验

## [0.4.55] - 2026-07-17

### Added
- 新增覆盖全部 13 个 CLI 能力的同步 `health_tools.api`，支持结构化结果、进度回调和取消
- 新增 Python API 架构说明与使用指南
- 新增仓库级 `use-ghealth-tool` AI Skill，包含端到端工作流、规则编写、故障排查和环境诊断
- 新增 CLI 与命令文档一致性测试

### Changed
- CLI 与独立 UI 项目统一通过公共 Python API 使用业务能力
- 重整 README、命令、规则、架构和维护者文档，覆盖全部主命令与现有规则能力

### Removed
- 移除内置 Streamlit UI、`ghealth_tool ui` 命令和 `[ui]` 可选依赖

## [0.4.27] - 2026-06-22

### Fixed
- `offline --list` 和 `cfg --offline-scan` 类别列现在显示标准英文等级名（exclusive/premium/medium/basic），而非固定中文"性能版本"

## [0.4.26] - 2026-06-22

### Changed
- `check` 命令 `-o` 选项现在输出统一CSV报告（含全部检查项结果+ACC异常详情）
- 默认输出文件名改为 `check_report.csv`（原 `acc_anomaly_report.csv`）
- CSV每文件一行，检查项列动态生成（结果+说明），ACC字段12列跟随其后

## [0.4.25] - 2026-06-22

### Added
- `check` command: ACC异常检测（全零/静止/循环）
- ACC检测输出汇总表格和CSV报告文件
- `ChipRule` 新增 `acc_columns` 字段，支持规则文件指定ACC列名
- `ChipRule` 新增 `frame_column` 字段，支持规则文件指定帧号列名
- ACC列名自动检测：匹配含acc+xyz的列名（大小写不敏感），或纯x/y/z
- 帧号列名自动检测：匹配frame_id/frame/fid（大小写不敏感）
- ACC报告中首帧字段使用实际FRAME_ID值
- `--checks` 选项新增 `acc` 检查项（默认启用）
- `-o, --output` 选项指定ACC报告CSV输出路径

## [0.2.0] - 2024-01-02

### Added
- `split` command: Split data by column value/size/time
- `process` command: Batch process CSV files with multi-threading
- STFT time-frequency analysis support in `plot` command
- Accuracy calculation support in `classify` command
- CSV handler with configurable format based on chip rules
- File encoding auto-detection
- Parallel processing utilities
- Classification helper functions (calculate_median, extract_from_path, etc.)
- Accuracy metrics (std, rmse, mae, mape, within_N, correlation)
- Patterns extension support in classify rules
- Default spo2_posture classification rule

### Changed
- Chip rules support info_row, header_row, data_start_row configuration
- `plot` command supports default parameters (sample-rate=25, bandpass=0.5-4.0)
- `classify` command supports --extend, --accuracy, --ref-column, --pred-column options
- Improved CSV reading with chip rule configuration

## [0.1.0] - 2024-01-01

### Added
- Initial release
- CLI framework based on Click
- `parse` command: Parse log files to CSV
- `plot` command: Plot PPG data time/frequency domain charts
- `classify` command: Classify and save data based on rules
- `convert` command: CSV format conversion
- `info` command: View data/rule file information
- `validate` command: Validate rule files
- Channel shorthand syntax support (e.g., `ch[0-15]`)
- Support for extracting classification info from filename/data columns/parent directory
- Built-in chip rules for GH3220, MAX30102, AFE4400
