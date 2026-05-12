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
| `--copy` | 复制文件（默认） |
| `--move` | 移动文件 |
| `--symlink` | 创建符号链接 |
| `--report` | 生成分类报告 |
| `--unknown` | 未匹配文件目录名 |
| `-c/--chip` | 芯片类型 |
| `-v/--verbose` | 详细输出 |

## 分类规则

支持基于文件名模式、数据列值范围、正则匹配等多种分类方式。

## 示例

```bash
# 按规则分类
ghealth_tool classify -i ./data/ -o ./classified/ -r spo2_posture.yaml -v

# 启用准确率计算
ghealth_tool classify -i ./data/ -o ./classified/ -r rule.yaml --accuracy --report -v
```
