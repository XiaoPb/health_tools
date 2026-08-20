# 绘图文件名标题统一实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为所有由输入文件生成的绘图统一增加输入文件名标题；AC 图优先落地，同时保持通道、子图和既有输出文件名不变。

**Architecture:** 在绘图 API 的文件级调用链中提取输入文件名，并作为可选 `file_name` 参数传入各绘图方法。普通图使用整图总标题，保留已有通道/子图标题；PSD 和分析证据图已有文件名信息，只统一格式和回归测试，不重复叠加标题。

**Tech Stack:** Python 3.9+, pandas, NumPy, SciPy, Matplotlib `Figure`, pytest, Black, Ruff。

---

### Task 1: 明确标题规则并补齐绘图单元测试

**Files:**
- Modify: `tests/test_plotter.py`
- Modify: `tests/test_progress.py`

- [ ] **Step 1: 为普通绘图写失败测试**

在 `tests/test_plotter.py` 中为 `plot_time`、`plot_freq`、`plot_ac`、`plot_fft`、`plot_spectrogram` 增加 `file_name="sample.csv"` 调用，并断言：

```python
assert fig._suptitle.get_text() == "sample.csv"
```

FFT 还要保留通道相关标题信息；测试应确认整图总标题包含 `sample.csv`，而不是只断言通道标题消失。

- [ ] **Step 2: 为 STFT 写失败测试**

在 `tests/test_plotter.py` 中覆盖单通道和多通道 `plot_stft(..., file_name="sample.csv")`，断言返回的 `Figure` 都有 `sample.csv` 总标题，并保留原有通道标题语义。

- [ ] **Step 3: 为芯片自动 STFT 写失败测试**

拦截 `plot_chip_stft` 调用，确认 `_plot_one` 传入输入文件名；再对 `STFTPlotter.plot_chip_stft` 断言总标题为 `sample.csv`。

- [ ] **Step 4: 运行新增测试确认按预期失败**

运行：

```bash
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest -q tests/test_plotter.py tests/test_progress.py -k "title or filename or file_name"
```

预期：新增断言失败，原因是现有绘图方法尚未设置文件名总标题。

### Task 2: 给普通绘图方法增加文件名标题能力

**Files:**
- Modify: `src/health_tools/core/plotter.py:118-325`
- Test: `tests/test_plotter.py`

- [ ] **Step 1: 扩展绘图方法签名**

为 `plot_time`、`plot_freq`、`plot_ac`、`plot_fft`、`plot_spectrogram` 增加末尾可选参数 `file_name: Optional[str] = None`；AC 的既有 `r_column` 参数位置保持不变，旧 positional 调用必须继续有效。

- [ ] **Step 2: 增加统一总标题辅助函数**

在 `plotter.py` 增加内部辅助函数：`file_name` 非空时调用 `fig.suptitle(file_name)`，为空时不添加标题。标题使用输入文件名，不使用输出图片名。

- [ ] **Step 3: 调整普通图布局**

设置总标题的图在保存前使用 `fig.tight_layout(rect=(0, 0, 1, 0.96))`，避免标题覆盖子图。保留 time/freq 的通道标签、AC 的三轴和 R 曲线、FFT 的双 Y 轴。

- [ ] **Step 4: 保留现有标题语义**

FFT 保留 `FFT - <channel>` 信息，可组合为 `sample.csv | FFT - CH0`；STFT 的通道标题继续由 `STFTPlotter` 负责，`DataPlotter` 只负责传递文件名。

- [ ] **Step 5: 运行单元测试确认通过**

运行：

```bash
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest -q tests/test_plotter.py
```

预期：文件名标题及原有 AC、FFT、线程绘图测试全部通过。

### Task 3: 沿 API 和 CLI 调用链传递输入文件名

**Files:**
- Modify: `src/health_tools/api/file_operations.py:879-930`
- Modify: `src/health_tools/commands/plot.py:172-265`
- Test: `tests/test_progress.py`

- [ ] **Step 1: 在 API 文件级绘图调用中传入文件名**

在 `_plot_one` 中使用 `path.name`，传给 `plot_time`、`plot_freq`、`plot_ac`、`plot_fft`、`plot_stft` 和 `plot_chip_stft`。AC 调用保留 `r_column=request.r_column`，并额外传入 `file_name=path.name`。

- [ ] **Step 2: 在旧 CLI 文件级路径同步传递文件名**

更新 `commands/plot.py` 的 `_plot_file`，使用 `input_file.name` 传入各绘图器，而不是 `input_file.stem`，确保 CLI 和 API 行为一致。

- [ ] **Step 3: 为调用链写回归测试**

扩展 fake plotter 记录收到的 `file_name`，断言：

```python
assert calls[0].file_name == "sample.csv"
```

至少覆盖 `time`、`ac`、`fft` 和自动 STFT 中的一种路径。

- [ ] **Step 4: 运行 API/CLI 定向测试**

运行：

```bash
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest -q tests/test_progress.py tests/test_api_contract.py
```

预期：相关测试通过，且没有因 fake plotter 参数变化产生 `TypeError`。

### Task 4: 补齐 STFT 和已有文件名标题绘图的一致性

**Files:**
- Modify: `src/health_tools/core/stft.py:275-428`
- Modify: `src/health_tools/core/psd_plotter.py:335-410`（仅必要时）
- Modify: `src/health_tools/core/analysis/reporting.py:136-150`（仅必要时）
- Test: `tests/test_plotter.py` 及相关 STFT/PSD/analysis 测试文件

- [ ] **Step 1: 扩展 STFTPlotter 方法参数**

为 `plot_stft`、`plot_multi_channel_stft`、`plot_chip_stft` 增加 `file_name: Optional[str] = None`，保持现有 `title` 参数和旧调用兼容。

- [ ] **Step 2: 设置 STFT 总标题并调整边距**

当 `file_name` 非空时调用 `fig.suptitle(file_name)`，并调整顶部边距；原有单通道标题、多通道标题和子图标签继续保留。

- [ ] **Step 3: 检查 PSD 和分析证据图**

PSD 当前使用 `group.base_name`，分析证据图使用 `record.file`。先增加标题断言；只有实际格式不符合“输入文件名”规则时才修改，避免重复标题或影响报告版式。

- [ ] **Step 4: 运行绘图全链路测试**

运行：

```bash
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest -q tests/test_plotter.py tests/test_progress.py tests/test_analysis.py -k "plot or stft or psd or evidence"
```

预期：新增标题断言通过，既有图像生成和报告测试不回退。

### Task 5: 更新文档、格式检查并提交

**Files:**
- Modify: `docs/cmd_plot.md`
- Modify: `tests/test_documentation.py`（如有命令页内容断言则同步更新）

- [ ] **Step 1: 更新命令文档**

在 `docs/cmd_plot.md` 的绘图类型说明中注明：`time`、`freq`、`ac`、`fft`、`stft` 和自动 STFT 图片顶部显示输入文件名；文件名含扩展名，输出文件名规则不变。

- [ ] **Step 2: 运行格式和静态检查**

运行：

```bash
black --check src/ tests/
ruff check src/ tests/
python -m compileall -q src tests
```

预期：Black、Ruff 和 compileall 均退出码为 0。

- [ ] **Step 3: 运行完整测试**

运行：

```bash
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest -q
```

记录总通过数和失败数；如果存在与本次改动无关的 PPT 模板失败，必须在最终报告中明确列出，不得将全量测试描述为全部通过。

- [ ] **Step 4: 检查差异并提交**

运行：

```bash
git diff --check
git status --short
git add docs/cmd_plot.md src/health_tools/core/plotter.py src/health_tools/core/stft.py src/health_tools/api/file_operations.py src/health_tools/commands/plot.py tests/test_plotter.py tests/test_progress.py
git commit -m "feat: 统一绘图文件名标题" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

提交前确认不包含已有的 `src/health_tools/templates/analysis_report.pptx` 修改或临时锁文件。

### Task 6: 统一支持指定单图高度以适配 PPT

**Files:**
- Modify: `src/health_tools/api/models.py:237-264`
- Modify: `src/health_tools/commands/plot.py:20-115`
- Modify: `src/health_tools/api/file_operations.py:821-930`
- Modify: `src/health_tools/core/plotter.py:80-325`
- Modify: `src/health_tools/core/stft.py:275-428`
- Modify: `src/health_tools/core/psd_plotter.py:335-410`（仅当 PSD 也需要公开高度参数时）
- Modify: `docs/cmd_plot.md`
- Test: `tests/test_plotter.py`, `tests/test_progress.py`, `tests/test_api_contract.py`

- [ ] **Step 1: 定义公共高度参数和兼容默认值**

在 `PlotRequest` 增加 `fig_height: Optional[float] = None`，CLI 增加 `--height FLOAT`，单位为英寸；未指定时沿用各图类型默认高度。高度必须大于 0；未指定时保持当前每种绘图的默认尺寸。新增 API 测试覆盖默认值、0、负数和非数字输入。

- [ ] **Step 2: 写失败测试验证图片高度**

在 `tests/test_plotter.py` 中为 `plot_time`、`plot_freq`、`plot_ac`、`plot_fft`、`plot_spectrogram` 增加 `fig_height=6.0` 调用，捕获 `Figure` 后断言：

```python
assert figure.get_figheight() == pytest.approx(6.0)
```

同时覆盖多子图图形，确认高度是整张图的总高度，而不是单个子图高度。

- [ ] **Step 3: 在普通绘图器统一应用高度并保护最小布局**

为普通绘图方法增加末尾可选参数 `fig_height: Optional[float] = None`，构造图形时保留现有宽度，仅替换高度：

```python
height = fig_height if fig_height is not None else default_height
fig = _new_figure((width, height))
```

当指定高度小于当前内容所需的最小高度时，采用 `max(fig_height, min_height)`，避免标题、图例、三轴或 R 轴重叠。最小高度按图类型集中定义；调用者指定较大高度时完整保留该高度。

- [ ] **Step 4: 将高度沿 API/CLI 文件级调用链传递**

在 `_plot_one` 和旧 CLI `_plot_file` 中，将 `request.fig_height` 或 CLI 的 `height` 传递给 time/freq/ac/fft/stft/spectrogram 绘图方法。AC 必须同时保留既有 `r_column` 和文件名标题参数；不改变输出文件名和通道分组。

扩展 fake plotter 测试，断言收到的高度值为 `6.0`，并覆盖 API 与 CLI 至少各一条调用路径。

- [ ] **Step 5: 统一处理 STFT 的高度约束**

为 `STFTPlotter.plot_stft`、`plot_multi_channel_stft`、`plot_chip_stft` 增加 `fig_height: Optional[float] = None`。单通道使用指定总高度；多通道和芯片自动模式使用指定总高度，但当高度不足以容纳每个子图时按 `max(指定高度, 最小子图高度 * 子图数量)` 扩展，并保留文件名总标题的顶部空间。

新增测试验证：指定高度时输出 `Figure.get_figheight()` 不小于请求值；多子图时不会因高度过小导致布局异常或保存失败。

- [ ] **Step 6: 明确 PPT 使用文档和非适用范围**

在 `docs/cmd_plot.md` 增加说明：`--height` 单位为英寸，控制整张输出图片高度；未指定时维持现有默认高度；过小高度会按图类型自动提升到可容纳标题、图例和子图的最小值；该参数不改变采样数据、时间范围、输出文件名或 DPI；`psd` 是否支持高度必须与 PSD 绘图器保持一致，若不支持需在文档中明确说明。

- [ ] **Step 7: 运行高度回归与完整验证**

运行：

```bash
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest -q tests/test_plotter.py tests/test_progress.py tests/test_api_contract.py -k "height or plot"
black --check src/ tests/
ruff check src/ tests/
python -m compileall -q src tests
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest -q
```

记录完整测试的通过/失败数量；若出现与本任务无关的 PPT 模板失败，必须单独列出，不能宣称全量通过。

- [ ] **Step 8: 检查差异并提交**

运行：

```bash
git diff --check
git status --short
git add docs/superpowers/plans/2026-08-19-plot-filename-titles.md
git commit -m "docs: 补充绘图单图高度计划" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

不要把工作区已有的 PPT 模板修改或临时锁文件加入提交。

---

## Self-Review Checklist

- [ ] AC、time、freq、FFT、spectrogram、STFT 和自动 STFT 均有对应任务。
- [ ] PSD 与分析证据图已明确检查，不会无故重复添加标题。
- [ ] 文件名来源统一为输入路径的 `Path.name`，包含扩展名。
- [ ] 旧绘图方法调用和测试替身保持兼容。
- [ ] 每个实现步骤都有对应的失败测试、通过测试和验证命令。
- [ ] 没有引入新的 CLI 选项，也不改变输出文件名。
- [ ] 单图高度使用英寸，默认行为兼容旧输出，过小值按图类型最小布局高度保护。
- [ ] 高度参数覆盖普通图、AC、FFT、STFT 和 spectrogram，并明确 PSD 是否支持。
