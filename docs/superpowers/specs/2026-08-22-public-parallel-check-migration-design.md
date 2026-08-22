# 公共并行框架与 check 迁移设计

## 背景与目标

当前仓库的并发实现分散在 `utils.parallel`、`check_operation` 和离线跑库模块中，主要使用线程池。对于包含 pandas、NumPy、编码检测和 Python 对象处理的文件级数据分析，增加线程数不能稳定利用多核，甚至会因为 GIL、磁盘竞争、内存带宽和底层数值库线程叠加而变慢。

本阶段建立跨平台公共并行框架，并将 `check` 作为首个 CPU/数据分析命令迁移到该框架。目标是：

- 在 Windows、Linux 和 macOS 上使用一致的公共 API；
- 为 I/O 型任务保留线程后端，为 CPU/数据分析任务提供进程后端；
- 限制在途任务数量，避免数百或上千个输入一次性创建 Future；
- 保持输入顺序、进度、取消、错误隔离和报告优先级行为；
- 不跨进程传输完整 DataFrame，避免 pickle 和内存复制成为新瓶颈；
- 让后续 `convert`、`classify`、`plot`、`evaluate` 可以只实现任务适配器即可迁移。

## 范围

### 本阶段包含

1. 公共并行执行协议和标准库线程/进程后端。
2. 有界提交、输入索引恢复、单任务错误封装、取消和进度回调。
3. 跨平台 worker 启动上下文：Windows 使用 `spawn`，非 Windows 默认使用安全的显式上下文；不依赖 fork 继承运行时状态。
4. `check` 单文件检查函数从嵌套闭包改为模块级可 pickle worker。
5. `check` 迁移到公共进程后端，并保留显式线程后端用于对照和 I/O 场景。
6. `check` 报告、`PRIMARY_RULES`、异常优先级、排序和分拣行为回归测试。
7. 合成数据和 2310 组真实数据的线程/进程基准。

### 本阶段不包含

- 不迁移 `offline` 的外部算法执行器；它保留自己的外部进程调度，只复用公共配置和结果语义。
- 不引入 Dask、Ray 或强制 joblib/loky 运行时依赖。
- 不改变任何检查规则、阈值、报告字段和异常优先级。
- 不把完整 DataFrame、线程锁、执行上下文或 Click 对象作为进程任务参数/返回值。

## 设计原则

### 1. 执行器与任务逻辑分离

公共层只负责调度，不了解 PPG、chip 或报告字段。命令层提供模块级 worker 和 reducer：

```python
result = run_parallel(
    tasks,
    worker=check_file_worker,
    config=ParallelConfig(backend="process", workers=4),
    context=execution_context,
)
```

`worker` 接收一个可 pickle 的任务输入，返回可 pickle 的轻量结果；主进程 reducer 再将结果转换为命令自己的报告对象或输出文件。

### 2. 后端

公共层提供两个后端：

- `thread`：`ThreadPoolExecutor`，适用于主要等待文件/网络/外部 I/O 的任务；
- `process`：`ProcessPoolExecutor`，适用于 CPU、pandas/NumPy 对象处理和需要绕过 GIL 的任务。

进程后端通过 `multiprocessing.get_context(...)` 获取上下文。默认上下文由平台决定：Windows 使用 `spawn`；非 Windows 也使用显式可配置上下文，默认不依赖父进程隐式继承。所有 worker 均必须定义在模块顶层，入口模块必须可导入。

### 3. 资源控制

`ParallelConfig` 包含：

- `backend`: `"thread"` 或 `"process"`；
- `workers`: 请求并发数；
- `max_workers`: 安全上限；
- `pending_factor`: 在途窗口倍数，默认 2；
- `mp_start_method`: 可选启动上下文；
- `inner_threads`: 子进程内部数值库线程数，默认 1；
- `shutdown_timeout`: 取消时的等待策略。

有效 worker 数由请求值、任务数、上限和平台资源共同限制。逻辑处理器数量只作为候选上限，不直接作为默认并发数。对于进程后端，worker 初始化时设置 `OMP_NUM_THREADS`、`MKL_NUM_THREADS`、`OPENBLAS_NUM_THREADS` 等环境变量（仅当调用方未显式设置时），避免进程数与 BLAS 线程数相乘造成过量竞争。

### 4. 有界调度

公共调度器只保持 `effective_workers * pending_factor` 个在途任务。任务完成后才补交新任务。这样可以限制 Future、序列化缓冲和任务结果的内存占用，并让取消能够停止尚未提交的任务。

调度器必须：

- 按完成顺序触发进度事件；
- 保存输入索引；
- 以输入索引排序后返回结果；
- 将单任务异常封装为 `TaskResult(status="failed", error=...)`，不阻塞其他任务；
- 批量取消时停止补交、取消尚未开始的 Future，并返回已完成的部分结果；
- 不在 worker 中调用 UI、Click、Rich 或用户回调。

### 5. 轻量跨进程协议

公共数据类型使用 `dataclass(frozen=True)` 或基础容器，只允许 `Path`、字符串、数字、布尔值、元组、列表、字典和可明确 pickle 的业务结果。禁止把以下对象放入进程任务输入/输出：

- pandas `DataFrame` 或大型 NumPy 数组；
- `ExecutionContext`、线程锁、Future、Executor；
- Click context、Rich progress 对象；
- 打开的文件句柄、logger handler 和闭包。

`check` worker 只接收文件路径和不可变检查配置。它在子进程内加载规则、读取 CSV、构造 DataFrame 并完成单文件检查，然后返回：状态、路径、芯片、序列化后的检查结果、ACC/IPD/金标明细的临时文件路径或轻量记录。主进程统一写主报告和精简报告。

### 6. 结果和异常优先级

`check` 的主进程汇总顺序保持输入文件顺序。`PRIMARY_RULES` 继续作为主要异常项和分拣类别的唯一事实来源，不在 worker 中提前决定目录分类。worker 只返回原始 `FileCheckReport` 所需的结构化检查结果；报告行和分类由现有主线程逻辑生成。

文件级失败继续转换为 `ItemStatus.FAIL`，包括稳定的原因和详情。报告识别、忽略 check 报告、空文件和规则不匹配行为保持不变。

## check 迁移结构

### 公共层

- `src/health_tools/utils/parallel.py`：执行器配置、任务结果、统一有界调度入口。
- `src/health_tools/utils/parallel_worker.py`：跨平台 worker 初始化和模块级调用包装。

### check 层

- `src/health_tools/api/check_parallel.py`：`CheckFileTask`、`CheckFileResult`、模块级 `check_file_worker`，负责把 `CheckRequest` 转换为可 pickle 配置并执行单文件检查。
- `src/health_tools/api/check_operation.py`：保留输入发现、取消/进度、结果归总、报告写入和 `PRIMARY_RULES`；移除嵌套 `check_one` 调度逻辑，改用公共 `run_parallel`。
- `src/health_tools/api/models.py`：必要时增加不可变的并行配置字段，但不破坏已有 `CheckRequest` 构造兼容性。

worker 不直接复用 `run_check`，避免递归进入批量调度；它复用当前文件级检查上下文和 `DataChecker` 逻辑。输出明细如果较大，worker 写入唯一临时文件并只返回路径，主进程在确认成功后纳入 artifacts。

## 错误、取消和进度

- 初始化失败：公共层转换为批量级 `OperationError`，包含 backend、启动方式和原始异常。
- 单任务失败：封装为 `TaskResult.failed`，继续处理其他文件。
- 用户取消：主进程停止提交新任务，取消可取消 Future；已运行任务在文件边界完成后回收；通过 `OperationCancelled.partial_result` 返回已完成结果。
- 回调异常：不在 worker 中执行；主进程回调失败按现有 `CallbackError` 处理。
- 任何取消或批量级异常都不生成不完整主报告。
- 进度事件的 `current` 使用输入文件路径，`completed/total` 仍按文件数统计。

## 测试策略

### 公共框架测试

- 线程和进程后端均能保持输入顺序；
- 在途窗口不超过 `effective_workers * pending_factor`；
- 单任务异常不阻塞其他任务；
- 取消停止新提交并返回部分结果；
- Windows `spawn` 和非 Windows 可选上下文都能运行模块级 worker；
- 不可 pickle 的闭包被明确报告为配置错误；
- 内部线程环境变量不覆盖调用方已有设置。

### check 回归测试

- `workers=1`、线程后端和进程后端的报告行、状态、主要异常项、分拣类别一致；
- `PRIMARY_RULES` 顺序完全不变；
- 空输入、空文件、规则不匹配、失败文件、check 报告过滤和取消行为一致；
- ACC、时间戳、采样、准确度和证据文件内容保持一致；
- 进程 worker 不返回 DataFrame；
- 2310 组真实数据能够完成并生成相同数量的报告行。

### 性能验收

对 100、500、1000 个合成文件和真实 2310 组数据比较：

- `thread` 与 `process` 的总耗时、吞吐和峰值内存；
- workers 为 1、2、4、8、物理核心数时的变化；
- CSV 读取、规则加载、编码检测、采样和 ACC 准备调用次数；
- 进程启动开销及任务粒度影响。

不把绝对耗时设为脆弱的 CI 门槛；发布默认后端和默认 worker 前，必须记录同一机器上的中位数结果，并确认报告内容一致。

## 分阶段交付

1. 公共并行协议和测试，先不改变现有命令。
2. `check` 迁移到公共框架，默认提供显式 `process` 后端并保留 `thread` 对照开关。
3. 真实数据和合成数据基准，确定默认后端/worker 和文档。
4. 后续命令按任务类型逐个迁移；每个命令独立提交行为回归和性能基准。

