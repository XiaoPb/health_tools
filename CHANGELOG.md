# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
