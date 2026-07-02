# split 命令

按列值、行数或时间分割 CSV 数据文件。

## 用法

```bash
ghealth_tool split -i <input> -o <output_dir> [options]
```

## 参数

| 参数 | 说明 |
|------|------|
| `-i/--input` | 输入文件或目录 |
| `-o/--output` | 输出目录 |
| `-c/--chip` | 芯片类型 |
| `--by-column` | 按列值分割（如 FRAME_ID） |
| `--column-value` | 分割阈值（默认: 0） |
| `--by-size` | 按行数分割 |
| `--by-time` | 按时间分割（秒） |
| `--time-column` | 时间列名 |
| `--filter` | 目录模式下仅处理文件名包含指定字符的 CSV |
| `-v/--verbose` | 详细输出 |

## 分割模式

| 模式 | 说明 |
|------|------|
| `--by-column` | 当指定列值变化时分割（如 FRAME_ID 归零） |
| `--by-size` | 每 N 行分割为一个文件 |
| `--by-time` | 按时间列每 N 秒分割 |

## 输出与异常汇总

- 输入为目录时递归处理 CSV，并使用进度条显示进度。
- 默认输出“分割结果”汇总，成功文件不逐条打印。
- 空文件、格式错误、列缺失和读取失败会统计到原因表；单个坏文件不会中断目录处理。
- 使用 `-v/--verbose` 时显示失败/跳过文件明细。

## 示例

```bash
# 按 FRAME_ID 分割
ghealth_tool split -i data.csv -o ./split/ --chip gh3036 --by-column FRAME_ID -v

# 按行数分割
ghealth_tool split -i data.csv -o ./split/ --by-size 1000 -v

# 按时间分割（每 60 秒）
ghealth_tool split -i data.csv -o ./split/ --by-time 60 --time-column TimeStamp -v
```
