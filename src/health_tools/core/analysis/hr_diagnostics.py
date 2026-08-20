"""心率原始信号佩戴与 AGC 证据检测。"""

from __future__ import annotations

from typing import Any, Dict, Sequence

import numpy as np


def detect_ipd_periodic_drift(
    ipd: Sequence[float],
    sample_rate: float,
    baseline_window_s: float = 2.0,
    amplitude_ua: float = 2.0,
    min_duration_s: float = 5.0,
) -> Dict[str, Any]:
    values = np.asarray(ipd, dtype=float)
    if values.size == 0 or not np.isfinite(sample_rate) or sample_rate <= 0:
        return {"status": "not_evaluable", "reason": "缺少有效 IPD 或采样率"}
    values = values[np.isfinite(values)]
    if values.size < max(3, int(min_duration_s * sample_rate)):
        return {"status": "not_evaluable", "reason": "有效持续时间不足"}
    window = max(3, int(round(baseline_window_s * sample_rate)))
    baseline = np.convolve(values, np.ones(window) / window, mode="same")
    residual = values - baseline
    robust_amp = float(np.percentile(residual, 95) - np.percentile(residual, 5))
    return {
        "status": "detected" if robust_amp > amplitude_ua else "not_detected",
        "id": "loose_wear_periodic",
        "amplitude_ua": robust_amp,
        "threshold_ua": float(amplitude_ua),
        "duration_s": float(values.size / sample_rate),
    }


def detect_agc_instability(
    values: Sequence[float],
    sample_rate: float,
    min_changes: int = 5,
    continuity_window_s: float = 5.0,
) -> Dict[str, Any]:
    data = np.asarray(values, dtype=float)
    if data.size < 2 or not np.isfinite(sample_rate) or sample_rate <= 0:
        return {"status": "not_evaluable", "change_count": 0, "max_burst_count": 0}
    changes = np.flatnonzero(np.diff(data) != 0) + 1
    max_burst = current = 1 if changes.size else 0
    for left, right in zip(changes[:-1], changes[1:]):
        if (right - left) / sample_rate <= continuity_window_s:
            current += 1
        else:
            current = 1
        max_burst = max(max_burst, current)
    return {
        "status": "detected" if max_burst > min_changes else "not_detected",
        "change_count": int(changes.size),
        "max_burst_count": int(max_burst),
        "threshold_count": int(min_changes),
        "continuity_window_s": float(continuity_window_s),
    }
