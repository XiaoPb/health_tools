# validate 命令

验证 YAML 规则文件格式和内容。

## 用法

```bash
ghealth_tool validate <rule_file> [options]
ghealth_tool val <rule_file> [options]
```

## 参数

| 参数 | 说明 |
|------|------|
| `rule_file` | YAML 规则文件路径 |
| `--strict` | 严格模式验证 |

别名：`val`。

## 验证内容

根据规则类型（通过路径自动检测）验证：

| 规则类型 | 必需字段 |
|----------|----------|
| chip | version, chip, csv.header_row, csv.data_start_row, columns |
| parse | regex, columns |
| classify | version, structure |
| convert | source_columns + target_columns 或 column_mapping |

规则类型通过文件路径中的 `chip`、`parse`、`classify`、`convert` 目录名判断。`--strict`
当前只额外要求 parse 规则包含 `description`。

## 输出与限制

验证成功返回 0，文件不存在、扩展名错误、YAML 语法错误或结构错误返回非零状态。当前没有
evaluate 专用结构验证，多 pattern parse 也不适用旧的顶层 `regex/columns` 检查；这些规则
必须使用目标命令和小样本继续验证。验证器不会读取真实数据，因此不能发现列名不匹配、
分类条件无结果或外部数据无法对齐。

## 示例

```bash
# 验证规则文件
ghealth_tool validate src/health_tools/rules/chip/gh3036.yaml

# 严格检查单 pattern parse 规则
ghealth_tool validate rules/parse/custom.yaml --strict
```

完整字段和验证边界见 [规则文件格式](rules.md#验证能力与限制)。
