"""时频分析模块"""

from typing import List, Optional, Tuple, Union

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import signal


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


class STFTPlotter:
    """STFT时频图绑图器"""

    def __init__(
        self,
        fs: float = 25.0,
        window_sec: float = 10.0,
        step_sec: float = 0.5,
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

    def process_data(
        self,
        data: np.ndarray,
    ) -> np.ndarray:
        """预处理数据"""
        data = np.asarray(data, dtype=float)

        data = data[~np.isnan(data)]

        if len(data) == 0:
            return data

        data = remove_baseline(data, method=self.remove_baseline_method)

        data = bandpass_filter(data, self.fs, self.lowcut, self.highcut)

        return data

    def plot_stft(
        self,
        data: np.ndarray,
        output_file: Optional[str] = None,
        title: str = "STFT Spectrogram",
        cmap: str = "jet",
        figsize: Tuple[float, float] = (12, 6),
        dpi: int = 150,
        ref_data: Optional[np.ndarray] = None,
        ref_label: str = "Reference",
    ) -> Optional[plt.Figure]:
        """
        绑制STFT时频图

        Args:
            data: 输入数据
            output_file: 输出文件路径
            title: 图表标题
            cmap: 颜色映射
            figsize: 图表大小
            dpi: DPI
            ref_data: 参考数据
            ref_label: 参考数据标签

        Returns:
            Figure对象（如果未保存文件）
        """
        data = self.process_data(data)

        if len(data) == 0:
            return None

        frequencies, times, Zxx = compute_stft(
            data, self.fs, self.window_sec, self.step_sec
        )

        if len(frequencies) == 0:
            return None

        if self.freq_bpm:
            frequencies = frequencies * 60
            freq_min, freq_max = self.freq_range
        else:
            freq_min = self.lowcut
            freq_max = self.highcut

        freq_mask = (frequencies >= freq_min) & (frequencies <= freq_max)
        frequencies = frequencies[freq_mask]
        Zxx = Zxx[freq_mask, :]

        if Zxx.size == 0:
            return None

        Zxx_db = 10 * np.log10(Zxx + 1e-10)

        fig, ax = plt.subplots(figsize=figsize)

        im = ax.pcolormesh(times, frequencies, Zxx_db, shading="gouraud", cmap=cmap)

        if ref_data is not None:
            ref_data = self.process_data(ref_data)
            if len(ref_data) == len(data):
                ref_times = np.arange(len(ref_data)) / self.fs
                if self.freq_bpm:
                    ref_data = ref_data * 60 / np.max(ref_data) * (freq_max - freq_min) / 2 + (freq_max + freq_min) / 2
                ax.plot(ref_times, ref_data, "w-", linewidth=1, label=ref_label, alpha=0.7)

        ax.set_ylabel("Frequency (BPM)" if self.freq_bpm else "Frequency (Hz)")
        ax.set_xlabel("Time (s)")
        ax.set_title(title)

        plt.colorbar(im, ax=ax, label="Power (dB)")

        plt.tight_layout()

        if output_file:
            plt.savefig(output_file, dpi=dpi)
            plt.close()
            return None

        return fig

    def plot_multi_channel_stft(
        self,
        data_dict: dict,
        output_file: Optional[str] = None,
        title: str = "Multi-Channel STFT",
        cmap: str = "jet",
        figsize: Tuple[float, float] = (12, 8),
        dpi: int = 150,
        normalize: bool = True,
    ) -> Optional[plt.Figure]:
        """
        绑制多通道STFT时频图

        Args:
            data_dict: {通道名: 数据} 字典
            output_file: 输出文件路径
            title: 图表标题
            cmap: 颜色映射
            figsize: 图表大小
            dpi: DPI
            normalize: 是否归一化

        Returns:
            Figure对象（如果未保存文件）
        """
        n_channels = len(data_dict)

        if n_channels == 0:
            return None

        fig, axes = plt.subplots(
            n_channels, 1, figsize=(figsize[0], figsize[1] * n_channels / 2), sharex=True
        )

        if n_channels == 1:
            axes = [axes]

        for ax, (channel_name, data) in zip(axes, data_dict.items()):
            data = self.process_data(data)

            if len(data) == 0:
                continue

            frequencies, times, Zxx = compute_stft(
                data, self.fs, self.window_sec, self.step_sec
            )

            if len(frequencies) == 0:
                continue

            if self.freq_bpm:
                frequencies = frequencies * 60
                freq_min, freq_max = self.freq_range
            else:
                freq_min = self.lowcut
                freq_max = self.highcut

            freq_mask = (frequencies >= freq_min) & (frequencies <= freq_max)
            frequencies = frequencies[freq_mask]
            Zxx = Zxx[freq_mask, :]

            if Zxx.size == 0:
                continue

            if normalize:
                Zxx = Zxx / (np.max(Zxx) + 1e-10)

            Zxx_db = 10 * np.log10(Zxx + 1e-10)

            im = ax.pcolormesh(times, frequencies, Zxx_db, shading="gouraud", cmap=cmap)
            ax.set_ylabel(f"{channel_name}\n(BPM)" if self.freq_bpm else f"{channel_name}\n(Hz)")
            ax.set_title(f"{channel_name}")

        axes[-1].set_xlabel("Time (s)")

        plt.suptitle(title)
        plt.tight_layout()

        if output_file:
            plt.savefig(output_file, dpi=dpi)
            plt.close()
            return None

        return fig
