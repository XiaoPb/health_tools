# config 命令

全局配置管理，设置用户级规则目录和离线工具配置。别名：`cfg`。

## 用法

```bash
ghealth_tool config [options]
ghealth_tool cfg [options]
```

## 参数

| 参数 | 说明 |
|------|------|
| `--init` | 初始化用户配置目录（~/.ghealth_tools/） |
| `--force` | 强制更新内置规则文件（覆盖已有） |
| `--show` | 显示当前配置（默认） |
| `--rules-dir` | 设置规则目录路径 |
| `--offline-path` | 设置离线工具搜索路径（自动扫描版本） |
| `--offline-default` | 设置芯片默认版本（格式: `chip=version`） |
| `--offline-scan` | 重新扫描离线工具版本 |

## 配置目录结构

```
~/.ghealth_tools/
├── config.yaml                    # 配置文件
├── rules/                         # 用户规则目录
│   ├── chip/                      # 芯片定义（优先于内置规则）
│   ├── parse/                     # 解析规则
│   ├── classify/                  # 分类规则
│   └── convert/                   # 转换规则
└── offline_algorithm_tools/       # 离线算法工具目录
    ├── gh3036/
    │   └── <category>/            # exclusive/premium/medium/basic
    │       └── <version>/
    │           └── TEE_Algorithm.exe
    └── gh3220/
        └── <category>/
            └── <version>/
                └── TEE_Algorithm.exe
```

## 规则优先级

1. 绝对路径 → 直接使用
2. 用户规则目录 `~/.ghealth_tools/rules/<type>/` → 存在则优先
3. 内置规则目录 → 兜底

## 示例

```bash
# 初始化配置
ghealth_tool cfg --init

# 查看配置
ghealth_tool cfg --show

# 修改规则目录
ghealth_tool cfg --rules-dir /path/to/custom/rules

# 设置离线工具路径（自动扫描版本）
ghealth_tool cfg --offline-path /path/to/offline_algorithm_tools

# 重新扫描离线工具版本
ghealth_tool cfg --offline-scan

# 设置芯片默认算法版本
ghealth_tool cfg --offline-default gh3220=V4300_GH_HR_exc_pv_v2.0.3.0

# 添加自定义芯片支持（初始化后复制模板修改即可）
cp rules/chip/gh3036.yaml ~/.ghealth_tools/rules/chip/my_chip.yaml
# 编辑 my_chip.yaml 后即可使用:
ghealth_tool parse -i log.txt -o output/ --chip my_chip
```
