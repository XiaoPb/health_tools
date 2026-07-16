# PSD Comp 折线与动态标题留白 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 PSD 的 PPG 子图中用亮青色虚线绘制有效 comp，并根据顶部指标行数动态增加留白。

**Architecture:** 在 `core/psd_plotter.py` 中抽出心率折线与图例绘制函数，使每条可选曲线在同一处决定样式和标签。绘图前生成指标文字行，将实际行数传给留白函数；第三行存在时只下移图轴，不改变画布尺寸。

**Tech Stack:** Python 3.9+、NumPy、Matplotlib、pytest、Black、Ruff、mypy

---

### Task 1: Comp 折线与动态图例

**Files:**
- Modify: `src/health_tools/core/psd_plotter.py`
- Test: `tests/test_offline.py`

- [x] **Step 1: 写入失败测试**

用 `unittest.mock.Mock` 作为坐标轴，直接测试新的 `_plot_hr_overlays`。有效 comp 应产生第四次
`plot` 调用，关键字参数为亮青色、虚线和线宽 2，图例顺序固定。

```python
ax = Mock()
psd_plotter._plot_hr_overlays(ax, second, offline_hr, online_hr, polar_hr, comp_hr)

assert ax.plot.call_args_list[3].kwargs == {
    "color": "#00E5FF",
    "linestyle": "--",
    "linewidth": 2,
}
ax.legend.assert_called_once_with(
    ["pred(offline)", "mcu(online)", "polar(ref)", "comp"]
)
```

再覆盖两个条件：comp 全为 0 时只有现有三条曲线；polar 全为 0 且 comp 有效时绘制
offline、online、comp，图例顺序为 `pred(offline), mcu(online), comp`。

- [x] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_offline.py -k "psd_hr_overlays" -v`

Expected: FAIL，提示 `_plot_hr_overlays` 尚不存在。

- [x] **Step 3: 实现折线与动态图例函数**

在 `psd_plotter.py` 中新增：

```python
def _plot_hr_overlays(
    ax,
    second: np.ndarray,
    offline_hr: np.ndarray,
    online_hr: np.ndarray,
    polar_hr: np.ndarray,
    comp_hr: np.ndarray,
) -> None:
    labels = ["pred(offline)", "mcu(online)"]
    ax.plot(second, offline_hr, "k-.", linewidth=2)
    ax.plot(second, online_hr, "w-.", linewidth=2)
    if _has_valid_ref(polar_hr):
        ax.plot(second, polar_hr, "r-.", linewidth=2)
        labels.append("polar(ref)")
    if _has_valid_ref(comp_hr):
        ax.plot(second, comp_hr, color="#00E5FF", linestyle="--", linewidth=2)
        labels.append("comp")
    ax.legend(labels)
```

PPG 子图调用该函数，删除原先写死的两组图例分支。

- [x] **Step 4: 运行折线测试确认通过**

Run: `pytest tests/test_offline.py -k "psd_hr_overlays" -v`

Expected: 三种曲线组合测试全部通过。

### Task 2: 根据指标行数动态留白

**Files:**
- Modify: `src/health_tools/core/psd_plotter.py`
- Test: `tests/test_offline.py`

- [x] **Step 1: 写入失败测试**

修改 `_subplot_top` 测试，显式传入指标行数。第三行时 axis 从 0.88 变为 0.84，rms 从
0.80 变为 0.76；一至两行和无 overlay 保持原值。

```python
assert psd_plotter._subplot_top(4, True, 2) == 0.88
assert psd_plotter._subplot_top(4, True, 3) == 0.84
assert psd_plotter._subplot_top(2, True, 2) == 0.80
assert psd_plotter._subplot_top(2, True, 3) == 0.76
assert psd_plotter._subplot_top(4, False, 0) == 0.88
```

- [x] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_offline.py -k "subplot_top" -v`

Expected: FAIL，现有函数不接受第三个参数。

- [x] **Step 3: 实现动态留白并复用指标行**

将留白函数改为：

```python
def _subplot_top(plot_count: int, has_overlay: bool, metric_row_count: int) -> float:
    if not has_overlay:
        return 0.88
    base_top = 0.80 if plot_count <= 2 else 0.88
    return base_top - 0.04 if metric_row_count >= 3 else base_top
```

读取 overlay 后只生成一次 `metric_rows`，同时用于 `subplots_adjust(top=...)` 和顶部文字循环，
避免布局判断与实际显示行数不一致。

- [x] **Step 4: 运行 PSD 单元测试确认通过**

Run: `pytest tests/test_offline.py -k "psd" -v`

Expected: PSD overlay、指标、留白及图片生成测试全部通过。

### Task 3: 文档、环境与视觉验证

**Files:**
- Modify: `.gitignore`
- Modify: `docs/cmd_plot.md`
- Modify: `docs/cmd_offline.md`
- Modify: `docs/architecture.md`
- Modify: `docs/superpowers/plans/2026-07-16-psd-comp-overlay-spacing.md`

- [x] **Step 1: 清理视觉伴侣工作区状态**

在 `.gitignore` 的项目规则中加入 `.superpowers/`，保留本地颜色与布局对比稿，但不让会话
文件进入版本控制。

- [x] **Step 2: 更新用户和架构文档**

`cmd_plot.md` 与 `cmd_offline.md` 说明 comp 有效时以 `#00E5FF` 虚线叠加，第三行指标触发
额外留白；`architecture.md` 将 VSHB overlay 描述更新为离线、在线、comp 与金标叠加。

- [x] **Step 3: 修复并确认开发环境来源**

Run: `pip install -e ".[dev]"`

Expected: 当前工作区及开发依赖安装成功。

Run: `python -c "import health_tools; print(health_tools.__file__)"`

Expected: 输出 `E:\Code\Python\health_tools\src\health_tools\__init__.py`。

- [x] **Step 4: 生成代表性图片并视觉检查**

在临时目录生成带表头 VSHB、PPG 与 ACC PSD 矩阵，分别调用：

```python
plotter.plot(result_dir, save_dir=axis_output, acc_mode="axis")
plotter.plot(result_dir, save_dir=rms_output, acc_mode="rms")
```

检查两张 PNG 非空，并查看图片确认：comp 为亮青色虚线；图例顺序正确；三行指标与 PPG
标题、图轴无重叠；axis 和 rms 的数据区域均非空。

- [x] **Step 5: 运行全量验证**

Run: `pytest`

Expected: 全量测试通过。

Run: `black --check src/ tests/`

Expected: 通过。

Run: `ruff check src/ tests/`

Expected: 通过。

Run: `mypy src/`

Expected: 通过。

- [x] **Step 6: 检查差异并提交**

Run: `git diff --check`

Expected: 无空白错误。

明确暂存 `.gitignore`、实现、测试、文档和计划文件，提交信息：

```text
feat: 优化 PSD comp 折线与标题留白

Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>
```
