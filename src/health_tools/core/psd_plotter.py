"""PSD时频图绘制（离线跑库结果可视化）"""

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
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
    vmin = np.nanmin(psd)
    vmax = np.nanmax(psd)
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
    ) -> List[Path]:
        """生成PSD时频图

        Args:
            result_dir: 离线跑库输出目录（含.vshb和.psd文件）
            save_dir: 图片保存目录，默认 result_dir/bmpfile
            acc_mode: ACC PSD模式，axis=三轴ACC，rms=合成ACC RMS
            save_to_source: 是否同步保存到对应VSHB所在目录

        Returns:
            保存的图片路径列表
        """
        if acc_mode not in self.PSD_GROUPS:
            raise ValueError(f"不支持的PSD ACC模式: {acc_mode}")

        psd_extensions, subplot_titles = self.PSD_GROUPS[acc_mode]
        if save_dir is None:
            save_dir = result_dir / "bmpfile"
        save_dir.mkdir(parents=True, exist_ok=True)

        vshb_files = sorted(result_dir.rglob("*_result.vshb"))
        if not vshb_files:
            return []

        saved: List[Path] = []
        for idx, vshb_path in enumerate(
            progress_track(vshb_files, "生成PSD时频图...", console=console, enabled=show_progress),
            start=1,
        ):
            try:
                fname = vshb_path.stem
                base_name = fname.replace("_result", "")
                console.print(f"  [dim]PSD ({idx}/{len(vshb_files)}) {base_name}[/dim]")

                overlay = _load_vshb_overlay(vshb_path)
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
                psd_dir = vshb_path.parent
                for ext in psd_extensions:
                    psd_path = psd_dir / (base_name + ext)
                    if psd_path.exists():
                        psd_all.append(_load_csv_like_matlab(psd_path))
                    else:
                        psd_all.append(np.zeros((128, max(len(second), 1))))

                fig = plt.figure(figsize=(19.2, 2.7 * len(subplot_titles)), dpi=100)
                axes = np.atleast_1d(fig.subplots(len(subplot_titles), 1))

                for i, ax in enumerate(axes.flat):
                    psd = psd_all[i]
                    if psd.shape[1] >= 128:
                        psd = psd[:, :128].T
                    else:
                        psd = psd.T
                    _imagesc_exact(ax, psd, subplot_titles[i])

                    if i == 0 and has_overlay:
                        _plot_hr_overlays(ax, second, hba_out, mcu_hr, polar_hr, comp_hr)

                fig.subplots_adjust(
                    left=0.03,
                    right=0.995,
                    bottom=0.05,
                    top=_subplot_top(len(subplot_titles), has_overlay, len(metric_rows)),
                    wspace=0.08,
                    hspace=0.25,
                )

                fig.text(
                    0.5,
                    0.98,
                    base_name,
                    ha="center",
                    va="top",
                    fontsize=12,
                    fontweight="bold",
                )
                if has_overlay:
                    for row_idx, metric_text in enumerate(metric_rows):
                        fig.text(
                            0.5,
                            0.95 - row_idx * 0.03,
                            metric_text,
                            ha="center",
                            va="top",
                            fontsize=10,
                        )

                save_path = save_dir / f"{base_name}.png"
                fig.canvas.draw()
                img = np.array(fig.canvas.buffer_rgba())[..., :3]
                plt.imsave(str(save_path), img)
                if save_to_source:
                    source_save_path = vshb_path.parent / f"{base_name}.png"
                    if source_save_path != save_path:
                        plt.imsave(str(source_save_path), img)
                plt.close(fig)
                saved.append(save_path)

            except Exception as e:
                console.print(f"  [red]PSD错误[/red] {vshb_path.name}: {e}")
                plt.close("all")

        return saved
