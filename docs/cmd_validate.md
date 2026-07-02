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
| chip | chip, columns |
| parse | regex, columns |
| classify | rules 或 classify_rules |
| convert | source_columns + target_columns 或 column_mapping |

## 示例

```bash
# 验证规则文件
ghealth_tool validate rules/chip/gh3036.yaml

# 严格模式
ghealth_tool validate convert_rule.yaml --strict
```
