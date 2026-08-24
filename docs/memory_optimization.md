# 大型 CSV 内存优化指南

本文总结大型 PPG CSV 在 GHealth Tools 中的读取、检查和批量处理经验，供后续
`convert`、`plot`、`evaluate`、`analyze`、`factory` 等命令复用。

## 1. 问题表现

大型 CSV 读取失败时，错误不一定表示文件格式真的错误。常见表现包括：

- `ParserError: Error tokenizing data. C error: out of memory`
- `MemoryError: Unable to allocate ... for an array`
- 同一份数据重复处理时，有的文件成功、有的文件失败

这类错误通常发生在 pandas C Parser 或 NumPy 创建临时数组时。多个大文件并行读取会
同时保留多个 DataFrame、解析缓冲区和检查中间数组，内存峰值可能远高于最终
DataFrame 的 `memory_usage()`。

因此应同时控制：

1. 同时读取的文件数。
2. 每个文件的列数和列类型。
3. 检查过程中的临时数组和缓存生命周期。

## 2. 当前已落地方案

### 2.1 默认单线程

大型文件命令默认使用单线程；只有显式指定 `--workers N` 时才启用文件级并行。

以 `check` 为例：

```bash
# 稳定内存占用，适合大型 CSV
ghealth_tool check -i ./data -c gh3036 --workers 1

# 确认内存充足后再提高并行度
ghealth_tool check -i ./data -c gh3036 --workers 4
```

并行度不是越高越好。每个任务都可能同时持有完整 DataFrame、数值化列、时间戳分析
结果和报告对象；应以进程峰值 RSS 为依据逐步调大，而不是只比较耗时。

### 2.2 整型列降为 `int32`

`src/health_tools/utils/csv_handler.py` 中的 `_downcast_integer_columns()` 会在不改变
数值范围的前提下，将可安全表示的整型列转换为 `int32`。

适用条件：

- 列确实是 pandas 整型列。
- 最小值和最大值都在 `int32` 范围内。
- 不对浮点列强制转换，避免改变小数语义。

读取规则已声明的整型 CSV 列也会优先使用 `np.int32` dtype。若列可能包含超过
`int32` 范围的计数器、时间戳或原始值，应保留更宽类型。

### 2.3 只读取需要保留的列

`CSVHandler.read()` 支持：

```python
info, frame = CSVHandler(chip_rule).read(
    path,
    trim_trailing_zero=True,
    protected_columns=["FRAME_ID", "ACCX", "ACCY", "ACCZ", "TimeStamp"],
)
```

实现流程是：

1. 读取少量样本，识别编号列族及需要删除的尾列。
2. 使用 pandas `usecols` 进行正式读取。
3. 对最终 DataFrame 做整型降级。

不要先完整读取 DataFrame 再执行 `drop()`：那样峰值已经发生，删除列只能降低后续
常驻内存，不能降低解析阶段峰值。

## 3. 500 行尾部裁剪策略

当前 `check` 使用 `TRAILING_ZERO_SCAN_ROWS = 500`，只扫描数据区前 500 行判断编号列族
的最后有效通道。

### 3.1 列族规则

列名末尾带数字的列会按前缀分组，例如：

- `ALGO_RESULT0..N`
- `AGC_INFO_CH0..N`
- `Rawdata0..N`
- `Ipd0..N`
- `REF_RESULT0..N`

每个列族保留从起始编号到前 500 行内最后一个非零通道的全部列。中间即使全零也
保留；最后有效编号之后的尾列删除。

例如：

```text
ALGO_RESULT0: 有数据
ALGO_RESULT4: 全零
ALGO_RESULT6: 有数据
ALGO_RESULT7: 前 500 行全零
```

结果是保留 `ALGO_RESULT0..6`，删除 `ALGO_RESULT7`。如果 `ALGO_RESULT7` 只在第 501
行以后出现非零值，也会被当作异常尾列删除。

### 3.2 必须保护的列

尾列裁剪只适合结果或通道列，以下列必须显式保护：

- 帧号：`FRAME_ID` 或规则指定帧列。
- ACC：`ACCX`、`ACCY`、`ACCZ` 或规则指定列。
- 时间戳。
- 心率、血氧金标和准确度参考列。
- 准确度计算所需的 Online/Comp/Ref 列。

保护列不参与尾列删除，即使前 500 行全零也不能因为内存优化而丢失。

### 3.3 语义限制

500 行是针对当前检查场景的工程启发式，不是通用数据清洗规则。以下场景不要直接
复用：

- 有效信号可能在前 500 行之后才开始。
- 列的零值本身具有业务含义，不能代表“未使用通道”。
- 后续算法需要完整的尾部通道历史。
- 数据文件很短但有效值位于最后几行，且列族尾部不能视为异常。

如果命令必须保证完整数据语义，应只使用 dtype、usecols 白名单或分块处理，不应使用
500 行尾部裁剪。

## 4. 被删除检查列的后续处理

列裁剪后，规则中声明的 `Rawdata`/`Ipd` 列可能已经不在 DataFrame 中。后续代码不能
简单把“不在 DataFrame”当成“规则缺列”。当前 `check` 的做法是：

1. `CSVHandler.excluded_columns` 记录实际删除的列名。
2. `_FileCheckContext` 分别记录被删除的 `excluded_zero_data_columns` 和
   `excluded_zero_ipd_columns`。
3. `_rule_mismatch()` 将这些列视为已跳过的全零预留通道，不报告结构缺失。
4. 范围、居中和 Ipd 转换检查在摘要中报告跳过数量。

其他命令如果采用列裁剪，也必须在自己的上下文中区分：

- 原文件没有该列：真实缺列，应报告错误或跳过。
- 原文件有该列但被优化裁剪：已知被跳过列，应保留可解释的跳过状态。

## 5. 生命周期与释放

单文件处理完成后应尽快释放大对象：

```python
del frame
del numeric_cache
gc.collect()
```

更重要的是解除容器和闭包对 DataFrame 的引用。仅调用 `gc.collect()` 不能释放仍被
缓存、Future、报告对象或异常 traceback 引用的对象。

建议每个文件任务遵循：

1. 读取并完成当前文件的全部检查。
2. 生成轻量结果，避免把完整 DataFrame 放入汇总对象。
3. 清空数值化列、采样位置、时间戳分析等文件级缓存。
4. 删除 DataFrame 和临时数组。
5. 再开始下一个文件或允许线程槽位继续执行。

## 6. 迁移其他命令的步骤

### 第一步：确认数据语义

列出命令真正需要的列，并区分：

- 必须完整保留的列。
- 可以用 `usecols` 白名单读取的列。
- 只用于输出、可延迟读取的列。
- 可证明为未使用尾通道的列。

不要依据列名猜测业务含义；优先使用 chip/command 规则和现有列解析函数。

### 第二步：降低单文件读取成本

优先级建议：

1. 使用 `usecols` 白名单，避免无用列进入 DataFrame。
2. 使用规则提供的 dtype，数值范围允许时降为 `int32`。
3. 对超大文件使用分块读取，并在块内完成聚合，避免拼接完整副本。
4. 只有确认“前 500 行可代表通道有效性”时，才启用尾列裁剪。

### 第三步：控制并行度

为命令提供明确的 `workers=1` 安全默认值，保留显式并行能力。调度时使用有界任务
窗口，不要一次性为目录中每个文件创建 Future。

### 第四步：验证结果和峰值

至少记录以下指标：

- 文件大小、行数、原始列数和保留列数。
- DataFrame `memory_usage(deep=True)`。
- 进程峰值 RSS，最好包含子进程。
- 读取耗时和总处理耗时。
- 删除列清单及被跳过的检查通道数量。

推荐使用仓库现有基准：

```bash
python tests/benchmarks/bench_check_performance.py --files 100,500,1000 --workers 1,2,4,8
```

单文件命令也应使用 `psutil.Process(...).memory_info().rss` 轮询采样峰值，而不能只看
命令结束后的 RSS。

## 7. 当前实测参考

2026 年 8 月 24 日，在约 944 MB 的 Santos CSV 上，当前 `check` 单文件默认单线程
实测进程峰值约为 `1156 MB`。直接使用裁剪读取时：

- 读取前 RSS：约 `84.8 MB`。
- 裁剪后列数：`176 -> 21`。
- DataFrame 内存：约 `181.7 MB`。
- 裁剪读取阶段 RSS：约 `294.6 MB`。
- 删除对象并回收后 RSS：约 `112.9 MB`。

这些数值受 Python、pandas、操作系统文件缓存、磁盘和检查项影响，只能作为同一机器
上的回归基线，不能作为所有文件的固定上限。

## 8. 常见误区

| 误区 | 后果 | 正确做法 |
|---|---|---|
| 看到 `ParserError` 就认为 CSV 格式损坏 | 忽略真实内存压力 | 同时检查 RSS、文件大小和 NumPy 分配错误 |
| 先完整读取，再 `drop` 无用列 | 解析峰值不降低 | 读取前确定 `usecols` |
| 所有命令统一使用 500 行裁剪 | 可能丢失后段才出现的有效信号 | 只在检查场景启用，并记录语义限制 |
| 只增加 workers 提速 | 多个大 DataFrame 同时驻留 | 先单线程建立内存基线，再逐步增加 |
| 只调用 `gc.collect()` | 仍有缓存或 Future 持有对象 | 先解除引用，再回收 |
| 把裁掉的列当作真实缺列 | 产生错误跳过或失败报告 | 记录 excluded 列并在检查上下文中区分 |
