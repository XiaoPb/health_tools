# 规则选择、编写与验证

完整字段见仓库 `docs/rules.md`。编写规则时先选择类型，再从包内同类型规则复制最接近的
结构，不从空白 YAML 猜字段。

## 类型选择

| 需要描述的差异 | 规则类型 |
|---|---|
| 标准 CSV 行号、编码、列顺序、ADC/检查/产测参数 | `chip` |
| 日志行如何提取成列或多组输出 | `parse` |
| 文件如何提取标签并放入目录 | `classify` |
| 第三方 CSV 如何映射、计算、填充或合并金标 | `convert` |
| 心率/血氧使用哪些列、阈值、分类和指标 | `evaluate` |

## 编写步骤

1. 运行 `ghealth_tool info <input.csv> --schema --preview 5` 获取真实表头与样本。
2. 找到 `src/health_tools/rules/<type>/` 中最接近的内置规则。
3. 使用 `{0-15}` 展开范围；需要字面方括号时写 `rawdata[{0-1}]`。
4. 保持列名大小写、空格和顺序与真实输入一致。
5. 把自定义规则放入用户规则目录的对应类型子目录，或用绝对路径调用。
6. 运行 `validate`；再用一个小文件执行目标命令并检查输出值。

## 关键不变量

- parse 正则捕获组数量必须等于该 pattern 展开后的列数。
- chip `columns` 是完整目标列顺序；convert 缺失目标列会补 0。
- convert `column_mapping` 是源列到目标列，不要反写。
- `forward_fill` 和 `expand_repeat` 可使用映射前源列名，转换器会解析到目标列。
- `extra_source.align.left_on/right_on` 必须成对存在；正则提取应包含捕获组。
- classify 的目标路径相对于输出目录，不要写绝对路径。
- evaluate 的列索引命令行参数是 1-based；规则默认优先使用列名。

## 验证限制

`validate` 只对 chip、单 pattern parse、classify、convert 做基础结构检查。evaluate 和多
pattern parse 必须通过目标命令验证；分类条件、计算公式、外部数据对齐也只有读取真实样本
才能证明正确。验证后检查输出列、行数、非零值和跳过原因。
