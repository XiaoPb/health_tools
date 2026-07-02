# parse 命令

log 文件解析为 CSV 格式。

## 用法

```bash
ghealth_tool parse -i <input> -o <output> -r <rule.yaml> [options]
ghealth_tool parse -i <input> -o <output> -c <chip> [options]
```

## 参数

| 参数 | 说明 |
|------|------|
| `-i/--input` | 输入文件（.log/.txt）或目录 |
| `-o/--output` | 输出 CSV 文件或目录 |
| `-r/--rule` | 解析规则 YAML 文件 |
| `-c/--chip` | 芯片类型（如 gh3036） |
| `--delimiter` | 字段分隔符（默认: 逗号） |
| `--encoding` | 输入文件编码（默认: utf-8） |
| `--filter` | 目录模式下仅处理文件名包含指定字符的文件 |
| `-v/--verbose` | 详细输出 |
| `--dry-run` | 仅验证规则，不生成文件 |

## 规则格式

### 单正则模式

```yaml
version: "1.0"
description: "解析规则描述"
target_chip: gh3036  # 可选，指定后输出完整芯片列格式

regex: '\[ADTdata\]\s*([\d\s,-]+)'
columns:
  - TimeStamp
  - FRAME_ID
  - ACCX
separator: ","
```

### 多正则模式

一组 log 解析不同数据到不同 CSV：

```yaml
version: "1.0"
description: "多数据解析"
target_chip: gh3036

patterns:
  adt:
    regex: '\[ADTdata\]\s*([\d\s,-]+)'
    columns: [TimeStamp, FRAME_ID, ACCX, ACCY, ACCZ]
    separator: ","
  hr:
    regex: '\[HR\][,\s]*([\d\s,-]+)'
    columns: [TimeStamp, HR, Confidence]
    separator: ","
```

输出文件名：`{原文件名}_{pattern名}.csv`

## 数据处理

- 使用 `re.search` 匹配（支持行内任意位置）
- 单捕获组 + 多列时自动按 separator 拆分
- 指定 `target_chip` 时输出完整芯片列格式（未匹配列填 0）
- 输出 CSV 包含 info 行 + header 行（与 chip 规则一致）

## 输出与异常汇总

- 目录模式使用进度条显示处理进度。
- 默认只在结束时输出“解析结果”汇总，包含成功、跳过、失败和警告数量。
- 空文件、无匹配记录、格式错误、读取失败等会按原因聚合统计，避免逐文件刷屏。
- 使用 `-v/--verbose` 时会额外显示失败/跳过文件明细和简短原因。

## 示例

```bash
# 单文件解析
ghealth_tool parse -i data.log -o output.csv -r parse_rule.yaml -v

# 目录批量解析
ghealth_tool parse -i ./logs/ -o ./csv_output/ -r parse_rule.yaml -v

# 多正则解析
ghealth_tool parse -i data.log -o ./output/ -r multi_rule.yaml -v

# 目录模式仅处理文件名包含 ppg 的日志
ghealth_tool parse -i ./logs/ -o ./csv_output/ -c gh3220 --filter ppg
```
