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

# extra_source: 从额外文件读取金标/参考列，并按指定列对齐
extra_source:
  suffix: ".txt"        # 自动在当前输入文件同目录查找匹配后缀的文件
  # path: "划船机.txt"    # 也可直接指定相对/绝对路径，优先级高于 suffix/pattern
  # pattern: "*.ref.csv" # 或使用 glob 模式
  csv:
    header_row: 1
    data_start_row: 2
    delimiter: ","
  align:
    left_on: time        # 原始数据对齐列
    right_on: time       # 金标文件对齐列
  column_mapping:
    polar: REF_RESULT0   # 金标列映射到输出列
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
| `extra_source` | 从额外文件读取参考列并按配置列对齐 |

### extra_source 字段说明

适用于金标数据不在原始 CSV 内，而是在同目录额外文件中的场景。

常用配置：

- `path`：直接指定金标文件路径
- `suffix`：按后缀自动查找，例如 `.txt`
- `pattern`：按 glob 模式查找，例如 `*.ref.csv`
- `csv`：额外文件的 CSV 解析配置
- `align.left_on`：原始数据中的对齐列名
- `align.right_on`：额外文件中的对齐列名
- `column_mapping`：额外文件列名到输出列名的映射

当前“动态心率”这类数据可配置为：原始数据和金标文件都按 `time` 列对齐；如果两边列名不同，也可分别设置 `left_on` 与 `right_on`。

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

# 动态心率目录批量转换（自动读取各子目录下 .txt 金标文件，并按 time 对齐）
ghealth_tool convert \
  -i "E:/LierdaWorkFiles/Chelsea_A/客户项目/舟海/Santos/问题处理/心率/0609/动态心率" \
  -o "E:/LierdaWorkFiles/Chelsea_A/客户项目/舟海/Santos/问题处理/心率/0609/动态心率_gh3036" \
  -r "E:/LierdaWorkFiles/Chelsea_A/客户项目/舟海/Santos/问题处理/心率/0609/动态心率/convert_gh3036.yaml" \
  -v
```
