# process 命令

批量处理目录中的 CSV 文件（并行处理，支持帧分割）。

## 用法

```bash
ghealth_tool process -i <input_dir> -o <output_dir> [options]
```

## 参数

| 参数 | 说明 |
|------|------|
| `-i/--input` | 输入目录 |
| `-o/--output` | 输出目录 |
| `-c/--chip` | 芯片类型 |
| `--split` | 按 FRAME_ID 分割数据 |
| `--frame-column` | 帧 ID 列名（默认: FRAME_ID） |
| `--workers` | 并行线程数（默认: 4） |
| `--pattern` | 文件匹配模式（默认: *.csv） |
| `--filter` | 仅处理文件名包含指定字符的 CSV |
| `-v/--verbose` | 详细输出 |

## 输出与异常汇总

- 批量处理使用进度条显示并行任务进度。
- 默认输出“处理结果”汇总，统计成功和失败数量。
- 空文件、读取失败、处理失败等原因会聚合展示。
- 使用 `-v/--verbose` 时显示失败文件明细。

## 示例

```bash
# 批量处理
ghealth_tool process -i ./raw/ -o ./processed/ --chip gh3036 -v

# 并行处理并分割
ghealth_tool process -i ./raw/ -o ./processed/ --chip gh3036 --split --workers 8 -v
```
