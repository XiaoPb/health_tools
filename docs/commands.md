# 命令详细说明

## parse - 日志解析

将原始日志文件按正则规则解析为CSV格式。

```bash
health_tool parse -i <输入> -o <输出> [-r <规则文件>] [-c <芯片>] [--delimiter <分隔符>]
```

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入日志文件或目录（必需） |
| `-o, --output` | 输出CSV文件或目录（必需） |
| `-r, --rule` | 解析规则文件（YAML） |
| `-c, --chip` | 芯片名称（使用内置芯片规则） |
| `--delimiter` | 字段分隔符（默认逗号） |

### 示例

```bash
# 单文件解析
health_tool parse -i raw.log -o output.csv -r parse/gh3220.yaml

# 目录批量解析
health_tool parse -i logs/ -o output/ -c gh3220

# 使用别名
health_tool p -i raw.log -o output.csv -c gh3220
```

### 工作原理

1. 加载解析规则（正则表达式 + 列名定义）
2. 逐行匹配日志，提取字段
3. 按芯片规则写入CSV（含信息行、表头）

---

## plot - 数据可视化

绘制PPG数据的时域图、频域图或时频图（STFT）。

```bash
health_tool plot -i <输入> -o <输出目录> [--type <类型>] [--sample-rate <采样率>]
```

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入CSV文件（必需） |
| `-o, --output` | 输出目录（必需） |
| `--type` | 图表类型：time / freq / both / stft |
| `--sample-rate` | 采样率（Hz） |
| `--channels` | 指定绘制的通道（逗号分隔） |
| `--window` | 窗口大小（秒） |
| `--overlap` | 窗口重叠率（0-1） |

### 示例

```bash
# 时域+频域
health_tool plot -i data.csv -o plots/ --type both --sample-rate 100

# 仅时域，指定通道
health_tool plot -i data.csv -o plots/ --type time --channels red,ir

# STFT时频图
health_tool plot -i data.csv -o plots/ --type stft --sample-rate 100 --window 10
```

---

## classify - 数据分类

根据文件名模式和规则将CSV文件分类到目录结构中。

```bash
health_tool classify -i <输入目录> -o <输出目录> [-r <规则>] [--accuracy] [--move]
```

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入CSV文件或目录（必需） |
| `-o, --output` | 输出目录（必需） |
| `-r, --rule` | 分类规则文件（默认 spo2_posture.yaml） |
| `--extend` | 扩展patterns文件（可多次使用） |
| `--accuracy` | 启用准确率计算 |

### 示例

```bash
# 基本分类
health_tool classify -i data/ -o classified/ -r classify/spo2_posture.yaml

# 使用别名 + 准确率
health_tool cls -i data/ -o classified/ --accuracy
```

---

## convert - 格式转换

CSV格式转换，支持列映射、前值填充、频率扩展、合并和分割。

```bash
health_tool convert -i <输入> -o <输出> [-r <规则>] [-c <芯片>] [--merge] [--split <行数>]
```

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入CSV文件或目录（必需） |
| `-o, --output` | 输出文件或目录（必需） |
| `-r, --rule` | 转换规则文件 |
| `-c, --chip` | 目标芯片格式 |
| `--from` | 源格式 |
| `--to` | 目标格式 |
| `--merge` | 合并目录中所有CSV |
| `--split` | 按行数分割输出 |
| `--init-rule` | 生成转换规则模板 |
| `-v, --verbose` | 详细输出 |

### 示例

```bash
# 使用转换规则
health_tool convert -i input.csv -o output.csv -r convert/my_rule.yaml -v

# 直接指定目标芯片
health_tool convert -i input.csv -o output.csv -c gh3036

# 合并目录并分割
health_tool convert -i data/ -o merged.csv --merge --split 5000 -r convert/rule.yaml

# 生成规则模板
health_tool convert --init-rule -c gh3220 -o my_convert_rule.yaml

# 使用别名
health_tool cv -i input.csv -o output.csv -r convert/rule.yaml
```

### 转换流程

1. 按 convert rule 的 `csv` 配置读取输入文件
2. 执行列映射（`column_mapping`）
3. 执行计算列（`computed`）
4. 执行频率扩展（`expand_repeat`）
5. 执行前值填充（`forward_fill`）
6. 补齐目标芯片缺失列（填0）
7. 按芯片列顺序排列
8. 保持Int64整数类型
9. 按芯片规则的CSV格式写入输出

### 前值填充 (forward_fill)

在首个非0值出现后，将后续的0值替换为前一个非0值：

```
输入: [0, 0, 3, 0, 0, 4, 0, 0, 5]
输出: [0, 0, 3, 3, 3, 4, 4, 4, 5]
```

规则中使用源列名（映射前的名称）。

### 频率扩展 (expand_repeat)

当某列采样率低于其他列时，将每个值重复N次以对齐行数：

```yaml
expand_repeat:
  polar_HR: 25    # 1Hz -> 25Hz，每个值重复25次
```

---

## split - 数据分割

按行数分割大型CSV文件。

```bash
health_tool split -i <输入> -o <输出目录> -n <行数>
```

| 参数 | 说明 |
|---|---|
| `-i, --input` | 输入CSV文件（必需） |
| `-o, --output` | 输出目录（必需） |
| `-n, --rows` | 每个分片的行数 |

---

## info - 信息查看

查看CSV数据文件或规则文件的基本信息。

```bash
health_tool info <文件路径> [--stats] [--preview <行数>] [--schema]
```

| 参数 | 说明 |
|---|---|
| `文件路径` | 要查看的文件 |
| `--stats` | 显示统计信息 |
| `--preview` | 预览前N行数据 |
| `--schema` | 显示规则文件结构 |

### 示例

```bash
# 查看CSV信息和统计
health_tool info data.csv --stats --preview 10

# 查看规则文件结构
health_tool info rules/chip/gh3220.yaml --schema

# 使用别名
health_tool i data.csv --stats
```

---

## validate - 规则验证

验证YAML规则文件的格式和内容是否正确。

```bash
health_tool validate <规则文件> [--strict]
```

| 参数 | 说明 |
|---|---|
| `规则文件` | 要验证的YAML文件 |
| `--strict` | 严格模式（检查列名是否存在于芯片定义中） |

---

## process - 批量处理

执行批量数据处理流水线。

```bash
health_tool process -i <输入目录> -o <输出目录> [选项]
```
