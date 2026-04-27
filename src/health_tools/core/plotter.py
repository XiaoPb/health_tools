from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import signal


@dataclass
class PlotConfig:
    sample_rate: Optional[int] = None
    window: int = 10
    overlap: float = 0.5
    fmt: str = "png"
    dpi: int = 150


class DataPlotter:
    def __init__(
        self,
        sample_rate: Optional[int] = None,
        window: int = 10,
        overlap: float = 0.5,
        fmt: str = "png",
        dpi: int = 150,
    ):
        self.sample_rate = sample_rate
        self.window = window
        self.overlap = overlap
        self.fmt = fmt
        self.dpi = dpi

    def plot_time(
        self,
        df: pd.DataFrame,
        output_file: Path,
        channels: Optional[List[str]] = None,
    ) -> None:
        if channels is None:
            channels = [col for col in df.columns if col != "timestamp"]

        fig, axes = plt.subplots(len(channels), 1, figsize=(12, 3 * len(channels)), sharex=True)
        if len(channels) == 1:
            axes = [axes]

        for ax, channel in zip(axes, channels):
            if channel in df.columns:
                data = pd.to_numeric(df[channel], errors="coerce")
                ax.plot(data.values, linewidth=0.5)
                ax.set_ylabel(channel)
                ax.grid(True, alpha=0.3)

        axes[-1].set_xlabel("Sample")
        plt.tight_layout()
        plt.savefig(output_file, dpi=self.dpi)
        plt.close()

    def plot_freq(
        self,
        df: pd.DataFrame,
        output_file: Path,
        channels: Optional[List[str]] = None,
    ) -> None:
        if channels is None:
            channels = [col for col in df.columns if col != "timestamp"]

        sample_rate = self.sample_rate or 100

        fig, axes = plt.subplots(len(channels), 1, figsize=(12, 3 * len(channels)), sharex=True)
        if len(channels) == 1:
            axes = [axes]

        for ax, channel in zip(axes, channels):
            if channel in df.columns:
                data = pd.to_numeric(df[channel], errors="coerce").dropna().values

                if len(data) > 0:
                    freqs, psd = signal.welch(data, fs=sample_rate, nperseg=min(256, len(data)))
                    ax.semilogy(freqs, psd, linewidth=0.5)
                    ax.set_ylabel(f"{channel}\nPSD")
                    ax.grid(True, alpha=0.3)

        axes[-1].set_xlabel("Frequency (Hz)")
        plt.tight_layout()
        plt.savefig(output_file, dpi=self.dpi)
        plt.close()

    def plot_spectrogram(
        self,
        df: pd.DataFrame,
        output_file: Path,
        channel: str,
    ) -> None:
        if channel not in df.columns:
            return

        sample_rate = self.sample_rate or 100
        data = pd.to_numeric(df[channel], errors="coerce").dropna().values

        if len(data) == 0:
            return

        fig, ax = plt.subplots(figsize=(12, 6))

        nperseg = min(256, len(data) // 4)
        if nperseg < 8:
            nperseg = 8

        freqs, times, Sxx = signal.spectrogram(data, fs=sample_rate, nperseg=nperseg)

        im = ax.pcolormesh(times, freqs, 10 * np.log10(Sxx + 1e-10), shading="gouraud")
        ax.set_ylabel("Frequency (Hz)")
        ax.set_xlabel("Time (s)")
        plt.colorbar(im, ax=ax, label="Power (dB)")

        plt.tight_layout()
        plt.savefig(output_file, dpi=self.dpi)
        plt.close()
