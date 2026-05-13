from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import signal

from health_tools.core.stft import STFTPlotter

MAX_PLOT_POINTS = 50000


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

        fig, axes = plt.subplots(len(channels), 1, figsize=(12, 3 * len(channels)), sharex=True)
        if len(channels) == 1:
            axes = [axes]

        try:
            for ax, channel in zip(axes, channels):
                if channel in df.columns:
                    data = pd.to_numeric(df[channel], errors="coerce").values
                    ax.plot(_downsample(data), linewidth=0.5)
                    ax.set_ylabel(channel)
                    ax.grid(True, alpha=0.3)

            axes[-1].set_xlabel("Sample")
            plt.tight_layout()
            plt.savefig(output_file, dpi=self.dpi)
        finally:
            plt.close(fig)

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

        fig, axes = plt.subplots(len(channels), 1, figsize=(12, 3 * len(channels)), sharex=True)
        if len(channels) == 1:
            axes = [axes]

        try:
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
            plt.tight_layout()
            plt.savefig(output_file, dpi=self.dpi)
        finally:
            plt.close(fig)

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

        fig, ax = plt.subplots(figsize=(12, 6))
        try:
            nperseg = min(256, len(data) // 4)
            nperseg = max(nperseg, 16)

            freqs, times, Sxx = signal.spectrogram(data, fs=self.sample_rate, nperseg=nperseg)
            im = ax.pcolormesh(times, freqs, 10 * np.log10(Sxx + 1e-10), shading="gouraud")
            ax.set_ylabel("Frequency (Hz)")
            ax.set_xlabel("Time (s)")
            plt.colorbar(im, ax=ax, label="Power (dB)")
            plt.tight_layout()
            plt.savefig(output_file, dpi=self.dpi)
        finally:
            plt.close(fig)

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
