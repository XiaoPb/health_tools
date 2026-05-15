"""PSD时频图绘制（离线跑库结果可视化）"""

from pathlib import Path
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import numpy as np
from rich.console import Console

console = Console()


def _load_csv_like_matlab(path: Path) -> np.ndarray:
    """读取CSV数据，兼容行尾逗号和空列"""
    data = np.genfromtxt(str(path), delimiter=",", dtype=float, invalid_raise=False)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    mask = ~np.all(np.isnan(data), axis=0)
    return data[:, mask]


def _calc_metrics(ref: np.ndarray, pred: np.ndarray) -> Dict[str, float]:
    """计算±10bpm准确度和MAE"""
    valid = ~(np.isnan(ref) | np.isnan(pred)) & (ref > 0)
    r, p = ref[valid], pred[valid]
    if len(r) == 0:
        return {"within_10": 0.0, "mae": 0.0}
    diff = np.abs(r - p)
    within_10 = float(np.mean(diff <= 10) * 100)
    mae = float(np.mean(diff))
    return {"within_10": round(within_10, 1), "mae": round(mae, 2)}


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


class PsdPlotter:
    """PSD时频图绘制器"""

    PSD_EXTENSIONS = ["0.prepsd", ".accxpsd", ".accypsd", ".acczpsd"]
    SUBPLOT_TITLES = ["PPG", "ACCX", "ACCY", "ACCZ"]

    def plot(self, result_dir: Path, save_dir: Optional[Path] = None) -> List[Path]:
        """生成PSD时频图

        Args:
            result_dir: 离线跑库输出目录（含.vshb和.psd文件）
            save_dir: 图片保存目录，默认 result_dir/bmpfile

        Returns:
            保存的图片路径列表
        """
        if save_dir is None:
            save_dir = result_dir / "bmpfile"
        save_dir.mkdir(parents=True, exist_ok=True)

        vshb_files = sorted(result_dir.rglob("*_result.vshb"))
        if not vshb_files:
            return []

        saved: List[Path] = []
        for idx, vshb_path in enumerate(vshb_files, start=1):
            try:
                fname = vshb_path.stem
                base_name = fname.replace("_result", "")
                console.print(f"  [dim]PSD ({idx}/{len(vshb_files)}) {base_name}[/dim]")

                result = _load_csv_like_matlab(vshb_path)
                second = result[:, 0]
                hba_out = result[:, 1]
                polar_hr = result[:, 2]
                mcu_hr = result[:, -2] if result.shape[1] >= 2 else np.zeros_like(second)

                psd_all = []
                psd_dir = vshb_path.parent
                for ext in self.PSD_EXTENSIONS:
                    psd_path = psd_dir / (base_name + ext)
                    if psd_path.exists():
                        psd_all.append(_load_csv_like_matlab(psd_path))
                    else:
                        psd_all.append(np.zeros((128, max(len(second), 1))))

                fig = plt.figure(figsize=(19.2, 10.8), dpi=100)
                axes = fig.subplots(4, 1)

                for i, ax in enumerate(axes.flat):
                    psd = psd_all[i]
                    if psd.shape[1] >= 128:
                        psd = psd[:, :128].T
                    else:
                        psd = psd.T
                    _imagesc_exact(ax, psd, self.SUBPLOT_TITLES[i])

                    if i == 0:
                        ax.plot(second, hba_out, "k-.", linewidth=2)
                        ax.plot(second, polar_hr, "r-.", linewidth=2)
                        ax.plot(second, mcu_hr, "w-.", linewidth=2)
                        ax.legend(["pred(offline)", "polar(ref)", "mcu(online)"])

                fig.subplots_adjust(
                    left=0.03, right=0.995, bottom=0.05, top=0.88, wspace=0.08, hspace=0.25
                )

                offline_m = _calc_metrics(polar_hr, hba_out)
                online_m = _calc_metrics(polar_hr, mcu_hr)
                fig.text(
                    0.5,
                    0.98,
                    base_name,
                    ha="center",
                    va="top",
                    fontsize=12,
                    fontweight="bold",
                )
                fig.text(
                    0.5,
                    0.95,
                    f"Offline: ±10bpm={offline_m['within_10']}%  MAE={offline_m['mae']}",
                    ha="center",
                    va="top",
                    fontsize=10,
                )
                fig.text(
                    0.5,
                    0.92,
                    f"Online:  ±10bpm={online_m['within_10']}%  MAE={online_m['mae']}",
                    ha="center",
                    va="top",
                    fontsize=10,
                )

                save_path = save_dir / f"{base_name}.png"
                fig.canvas.draw()
                img = np.array(fig.canvas.buffer_rgba())[..., :3]
                plt.imsave(str(save_path), img)
                plt.close(fig)
                saved.append(save_path)

            except Exception as e:
                console.print(f"  [red]PSD错误[/red] {vshb_path.name}: {e}")
                plt.close("all")

        return saved
