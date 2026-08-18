# Convert Classify 扁平分类输出设计

## 背景

`convert` 处理目录输入时，会先根据源文件相对于输入目录的路径计算输出位置。当前在配置
`classify` 后，分类目录继续追加在该输出位置的父目录下，因此源文件
`Abigail/Abigail_操场跑_左手/操场跑/data.csv` 会被写到类似下面的位置：

```text
data_gh3036/Abigail/Abigail_操场跑_左手/操场跑/操场跑/data.csv
```

分类规则已经通过 `rules[].target` 完整定义目标目录，原输入相对路径不应继续参与分类后的
输出布局。期望输出为：

```text
data_gh3036/操场跑/data.csv
```

## 目标

只要 convert 规则配置了 `classify`，所有转换结果都完全按照分类结果写入
`{输出根目录}/{类别路径}/{输出文件名}`，不保留源文件相对于输入目录的任何父目录。

未配置 `classify` 的 convert 行为保持不变，目录转换仍保留原相对路径。

## 输出路径语义

### 目录输入

配置 `classify` 时，普通转换结果直接写入：

```text
{output}/{category}/{filename}
```

其中 `category` 是 `rules[].target` 或条件分类的 `classify[].target` 解析结果，可以包含多级
相对目录。源文件的相对父目录只用于 `path.regex` 提取变量，不参与输出路径拼接。

### 单文件输入

单文件转换继续把用户指定输出文件的父目录视为输出根目录：

```text
{output_file.parent}/{category}/{filename}
```

`rename` 未配置时使用用户指定的输出文件名；配置后使用模板解析出的文件名。

### 默认分类

分类规则未命中时，结果写入：

```text
{输出根目录}/{default}/{filename}
```

未显式配置 `default` 时使用 `unclassified`。默认分类同样不保留原相对路径。

### Split 分段

规则配置 `split` 时，每个分段独立分类并写入：

```text
{输出根目录}/{category}/{filename}_{序号}.csv
```

不同分段可以进入不同类别；所有分段均不保留原相对路径。

### 合并模式

合并模式没有源文件相对目录，维持现有输出语义：以合并输出文件的父目录为输出根目录，
追加分类路径和输出文件名。本改动不改变合并模式的 filename/path 分类限制。

## 实现边界

改动集中在 convert 的写出路径计算。目录扫描阶段仍生成包含源相对路径的候选
`destination`，以保持未分类转换的现有行为；进入分类写出分支后，改用本次 convert 请求的
统一输出根目录，而不是 `destination.parent`。

输出根目录应由调用层明确传给单文件转换函数，避免从任意层级的 `destination` 反推。分类器
仍接收源文件和 `input_root`，因此 `path.regex` 能继续匹配完整的相对输入路径并提取 `name`、
`scene`、`side` 等变量。

## 兼容性

- 未配置 `classify`：输出路径不变，继续保留目录结构。
- 配置 `classify`：目录输出从“原相对目录/类别”改为“类别”，这是本需求要求的行为变更。
- `rename`、`default`、条件分类、数据列分类和 path/filename 字段提取逻辑不变。
- 分类目标中的多级目录仍受支持，例如 `{project}/{scene}`。
- 文件名冲突处理沿用 convert 当前行为，本次不新增冲突策略。

## 测试设计

在 `tests/test_api_operations.py` 覆盖以下行为：

1. 将现有目录分类测试从“保留子目录”改为断言输出直接位于类别目录。
2. 路径正则仍能从原相对路径提取 `scene`，但输出仅包含一次 `{scene}` 分类目录。
3. 未命中规则时，文件直接进入输出根目录下的 `unclassified`。
4. 目录输入配合 `split` 时，各分段直接进入分类目录并保留序号命名。
5. 未配置 `classify` 的目录转换继续保留源相对目录，防止通用 convert 行为回归。

验证时先确认 `health_tools.__file__` 指向当前工作区的 `src`，再运行相关测试，并执行 Black、
Ruff 和全量 pytest。

## 文档更新

同步更新：

- `docs/cmd_convert.md`：说明配置分类后，类别路径取代源相对目录。
- `docs/rules.md`：明确 `path.regex` 仍匹配源相对路径，但该路径只用于字段提取，不参与输出。
