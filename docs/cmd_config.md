# config 命令

全局配置管理，设置用户级规则目录。

## 用法

```bash
ghealth_tool config [options]
```

## 参数

| 参数 | 说明 |
|------|------|
| `--init` | 初始化用户配置目录（~/.ghealth_tools/） |
| `--show` | 显示当前配置（默认） |
| `--rules-dir` | 设置规则目录路径 |

## 配置目录结构

```
~/.ghealth_tools/
├── config.yaml          # 配置文件
└── rules/               # 用户规则目录
    ├── chip/            # 芯片定义（优先于内置规则）
    ├── parse/           # 解析规则
    ├── classify/        # 分类规则
    └── convert/         # 转换规则
```

## 规则优先级

1. 绝对路径 → 直接使用
2. 用户规则目录 `~/.ghealth_tools/rules/<type>/` → 存在则优先
3. 内置规则目录 → 兜底

## 示例

```bash
# 初始化配置
ghealth_tool config --init

# 查看配置
ghealth_tool config --show

# 修改规则目录
ghealth_tool config --rules-dir /path/to/custom/rules

# 添加自定义芯片支持（初始化后复制模板修改即可）
cp rules/chip/gh3036.yaml ~/.ghealth_tools/rules/chip/my_chip.yaml
# 编辑 my_chip.yaml 后即可使用:
ghealth_tool parse -i log.txt -o output/ --chip my_chip
```
