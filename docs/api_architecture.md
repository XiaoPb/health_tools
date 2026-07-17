# Python API 架构

`health_tools.api` 是 GHealth Tools 唯一承诺稳定的 Python 调用入口。独立 UI、自动化脚本和
其他应用不应导入 `commands`、`core`、`rules` 或 `utils`；这些模块属于内部实现，可以在不
改变公共 API 的情况下调整。

## 分层与依赖

```text
独立 UI / Python 脚本
          |
          v
health_tools.api          请求、校验、编排、结果、进度与取消
          |
          +---- rules / config
          v
core / models / utils     算法、规则模型和文件工具
```

API 不依赖 Click、Rich 或任何 UI 框架，也不向标准输出写内容。CLI 负责把命令行参数转换成
请求对象，并把结构化结果呈现到终端。

## 请求与结果

每个能力由一个冻结的请求 dataclass 和一个同步 `run_*` 函数组成。路径字段使用 `Path`，
可选值使用枚举或明确的字符串约束。请求对象不包含 `verbose`、终端日志级别等展示选项。

文件批处理返回 `BatchResult`：

- `items`：每个输入的 `ItemResult`，状态为 `OK`、`SKIP`、`WARN` 或 `FAIL`。
- `artifacts`：本次调用生成的文件或目录。
- `ok_count`、`skip_count`、`warn_count`、`fail_count`：聚合计数。

信息、规则验证、规则目录、配置、质量检查和离线流程返回专用结果类型。结果对象不可变，调用方可以
安全地在线程之间传递。

规则目录将用户和内置来源建模为不可变 variant。列表默认返回当前有效来源，读取可显式选择
`user` 或 `builtin`。保存只能写当前用户规则目录，文件名和解析后路径均需通过边界检查。

## 错误模型

所有公共异常继承 `GHealthError`：

| 异常 | 含义 |
|---|---|
| `RequestValidationError` | 参数组合、路径或枚举值无效 |
| `RuleLoadError` | 芯片、解析、转换、分类或评估规则无法加载 |
| `OperationError` | 输出目录、外部工具或整个任务执行失败 |
| `CallbackError` | 调用方的进度或取消回调抛出异常 |
| `OperationCancelled` | 任务在安全检查点被取消 |

单个文件失败写入 `BatchResult` 并继续处理；无法开始或无法继续整个任务时抛异常。

## 进度与取消

批处理和其他长任务的 `run_*` 函数接受可选 `ExecutionContext`。`on_progress` 接收
`ProgressEvent`，字段包括
操作名、阶段、已完成数、总数、消息和当前输入。相同阶段的 `completed` 单调递增。

`is_cancelled` 应快速返回布尔值，不应阻塞。API 在文件之间和离线流程各阶段检查取消。
取消后抛出 `OperationCancelled`，其 `stage` 和 `partial_result` 可用于刷新界面。已完成输出
保留，不执行事务回滚。

离线外部程序使用可轮询进程。收到取消后会终止由本次 API 调用启动的进程，再抛出取消
异常。外部程序已经写入的文件仍会保留。

## 线程模型与副作用

API 是同步接口，不创建面向调用方的任务 ID。UI 应自行在线程池或任务队列中调用。不同
输出目录的任务可以并行；写入同一目录、修改全局配置或移动同一批源文件的任务不得并行。

以下调用包含显式副作用：

- `ClassifyRequest(mode="move")` 移动源文件。
- `CheckRequest(sort_report=True)` 按报告移动源文件。
- 正常 `run_offline` 会预检并移动不符合芯片表头的 CSV。
- `run_config` 修改用户目录下的全局配置。
- `run_save_rule` 在用户规则目录创建或替换 YAML；内置规则始终只读。

规则和配置文档的 revision 是原始 UTF-8 字节的 SHA-256。保存时在同一进程写锁内重新检查
当前 revision，候选内容校验通过后使用同目录临时文件和原子替换落盘。该机制用于发现 UI
读取后发生的外部修改；冲突时不写入目标文件。规则目录、规则读取和离线资源查询是短时同步
操作，不接收 `ExecutionContext`。

## 兼容策略

公共函数名、请求字段和结果字段属于兼容承诺。新增可选字段必须提供默认值；删除字段、修改
字段含义或改变异常类别属于破坏性变更。内部模块和私有下划线符号不在兼容范围内。

补丁版本可以新增带默认值的请求/结果字段、新的枚举成员和新函数。独立 UI 应精确依赖已发布
版本，不直接安装仓库源码；需要新增字段时先提升其最低依赖版本。
