"""PSD时频图绘制（离线跑库结果可视化）"""

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from rich.console import Console

from health_tools.core.vshb import read_vshb_result
from health_tools.utils.accuracy import (
    DEFAULT_ACCURACY_THRESHOLDS,
    calculate_accuracy,
    format_accuracy_threshold,
    normalize_accuracy_thresholds,
    prepare_accuracy_columns,
    resolve_accuracy_methods,
)
from health_tools.utils.progress import progress_track

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "WenQuanYi Micro Hei"]
plt.rcParams["axes.unicode_minus"] = False

console = Console()


@dataclass(frozen=True)
class PsdGroup:
    """一组 VSHB 及其配套 PSD 文件与输出位置。"""

    index: int
    vshb_path: Path
    base_name: str
    save_path: Path
    source_save_path: Optional[Path]


@dataclass(frozen=True)
class PsdPlotResult:
    """PSD 批量绘图结果。"""

    saved: Tuple[Path, ...]
    failures: Tuple[Tuple[Path, str], ...]


def _empty_overlay() -> Dict[str, np.ndarray]:
    """返回空折线数据，表示仅绘制PSD图。"""
    empty = np.array([])
    return {"time": empty, "offline": empty, "ref": empty, "online": empty, "comp": empty}


def _load_csv_like_matlab(path: Path) -> np.ndarray:
    """读取CSV数据，兼容行尾逗号和空列"""
    data = np.genfromtxt(str(path), delimiter=",", dtype=float, invalid_raise=False)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    mask = ~np.all(np.isnan(data), axis=0)
    return data[:, mask]


def _load_vshb_overlay(path: Path) -> Dict[str, np.ndarray]:
    """读取vshb折线数据，失败时返回空数据。"""
    try:
        result = read_vshb_result(path, positional_online_col=30)
    except Exception:
        return _empty_overlay()
    if result.empty:
        return _empty_overlay()
    return {
        "time": result["time"].to_numpy(),
        "offline": result["offline"].to_numpy(),
        "ref": result["ref"].to_numpy(),
        "online": result["online"].to_numpy(),
        "comp": result["comp"].to_numpy(),
    }


def _resolved_thresholds(thresholds: Optional[Sequence[float]]) -> Tuple[float, ...]:
    return normalize_accuracy_thresholds(thresholds) or DEFAULT_ACCURACY_THRESHOLDS


def _calc_metrics(
    ref: np.ndarray,
    pred: np.ndarray,
    accuracy_thresholds: Optional[Sequence[float]] = None,
    accuracy_inclusive: bool = False,
    trim_zero_padding: bool = True,
) -> Dict[str, float]:
    """计算动态阈值准确度和 MAE。"""
    thresholds = _resolved_thresholds(accuracy_thresholds)
    methods = resolve_accuracy_methods(["mae", "within_5", "within_10", "within_15"], thresholds)
    metrics = calculate_accuracy(
        pd.DataFrame({"ref": ref, "pred": pred}),
        "ref",
        "pred",
        methods,
        inclusive=accuracy_inclusive,
        trim_zero_padding=trim_zero_padding,
    )
    if not metrics.get("samples"):
        return {}
    metrics.pop("samples", None)
    for key in list(metrics):
        if key.startswith("within_"):
            metrics[key] = round(metrics[key], 1)
    metrics["mae"] = round(metrics["mae"], 2)
    return metrics


def _format_metric_line(
    label: str,
    metrics: Dict[str, float],
    accuracy_thresholds: Optional[Sequence[float]] = None,
) -> str:
    """格式化PSD图顶部准确度摘要。"""
    parts = []
    for threshold in _resolved_thresholds(accuracy_thresholds):
        threshold_text = format_accuracy_threshold(threshold)
        parts.append(f"±{threshold_text}bpm={metrics[f'within_{threshold_text}']}%")
    return f"{label}: " + "  ".join(parts) + f"  MAE={metrics['mae']}"


def _has_valid_ref(ref: np.ndarray) -> bool:
    """判断PSD叠线是否有有效polar金标。"""
    return bool(np.any((~np.isnan(ref)) & (ref > 0)))


def _imagesc_exact(ax, psd: np.ndarray, title: str) -> None:
    """像素级对齐渲染PSD矩阵"""
    finite = np.asarray(psd, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return
    vmin = np.min(finite)
    vmax = np.max(finite)
    if vmax <= vmin:
        vmax = vmin + 1e-12
    ax.imshow(
        psd,
        cmap="viridis",
        origin="lower",
        aspect="auto",
        interpolation="nearest",
        vmin=vmin,
        vmax=vmax,
        extent=[1, psd.shape[1], 0, 250],
    )
    ax.set_title(title)
    ax.margins(0)


def _subplot_top(plot_count: int, has_overlay: bool, metric_row_count: int) -> float:
    """根据子图数量和顶部指标行数预留标题空间。"""
    if not has_overlay:
        return 0.88
    base_top = 0.80 if plot_count <= 2 else 0.88
    return round(base_top - 0.04, 2) if metric_row_count >= 3 else base_top


def _metric_text_rows(
    polar_hr: np.ndarray,
    hba_out: np.ndarray,
    mcu_hr: np.ndarray,
    comp_hr: np.ndarray,
    accuracy_thresholds: Optional[Sequence[float]] = None,
    accuracy_inclusive: bool = False,
) -> List[str]:
    """生成PSD图顶部准确度说明。"""
    prepared = prepare_accuracy_columns(
        {"polar": polar_hr, "offline": hba_out, "online": mcu_hr, "comp": comp_hr}
    )
    if prepared.start == prepared.end:
        return []
    active = set(prepared.active_columns)
    columns = prepared.columns
    comparisons = []
    if "polar" in active:
        for name, label in (
            ("offline", "Offline vs Polar"),
            ("online", "Online vs Polar"),
            ("comp", "Comp vs Polar"),
        ):
            if name in active:
                comparisons.append((label, "polar", name))
    elif {"offline", "online"}.issubset(active):
        comparisons.append(("Online vs Offline", "offline", "online"))

    rows = []
    for label, ref_name, pred_name in comparisons:
        metrics = _calc_metrics(
            columns[ref_name],
            columns[pred_name],
            accuracy_thresholds,
            accuracy_inclusive,
            trim_zero_padding=False,
        )
        if metrics:
            rows.append(_format_metric_line(label, metrics, accuracy_thresholds))
    return rows


def _plot_hr_overlays(
    ax: Axes,
    second: np.ndarray,
    offline_hr: np.ndarray,
    online_hr: np.ndarray,
    polar_hr: np.ndarray,
    comp_hr: np.ndarray,
) -> None:
    """在PPG子图绘制心率折线和对应图例。"""
    labels = ["pred(offline)", "mcu(online)"]
    ax.plot(second, offline_hr, "k-.", linewidth=2)
    ax.plot(second, online_hr, "w-.", linewidth=2)
    if _has_valid_ref(polar_hr):
        ax.plot(second, polar_hr, "r-.", linewidth=2)
        labels.append("polar(ref)")
    if _has_valid_ref(comp_hr):
        ax.plot(second, comp_hr, color="#00E5FF", linestyle="--", linewidth=2)
        labels.append("comp")
    ax.legend(labels, loc="upper right")


class PsdPlotter:
    """PSD时频图绘制器"""

    PSD_GROUPS = {
        "axis": (["0.prepsd", ".accxpsd", ".accypsd", ".acczpsd"], ["PPG", "ACCX", "ACCY", "ACCZ"]),
        "rms": (["0.prepsd", ".accrmspsd"], ["PPG", "ACCRMS"]),
    }

    def plot(
        self,
        result_dir: Path,
        save_dir: Optional[Path] = None,
        show_progress: bool = False,
        acc_mode: str = "axis",
        save_to_source: bool = False,
        accuracy_thresholds: Optional[Sequence[float]] = None,
        accuracy_inclusive: bool = False,
        workers: int = 8,
    ) -> PsdPlotResult:
        """生成PSD时频图

        Args:
            result_dir: 离线跑库输出目录（含.vshb和.psd文件）
            save_dir: 图片保存目录，默认 result_dir/bmpfile
            acc_mode: ACC PSD模式，axis=三轴ACC，rms=合成ACC RMS
            save_to_source: 是否同步保存到对应VSHB所在目录

        Returns:
            成功保存路径与失败文件信息
        """
        if acc_mode not in self.PSD_GROUPS:
            raise ValueError(f"不支持的PSD ACC模式: {acc_mode}")

        psd_extensions, subplot_titles = self.PSD_GROUPS[acc_mode]
        save_dir = save_dir or result_dir / "bmpfile"
        vshb_files = sorted(result_dir.rglob("*_result.vshb"))
        if not vshb_files:
            return PsdPlotResult((), ())

        groups = self._build_groups(vshb_files, save_dir, save_to_source)
        self._validate_output_paths(groups)
        save_dir.mkdir(parents=True, exist_ok=True)

        max_workers = min(max(int(workers), 1), 8, len(groups))
        saved: List[Optional[Path]] = [None] * len(groups)
        failures: List[Optional[Tuple[Path, str]]] = [None] * len(groups)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures: Dict[Future[Optional[Path]], PsdGroup] = {
                executor.submit(
                    self._render_group,
                    group,
                    psd_extensions,
                    subplot_titles,
                    accuracy_thresholds,
                    accuracy_inclusive,
                ): group
                for group in groups
            }
            completed = as_completed(futures)
            for future in progress_track(
                completed,
                "生成PSD时频图...",
                total=len(groups),
                console=console,
                enabled=show_progress,
            ):
                group = futures[future]
                try:
                    saved[group.index] = future.result()
                except Exception as exc:
                    console.print(f"  [red]PSD错误[/red] {group.vshb_path.name}: {exc}")
                    failures[group.index] = (group.vshb_path, str(exc))

        return PsdPlotResult(
            tuple(path for path in saved if path is not None),
            tuple(failure for failure in failures if failure is not None),
        )

    @staticmethod
    def _build_groups(
        vshb_files: Sequence[Path], save_dir: Path, save_to_source: bool
    ) -> Tuple[PsdGroup, ...]:
        groups = []
        for index, vshb_path in enumerate(vshb_files):
            base_name = vshb_path.stem.replace("_result", "")
            save_path = save_dir / f"{base_name}.png"
            source_save_path = vshb_path.parent / f"{base_name}.png" if save_to_source else None
            if source_save_path is not None and source_save_path.resolve() == save_path.resolve():
                source_save_path = None
            groups.append(PsdGroup(index, vshb_path, base_name, save_path, source_save_path))
        return tuple(groups)

    @staticmethod
    def _validate_output_paths(groups: Sequence[PsdGroup]) -> None:
        owners: Dict[Path, Path] = {}
        for group in groups:
            for output_path in (group.save_path, group.source_save_path):
                if output_path is None:
                    continue
                resolved = output_path.resolve()
                if resolved in owners:
                    raise ValueError(
                        f"PSD 输出文件冲突: {output_path} "
                        f"({owners[resolved]} 与 {group.vshb_path})"
                    )
                owners[resolved] = group.vshb_path

    def _render_group(
        self,
        group: PsdGroup,
        psd_extensions: Sequence[str],
        subplot_titles: Sequence[str],
        accuracy_thresholds: Optional[Sequence[float]],
        accuracy_inclusive: bool,
    ) -> Optional[Path]:
        console.print(f"  [dim]PSD {group.base_name}[/dim]")
        overlay = _load_vshb_overlay(group.vshb_path)
        second = overlay["time"]
        hba_out = overlay["offline"]
        polar_hr = overlay["ref"]
        mcu_hr = overlay["online"]
        comp_hr = overlay["comp"]
        has_overlay = len(second) > 0
        metric_rows = (
            _metric_text_rows(
                polar_hr,
                hba_out,
                mcu_hr,
                comp_hr,
                accuracy_thresholds,
                accuracy_inclusive,
            )
            if has_overlay
            else []
        )

        psd_all = []
        for extension in psd_extensions:
            psd_path = group.vshb_path.parent / (group.base_name + extension)
            if psd_path.exists():
                loaded = _load_csv_like_matlab(psd_path)
                psd_all.append(loaded if self._has_valid_psd(loaded) else None)
            else:
                psd_all.append(None)

        active = [(title, psd) for title, psd in zip(subplot_titles, psd_all) if psd is not None]
        if not active:
            console.print(f"  [yellow]WARN[/yellow] {group.base_name} 不包含有效PSD数据，已跳过")
            return None

        fig: Optional[Figure] = None
        try:
            fig = Figure(figsize=(19.2, 2.7 * len(active)), dpi=100)
            FigureCanvasAgg(fig)
            axes = np.atleast_1d(fig.subplots(len(active), 1))
            for index, ax in enumerate(axes.flat):
                title, psd = active[index]
                psd = psd[:, :128].T if psd.shape[1] >= 128 else psd.T
                _imagesc_exact(ax, psd, title)
                if index == 0 and has_overlay:
                    _plot_hr_overlays(ax, second, hba_out, mcu_hr, polar_hr, comp_hr)

            fig.subplots_adjust(
                left=0.03,
                right=0.995,
                bottom=0.05,
                top=_subplot_top(len(active), has_overlay, len(metric_rows)),
                wspace=0.08,
                hspace=0.25,
            )
            fig.text(
                0.5,
                0.98,
                group.base_name,
                ha="center",
                va="top",
                fontsize=12,
                fontweight="bold",
            )
            if has_overlay:
                for row_index, metric_text in enumerate(metric_rows):
                    fig.text(
                        0.5,
                        0.95 - row_index * 0.03,
                        metric_text,
                        ha="center",
                        va="top",
                        fontsize=10,
                    )

            fig.canvas.draw()
            image = np.array(fig.canvas.buffer_rgba())[..., :3]
            mpimg.imsave(str(group.save_path), image)
            if group.source_save_path is not None:
                mpimg.imsave(str(group.source_save_path), image)
            return group.save_path
        finally:
            if fig is not None:
                plt.close(fig)

    @staticmethod
    def _has_valid_psd(psd: np.ndarray) -> bool:
        """判断PSD矩阵是否包含可绘制的有限非零数据。"""
        values = np.asarray(psd, dtype=float)
        return bool(np.any(np.isfinite(values) & (values != 0)))
