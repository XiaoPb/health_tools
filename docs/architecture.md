# 架构说明

## 分层架构

```
commands/     CLI命令定义（Click）
    ↓
core/         业务逻辑引擎
    ↓
rules/        规则加载与验证
    ↓
utils/        通用工具（CSV处理、列展开、文件操作）
    ↓
models/       数据类定义（规则模型）
```

依赖方向自上而下，禁止反向依赖。`core/` 不被 `rules/` 或 `utils/` 引用。

## 模块职责

### models/

定义所有规则数据类，无外部依赖（仅依赖 `utils/columns.py`）：

| 类 | 用途 |
|---|---|
| `ChipRule` | 芯片CSV格式定义（列名、编码、分隔符、行号） |
| `ParseRule` | 日志解析正则和列映射 |
| `ConvertRule` | 格式转换规则（列映射、前值填充、频率扩展） |
| `ClassifyRule` | 文件分类规则 |
| `DataColumn` | 分类规则中的数据列定义 |

### utils/

通用工具函数，仅依赖 `models/`：

| 模块 | 用途 |
|---|---|
| `columns.py` | 列名范围展开（`[0-15]` 和 `{0-15}` 语法） |
| `csv_handler.py` | 统一CSV读写，支持信息行、自定义表头、编码检测 |
| `file.py` | 文件编码检测、路径工具 |
| `parallel.py` | 并行处理封装 |
| `logger.py` | 日志配置 |
| `accuracy.py` | 准确率计算工具 |

### rules/

规则文件的加载和验证：

| 模块 | 用途 |
|---|---|
| `loader.py` | 从YAML加载规则，支持内置路径和自定义路径 |
| `validator.py` | 规则文件格式验证 |

`RuleLoader` 查找顺序：内置 `rules/` 目录 → 绝对路径 → 相对路径。

### core/

业务逻辑引擎，每个引擎类对应一个命令：

| 类 | 用途 |
|---|---|
| `LogParser` | 正则解析日志文件为DataFrame |
| `DataConverter` | 列映射、前值填充、频率扩展、Int64类型保持 |
| `DataClassifier` | 按规则分类文件到目录结构 |
| `DataSplitter` | 按行数分割CSV |
| `BatchProcessor` | 批量处理调度 |
| `DataPlotter` | 时域/频域绘图 |
| `STFTPlotter` | 短时傅里叶变换时频图 |

### commands/

Click命令定义，每个文件导出一个 `*_cmd` 函数注册到 `cli.py`：

| 命令 | 别名 | 功能 |
|---|---|---|
| `parse` | `p` | 日志解析转CSV |
| `plot` | `pl` | 数据可视化 |
| `classify` | `cls` | 数据分类 |
| `convert` | `cv` | 格式转换 |
| `split` | — | 数据分割 |
| `info` | `i` | 文件信息查看 |
| `validate` | — | 规则验证 |
| `process` | — | 批量处理 |

## 规则系统

所有规则以YAML文件存储在 `rules/` 目录下，按类型分子目录：

```
rules/
├── chip/        芯片CSV格式定义
├── parse/       日志解析规则
├── classify/    分类规则
└── convert/     转换规则
```

规则文件通过 `RuleLoader` 加载为对应的数据类实例，传入 `core/` 引擎使用。

## 数据流

### parse 命令
```
日志文件 → LogParser(ParseRule) → DataFrame → CSVHandler(ChipRule) → CSV文件
```

### convert 命令
```
CSV文件 → CSVHandler(csv_config) → DataFrame → DataConverter(ConvertRule) → CSVHandler(ChipRule) → CSV文件
```

### classify 命令
```
CSV目录 → DataClassifier(ClassifyRule) → 分类目录结构
```

## 列名展开机制

`utils/columns.py` 提供统一的列名展开，消除了5处重复实现：

- `name[0-15]`：方括号语法，用于 chip/parse 规则（向后兼容）
- `name{0-15}`：花括号语法，可出现在字符串任意位置
- convert 规则使用 `brace_only=True`，`[]` 保留为字面量列名

示例：`rawdata[{0-1}]` 展开为 `rawdata[0]`, `rawdata[1]`（花括号展开，方括号保留）。
