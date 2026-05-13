"""产测计算模块（SNR/CTR/Noise）

基于 Chelsea A 性能测试原理文档:
- SNR = 20 * log10(Avg / Std) dB (高通滤波后)
- Noise = 6 * std (转换为 uV)
- CTR = Ipd / Iled (nA/mA)

rawdata_uv = (rawdata_value - adc_offset) / adc_full_scale * adc_vref * 1_000_000
ipd_pA = rawdata_uv / (tia_ratio * gain_tia_map[gain]) * 1000
ctr = ipd_pA * 1000 / led_current_sum (nA/mA)
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt

from health_tools.utils.columns import expand_columns


@dataclass
class ChannelMetrics:
    channel: str
    snr: float
    noise: float
    ctr: float
    mean: float
    std: float
    min_val: float
    max_val: float
    sample_rate: float = 100.0
    duration_seconds: float = 0.0
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


def rawdata_to_uv(
    value: float,
    adc_full_scale: float,
    adc_offset: float,
    adc_vref: float,
) -> float:
    return (value - adc_offset) / adc_full_scale * adc_vref * 1_000_000.0


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
        m = re.search(r"(\d+)$", channel_name)
        return int(m.group(1)) if m else 0


class FactoryCalculator:
    def __init__(
        self,
        gain: Optional[float] = None,
        current: Optional[float] = None,
        sample_rate: float = 100.0,
        adc_full_scale: float = 8388608.0,
        adc_offset: float = 0.0,
        adc_vref: float = 1.8,
        tia_ratio: float = 2.0,
        snr_config: Optional[Dict[str, Any]] = None,
        ctr_config: Optional[Dict[str, Any]] = None,
        noise_config: Optional[Dict[str, Any]] = None,
    ):
        self.gain = gain
        self.current = current
        self.sample_rate = sample_rate
        self.adc_full_scale = adc_full_scale
        self.adc_offset = adc_offset
        self.adc_vref = adc_vref
        self.tia_ratio = tia_ratio

        self.snr_cfg = snr_config or {
            "skip_head_seconds": 10.0,
            "skip_tail_seconds": 10.0,
            "min_duration_seconds": 90.0,
        }
        self.ctr_cfg = ctr_config or {
            "skip_head_seconds": 1.0,
            "skip_tail_seconds": 0.0,
            "min_duration_seconds": 2.0,
        }
        self.noise_cfg = noise_config or {
            "skip_head_seconds": 2.0,
            "skip_tail_seconds": 0.0,
            "min_duration_seconds": 4.0,
        }

    def _trim_data(self, values: np.ndarray, metric: str) -> Optional[np.ndarray]:
        """按指标类型剔除前后不稳定数据，数据不足时返回 None。"""
        cfg = getattr(self, f"{metric}_cfg")
        n = len(values)
        total_seconds = n / self.sample_rate
        if total_seconds < cfg.get("min_duration_seconds", 0):
            return None

        head = int(cfg.get("skip_head_seconds", 0) * self.sample_rate)
        tail = int(cfg.get("skip_tail_seconds", 0) * self.sample_rate)
        end_idx = n - tail if tail > 0 else n

        if head >= end_idx:
            return None
        return values[head:end_idx]

    def calculate_snr(self, stable_data: np.ndarray) -> tuple:
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
        if len(stable_data) < MIN_FILTER_SAMPLES:
            return 0.0, 0.0

        std_raw = float(np.std(stable_data))
        noise_raw = rawdata_to_uv(
            6.0 * std_raw, self.adc_full_scale, self.adc_offset, self.adc_vref
        )

        filtered = highpass_filter(stable_data, cutoff=0.5, fs=self.sample_rate)
        std_filtered = float(np.std(filtered))
        noise = rawdata_to_uv(
            6.0 * std_filtered, self.adc_full_scale, self.adc_offset, self.adc_vref
        )
        return noise_raw, noise

    def calculate_ctr(
        self,
        stable_data: np.ndarray,
        current: Optional[float] = None,
        gain: Optional[float] = None,
    ) -> float:
        """CTR (nA/mA) = ipd_nA / iled_mA

        rawdata_uv = (x - adc_offset) / adc_full_scale * adc_vref * 1e6
        ipd_pA = rawdata_uv / (tia_ratio * RF_KΩ) * 1000
        ctr = ipd_pA / 1000 / iled_mA  (nA/mA)
        """
        rf = gain if gain is not None else self.gain
        if rf is None or rf <= 0:
            return 0.0
        iled = current if current is not None else self.current
        if iled is None or iled <= 0:
            return 0.0

        mean_val = float(np.mean(stable_data))
        uv = rawdata_to_uv(mean_val, self.adc_full_scale, self.adc_offset, self.adc_vref)
        ipd_pA = uv * 1000.0 / (self.tia_ratio * rf)
        ipd_nA = ipd_pA / 1000.0
        return ipd_nA / iled

    def calculate_channel(
        self,
        data: pd.Series,
        channel_name: str,
        ch_gain: Optional[float] = None,
        ch_current: Optional[float] = None,
    ) -> Optional[ChannelMetrics]:
        values = pd.to_numeric(data, errors="coerce").dropna().values.astype(float)
        if len(values) == 0:
            return None

        snr_data = self._trim_data(values, "snr")
        ctr_data = self._trim_data(values, "ctr")
        noise_data = self._trim_data(values, "noise")

        if snr_data is None and ctr_data is None and noise_data is None:
            return None

        snr = 0.0
        noise = 0.0
        ctr = 0.0

        if snr_data is not None:
            _, snr = self.calculate_snr(snr_data)
        if noise_data is not None:
            _, noise = self.calculate_noise(noise_data)
        if ctr_data is not None:
            ctr = self.calculate_ctr(ctr_data, current=ch_current, gain=ch_gain)

        ref_data = (
            snr_data if snr_data is not None else (ctr_data if ctr_data is not None else noise_data)
        )
        mean_val = float(np.mean(ref_data))
        std_val = float(np.std(ref_data))
        min_val = float(np.min(ref_data))
        max_val = float(np.max(ref_data))

        duration_seconds = len(values) / self.sample_rate

        return ChannelMetrics(
            channel=channel_name,
            snr=snr,
            noise=noise,
            ctr=ctr,
            mean=mean_val,
            std=std_val,
            min_val=min_val,
            max_val=max_val,
            sample_rate=self.sample_rate,
            duration_seconds=duration_seconds,
            gain=ch_gain if ch_gain is not None else self.gain,
            current=ch_current if ch_current is not None else self.current,
        )

    def calculate(
        self,
        df: pd.DataFrame,
        channels: Optional[List[str]] = None,
        extractor: Optional["ChipInfoExtractor"] = None,
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

            metrics = self.calculate_channel(df[ch], ch, ch_gain=ch_gain, ch_current=ch_current)
            if metrics is not None:
                results.append(metrics)

        return results

    def to_dataframe(self, results: List[ChannelMetrics], file_name: str = "") -> pd.DataFrame:
        records = []
        for m in results:
            record = {
                "file_name": file_name,
                "ch_num": m.channel,
                "snr(dB)": round(m.snr, 2),
                "ctr(nA/mA)": round(m.ctr, 2),
                "noise(uV)": round(m.noise, 2),
                "mean": round(m.mean, 2),
                "max": round(m.max_val, 2),
                "min": round(m.min_val, 2),
                "gain": round(m.gain, 2) if m.gain is not None else "",
                "current(mA)": round(m.current, 2) if m.current is not None else "",
                "sample_rate(Hz)": round(m.sample_rate, 1),
                "duration(s)": round(m.duration_seconds, 1),
            }
            records.append(record)
        return pd.DataFrame(records)
