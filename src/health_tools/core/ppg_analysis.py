"""PPG AC、PI 与 FFT 信号分析。"""

from __future__ import annotations

import re
from typing import List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import signal


class SignalAnalysisError(ValueError):
    """信号无法按请求完成分析。"""


def prepare_signal(values: Sequence[object]) -> np.ndarray:
    """把输入转换为连续浮点信号，并线性填充缺失值。"""
    series = pd.Series(values, dtype="object")
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() == 0:
        raise SignalAnalysisError("信号不包含有效数值")
    return numeric.interpolate(method="linear", limit_direction="both").to_numpy(dtype=float)


def validate_bandpass(sample_rate: float, lowcut: float, highcut: float) -> None:
    """校验带通范围满足数字滤波条件。"""
    if sample_rate <= 0:
        raise SignalAnalysisError("采样率必须大于 0")
    if lowcut <= 0 or highcut <= lowcut:
        raise SignalAnalysisError("带通范围必须满足 0 < low < high")
    if highcut >= sample_rate / 2:
        raise SignalAnalysisError(
            f"带通上限 {highcut:g} Hz 必须小于奈奎斯特频率 {sample_rate / 2:g} Hz"
        )


def bandpass_signal(
    values: Sequence[object],
    sample_rate: float,
    lowcut: float = 0.5,
    highcut: float = 4.0,
    order: int = 4,
    remove_baseline: bool = True,
    baseline_method: str = "mean",
) -> np.ndarray:
    """去基线后执行 Butterworth 零相位带通滤波。"""
    validate_bandpass(sample_rate, lowcut, highcut)
    data = prepare_signal(values)
    if remove_baseline:
        if baseline_method == "mean":
            data = data - np.mean(data)
        elif baseline_method == "median":
            data = data - np.median(data)
        else:
            raise SignalAnalysisError(f"不支持的基线去除方法: {baseline_method}")

    sos = signal.butter(order, [lowcut, highcut], btype="bandpass", fs=sample_rate, output="sos")
    try:
        return signal.sosfiltfilt(sos, data)
    except ValueError as exc:
        raise SignalAnalysisError(f"信号长度不足以执行带通滤波: {len(data)} 个采样点") from exc


def compute_pi(
    raw_values: Sequence[object],
    ac_values: Sequence[object],
    sample_rate: float,
    window_seconds: float = 5.0,
) -> pd.Series:
    """使用居中的完整滑动窗口计算 PI 百分比。"""
    raw = prepare_signal(raw_values)
    ac = prepare_signal(ac_values)
    if len(raw) != len(ac):
        raise SignalAnalysisError("原始 PPG 与 AC 信号长度不一致")
    window_size = int(round(sample_rate * window_seconds))
    if window_size < 1:
        raise SignalAnalysisError("PI 滑动窗口必须至少包含 1 个采样点")

    dc_mean = pd.Series(raw).rolling(window_size, center=True, min_periods=window_size).mean()
    ac_rms = (
        pd.Series(np.square(ac)).rolling(window_size, center=True, min_periods=window_size).mean()
    ) ** 0.5
    valid_dc = dc_mean.abs() > np.finfo(float).eps
    return (ac_rms / dc_mean * 100).where(valid_dc)


def compute_single_sided_fft(
    values: Sequence[object], sample_rate: float
) -> Tuple[np.ndarray, np.ndarray]:
    """计算排除 0 Hz 的单边幅值谱。"""
    if sample_rate <= 0:
        raise SignalAnalysisError("采样率必须大于 0")
    data = prepare_signal(values)
    if len(data) < 2:
        raise SignalAnalysisError("FFT 至少需要 2 个采样点")

    spectrum = np.fft.rfft(data)
    amplitude = np.abs(spectrum) * (2.0 / len(data))
    if len(data) % 2 == 0:
        amplitude[-1] /= 2.0
    frequencies = np.fft.rfftfreq(len(data), d=1.0 / sample_rate)
    return frequencies[1:], amplitude[1:]


def resolve_ppg_channels(df: pd.DataFrame, chip_name: str) -> List[str]:
    """根据芯片列命名选择非零 PPG 通道。"""
    chip = chip_name.lower()
    if chip.startswith("gh3036"):
        pattern = re.compile(r"(?i)^Ipd\d+$")
    elif chip.startswith("gh3220"):
        pattern = re.compile(r"(?i)^CH\d+$")
    else:
        raise SignalAnalysisError("无法自动识别 PPG 通道，请使用 --channels 显式指定")

    channels = []
    for column in df.columns:
        if not pattern.match(str(column)):
            continue
        values = pd.to_numeric(df[column], errors="coerce").fillna(0)
        if values.ne(0).any():
            channels.append(str(column))
    if not channels:
        raise SignalAnalysisError("未找到非零 PPG 通道，请使用 --channels 检查输入列")
    return channels


def resolve_acc_columns(
    df: pd.DataFrame, acc_mapping: Optional[Mapping[str, str]] = None
) -> List[str]:
    """优先按规则映射，其次按常见列名识别完整 ACC 三轴。"""
    if acc_mapping:
        mapped = [acc_mapping.get(axis, "") for axis in ("x", "y", "z")]
        if all(column in df.columns for column in mapped):
            return mapped

    pattern_groups = (
        (r"(?i).*acc.*x.*", r"(?i).*acc.*y.*", r"(?i).*acc.*z.*"),
        (r"(?i)^x$", r"(?i)^y$", r"(?i)^z$"),
    )
    for patterns in pattern_groups:
        found = []
        for pattern in patterns:
            column = next((str(col) for col in df.columns if re.match(pattern, str(col))), "")
            if not column:
                break
            found.append(column)
        if len(found) == 3:
            return found
    return []
