"""SNR/CTR/Noise 产测计算模块

基于 Chelsea A 性能测试原理文档:
- SNR = 20 * log10(Avg / Std) dB (高通滤波后)
- Noise = 6 * std (转换为 uV)
- CTR = Ipd / Iled (nA/mA)

数据处理：剔除前后不稳定数据（默认各10秒），对中间稳定段计算。
文件总时长不满足 min_duration_seconds 时跳过。
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt

from health_tools.utils.columns import expand_columns


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
    gain: Optional[float] = None
    current: Optional[float] = None


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


def _parse_bits(bits_str: str) -> Tuple[int, int]:
    """解析位段字符串 '[high:low]' 返回 (high, low)"""
    m = re.match(r"\[(\d+):(\d+)\]", bits_str)
    if not m:
        raise ValueError(f"无效位段格式: {bits_str}")
    return int(m.group(1)), int(m.group(2))


def _extract_bits(value: int, high: int, low: int) -> int:
    """从整数中提取 [high:low] 位段"""
    mask = (1 << (high - low + 1)) - 1
    return (int(value) >> low) & mask


class ChipInfoExtractor:
    """从 DataFrame 中根据 chip_info 配置提取增益和灯电流"""

    def __init__(self, chip_info: Dict[str, Any], gain_tia_map: Dict[str, Any]):
        self.chip_info = chip_info
        self.gain_tia_map = gain_tia_map

    def _find_source_column(
        self, source_pattern: str, df: pd.DataFrame, ch_idx: int
    ) -> Optional[str]:
        """根据 source 模式和通道索引找到实际列名"""
        expanded = expand_columns([source_pattern])
        if ch_idx < len(expanded) and expanded[ch_idx] in df.columns:
            return expanded[ch_idx]
        for col in expanded:
            if col in df.columns:
                return col
        return None

    def extract_gain(self, df: pd.DataFrame, channel_name: str) -> Optional[float]:
        """从数据中提取通道对应的增益值（TIA电阻 KΩ）"""
        gain_cfg = self.chip_info.get("gain")
        if not gain_cfg or gain_cfg.get("optional"):
            return None

        source = gain_cfg.get("source", "")
        bits_str = gain_cfg.get("bits")
        if not source or not bits_str:
            return None

        ch_idx = self._get_channel_index(channel_name)
        col = self._find_source_column(source, df, ch_idx)
        if col is None or col not in df.columns:
            return None

        values = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(values) == 0:
            return None

        median_val = int(values.median())
        high, low = _parse_bits(bits_str)
        gain_level = _extract_bits(median_val, high, low)

        tia_map = self.gain_tia_map.get("map", {})
        if gain_level in tia_map:
            return float(tia_map[gain_level])
        if str(gain_level) in tia_map:
            return float(tia_map[str(gain_level)])
        return float(gain_level)

    def extract_current(self, df: pd.DataFrame, channel_name: str) -> Optional[float]:
        """从数据中提取通道对应的 LED 电流（mA）"""
        current_cfg = self.chip_info.get("led_current_sum")
        if not current_cfg or current_cfg.get("optional"):
            return None

        source = current_cfg.get("source", "")
        bits_str = current_cfg.get("bits")
        if not source or not bits_str:
            return None

        ch_idx = self._get_channel_index(channel_name)
        col = self._find_source_column(source, df, ch_idx)
        if col is None or col not in df.columns:
            return None

        values = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(values) == 0:
            return None

        median_val = int(values.median())
        high, low = _parse_bits(bits_str)
        raw_current = _extract_bits(median_val, high, low)

        unit = current_cfg.get("unit", "")
        if unit == "0.1mA":
            return raw_current * 0.1
        return float(raw_current)

    def _get_channel_index(self, channel_name: str) -> int:
        """从通道名中提取数字索引"""
        m = re.search(r"(\d+)$", channel_name)
        return int(m.group(1)) if m else 0


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

    def calculate_ctr(
        self,
        stable_data: np.ndarray,
        current: Optional[float] = None,
        gain: Optional[float] = None,
        adc_full_scale: float = 8388608.0,
        adc_offset: float = 0.0,
    ) -> float:
        """CTR (nA/mA) = Ipd(nA) / Iled(mA)

        Ipd (pA) = RAWDATA_TO_PA(mean, RF) = RAWDATA_TO_UV(x) * 1000 / (2 * RF)
        Ipd (nA) = Ipd(pA) / 1000
        RAWDATA_TO_UV(x) = (x - ADC_OFFSET) * 1.8 * 1e6 / ADC_FULL_SCALE
        RF = gain (KΩ)
        """
        rf = gain if gain is not None else self.gain
        if rf is None or rf <= 0:
            return 0.0
        iled = current if current is not None else self.current
        if iled is None or iled <= 0:
            return 0.0
        mean_val = float(np.mean(stable_data))
        uv = (mean_val - adc_offset) * 1.8 * 1_000_000.0 / adc_full_scale
        ipd_pA = uv * 1000.0 / (2.0 * rf)
        ipd_nA = ipd_pA / 1000.0
        return ipd_nA / iled

    def calculate_channel(
        self,
        data: pd.Series,
        channel_name: str,
        ch_gain: Optional[float] = None,
        ch_current: Optional[float] = None,
        adc_full_scale: float = 8388608.0,
        adc_offset: float = 0.0,
    ) -> Optional[ChannelMetrics]:
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
        ctr = self.calculate_ctr(
            stable_data,
            current=ch_current,
            gain=ch_gain,
            adc_full_scale=adc_full_scale,
            adc_offset=adc_offset,
        )

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
            gain=ch_gain if ch_gain is not None else self.gain,
            current=ch_current if ch_current is not None else self.current,
        )

    def calculate(
        self,
        df: pd.DataFrame,
        channels: Optional[List[str]] = None,
        extractor: Optional["ChipInfoExtractor"] = None,
        adc_full_scale: float = 8388608.0,
        adc_offset: float = 0.0,
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

            ch_gain = None
            ch_current = None
            if extractor and self.gain is None:
                ch_gain = extractor.extract_gain(df, ch)
            if extractor and self.current is None:
                ch_current = extractor.extract_current(df, ch)

            metrics = self.calculate_channel(
                df[ch],
                ch,
                ch_gain=ch_gain,
                ch_current=ch_current,
                adc_full_scale=adc_full_scale,
                adc_offset=adc_offset,
            )
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
                "ctr(nA/mA)": round(m.ctr, 2),
                "noise_raw(uV)": round(m.noise_raw, 2),
                "noise(uV)": round(m.noise, 2),
                "mean": round(m.mean, 2),
                "max": round(m.max_val, 2),
                "min": round(m.min_val, 2),
                "gain": round(m.gain, 2) if m.gain is not None else "",
                "current(mA)": round(m.current, 2) if m.current is not None else "",
            }
            records.append(record)
        return pd.DataFrame(records)
