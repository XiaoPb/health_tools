# 公共并行框架与 check 迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立跨 Windows/Linux/macOS 的公共线程/进程并行框架，并将 `check` 的文件级检查迁移到进程后端，同时保持报告顺序、`PRIMARY_RULES` 异常优先级、取消和错误语义不变。

**Architecture:** 在 `utils.parallel` 中提供统一的 `ParallelConfig`、轻量任务结果、跨平台 executor 工厂和有界调度器。命令层只提供模块级可 pickle worker 与轻量输入/输出；主进程负责进度、取消、顺序恢复和文件写入。`check` 首先提取模块级单文件 worker，worker 在子进程内读取 CSV 并生成检查结果，主进程统一生成报告。

**Tech Stack:** Python 3.9+、`concurrent.futures`、`multiprocessing`、pandas、NumPy、pytest、现有 `ExecutionContext`/`OperationCancelled` API；第一阶段不新增生产运行时依赖。

---

## 文件边界

### 公共框架

- Create: `src/health_tools/utils/parallel.py`：公共配置、任务结果、executor 工厂、有界调度入口；保留现有兼容包装。
- Create: `src/health_tools/utils/parallel_worker.py`：进程 initializer、内部线程环境变量设置和模块级 worker 包装；不得在模块导入阶段加载 pandas/NumPy。
- Modify: `src/health_tools/utils/__init__.py`：惰性导出新的公共类型和 `run_parallel`。
- Create: `tests/support_parallel_workers.py`：可被 Windows `spawn` 导入的顶层测试 worker。
- Create: `tests/test_parallel.py`：公共框架顺序、窗口、错误、取消、跨平台 backend 测试。
- Modify: `tests/test_progress.py`：锁定旧兼容包装仍保持输入顺序和异常返回格式。

### check 迁移

- Create: `src/health_tools/api/check_parallel.py`：`CheckFileTask`、`CheckWorkerConfig`、`CheckFileResult` 和模块级 `check_file_worker`。
- Modify: `src/health_tools/api/models.py:522-561`：为 `CheckRequest` 增加 `parallel_backend` 字段。
- Modify: `src/health_tools/commands/check.py`：增加 `--parallel-backend {process,thread}`。
- Modify: `src/health_tools/api/check_operation.py:931-1317`：改用公共 `run_parallel`，保留输入发现、取消、报告归总和 `PRIMARY_RULES`。
- Modify: `docs/cmd_check.md`：记录 backend、workers、窗口、顺序和取消语义。
- Modify: `tests/test_check_performance.py`、`tests/test_api_contract.py`、`tests/test_cli.py`、`tests/test_check_sort.py`：增加迁移回归。
- Modify: `tests/benchmarks/bench_check_performance.py`：增加 backend 对比。
- Create: `docs/parallel.md`：公共框架使用约定和后续命令迁移模板。

### Task 1: 建立公共并行框架的失败测试

**Files:** `tests/support_parallel_workers.py`, `tests/test_parallel.py`

- [ ] **Step 1: 写可被 spawn 导入的顶层测试 worker**

```python
from __future__ import annotations
import time

def add_one(value: int) -> int:
    return value + 1

def fail_on_three(value: int) -> int:
    if value == 3:
        raise ValueError("three is invalid")
    return value

def sleep_and_return(value: float) -> float:
    time.sleep(value)
    return value
```

- [ ] **Step 2: 写顺序、错误、窗口和取消红测试**

测试 `run_parallel` 和 `ParallelConfig`：进程 backend 保持 `[3, 1, 2]` 的输入顺序；单任务异常返回 `status="failed"` 且不阻塞其他任务；fake executor 统计在途任务不超过 `workers * pending_factor`；取消回调停止新提交并返回已完成结果。fake executor 必须实现 `submit`、`shutdown` 和 Future 的 `result/cancel/done`，不得用 wall-clock 断言。

- [ ] **Step 3: 写配置和环境测试**

覆盖非法 backend、`workers < 1`、`pending_factor < 1`、`inner_threads < 1`；覆盖用户已有 `OMP_NUM_THREADS`/`MKL_NUM_THREADS` 不被覆盖，以及 Windows `spawn` 和 POSIX 可用启动上下文。

- [ ] **Step 4: 运行红测试**

```powershell
python -c "import health_tools; print(health_tools.__file__)"
pytest tests/test_parallel.py -q
```

预期因公共 API 尚不存在而失败，但不得出现测试收集错误。

- [ ] **Step 5: 提交测试**

```powershell
git add tests/support_parallel_workers.py tests/test_parallel.py
git commit -m "test: define public parallel execution contract" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 2: 实现公共配置、结果协议和跨平台 executor

**Files:** `src/health_tools/utils/parallel.py`, `src/health_tools/utils/parallel_worker.py`, `src/health_tools/utils/__init__.py`, `tests/test_parallel.py`

- [ ] **Step 1: 定义不可变类型**

实现：

```python
@dataclass(frozen=True)
class ParallelConfig:
    backend: Literal["thread", "process"] = "thread"
    workers: Optional[int] = None
    max_workers: Optional[int] = None
    pending_factor: int = 2
    mp_start_method: Optional[str] = None
    inner_threads: int = 1

@dataclass(frozen=True)
class ParallelResult(Generic[T]):
    index: int
    value: Optional[T]
    status: Literal["ok", "failed", "cancelled"]
    error: Optional[str] = None
    duration: float = 0.0

@dataclass(frozen=True)
class ParallelBatch(Generic[T]):
    results: Tuple[ParallelResult[T], ...]
    cancelled: bool = False
```

`ParallelConfig.__post_init__` 拒绝非法值；`workers=None` 交给平台资源策略计算。

- [ ] **Step 2: 实现 worker 数和启动上下文策略**

有效 worker 不超过任务数；优先使用物理核心数，无法检测时回退 `os.cpu_count()`；默认上限为 32。Windows 默认 `spawn`；POSIX 优先 `forkserver`（可用时），否则 `spawn`；显式 `mp_start_method` 严格执行。

- [ ] **Step 3: 实现进程 initializer**

在 `parallel_worker.py` 实现 `initialize_worker(inner_threads)`，用 `os.environ.setdefault` 设置 `OMP_NUM_THREADS`、`MKL_NUM_THREADS`、`OPENBLAS_NUM_THREADS`。该模块顶层不得导入 pandas、NumPy 或业务模块。

- [ ] **Step 4: 实现 executor 工厂和公共导出**

线程 backend 使用 `ThreadPoolExecutor`；进程 backend 使用带 `mp_context`、`initializer` 和 `initargs` 的 `ProcessPoolExecutor`。不支持指定 initializer 时抛出带 backend/平台信息的 `RuntimeError`，不得静默降级到线程。

- [ ] **Step 5: 运行基础测试并提交**

```powershell
pytest tests/test_parallel.py -q
git add src/health_tools/utils/parallel.py src/health_tools/utils/parallel_worker.py src/health_tools/utils/__init__.py tests/test_parallel.py
git commit -m "feat: add cross-platform parallel executor backends" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 3: 实现有界调度、取消、进度和旧 API 兼容

**Files:** `src/health_tools/utils/parallel.py`, `tests/test_parallel.py`, `tests/test_progress.py`

- [ ] **Step 1: 实现 `run_parallel`**

签名固定为：

```python
def run_parallel(
    tasks: Sequence[T],
    worker: Callable[[T], R],
    *,
    config: ParallelConfig,
    is_cancelled: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[int, int, T], None]] = None,
) -> ParallelBatch[R]
```

按 `enumerate(tasks)` 产生索引，初始最多提交 `effective_workers * pending_factor` 个 Future；每批完成后补交；结果按索引排序。

- [ ] **Step 2: 封装异常和耗时**

捕获单任务 `Exception` 为 `ParallelResult(status="failed", error=error_text)`，不阻塞其他任务；`BaseException` 进入统一 shutdown 分支。每项用 `time.perf_counter()` 记录耗时。

- [ ] **Step 3: 实现取消和进度**

在初始提交、等待前后、补交前检查取消；取消后停止读任务迭代器，取消未开始 Future，返回 `ParallelBatch.cancelled=True`。只在主进程执行 `on_progress`；回调异常向调用方传播。

- [ ] **Step 4: 保持旧包装**

让 `parallel_process`、`parallel_process_with_index`、`batch_process` 调用 thread backend 的 `run_parallel`，保持既有错误字典和输入顺序返回格式。

- [ ] **Step 5: 验证并提交**

```powershell
pytest tests/test_parallel.py tests/test_progress.py -q
git add src/health_tools/utils/parallel.py tests/test_parallel.py tests/test_progress.py
git commit -m "feat: add bounded cancellation-aware parallel scheduling" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 4: 定义 check 的 pickle-safe 任务和结果

**Files:** `src/health_tools/api/check_parallel.py`, `src/health_tools/api/models.py:522-561`, `tests/test_check_performance.py`

- [ ] **Step 1: 增加 `CheckRequest.parallel_backend`**

在 frozen dataclass 末尾增加 `parallel_backend: Literal["process", "thread"] = "process"`，验证错误文本固定为 `parallel_backend 必须是 process 或 thread`，不破坏既有关键字构造。

- [ ] **Step 2: 定义 `CheckWorkerConfig` 和 `CheckFileTask`**

配置只含路径、字符串、数字、布尔值、元组和可 pickle 的 mapping；不得包含 `ExecutionContext`、回调、compiled regex、Executor 或打开文件。任务包含稳定 `index`、`path` 和配置。

- [ ] **Step 3: 定义轻量 `CheckFileResult`**

返回 `index`、`path`、`ItemResult`、可选 `FileCheckReport`、可选 `AccAnomalyReport`，以及 IPD/evidence 临时 CSV 的 `Path`。DataFrame 只能在 worker 内存在，不能出现在返回对象的字段中。

- [ ] **Step 4: 写序列化红测试**

使用最小 GH3036 CSV fixture 验证 `pickle.loads(pickle.dumps(task)) == task`；调用 worker 后递归检查 dataclass 字段，断言不包含 pandas `DataFrame`；验证临时文件按任务 index 唯一命名。

- [ ] **Step 5: 提交任务协议**

```powershell
git add src/health_tools/api/models.py tests/test_check_performance.py
git commit -m "test: define pickle-safe check worker contract" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 5: 提取模块级 check 单文件 worker

**Files:** `src/health_tools/api/check_parallel.py`, `src/health_tools/api/check_operation.py:990-1207`, `tests/test_check_performance.py`, `tests/test_check_rules.py`, `tests/test_acc_checker.py`

- [ ] **Step 1: 提取 `_check_file_impl(task)`**

按现有顺序迁移嵌套 `check_one` 的纯文件逻辑：识别 chip、加载规则、CSV 读取、空文件/规则不匹配、`_FileCheckContext`、range/frame/center/agc、timestamp、reference/accuracy sampling、IPD、ACC、accuracy、evidence。不得改变检查项顺序、状态和摘要。

- [ ] **Step 2: 采用局部重依赖导入**

`check_parallel.py` 顶层只导入 dataclass、Path、typing 和轻量 API models；`check_file_worker` 内局部导入 pandas、NumPy、RuleLoader、CSVHandler、DataChecker 及 `check_operation` 私有 helper，确保 initializer 先设置内部线程数。

- [ ] **Step 3: 将 DataFrame 明细写入临时目录**

worker 用 `_write_worker_detail(frame, config.temp_dir / f"{index:08d}" / name)` 写 IPD/evidence，编码 UTF-8-SIG、`index=False`；目标已存在时抛出任务失败。返回临时 `Path`，不返回 DataFrame。

- [ ] **Step 4: 删除嵌套 worker 实现**

`check_operation.py` 保留 `_FileCheckContext`、报告辅助函数、`_save_report` 和 `PRIMARY_RULES`；删除嵌套 `check_one`，防止线程/进程维护两套逻辑。

- [ ] **Step 5: 运行单文件回归**

```powershell
pytest tests/test_check_rules.py tests/test_acc_checker.py tests/test_check_performance.py -q
```

预期现有结果、ACC 字段、时间戳/采样调用次数和失败详情保持一致；提取差异必须在此阶段解决。

- [ ] **Step 6: 提交 worker 提取**

```powershell
git add src/health_tools/api/check_parallel.py src/health_tools/api/check_operation.py tests/test_check_performance.py tests/test_check_rules.py tests/test_acc_checker.py
git commit -m "refactor: extract pickle-safe check file worker" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 6: 将 `run_check` 迁移到公共 backend

**Files:** `src/health_tools/api/check_operation.py:931-1317`, `src/health_tools/commands/check.py`, `tests/test_check_performance.py`, `tests/test_api_contract.py`, `tests/test_cli.py`

- [ ] **Step 1: 增加 CLI backend 选项**

增加 `--parallel-backend`，choices 为 `process/thread`，默认 `process`，并传入 `CheckRequest.parallel_backend`；旧命令不传该选项时行为只改变执行后端，不改变检查语义。

- [ ] **Step 2: 构造 task 和临时目录**

在普通模式完成输入发现、checks 校验和参数校验后创建唯一临时目录；按稳定输入 index 构造 `CheckFileTask`。空文件列表不创建 executor，保持原有空结果。

- [ ] **Step 3: 调用公共调度器**

替换原始 `ThreadPoolExecutor`/`pending` 代码：

```python
batch = run_parallel(
    tasks,
    check_file_worker,
    config=ParallelConfig(
        backend=request.parallel_backend,
        workers=request.workers,
        max_workers=32,
        pending_factor=2,
    ),
    is_cancelled=lambda: ctx.is_cancelled() if ctx.is_cancelled else False,
    on_progress=emit_check_progress,
)
```

`emit_check_progress` 只在主进程调用 `ctx.emit`，并保留 `ctx.check_cancelled` 的 partial result 检查。

- [ ] **Step 4: 按 index 汇总并移动明细**

遍历 `ParallelBatch.results` 的输入顺序，保留 `_is_failed_check_report(item, path)` 的过滤时机；填充 `items`、`reports`、`acc_reports`、`ipd_details`、`reference_details`。临时明细移动到原有 artifacts 目标后才加入 artifacts。

- [ ] **Step 5: 保持取消和报告语义**

取消或批量异常时清理临时目录并抛出带 partial batch 的 `OperationCancelled`；全部文件回收后才调用 `_save_report` 和 `_save_compact_report`。不得修改 `PRIMARY_RULES`、`_primary_match`、`_sort_category`。

- [ ] **Step 6: 增加线程/进程一致性测试**

同一最小输入分别运行 `parallel_backend="process"`、`"thread"`，比较报告行、状态、主要异常项、分拣类别、IPD/evidence 文件内容；另测 workers=1 与 workers=4 的输入顺序、失败文件、空文件和 check 报告过滤。

- [ ] **Step 7: 提交迁移**

```powershell
git add src/health_tools/api/check_operation.py src/health_tools/commands/check.py tests/test_check_performance.py tests/test_api_contract.py tests/test_cli.py
git commit -m "feat: migrate check to public process parallel backend" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 7: 编写公共和 check 文档

**Files:** `docs/parallel.md`, `docs/cmd_check.md`, `tests/test_documentation.py`

- [ ] **Step 1: 写公共迁移模板**

文档提供模块级 worker、轻量 pickle task/result、主进程 reducer 的完整模板，并说明 `ParallelConfig`、backend、workers、窗口、取消、内部线程限制和后续命令迁移步骤。

- [ ] **Step 2: 更新 check 命令页**

记录 `--parallel-backend`、`--workers` 默认值/上限、process/thread 选择建议、报告顺序保持、取消行为和“更多 worker 不保证线性加速”。明确 `PRIMARY_RULES` 是异常显示和分拣的优先级事实来源。

- [ ] **Step 3: 增加文档测试并提交**

`tests/test_documentation.py` 断言公共文档包含 `ParallelConfig`、`run_parallel`、`process`、`thread`，check 文档包含 `--parallel-backend` 和优先级语义。

```powershell
git add -f docs/parallel.md docs/cmd_check.md
git add tests/test_documentation.py
git commit -m "docs: document public parallel framework and check backend" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 8: 扩展 benchmark 并确定资源策略

**Files:** `tests/benchmarks/bench_check_performance.py`, `tests/test_check_performance.py`, `docs/parallel.md`

- [ ] **Step 1: 支持 backend 参数**

扩展命令：

```powershell
python tests/benchmarks/bench_check_performance.py --files 100,500,1000 --workers 1,2,4,8 --backends thread,process
```

输出 `backend`、`workers`、耗时、峰值 RSS、CSV/时间戳/采样/ACC 调用计数和报告校验状态；始终写入临时目录。

- [ ] **Step 2: 增加报告等价性校验**

分别保存 thread/process 报告，按文件名和主要异常项排序比较；差异时返回非零退出码，不能只比较耗时。

- [ ] **Step 3: 运行合成 smoke benchmark**

```powershell
python tests/benchmarks/bench_check_performance.py --files 10 --workers 1,2 --backends thread,process
```

预期两种 backend 都完成且报告等价。

- [ ] **Step 4: 运行真实 2310 组数据**

在 `E:\Code\Python\health_tools\test_data\data_gh3036_offline\fail_category_check_input_20260821` 上以 thread/process、workers 1/2/4/8 交替运行，每种配置至少两次，输出到 `debug/real2310_parallel_20260822`。记录成功/跳过/失败、耗时、峰值内存和报告行等价性，不覆盖既有结果。

- [ ] **Step 5: 根据中位数记录默认策略**

只有完成真实和合成数据的语义等价校验后，才确定推荐 worker 上限；不因单次机器结果修改检查规则或优先级。

- [ ] **Step 6: 提交 benchmark**

```powershell
git add tests/benchmarks/bench_check_performance.py tests/test_check_performance.py docs/parallel.md
git commit -m "test: benchmark thread and process check backends" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 9: 全量验证和收尾

**Files:** 仅在验证发现回归时修改明确文件。

- [ ] **Step 1: 验证导入来源**

```powershell
python -c "import health_tools; print(health_tools.__file__)"
```

预期路径以 `E:\Code\Python\health_tools\src\health_tools\__init__.py` 开头。

- [ ] **Step 2: 运行专项测试**

```powershell
pytest tests/test_parallel.py tests/test_progress.py tests/test_check_performance.py tests/test_check_rules.py tests/test_acc_checker.py tests/test_check_accuracy.py tests/test_check_sampling.py tests/test_check_sort.py tests/test_reference_checker.py tests/test_api_contract.py tests/test_cli.py tests/test_documentation.py -q
```

若 Windows 环境出现 pytest Qt 插件错误，按项目约定使用 `pytest -p no:pytest-qt` 重跑并记录。

- [ ] **Step 3: 运行质量检查**

```powershell
black --check src/ tests/
ruff check src/ tests/
mypy src/
```

三个命令必须返回 0。

- [ ] **Step 4: 运行全量测试**

```powershell
pytest -q
```

记录通过数量和既有 NumPy warning，不把环境 warning 当业务失败。

- [ ] **Step 5: 检查 diff、临时文件和提交元数据**

```powershell
git diff --check
git status --short --branch
git log --oneline --decorate --max-count=12
```

确认无大体积 benchmark 数据、临时 CSV、进程日志或未跟踪数据库；每个提交都包含 `Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>`。

- [ ] **Step 6: 处理验证发现的真实回归**

如果专项测试、质量检查或全量测试发现回归，先针对失败测试完成最小修复，再重新运行对应命令、专项测试和全量测试；只有验证结果恢复后，才提交实际修改过的文件，并使用 `fix: address parallel check verification regressions` 提交说明。若没有回归，不创建额外提交。

---

## 计划自检

- 公共线程/进程后端、跨平台启动、有界调度、资源限制、轻量序列化、取消、进度和错误隔离由 Task 1-3 覆盖。
- `check` 的模块级 worker、临时明细、主进程报告、`PRIMARY_RULES`、CLI backend 和结果一致性由 Task 4-6 覆盖。
- 文档、基准、真实 2310 组数据验收和全量质量检查由 Task 7-9 覆盖。
- 新增 API 先在 Task 2-3 定义，Task 6 才使用；类型和字段命名一致。
- 计划没有保留实现占位符；`run_parallel` 代码块只展示完整参数签名，所有测试和实现步骤均要求写入可执行代码。
