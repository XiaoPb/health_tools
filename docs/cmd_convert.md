# convert 命令

CSV 格式转换：列重命名、映射、扩展、填充、合并、分割。

## 用法

```bash
ghealth_tool convert -i <input> -o <output> -r <rule.yaml> [options]
ghealth_tool convert --init-rule -c <chip> -i <source.csv> -o <template.yaml>
```

## 参数

| 参数 | 说明 |
|------|------|
| `-i/--input` | 输入 CSV 文件或目录 |
| `-o/--output` | 输出文件或目录 |
| `-r/--rule` | 转换规则 YAML 文件 |
| `-c/--chip` | 目标芯片格式 |
| `--from` | 源格式: compact\|expand\|chip |
| `--to` | 目标格式: compact\|expand\|chip |
| `--merge` | 合并多个文件为一个 |
| `--split` | 按行数分割输出 |
| `--init-rule` | 生成转换规则模板 |
| `-v/--verbose` | 详细输出 |

## 规则格式

```yaml
version: "1.0"
description: "转换规则描述"
target_chip: gh3036

csv:
  info_row: 1
  header_row: 2
  data_start_row: 3
  delimiter: ","

column_mapping:
  source_col: TargetCol
  rawdata{0-15}: Rawdata{0-15}  # 支持范围展开

# forward_fill: 前向填充（0 值用前一个非零值替代）
forward_fill:
  - polar_HR

# expand_repeat: 低采样率列重复扩展
expand_repeat:
  polar_HR: 25  # 每个值重复 25 次

computed:
  FLAG0: "status * 1"
```

### 字段说明

| 字段 | 说明 |
|------|------|
| `target_chip` | 目标芯片（输出按芯片列格式） |
| `csv` | 输入 CSV 解析配置 |
| `column_mapping` | 源列 → 目标列映射（支持 `{start-end}` 展开） |
| `forward_fill` | 前向填充列（零值用前一个非零值替代） |
| `expand_repeat` | 列重复扩展（低采样率对齐高采样率） |
| `computed` | 计算列（支持 +, -, *, / 运算） |

## 生成规则模板

`--init-rule` 从源 CSV 推测 column_mapping：

```bash
# 从源 CSV 推测映射关系
ghealth_tool convert --init-rule -c gh3036 -i source.csv -o convert_rule.yaml

# 不指定源文件时生成空模板
ghealth_tool convert --init-rule -c gh3036 -o convert_rule.yaml
```

生成的模板包含：
- csv 配置（info_row, header_row, data_start_row, delimiter）
- column_mapping（自动匹配的列 + 未匹配列标记为 Unknown）
- forward_fill 和 expand_repeat 以注释形式提供

## 示例

```bash
# 按规则转换
ghealth_tool convert -i input.csv -o output.csv -r convert_rule.yaml -v

# 目录批量转换
ghealth_tool convert -i ./input/ -o ./output/ -r convert_rule.yaml -v

# 合并多文件
ghealth_tool convert -i ./input/ -o merged.csv -r rule.yaml --merge -v

# 合并并分割
ghealth_tool convert -i ./input/ -o output.csv -r rule.yaml --merge --split 1000 -v
```
