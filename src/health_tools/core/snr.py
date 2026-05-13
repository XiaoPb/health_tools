"""SNR/CTR/Noise 产测计算模块

基于 Chelsea A 性能测试原理文档:
- SNR = 20 * log10(Avg / Std) dB (高通滤波后)
- Noise = 6 * std (转换为 uV)
- CTR = Ipd / Iled (nA/mA)

数据处理：剔除前后不稳定数据（默认各10秒），对中间稳定段计算。
文件总时长不满足 min_duration_seconds 时跳过。
"""

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt


ADC_RESOLUTION = 2**23
VREF = 1.8


@dataclass
class ChannelMetrics:
    channel: str
    snr_raw: float
    snr: float
    noise_raw: float
    noise: float
    ctr: float
    mean: float
    std: float
    min_val: float
    max_val: float


MIN_FILTER_SAMPLES = 15


def highpass_filter(
    data: np.ndarray, cutoff: float = 0.5, fs: float = 100.0, order: int = 2
) -> np.ndarray:
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
        skip_head_seconds: float = 10.0,
        skip_tail_seconds: float = 10.0,
        min_duration_seconds: float = 90.0,
    ):
        self.gain = gain
        self.current = current
        self.sample_rate = sample_rate
        self.skip_head_seconds = skip_head_seconds
        self.skip_tail_seconds = skip_tail_seconds
        self.min_duration_seconds = min_duration_seconds

    def _trim_data(self, values: np.ndarray) -> Optional[np.ndarray]:
        """剔除前后不稳定数据，返回中间稳定段。数据不足时返回 None。"""
        n = len(values)
        total_seconds = n / self.sample_rate
        if total_seconds < self.min_duration_seconds:
            return None

        head = int(self.skip_head_seconds * self.sample_rate)
        tail = int(self.skip_tail_seconds * self.sample_rate)
        end_idx = n - tail if tail > 0 else n

        if head >= end_idx:
            return None

        return values[head:end_idx]

    def calculate_snr(self, stable_data: np.ndarray) -> tuple:
        """对稳定段数据计算 (snr_raw_db, snr_filtered_db)"""
        if len(stable_data) < MIN_FILTER_SAMPLES:
            return 0.0, 0.0

        avg = float(np.mean(stable_data))
        std_raw = float(np.std(stable_data))

        filtered = highpass_filter(stable_data, cutoff=0.5, fs=self.sample_rate)
        std_filtered = float(np.std(filtered))

        snr_raw = 20.0 * np.log10(avg / std_raw) if (avg > 0 and std_raw > 0) else 0.0
        snr = 20.0 * np.log10(avg / std_filtered) if (avg > 0 and std_filtered > 0) else 0.0
        return snr_raw, snr

    def calculate_noise(self, stable_data: np.ndarray) -> tuple:
        """对稳定段数据计算 (noise_raw_uv, noise_filtered_uv)"""
        if len(stable_data) < MIN_FILTER_SAMPLES:
            return 0.0, 0.0

        std_raw = float(np.std(stable_data))
        noise_raw = rawdata_to_uv(6.0 * std_raw)

        filtered = highpass_filter(stable_data, cutoff=0.5, fs=self.sample_rate)
        std_filtered = float(np.std(filtered))
        noise = rawdata_to_uv(6.0 * std_filtered)

        return noise_raw, noise

    def calculate_ctr(self, stable_data: np.ndarray) -> float:
        """CTR = Ipd_mean / Iled (nA/mA)"""
        if self.current is None or self.current <= 0:
            return 0.0
        ipd_mean = float(np.mean(stable_data))
        return ipd_mean / self.current

    def calculate_channel(self, data: pd.Series, channel_name: str) -> Optional[ChannelMetrics]:
        values = pd.to_numeric(data, errors="coerce").dropna().values.astype(float)
        if len(values) == 0:
            return None

        stable_data = self._trim_data(values)
        if stable_data is None:
            return None

        mean_val = float(np.mean(stable_data))
        std_val = float(np.std(stable_data))
        min_val = float(np.min(stable_data))
        max_val = float(np.max(stable_data))

        snr_raw, snr = self.calculate_snr(stable_data)
        noise_raw, noise = self.calculate_noise(stable_data)
        ctr = self.calculate_ctr(stable_data)

        return ChannelMetrics(
            channel=channel_name,
            snr_raw=snr_raw,
            snr=snr,
            noise_raw=noise_raw,
            noise=noise,
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
                col for col in df.columns if pd.to_numeric(df[col], errors="coerce").notna().any()
            ]

        results = []
        for ch in channels:
            if ch not in df.columns:
                continue
            numeric = pd.to_numeric(df[ch], errors="coerce").dropna()
            if len(numeric) == 0 or (numeric == 0).all():
                continue
            metrics = self.calculate_channel(df[ch], ch)
            if metrics is not None:
                results.append(metrics)

        return results

    def check_duration(self, df: pd.DataFrame) -> bool:
        """检查数据时长是否满足最小要求"""
        total_seconds = len(df) / self.sample_rate
        return total_seconds >= self.min_duration_seconds

    def to_dataframe(self, results: List[ChannelMetrics], file_name: str = "") -> pd.DataFrame:
        records = []
        for m in results:
            record = {
                "file_name": file_name,
                "ch_num": m.channel,
                "snr_raw(dB)": round(m.snr_raw, 2),
                "snr(dB)": round(m.snr, 2),
                "ctr(nA/mA)": round(m.ctr, 4),
                "noise_raw(uV)": round(m.noise_raw, 2),
                "noise(uV)": round(m.noise, 2),
                "mean": round(m.mean, 2),
                "max": round(m.max_val, 2),
                "min": round(m.min_val, 2),
                "gain": self.gain if self.gain is not None else "",
                "current(mA)": self.current if self.current is not None else "",
            }
            records.append(record)
        return pd.DataFrame(records)
