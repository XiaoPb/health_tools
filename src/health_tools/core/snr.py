"""SNR/CTR/Noise 产测计算模块

基于 Chelsea A 性能测试原理文档:
- SNR = 20 * log10(Avg / Std) dB (高通滤波后)
- Noise = 6 * std (转换为 uV)
- CTR = Ipd / Iled (nA/mA)
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt


ADC_RESOLUTION = 2**23
VREF = 1.8


@dataclass
class ChannelMetrics:
    channel: str
    snr_db: float
    noise_uv: float
    ctr: float
    mean: float
    std: float
    min_val: float
    max_val: float


MIN_FILTER_SAMPLES = 15


def highpass_filter(data: np.ndarray, cutoff: float = 0.5, fs: float = 100.0, order: int = 2) -> np.ndarray:
    if len(data) < MIN_FILTER_SAMPLES:
        return data
    nyq = fs / 2.0
    normalized_cutoff = cutoff / nyq
    if normalized_cutoff >= 1.0:
        normalized_cutoff = 0.99
    b, a = butter(order, normalized_cutoff, btype="high")
    return filtfilt(b, a, data)


def rawdata_to_uv(rawdata_value: float) -> float:
    return rawdata_value / ADC_RESOLUTION * VREF * 1_000_000


class SNRCalculator:
    def __init__(
        self,
        gain: Optional[float] = None,
        current: Optional[float] = None,
        sample_rate: float = 100.0,
        skip_seconds: float = 10.0,
        total_seconds: float = 90.0,
        middle_seconds: float = 50.0,
    ):
        self.gain = gain
        self.current = current
        self.sample_rate = sample_rate
        self.skip_seconds = skip_seconds
        self.total_seconds = total_seconds
        self.middle_seconds = middle_seconds

    def calculate_snr(self, values: np.ndarray) -> float:
        """SNR = 20 * log10(Avg / Std) dB, 高通滤波去基线后计算"""
        n = len(values)
        skip_samples = int(self.skip_seconds * self.sample_rate)
        if skip_samples >= n:
            skip_samples = 0

        remaining = values[skip_samples:]
        n_remaining = len(remaining)

        mid_start = max(0, (n_remaining - int(self.middle_seconds * self.sample_rate)) // 2)
        mid_end = min(n_remaining, mid_start + int(self.middle_seconds * self.sample_rate))
        middle_data = remaining[mid_start:mid_end]

        if len(middle_data) < 10:
            return 0.0

        avg = float(np.mean(middle_data))

        filtered = highpass_filter(remaining, cutoff=0.5, fs=self.sample_rate)
        filtered_middle = filtered[mid_start:mid_end]
        std = float(np.std(filtered_middle))

        if std <= 0 or avg <= 0:
            return 0.0

        return 20.0 * np.log10(avg / std)

    def calculate_noise(self, values: np.ndarray) -> float:
        """Noise = 6 * std(filtered_data), 转换为 uV"""
        filtered = highpass_filter(values, cutoff=0.5, fs=self.sample_rate)
        n = len(filtered)
        use_data = filtered[n // 2:] if n > 100 else filtered

        std = float(np.std(use_data))
        noise_raw = 6.0 * std
        return rawdata_to_uv(noise_raw)

    def calculate_ctr(self, ipd_values: np.ndarray) -> float:
        """CTR = Ipd_mean / Iled (nA/mA)"""
        if self.current is None or self.current <= 0:
            return 0.0
        ipd_mean = float(np.mean(ipd_values))
        return ipd_mean / self.current

    def calculate_channel(self, data: pd.Series, channel_name: str) -> ChannelMetrics:
        values = pd.to_numeric(data, errors="coerce").dropna().values.astype(float)
        if len(values) == 0:
            return ChannelMetrics(
                channel=channel_name,
                snr_db=0.0, noise_uv=0.0, ctr=0.0,
                mean=0.0, std=0.0, min_val=0.0, max_val=0.0,
            )

        mean_val = float(np.mean(values))
        std_val = float(np.std(values))
        min_val = float(np.min(values))
        max_val = float(np.max(values))

        snr_db = self.calculate_snr(values)
        noise_uv = self.calculate_noise(values)
        ctr = self.calculate_ctr(values)

        return ChannelMetrics(
            channel=channel_name,
            snr_db=snr_db,
            noise_uv=noise_uv,
            ctr=ctr,
            mean=mean_val,
            std=std_val,
            min_val=min_val,
            max_val=max_val,
        )

    def calculate(
        self, df: pd.DataFrame, channels: Optional[List[str]] = None
    ) -> List[ChannelMetrics]:
        if channels is None:
            channels = [
                col for col in df.columns
                if pd.to_numeric(df[col], errors="coerce").notna().any()
            ]

        results = []
        for ch in channels:
            if ch in df.columns:
                metrics = self.calculate_channel(df[ch], ch)
                results.append(metrics)

        return results

    def to_dataframe(self, results: List[ChannelMetrics]) -> pd.DataFrame:
        records = []
        for m in results:
            record = {
                "Channel": m.channel,
                "SNR(dB)": round(m.snr_db, 2),
                "Noise(uV)": round(m.noise_uv, 2),
                "CTR(nA/mA)": round(m.ctr, 4),
                "Mean": round(m.mean, 2),
                "Std": round(m.std, 2),
                "Min": round(m.min_val, 2),
                "Max": round(m.max_val, 2),
            }
            if self.gain is not None:
                record["Gain"] = self.gain
            if self.current is not None:
                record["Current(mA)"] = self.current
            records.append(record)
        return pd.DataFrame(records)
