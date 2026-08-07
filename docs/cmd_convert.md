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
| `--filter` | 目录模式下仅处理文件名包含指定字符的 CSV |
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
# split: 先分割再转换（每段独立 forward_fill）
split:
  by_column: source_col   # 须为映射前的源列名
  column_value: 0
# classify: 转换后分类（支持 extract/classify 条件分类与 filename 重分类；extract 作用于转换后的列）
classify:
  default: unclassified
  filename:
    regex: '(?P<motion>sit|walk).*\.csv'
  structure:
    sit: ''
    walk: ''
  rules:
    - target: '{motion}'
  rename: '{motion}_{filename}'

# expand_repeat: 低采样率列重复扩展
expand_repeat:
  polar_HR: 25  # 每个值重复 25 次

computed:
  FLAG0: "status * 1"

# extra_source: 从额外文件读取金标/参考列，并按指定列对齐
extra_source:
  - name: hr_ref
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
| `split` | 先分割再转换；支持 by_column/by_size/by_time（三选一） |
| `classify` | 转换后分类；支持完整 classify 参数（含 filename/rules/rename） |
| `expand_repeat` | 列重复扩展（低采样率对齐高采样率） |
| `computed` | 计算列（支持 +, -, *, / 运算） |
| `extra_source` | 从额外文件读取参考列并按配置列对齐 |

### extra_source 字段说明

适用于金标数据不在原始 CSV 内，而是在同目录额外文件中的场景。`extra_source`
可以写成单个字典，也可以写成列表以合并多个参考来源。

常用配置：

- `path`：直接指定金标文件路径
- `suffix`：按后缀自动查找，例如 `.txt`
- `pattern`：按 glob 模式查找，例如 `*.ref.csv`
- `csv`：额外文件的 CSV 解析配置
- `align.left_on`：原始数据中的对齐列名
- `align.right_on`：额外文件中的对齐列名
- `column_mapping`：额外文件列名到输出列名的映射
- `required_columns`：额外文件必须包含的列，缺少时跳过该候选文件
- `any_required_columns`：至少命中其中一个列名，适合同一含义有多个列名的金标文件
- `align.right_extract`：从右侧对齐列中用正则提取实际对齐值，如中文时间戳中的 `HH:MM:SS`

当前“动态心率”这类数据可配置为：原始数据和金标文件都按 `time` 列对齐；如果两边列名不同，也可分别设置 `left_on` 与 `right_on`。

当找到对比文件但按对齐列合并后没有有效数据时，命令会生成
`extra_source_align_errors.csv`，记录原始文件、对比文件、对比源和失败原因，便于批量排查金标时间不一致的问题。

## 规则 split

规则文件配置 `split` 时，convert 在读取并合并 `extra_source` 后先按配置分割，再对每段
分别执行映射、computed、expand_repeat、forward_fill 并写出 `<输出名>_<序号>.csv`。
适用于按帧分割：`forward_fill` 不会跨段串值。`--split <N>` 仅在没有规则 `split` 的合并
模式下按转换后的行数分割输出。

`by_column` 与 `time_column` 必须使用映射前的源列名（即 `column_mapping` 左侧的列名）。

## 规则 classify

规则文件配置 `classify` 时，convert 在转换完成（含 `split` 分段）后对每个转换结果执行分类，
写入 `{输出目录}/{类别路径}/{输出文件名}`。块内支持完整 classify 规则参数：`filename`/`path`/
`data_columns`/`structure`/`rules`（简单分类，含文件名重分类）、`extract`/`classify`（条件
分类）、`default`、`rename`（重命名输出文件名）。`extract` 的列参数使用转换后的目标列名（如
`REF_RESULT5`）；未命中任何条件时输出到 `classify.default` 目录（默认 `unclassified`），
保证转换产物不丢失。

## 输出与异常汇总

- 目录转换和合并转换都使用进度条显示进度。
- 默认保留转换结果表，但隐藏成功文件，只展示跳过/失败项。
- 结束后额外输出“转换汇总”，按 `规则不匹配`、`文件为空`、`格式不对`、`读取失败` 等原因统计。
- 使用 `-v/--verbose` 时展示成功文件和失败/跳过明细。

## 生成规则模板

`--init-rule` 从源 CSV 推测 column_mapping：

```bash
# 从源 CSV 推测映射关系
ghealth_tool convert --init-rule -c gh3036 -i source.csv -o custom_rules/convert/vendor.yaml

# 不指定源文件时生成空模板
ghealth_tool convert --init-rule -c gh3036 -o custom_rules/convert/template.yaml
```

生成的模板包含：
- csv 配置（info_row, header_row, data_start_row, delimiter）
- column_mapping（自动匹配的列 + 未匹配列标记为 Unknown）
- forward_fill 和 expand_repeat 以注释形式提供

## 示例

```bash
# 按规则转换
ghealth_tool convert -i input.csv -o output.csv -r custom_rules/convert/vendor.yaml -v

# 目录批量转换
ghealth_tool convert -i ./input/ -o ./output/ -r custom_rules/convert/vendor.yaml -v

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
