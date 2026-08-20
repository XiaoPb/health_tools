"""血氧静止/运动与 FFT 信号质量检测。"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence

import numpy as np


def classify_spo2_motion(
    acc: Mapping[str, Sequence[float]] | Sequence[Sequence[float]],
    sample_rate: float,
    motion_amplitude_threshold: float = 0.1,
) -> Dict[str, Any]:
    if not np.isfinite(sample_rate) or sample_rate <= 0:
        return {"status": "not_evaluable", "scene": "unknown"}
    if isinstance(acc, Mapping):
        values = [np.asarray(value, dtype=float) for value in acc.values()]
    else:
        values = [np.asarray(value, dtype=float) for value in acc]
    if not values:
        return {"status": "not_evaluable", "scene": "unknown"}
    length = min(value.size for value in values)
    matrix = np.vstack([value[:length] for value in values])
    magnitude = np.sqrt(np.nanmean(matrix**2, axis=0))
    amplitude = float(np.nanstd(magnitude) / max(np.nanmedian(np.abs(magnitude)), 1e-9))
    return {
        "status": "ok",
        "scene": "motion" if amplitude >= motion_amplitude_threshold else "rest",
        "motion_amplitude": amplitude,
        "threshold": float(motion_amplitude_threshold),
    }


def analyze_fft_quality(
    channels: Mapping[str, Sequence[float]], sample_rate: float, weak_channel_ratio: float = 0.25
) -> Dict[str, Any]:
    if not np.isfinite(sample_rate) or sample_rate <= 0 or not channels:
        return {"status": "not_evaluable", "weak_channels": []}
    energies: Dict[str, float] = {}
    peaks: Dict[str, float] = {}
    for name, values in channels.items():
        data = np.asarray(values, dtype=float)
        data = data[np.isfinite(data)]
        if data.size < 4:
            continue
        spectrum = np.abs(np.fft.rfft(data - np.mean(data)))
        index = int(np.argmax(spectrum[1:]) + 1)
        peaks[name] = float(spectrum[index] / max(np.median(spectrum[1:]), 1e-9))
        energies[name] = float(np.sqrt(np.mean(data**2)))
    if not energies:
        return {"status": "not_evaluable", "weak_channels": []}
    maximum = max(energies.values())
    weak = [name for name, value in energies.items() if value < maximum * weak_channel_ratio]
    return {
        "status": "ok",
        "peak_clarity": peaks,
        "channel_energy": energies,
        "weak_channels": weak,
    }
