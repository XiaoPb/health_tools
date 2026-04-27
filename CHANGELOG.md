# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
