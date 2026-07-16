# Offline PSD 双份保存与固定图例 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 固定 PSD 图例到右上角，并让 offline 将每张 PSD 同时保存到集中目录和对应 VSHB 目录。

**Architecture:** `PsdPlotter.plot` 增加默认关闭的 `save_to_source` 参数，渲染完成后使用同一 RGB 数组写入主路径和可选源目录路径。offline 命令显式开启该参数，普通 plot 与 UI 依赖默认值维持单份输出。

**Tech Stack:** Python 3.9+、NumPy、Matplotlib、Pillow、pytest、Black、Ruff、mypy

---

### Task 1: 固定图例到右上角

**Files:**
- Modify: `src/health_tools/core/psd_plotter.py`
- Test: `tests/test_offline.py`

- [ ] **Step 1: 更新图例失败测试**

三个 `_plot_hr_overlays` 测试都应断言图例标签之外还显式传入右上角位置：

```python
ax.legend.assert_called_once_with(
    ["pred(offline)", "mcu(online)", "polar(ref)", "comp"],
    loc="upper right",
)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_offline.py -k "psd_hr_overlays" -v`

Expected: FAIL，现有图例调用缺少 `loc`。

- [ ] **Step 3: 实现固定图例位置**

将 `_plot_hr_overlays` 最后一行改为：

```python
ax.legend(labels, loc="upper right")
```

- [ ] **Step 4: 运行图例测试确认通过**

Run: `pytest tests/test_offline.py -k "psd_hr_overlays" -v`

Expected: 三种曲线组合测试全部通过。

### Task 2: 使用同一图像双份保存

**Files:**
- Modify: `src/health_tools/core/psd_plotter.py`
- Test: `tests/test_offline.py`

- [ ] **Step 1: 写入双份保存失败测试**

在嵌套目录创建有效 VSHB 和 PSD 文件，开启 `save_to_source=True`。断言返回值只含主副本，
VSHB 同目录也存在同名 PNG，并用 Pillow 解码比较像素数组：

```python
saved = PsdPlotter().plot(
    result_dir,
    save_dir=output_dir,
    save_to_source=True,
)
source_copy = nested_dir / "sample.png"
assert saved == [output_dir / "sample.png"]
assert np.array_equal(np.asarray(Image.open(saved[0])), np.asarray(Image.open(source_copy)))
```

另一个测试使用默认参数，断言 VSHB 同目录不生成 PNG。

- [ ] **Step 2: 运行保存测试确认失败**

Run: `pytest tests/test_offline.py -k "psd_source_copy" -v`

Expected: FAIL，`plot` 尚不接受 `save_to_source`。

- [ ] **Step 3: 实现可选源目录副本**

给 `plot` 增加 `save_to_source: bool = False`。渲染后构建目标列表，去重后写入同一数组：

```python
save_path = save_dir / f"{base_name}.png"
save_paths = [save_path]
if save_to_source:
    save_paths.append(vshb_path.parent / f"{base_name}.png")
for target_path in dict.fromkeys(save_paths):
    plt.imsave(str(target_path), img)
saved.append(save_path)
```

返回列表只追加主副本。更新 docstring 说明参数和返回约定。

- [ ] **Step 4: 运行 PSD 绘图测试确认通过**

Run: `pytest tests/test_offline.py -k "psd" -v`

Expected: 双份保存、默认单份保存、嵌套目录和现有 axis/rms 测试全部通过。

### Task 3: Offline 开启双份保存

**Files:**
- Modify: `src/health_tools/commands/offline.py`
- Test: `tests/test_progress.py`

- [ ] **Step 1: 更新 offline 参数传递失败测试**

offline 相关的 `PsdPlotter.plot` 测试替身接受 `save_to_source=False`，并在阶段进度测试中记录
该值：

```python
def fake_plot(
    self,
    result_dir,
    save_dir=None,
    show_progress=False,
    acc_mode="axis",
    save_to_source=False,
):
    calls.append(("plot", show_progress, acc_mode, save_to_source))
    return []
```

断言 offline 传入 `True`；普通 `plot --type psd` 仍通过默认值得到 `False`。

- [ ] **Step 2: 运行命令测试确认失败**

Run: `pytest tests/test_progress.py -k "offline_command_enables_stage_progress or plot_psd" -v`

Expected: offline 记录的 `save_to_source` 仍为 `False`。

- [ ] **Step 3: Offline 显式开启源目录副本**

在 `_run_psd_plot` 中调用：

```python
saved = plotter.plot(
    result_dir,
    save_dir=save_dir,
    show_progress=True,
    acc_mode=acc_mode,
    save_to_source=True,
)
```

成功消息说明图片同步保存到各 VSHB 目录。

- [ ] **Step 4: 运行 offline 与 plot 测试确认通过**

Run: `pytest tests/test_progress.py -k "offline or plot_psd" -v`

Expected: offline 开启双份保存，普通 plot 保持单份保存，所有选中测试通过。

### Task 4: 文档、全量验证与提交

**Files:**
- Modify: `docs/cmd_offline.md`
- Modify: `docs/cmd_plot.md`
- Modify: `docs/superpowers/plans/2026-07-16-offline-psd-source-copy.md`

- [ ] **Step 1: 更新命令文档**

`cmd_offline.md` 写明集中副本和 VSHB 同目录副本；`cmd_plot.md` 写明直接 PSD 绘图仅写
`-o/--output` 指定目录。两页都说明图例固定右上角。

- [ ] **Step 2: 确认环境与全量质量检查**

Run: `python -c "import health_tools; print(health_tools.__file__)"`

Expected: 输出当前工作区 `src/health_tools/__init__.py`。

Run: `pytest`

Expected: 全量测试通过。

Run: `black --check src/ tests/`

Expected: 通过。

Run: `ruff check src/ tests/`

Expected: 通过。

Run: `mypy src/`

Expected: 通过。

- [ ] **Step 3: 检查差异并提交**

Run: `git diff --check`

Expected: 无空白错误。

明确暂存实现、测试、文档和计划文件，提交信息：

```text
feat: 双份保存 offline PSD 图片

Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>
```
