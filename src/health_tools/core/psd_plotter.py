"""PSD时频图绘制（离线跑库结果可视化）"""

from pathlib import Path
from typing import List, Optional

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

        vshb_files = sorted(result_dir.glob("*_result.vshb"))
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
                for ext in self.PSD_EXTENSIONS:
                    psd_path = result_dir / (base_name + ext)
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
                    left=0.03, right=0.995, bottom=0.05, top=0.95, wspace=0.08, hspace=0.25
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
