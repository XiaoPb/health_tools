# classify 命令

根据规则对 CSV 文件进行分类，按类别归档到子目录。

## 用法

```bash
ghealth_tool classify -i <input> -o <output> -r <rule.yaml> [options]
```

## 参数

| 参数 | 说明 |
|------|------|
| `-i/--input` | 输入 CSV 文件或目录 |
| `-o/--output` | 输出目录 |
| `-r/--rule` | 分类规则 YAML 文件 |
| `--extend` | 扩展 patterns 文件（可多次使用） |
| `--accuracy` | 启用准确率计算 |
| `--ref-column` | 参考列名（覆盖规则配置） |
| `--pred-column` | 预测列名（覆盖规则配置） |
| `--accuracy-thresholds` | 固定准确度阈值，逗号分隔；未指定时由规则 `methods` 决定，无规则配置时默认 `5,10,15` |
| `--accuracy-inclusive/--accuracy-strict` | 阈值边界包含/严格模式；默认 strict，即 `abs(error) < threshold` |
| `--copy` | 复制文件（默认） |
| `--move` | 移动文件 |
| `--symlink` | 创建符号链接 |
| `--report` | 生成分类报告 |
| `--unknown` | 未匹配文件目录名 |
| `-c/--chip` | 芯片类型 |
| `--filter` | 仅处理文件名包含指定字符的 CSV |
| `--dry-run` | 预览模式：计算目标路径但不写入文件 |
| `--min-rows` | 跳过行数少于该值的文件（覆盖规则 filters.min_rows） |
| `--min-size` | 跳过大小（KB）小于该值的文件（覆盖规则 filters.min_size_kb） |
| `--conflict` | 输出路径冲突策略：skip（默认）/rename/overwrite |
| `-v/--verbose` | 详细输出 |

## 分类规则

支持基于文件名模式、数据列值范围、正则匹配等多种分类方式。

## 准确度统计口径

指定 `--accuracy` 后才计算准确度，统一遵循以下规则：

- 默认 strict 模式按 `abs(error) < threshold` 计入；指定 `--accuracy-inclusive` 后改为
  `abs(error) <= threshold`。固定阈值默认为 `5,10,15`。
- 分类规则显式声明 `accuracy.methods` 时使用规则方法，否则使用含 `5/10/15` 的默认方法；
  `accuracy.thresholds` 始终作为额外的自定义命名指标。显式 `--accuracy-thresholds` 只替换
  `methods` 中固定数值形式的 `within_N`；其他方法以及 `thresholds` 中自定义命名的固定
  阈值、百分比阈值均保留。
- 参考列或预测列如果没有任意一个 finite 且非 `0` 的值，则整列禁用，不参与有效边界、
  比较或报告汇总。剩余全部启用列共同确定首尾共享边界：从首个到最后一个“所有启用列
  均为 finite 且非 `0`”的行截取同一切片。切片中间的 `0` 保留并参与正常误差计算，
  `NaN`/`Inf` 仅在参考值与预测值配对计算时过滤。

## 输出与异常汇总

- 目录模式使用进度条显示分类进度。
- 默认输出“分类结果”汇总，成功分类文件不逐条打印。
- 未匹配规则的文件会统计为跳过；指定 `--unknown` 时仍会复制/移动到未知目录。
- 准确率计算失败会统计为警告，不影响文件分类。
- 使用 `-v/--verbose` 时显示失败、跳过、警告文件明细，以及规则提取到的调试值。

## 示例

```bash
# 按规则分类
ghealth_tool classify -i ./data/ -o ./classified/ -r spo2_posture.yaml -v

# 启用准确率计算
ghealth_tool classify -i ./data/ -o ./classified/ -r rule.yaml --accuracy --report -v

# 覆盖固定阈值，并把等于阈值的误差计入
ghealth_tool classify -i ./data/ -o ./classified/ -r rule.yaml --accuracy \
  --accuracy-thresholds 3,6,9 --accuracy-inclusive

# 未匹配文件放入 unknown 目录
ghealth_tool classify -i ./data/ -o ./classified/ -r rule.yaml --unknown unknown

# 路径重命名 + 小文件过滤（dry-run 预览）
ghealth_tool classify -i ./data/ -o ./classified/ -r path_rename.yaml --dry-run -v

# 确认无误后正式执行，冲突时自动追加后缀
ghealth_tool classify -i ./data/ -o ./classified/ -r path_rename.yaml --conflict rename
```
