from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from matplotlib import rcParams
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from scipy import signal

from health_tools.core.ppg_analysis import (
    SignalAnalysisError,
    bandpass_signal,
    compute_pi,
    compute_single_sided_fft,
    prepare_signal,
)
from health_tools.core.stft import STFTPlotter

MAX_PLOT_POINTS = 50000


def _new_figure(figsize: Tuple[float, float]) -> Figure:
    """创建不依赖 pyplot 全局 GUI 后端的绘图画布。"""
    figure = Figure(figsize=figsize)
    FigureCanvasAgg(figure)
    return figure


@dataclass
class PlotConfig:
    sample_rate: Optional[int] = None
    window: int = 10
    overlap: float = 0.5
    fmt: str = "png"
    dpi: int = 150


def _downsample(data: np.ndarray, max_points: int = MAX_PLOT_POINTS) -> np.ndarray:
    if len(data) <= max_points:
        return data
    step = len(data) // max_points
    return data[::step]


def _peak_symmetric_limit(signals: List[np.ndarray]) -> float:
    """按峰值数量最多的信号峰高分布确定对称 Y 轴半幅。"""
    candidates = []
    for values in signals:
        finite = np.asarray(values, dtype=float)
        finite = finite[np.isfinite(finite)]
        if finite.size < 3:
            candidates.append((0, 0.0))
            continue
        peaks, _ = signal.find_peaks(np.abs(finite))
        heights = np.abs(finite[peaks])
        heights = heights[heights > np.finfo(float).eps]
        candidates.append((len(heights), float(np.max(heights)) if heights.size else 0.0))

    if not candidates:
        return 1.0
    dominant_index = max(range(len(candidates)), key=lambda index: candidates[index][0])
    dominant = np.asarray(signals[dominant_index], dtype=float)
    dominant = dominant[np.isfinite(dominant)]
    peaks, _ = signal.find_peaks(np.abs(dominant))
    heights = np.abs(dominant[peaks])
    heights = heights[heights > np.finfo(float).eps]
    if heights.size:
        bins = min(10, max(3, int(np.sqrt(len(heights)))))
        _, edges = np.histogram(heights, bins=bins)
        counts, _ = np.histogram(heights, bins=edges)
        mode = int(np.argmax(counts))
        limit = float(edges[mode + 1])
    else:
        limit = float(np.nanmax(np.abs(dominant))) if dominant.size else 1.0
    return max(limit * 1.05, np.finfo(float).eps)


class DataPlotter:
    def __init__(
        self,
        sample_rate: Optional[int] = None,
        window: int = 10,
        overlap: float = 0.5,
        fmt: str = "png",
        dpi: int = 150,
        bandpass: Optional[str] = None,
        remove_baseline: bool = True,
        baseline_method: str = "mean",
        freq_bpm: bool = True,
        freq_range: Tuple[float, float] = (30.0, 240.0),
    ):
        self.sample_rate = sample_rate if sample_rate else 25
        self.window = window
        self.overlap = overlap
        self.fmt = fmt
        self.dpi = dpi

        self.bandpass = bandpass
        self.remove_baseline_flag = remove_baseline
        self.baseline_method = baseline_method
        self.freq_bpm = freq_bpm
        self.freq_range = freq_range

        if bandpass:
            try:
                parts = bandpass.split("-")
                self.lowcut = float(parts[0])
                self.highcut = float(parts[1])
            except (ValueError, IndexError):
                self.lowcut = 0.5
                self.highcut = 4.0
        else:
            self.lowcut = 0.5
            self.highcut = 4.0

    def plot_time(
        self,
        df: pd.DataFrame,
        output_file: Path,
        channels: Optional[List[str]] = None,
    ) -> None:
        if channels is None:
            channels = [col for col in df.columns if col != "timestamp"]
        if not channels:
            return

        fig = _new_figure((12, 3 * len(channels)))
        axes = np.atleast_1d(fig.subplots(len(channels), 1, sharex=True))

        for ax, channel in zip(axes, channels):
            if channel in df.columns:
                data = pd.to_numeric(df[channel], errors="coerce").values
                ax.plot(_downsample(data), linewidth=0.5)
                ax.set_ylabel(channel)
                ax.grid(True, alpha=0.3)

        axes[-1].set_xlabel("Sample")
        fig.tight_layout()
        fig.savefig(output_file, dpi=self.dpi)

    def plot_freq(
        self,
        df: pd.DataFrame,
        output_file: Path,
        channels: Optional[List[str]] = None,
    ) -> None:
        if channels is None:
            channels = [col for col in df.columns if col != "timestamp"]
        if not channels:
            return

        sample_rate = self.sample_rate

        fig = _new_figure((12, 3 * len(channels)))
        axes = np.atleast_1d(fig.subplots(len(channels), 1, sharex=True))

        for ax, channel in zip(axes, channels):
            if channel in df.columns:
                data = pd.to_numeric(df[channel], errors="coerce").dropna().values
                if len(data) > 0:
                    nperseg = min(256, len(data))
                    freqs, psd = signal.welch(data, fs=sample_rate, nperseg=nperseg)
                    ax.semilogy(freqs, psd, linewidth=0.5)
                    ax.set_ylabel(f"{channel}\nPSD")
                    ax.grid(True, alpha=0.3)

        axes[-1].set_xlabel("Frequency (Hz)")
        fig.tight_layout()
        fig.savefig(output_file, dpi=self.dpi)

    def plot_ac(
        self,
        df: pd.DataFrame,
        output_file: Path,
        channels: List[str],
        acc_columns: List[str],
        r_column: Optional[str] = None,
    ) -> None:
        """绘制三轴 ACC、滤波后 PPG、PI 和 R。"""
        if not channels:
            raise SignalAnalysisError("AC 绘图至少需要 1 个 PPG 通道")
        if len(channels) > 4:
            raise SignalAnalysisError("每张 AC 图最多支持 4 个 PPG 通道")
        missing = [column for column in channels + acc_columns if column not in df.columns]
        if r_column and r_column not in df.columns:
            missing.append(r_column)
        if missing:
            raise SignalAnalysisError(f"输入缺少绘图列: {', '.join(missing)}")
        if len(acc_columns) != 3:
            raise SignalAnalysisError("AC 绘图需要完整的 ACC X/Y/Z 三轴")

        time = np.arange(len(df), dtype=float) / self.sample_rate
        fig = _new_figure((14, 10))
        base_axes = np.atleast_1d(fig.subplots(3, 1, sharex=True))
        acc_axes = [base_axes[0], base_axes[0].twinx(), base_axes[0].twinx()]
        acc_axes[2].spines["right"].set_position(("axes", 1.12))
        r_axis = base_axes[2].twinx()
        colors = rcParams["axes.prop_cycle"].by_key()["color"]

        for axis, column in zip(acc_axes, acc_columns):
            acc = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)
            axis.plot(time, acc, linewidth=0.6, label=column)
            axis.set_ylabel(column)
            axis.legend(loc="upper right")
            axis.grid(True, alpha=0.3)

        filtered_signals = []
        pi_values = {}
        for index, channel in enumerate(channels):
            raw = prepare_signal(df[channel])
            filtered = bandpass_signal(
                raw,
                self.sample_rate,
                self.lowcut,
                self.highcut,
                remove_baseline=self.remove_baseline_flag,
                baseline_method=self.baseline_method,
            )
            pi = compute_pi(raw, filtered, self.sample_rate)
            filtered_signals.append(filtered)
            pi_values[channel] = pi
            color = colors[index % len(colors)]
            base_axes[1].plot(time, filtered, linewidth=0.7, color=color, label=channel)
            base_axes[2].plot(time, pi, linewidth=0.8, color=color, label=channel)

        limit = _peak_symmetric_limit(filtered_signals)
        base_axes[1].set_ylim(-limit, limit)
        if r_column:
            r_values = pd.to_numeric(df[r_column], errors="coerce").to_numpy(dtype=float)
        else:
            if "CH0" not in pi_values or "CH1" not in pi_values:
                raise SignalAnalysisError("AC 绘图未同时包含 CH0 和 CH1，无法计算 R 曲线")
            denominator = pi_values["CH1"].to_numpy(dtype=float)
            numerator = pi_values["CH0"].to_numpy(dtype=float)
            r_values = (
                np.divide(
                    numerator,
                    denominator,
                    out=np.full_like(numerator, np.nan),
                    where=np.isfinite(denominator) & (np.abs(denominator) > np.finfo(float).eps),
                )
                * 10000.0
            )
        r_axis.plot(time, r_values, linewidth=0.8, color="#111827", label="R")
        r_axis.set_ylabel("R")
        r_axis.legend(loc="lower right")
        r_axis.grid(False)

        base_axes[1].set_ylabel("Filtered PPG")
        base_axes[2].set_ylabel("PI (%)")
        base_axes[2].set_xlabel("Time (s)")
        for ax in base_axes[1:]:
            ax.legend(loc="upper right")
            ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(output_file, dpi=self.dpi)

    def plot_fft(self, df: pd.DataFrame, output_file: Path, channel: str) -> None:
        """使用独立 Y 轴叠加原始与带通后 PPG 的单边 FFT。"""
        if channel not in df.columns:
            raise SignalAnalysisError(f"输入缺少 PPG 通道: {channel}")
        raw = prepare_signal(df[channel])
        filtered = bandpass_signal(
            raw,
            self.sample_rate,
            self.lowcut,
            self.highcut,
            remove_baseline=self.remove_baseline_flag,
            baseline_method=self.baseline_method,
        )
        raw_freqs, raw_amplitude = compute_single_sided_fft(raw, self.sample_rate)
        filtered_freqs, filtered_amplitude = compute_single_sided_fft(filtered, self.sample_rate)

        fig = _new_figure((12, 5))
        raw_axis = fig.subplots()
        filtered_axis = raw_axis.twinx()
        raw_line = raw_axis.plot(
            raw_freqs, raw_amplitude, color="#2563EB", linewidth=0.8, label="Raw FFT"
        )[0]
        filtered_line = filtered_axis.plot(
            filtered_freqs,
            filtered_amplitude,
            color="#DC2626",
            linewidth=0.8,
            label="Filtered FFT",
        )[0]
        raw_axis.set_xlabel("Frequency (Hz)")
        raw_axis.set_ylabel("Raw amplitude", color=raw_line.get_color())
        filtered_axis.set_ylabel("Filtered amplitude", color=filtered_line.get_color())
        raw_axis.set_xlim(0, self.sample_rate / 2)
        raw_axis.grid(True, alpha=0.3)
        raw_axis.set_title(f"FFT - {channel}")
        raw_axis.legend([raw_line, filtered_line], ["Raw FFT", "Filtered FFT"], loc="upper right")
        fig.tight_layout()
        fig.savefig(output_file, dpi=self.dpi)

    def plot_spectrogram(
        self,
        df: pd.DataFrame,
        output_file: Path,
        channel: str,
    ) -> None:
        if channel not in df.columns:
            return

        data = pd.to_numeric(df[channel], errors="coerce").dropna().values
        if len(data) < 16:
            return

        fig = _new_figure((12, 6))
        ax = fig.subplots()
        nperseg = min(256, len(data) // 4)
        nperseg = max(nperseg, 16)

        freqs, times, Sxx = signal.spectrogram(data, fs=self.sample_rate, nperseg=nperseg)
        im = ax.pcolormesh(times, freqs, 10 * np.log10(Sxx + 1e-10), shading="gouraud")
        ax.set_ylabel("Frequency (Hz)")
        ax.set_xlabel("Time (s)")
        fig.colorbar(im, ax=ax, label="Power (dB)")
        fig.tight_layout()
        fig.savefig(output_file, dpi=self.dpi)

    def plot_stft(
        self,
        df: pd.DataFrame,
        output_file: Path,
        channels: Optional[List[str]] = None,
        ref_column: Optional[str] = None,
    ) -> None:
        if channels is None:
            channels = [col for col in df.columns if col != "timestamp"]
        if not channels:
            return

        plotter = STFTPlotter(
            fs=self.sample_rate,
            window_sec=self.window,
            step_sec=self.window * (1 - self.overlap),
            lowcut=self.lowcut,
            highcut=self.highcut,
            remove_baseline_method=self.baseline_method if self.remove_baseline_flag else None,
            freq_bpm=self.freq_bpm,
            freq_range=self.freq_range,
        )

        ref_data = None
        if ref_column and ref_column in df.columns:
            ref_data = pd.to_numeric(df[ref_column], errors="coerce").fillna(0).values

        if len(channels) == 1:
            data = pd.to_numeric(df[channels[0]], errors="coerce").dropna().values
            plotter.plot_stft(
                data,
                str(output_file),
                title=f"STFT - {channels[0]}",
                ref_data=ref_data,
                ref_label=ref_column or "Reference",
            )
        else:
            data_dict = {}
            for channel in channels:
                if channel in df.columns:
                    data_dict[channel] = pd.to_numeric(df[channel], errors="coerce").dropna().values

            if data_dict:
                plotter.plot_multi_channel_stft(
                    data_dict,
                    str(output_file),
                    title="Multi-Channel STFT",
                    ref_data=ref_data,
                    ref_label=ref_column or "Reference",
                )

    def plot_chip_stft(
        self,
        df: pd.DataFrame,
        output_dir: Path,
        stem: str,
    ) -> List[str]:
        plotter = STFTPlotter(
            fs=self.sample_rate,
            window_sec=self.window,
            step_sec=self.window * (1 - self.overlap),
            lowcut=self.lowcut,
            highcut=self.highcut,
            remove_baseline_method=self.baseline_method if self.remove_baseline_flag else None,
            freq_bpm=self.freq_bpm,
            freq_range=self.freq_range,
        )

        ipd_cols = [c for c in df.columns if c.startswith("Ipd")]
        nonzero_ipd = []
        for col in ipd_cols:
            vals = pd.to_numeric(df[col], errors="coerce").fillna(0)
            if (vals != 0).any():
                nonzero_ipd.append(col)

        output_files = []
        for channel in nonzero_ipd:
            out_file = output_dir / f"{stem}_stft_{channel}.png"
            plotter.plot_chip_stft(df, str(out_file), channel)
            output_files.append(str(out_file))

        return output_files
