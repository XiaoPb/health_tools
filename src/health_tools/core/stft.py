"""时频分析模块"""

from typing import Optional, Tuple

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from scipy import signal


def _new_figure(figsize: Tuple[float, float]) -> Figure:
    """创建可安全用于工作线程的无界面 Agg 画布。"""
    figure = Figure(figsize=figsize)
    FigureCanvasAgg(figure)
    return figure


def remove_baseline(
    data: np.ndarray,
    method: str = "mean",
    window_size: Optional[int] = None,
) -> np.ndarray:
    """
    去除基线

    Args:
        data: 输入数据
        method: 去除方法 (mean, median, moving_mean, moving_median)
        window_size: 滑动窗口大小（用于moving方法）

    Returns:
        去除基线后的数据
    """
    if len(data) == 0:
        return data

    if method == "mean":
        baseline = np.mean(data)
        return data - baseline

    elif method == "median":
        baseline = np.median(data)
        return data - baseline

    elif method == "moving_mean":
        if window_size is None:
            window_size = len(data) // 10
        if window_size < 1:
            window_size = 1
        baseline = np.convolve(data, np.ones(window_size) / window_size, mode="same")
        return data - baseline

    elif method == "moving_median":
        if window_size is None:
            window_size = len(data) // 10
        if window_size < 1:
            window_size = 1
        from scipy.ndimage import median_filter

        baseline = median_filter(data, size=window_size)
        return data - baseline

    return data


def bandpass_filter(
    data: np.ndarray,
    fs: float,
    lowcut: float = 0.5,
    highcut: float = 4.0,
    order: int = 4,
) -> np.ndarray:
    """
    带通滤波

    Args:
        data: 输入数据
        fs: 采样率
        lowcut: 低频截止
        highcut: 高频截止
        order: 滤波器阶数

    Returns:
        滤波后的数据
    """
    if len(data) == 0 or fs <= 0:
        return data

    nyquist = fs / 2

    if lowcut >= nyquist or highcut >= nyquist:
        return data

    low = lowcut / nyquist
    high = highcut / nyquist

    if low >= high:
        return data

    try:
        b, a = signal.butter(order, [low, high], btype="band")
        return signal.filtfilt(b, a, data)
    except Exception:
        return data


def compute_stft(
    data: np.ndarray,
    fs: float,
    window_sec: float = 10.0,
    step_sec: float = 0.5,
    nperseg: Optional[int] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    计算短时傅里叶变换

    Args:
        data: 输入数据
        fs: 采样率
        window_sec: 窗口大小（秒）
        step_sec: 步长（秒）
        nperseg: 每段长度（覆盖window_sec）

    Returns:
        (frequencies, times, Zxx)
    """
    if len(data) == 0 or fs <= 0:
        return np.array([]), np.array([]), np.array([[]])

    if nperseg is None:
        nperseg = int(window_sec * fs)

    nperseg = min(nperseg, len(data))

    if nperseg < 8:
        nperseg = 8

    noverlap = nperseg - int(step_sec * fs)
    if noverlap < 0:
        noverlap = 0

    try:
        frequencies, times, Zxx = signal.stft(
            data,
            fs=fs,
            nperseg=nperseg,
            noverlap=noverlap,
        )
        return frequencies, times, np.abs(Zxx)
    except Exception:
        return np.array([]), np.array([]), np.array([[]])


def compute_psd(
    data: np.ndarray,
    fs: float,
    nperseg: Optional[int] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    计算功率谱密度

    Args:
        data: 输入数据
        fs: 采样率
        nperseg: 每段长度

    Returns:
        (frequencies, psd)
    """
    if len(data) == 0 or fs <= 0:
        return np.array([]), np.array([])

    if nperseg is None:
        nperseg = min(256, len(data))

    nperseg = min(nperseg, len(data))

    if nperseg < 8:
        nperseg = 8

    try:
        frequencies, psd = signal.welch(data, fs=fs, nperseg=nperseg)
        return frequencies, psd
    except Exception:
        return np.array([]), np.array([])


def normalize_per_time_column(zxx_amp: np.ndarray) -> np.ndarray:
    """逐时间列 0-100 归一化（向量化）"""
    z = zxx_amp.astype(np.float32)
    col_min = z.min(axis=0, keepdims=True)
    col_ptp = np.ptp(z, axis=0, keepdims=True)
    col_ptp[col_ptp < 1e-10] = 1.0
    return (z - col_min) / col_ptp * 100


class STFTPlotter:
    """STFT时频图绑图器"""

    def __init__(
        self,
        fs: float = 25.0,
        window_sec: float = 25.0,
        step_sec: float = 1.0,
        lowcut: float = 0.5,
        highcut: float = 4.0,
        remove_baseline_method: str = "mean",
        freq_bpm: bool = True,
        freq_range: Tuple[float, float] = (30.0, 240.0),
    ):
        self.fs = fs
        self.window_sec = window_sec
        self.step_sec = step_sec
        self.lowcut = lowcut
        self.highcut = highcut
        self.remove_baseline_method = remove_baseline_method
        self.freq_bpm = freq_bpm
        self.freq_range = freq_range

    def process_data(self, data: np.ndarray) -> np.ndarray:
        """预处理：去基线 + 带通滤波"""
        data = np.asarray(data, dtype=float)
        data = data[~np.isnan(data)]
        if len(data) == 0:
            return data
        if self.remove_baseline_method:
            data = remove_baseline(data, method=self.remove_baseline_method)
        data = bandpass_filter(data, self.fs, self.lowcut, self.highcut)
        return data

    def _compute_normalized_stft(self, data: np.ndarray):
        """预处理 + STFT + 逐列归一化，返回 (freqs, times, normalized_zxx)"""
        processed = self.process_data(data)
        if len(processed) == 0:
            return None, None, None
        freqs, times, zxx = compute_stft(processed, self.fs, self.window_sec, self.step_sec)
        if len(freqs) == 0:
            return None, None, None
        zxx_norm = normalize_per_time_column(zxx)
        return freqs, times, zxx_norm

    def _plot_subplot(
        self,
        ax,
        times,
        freqs_bpm,
        zxx_norm,
        title,
        ref_data=None,
        ref_label="REF_RESULT0",
        algo_data=None,
        cmap="viridis",
    ):
        """绘制单个 STFT 子图"""
        freq_min, freq_max = self.freq_range
        freq_mask = (freqs_bpm >= freq_min) & (freqs_bpm <= freq_max)
        freqs_masked = freqs_bpm[freq_mask]
        zxx_masked = zxx_norm[freq_mask, :]

        ax.pcolormesh(times, freqs_masked, zxx_masked, cmap=cmap, shading="auto")
        ax.set_ylabel(title)
        ax.set_ylim([freq_min, freq_max])

        if ref_data is not None and len(ref_data) > 0:
            total_duration = times[-1] if len(times) > 0 else len(ref_data) / self.fs
            ref_times = np.linspace(0, total_duration, len(ref_data))
            ax.plot(ref_times, ref_data, "r--", linewidth=1.5, label=ref_label)
        if algo_data is not None and len(algo_data) > 0:
            total_duration = times[-1] if len(times) > 0 else len(algo_data) / self.fs
            algo_times = np.linspace(0, total_duration, len(algo_data))
            ax.plot(algo_times, algo_data, "w-", linewidth=1.0, label="ALGO_RESULT0")
        if ref_data is not None or algo_data is not None:
            ax.legend(loc="upper right", fontsize=8)

    def plot_chip_stft(
        self,
        df,
        output_file: str,
        channel: str,
        ref_columns=None,
        dpi: int = 300,
    ) -> None:
        """模式A：chip自动模式，5子图（channel + ACCXYZ + CH-ACC）"""
        import pandas as pd

        if ref_columns is None:
            ref_columns = ["REF_RESULT0", "ALGO_RESULT0"]

        ch_data = pd.to_numeric(df[channel], errors="coerce").fillna(0).values
        acc_cols = ["ACCX", "ACCY", "ACCZ"]
        acc_data = {}
        for col in acc_cols:
            if col in df.columns:
                acc_data[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).values

        ref_data = None
        if ref_columns[0] in df.columns:
            ref_data = pd.to_numeric(df[ref_columns[0]], errors="coerce").fillna(0).values
        algo_data = None
        if len(ref_columns) > 1 and ref_columns[1] in df.columns:
            algo_data = pd.to_numeric(df[ref_columns[1]], errors="coerce").fillna(0).values

        results = {}
        freqs_out, times_out = None, None

        ch_result = self._compute_normalized_stft(ch_data)
        if ch_result[0] is not None:
            freqs_out, times_out = ch_result[0], ch_result[1]
            results[channel] = ch_result[2]

        acc_stft_list = []
        for col in acc_cols:
            if col in acc_data:
                r = self._compute_normalized_stft(acc_data[col])
                if r[0] is not None:
                    results[col] = r[2]
                    acc_stft_list.append(r[2])
                    if freqs_out is None:
                        freqs_out, times_out = r[0], r[1]

        if freqs_out is None:
            return

        if acc_stft_list and channel in results:
            acc_combined = np.mean(acc_stft_list, axis=0)
            acc_combined_norm = normalize_per_time_column(acc_combined)
            ch_minus_acc = results[channel] - acc_combined_norm
            ch_minus_acc[ch_minus_acc < 0] = 0
            results[f"{channel} - ACC"] = normalize_per_time_column(ch_minus_acc)

        freqs_bpm = freqs_out * 60 if self.freq_bpm else freqs_out
        titles = [channel] + acc_cols + [f"{channel} - ACC"]
        n_plots = len([t for t in titles if t in results])

        fig = _new_figure((18, 4.4 * n_plots))
        axes = np.atleast_1d(fig.subplots(n_plots, 1))

        idx = 0
        for title in titles:
            if title not in results:
                continue
            self._plot_subplot(
                axes[idx],
                times_out,
                freqs_bpm,
                results[title],
                title,
                ref_data=ref_data,
                algo_data=algo_data,
            )
            idx += 1

        axes[-1].set_xlabel("Time (s)")
        fig.subplots_adjust(left=0.08, right=0.94, top=0.96, bottom=0.06, hspace=0.4)
        fig.savefig(output_file, dpi=dpi)

    def plot_stft(
        self,
        data: np.ndarray,
        output_file: Optional[str] = None,
        title: str = "STFT Spectrogram",
        cmap: str = "viridis",
        figsize: Tuple[float, float] = (18, 6),
        dpi: int = 300,
        ref_data: Optional[np.ndarray] = None,
        ref_label: str = "Reference",
    ) -> Optional[Figure]:
        """单通道 STFT（模式B单通道）"""
        freqs, times, zxx_norm = self._compute_normalized_stft(data)
        if freqs is None:
            return None

        freqs_bpm = freqs * 60 if self.freq_bpm else freqs

        fig = _new_figure(figsize)
        ax = fig.subplots()
        self._plot_subplot(
            ax, times, freqs_bpm, zxx_norm, title, ref_data=ref_data, ref_label=ref_label, cmap=cmap
        )
        ax.set_xlabel("Time (s)")
        fig.tight_layout()

        if output_file:
            fig.savefig(output_file, dpi=dpi)
            return None
        return fig

    def plot_multi_channel_stft(
        self,
        data_dict: dict,
        output_file: Optional[str] = None,
        title: str = "Multi-Channel STFT",
        cmap: str = "viridis",
        figsize: Tuple[float, float] = (18, 6),
        dpi: int = 300,
        ref_data: Optional[np.ndarray] = None,
        ref_label: str = "Reference",
    ) -> Optional[Figure]:
        """多通道 STFT（模式B多通道）"""
        n_channels = len(data_dict)
        if n_channels == 0:
            return None

        fig = _new_figure((figsize[0], 4.4 * n_channels))
        axes = np.atleast_1d(fig.subplots(n_channels, 1, sharex=True))

        for ax, (channel_name, data) in zip(axes, data_dict.items()):
            freqs, times, zxx_norm = self._compute_normalized_stft(data)
            if freqs is None:
                continue
            freqs_bpm = freqs * 60 if self.freq_bpm else freqs
            self._plot_subplot(
                ax,
                times,
                freqs_bpm,
                zxx_norm,
                channel_name,
                ref_data=ref_data,
                ref_label=ref_label,
                cmap=cmap,
            )

        axes[-1].set_xlabel("Time (s)")
        fig.suptitle(title)
        fig.subplots_adjust(left=0.08, right=0.94, top=0.96, bottom=0.06, hspace=0.4)

        if output_file:
            fig.savefig(output_file, dpi=dpi)
            return None
        return fig
