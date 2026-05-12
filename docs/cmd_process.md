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
| `-v/--verbose` | 详细输出 |

## 示例

```bash
# 批量处理
ghealth_tool process -i ./raw/ -o ./processed/ --chip gh3036 -v

# 并行处理并分割
ghealth_tool process -i ./raw/ -o ./processed/ --chip gh3036 --split --workers 8 -v
```
