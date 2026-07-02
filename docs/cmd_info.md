# info 命令

查看 CSV 或 YAML 规则文件的信息。

## 用法

```bash
ghealth_tool info <file_path> [options]
ghealth_tool i <file_path> [options]
```

## 参数

| 参数 | 说明 |
|------|------|
| `target` | 文件路径（CSV 或 YAML） |
| `--stats` | 显示统计信息 |
| `--schema` | 显示数据结构/列信息 |
| `--preview` | 预览前 N 行（默认: 10） |

别名：`i`。

## 支持的文件类型

- **CSV 文件**：显示行数、列数、列名、数据类型、预览
- **YAML 规则文件**：显示规则类型、配置内容

## 示例

```bash
# 查看 CSV 信息
ghealth_tool info data.csv

# 查看统计信息
ghealth_tool info data.csv --stats

# 查看规则文件
ghealth_tool info rules/chip/gh3036.yaml
```
