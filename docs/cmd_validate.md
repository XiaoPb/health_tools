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

| 类型 | 必需字段 | `--strict` 额外要求 |
|---|---|---|
| chip | `version`、`chip`、`csv`（为 dict 时含 `header_row`/`data_start_row`）、非空 `columns` | 无 |
| parse | `version`；单 pattern：`regex`、`columns`；多 pattern：非空 `patterns` 字典，每项含 `regex`/`columns` | `description` |
| classify | `version`；非空 `structure`，或同时提供 `extract`/`classify` 列表，或纯 `patterns` 关键词库 | 简单结构需 `rules` |
| convert | `version`；`column_mapping` 或同时提供 `source_columns`/`target_columns`（等长） | 无 |
| evaluate | `type` ∈ {hr, spo2}、`ref_column`、`pred_column` | `description` |
| analysis | `version`、`type` ∈ {hr, spo2, other}、`columns`、非空 `detectors`、`thresholds`（可选）、非空 `causes` | `description` |

规则类型通过文件路径中的 `chip`/`parse`/`classify`/`convert`/`evaluate`/`analysis`
目录名判断，建议自定义文件保留类型目录。parse 会额外校验正则可编译、捕获组与 `columns`
数量匹配；convert 会校验 `source_columns`/`target_columns` 等长。

## 输出与限制

验证成功返回 0，文件不存在、扩展名错误、YAML 语法错误或结构错误返回非零状态。验证器
不读取真实数据，因此不能发现列名不匹配、分类条件无结果或外部数据无法对齐；多 pattern
parse 不适用旧的顶层 `regex/columns` 检查。`evaluate` 和 `analysis` 支持结构验证，但
仍需使用目标命令对小样本验证列和阈值。

## 示例

```bash
# 验证规则文件
ghealth_tool validate src/health_tools/rules/chip/gh3036.yaml

# 严格检查单 pattern parse 规则
ghealth_tool validate rules/parse/custom.yaml --strict
```

完整字段和验证边界见 [规则文件格式](rules.md#验证能力与限制)。
