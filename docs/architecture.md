# 架构说明

GHealth Tools 同时提供 Click 命令行和同步 Python API。两种入口复用同一组业务逻辑、
规则模型和 CSV 工具；独立 UI 项目只依赖公共 API。

## 组件关系

```text
cli.py / commands/        Click 参数与终端呈现
          |
          v
api/                     公共请求、结果、校验、进度、取消与业务编排
          |  \
          |   +---------- config.py / rules/loader.py
          v
core/                    解析、转换、检查、绘图、评估、离线跑库等算法逻辑
          |
          v
models/ + utils/         规则数据类、CSV、列展开、文件、并行和准确度工具

```

主要依赖方向是入口层到业务层，再到规则与工具层。`models/rules.py` 为复用列展开逻辑会
依赖 `utils/columns.py`，这是当前结构中的明确例外。新增功能应优先放入 `core/`，命令层只
负责解析参数和呈现结果。

## 入口与延迟加载

`ghealth_tool` 指向 `health_tools.cli:main`。`cli.py` 中的 `LazyGroup` 只在用户调用某个
命令时导入对应模块，缩短主帮助命令的启动时间。

主命令及别名由 `COMMAND_MAP` 和 `PRIMARY_COMMANDS` 定义。新增命令时必须同时更新：

1. `src/health_tools/cli.py` 中的命令映射、帮助和主命令顺序。
2. `src/health_tools/commands/` 中的 Click 命令。
3. `docs/cmd_<command>.md` 和命令索引。
4. CLI 与文档一致性测试。

## 模块职责

### models

| 类型 | 职责 |
|---|---|
| `ChipRule` | CSV 格式、列顺序、检查列、产测与芯片参数 |
| `ParseRule` / `ParsePattern` | 单正则或多 pattern 日志解析 |
| `ConvertRule` | 列映射、计算、填充、扩展和 `extra_source` |
| `ClassifyRule` / `DataColumn` | 文件/数据提取、分类与准确度配置 |
| `EvaluateRule` | 评估列、异常检测、分类和准确度方法 |

### rules

`RuleLoader` 把 YAML 转为规则数据类，并负责用户规则和内置规则的查找。`RuleValidator`
提供基础结构验证；命令层的 `validate.py` 还包含转换规则扩展字段校验。

规则类型目录：

```text
src/health_tools/rules/
├── chip/
├── parse/
├── classify/
├── convert/
├── evaluate/
└── analysis/
```

### core

| 模块 | 主要职责 |
|---|---|
| `parser.py` | 单 pattern 和多 pattern 日志解析 |
| `converter.py` | CSV 映射、计算、填充、扩展、外部数据对齐 |
| `classifier.py` | 分类字段提取和目录路由 |
| `checker.py` | 数据范围、帧、居中、Ipd、ACC、时间戳检查 |
| `plotter.py`, `stft.py` | 时域、频域、STFT 绘图 |
| `psd_plotter.py`, `vshb.py` | 离线 PSD 及在线/离线/comp/金标叠加 |
| `factory.py` | SNR、CTR、Noise 产测指标 |
| `evaluator.py` | 心率/血氧批量评估 |
| `offline.py` | 算法版本扫描、命令构建、跑库、整理和准确度 |
| `offline_parallel.py` | 一级子目录任务发现、隔离输出、并发队列、失败重试和单线程合并 |
| `offline_input_filter.py` | 跑库前严格检查表头并隔离不合规 CSV |
| `analysis/` | 原始/PSD 特征、原因匹配、结论和报告数据 |
| `splitter.py`, `processor.py` | 文件分割和批处理 |

### commands

每个文件导出一个 `*_cmd` Click 命令。命令层负责：

- 校验必填参数和互斥选项。
- 通过 `RuleLoader` 解析规则。
- 调用 `core/` 完成业务操作。
- 使用 Rich 进度条与 `ResultCollector` 汇总结果。
- 将领域异常转换为中文、可执行的错误信息。

### api

`health_tools.api` 是对外稳定入口。请求对象使用冻结 dataclass，返回结构化结果；
`ExecutionContext` 提供进度与协作式取消。API 不依赖 Click 或 Rich，也不直接写终端。
接口的完整边界见 [Python API 架构](api_architecture.md)。

规则管理 API 合并用户和内置来源，只允许原子写入当前用户规则目录；配置 REPLACE 使用
revision 检测外部编辑冲突。离线资源目录 API 提供芯片、分类、版本、默认标记和 EXE
可用性，UI 不读取内部配置结构。

## 配置与规则查找

`config.py` 管理 `~/.ghealth_tools/config.yaml`、用户规则目录和离线算法工具目录。相对规则
名按以下顺序解析：

1. 配置的用户规则目录或 `~/.ghealth_tools/rules/<type>/`。
2. 包内 `src/health_tools/rules/<type>/`。
3. 未命中时保留原相对路径，由当前工作目录解析并在读取时报错。

绝对路径不经过用户/内置目录替换。芯片名会自动补 `.yaml` 并在 `chip/` 下查找。

## 主要数据流

```text
parse:    log -> ParseRule -> LogParser -> DataFrame -> ChipRule -> CSV
convert:  CSV -> ConvertRule -> DataConverter -> ChipRule -> CSV
check:    CSV -> ChipRule -> DataChecker -> check_report.csv -> optional sort
evaluate: CSV directory -> EvaluateRule -> BatchEvaluator -> reports
offline:  input -> preflight -> child task queue -> isolated raw outputs
          -> single-thread merge -> parallel PSD -> accuracy
analyze:  raw CSV -> check/evaluate -> feature diagnosis
          -> optional copied offline run -> PSD evidence -> Markdown/PPT
```

`analyze` 还有一层明确的工作区状态机：`analysis_state.json` 记录 `discover`、`check`、`raw`、`evaluate`、`offline`、`plot`、`diagnose`、`report`，每个阶段只有 `pending`、`running`、`completed`、`failed` 四种状态。`--resume` 只复用状态一致且产物仍有效的已完成阶段，`--no-resume` 遇到既有状态就拒绝继续，`--restart` 则清理分析目录内已归属的产物后重新开始。

分析输入也按路径角色分开：`--input` 只定义待分析源，`--check-report`、`--offline-result`、`--figure-dir` 是独立的复用输入。若输出目录嵌在输入目录内，源文件发现会自动排除输出子树，避免把历史分析产物再次纳入原始 CSV。

## 列展开

`utils/columns.py` 统一处理 `{start-end}` 范围。`CH{0-3}` 展开为 `CH0` 到 `CH3`，
`rawdata[{0-1}]` 展开为 `rawdata[0]`、`rawdata[1]`。方括号范围语法为旧规则兼容能力；
转换映射中 `[]` 通常表示字面量。

## 诊断优先级

`core/analysis/diagnosis.py` 会先按规则 `priority` 从高到低排序，再从上到下寻找第一个满足条件的原因。也就是说，当多个原因都能解释同一批特征时，数字更大的规则先赢；`origin=algorithm` 的原因还要求原始数据、参考数据和算法异常条件同时成立。

## 扩展原则

- 新业务逻辑写入小而独立的 `core` 单元，并先补测试。
- 用户可配置的数据结构放入规则，而不是硬编码在命令层。
- 批量命令复用进度、错误归类和汇总工具。
- 保持 Python 3.10 兼容、100 字符行宽和中文用户文本。
- 修改命令、规则字段或输出结构时，同步更新命令页、规则文档和变更记录。
