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
        return {"status": "not_evaluable", "detected": False, "reason": "缺少有效 IPD 或采样率"}
    values = values[np.isfinite(values)]
    if values.size < max(3, int(min_duration_s * sample_rate)):
        return {"status": "not_evaluable", "detected": False, "reason": "有效持续时间不足"}
    window = max(3, int(round(baseline_window_s * sample_rate)))
    baseline = np.convolve(values, np.ones(window) / window, mode="same")
    residual = values - baseline
    robust_amp = float(np.percentile(residual, 95) - np.percentile(residual, 5))
    active = amplitude_ua / 2.0
    positive_ratio = float(np.mean(residual > active))
    negative_ratio = float(np.mean(residual < -active))
    detected = robust_amp > amplitude_ua and positive_ratio >= 0.03 and negative_ratio >= 0.03
    return {
        "status": "detected" if detected else "not_detected",
        "detected": detected,
        "id": "loose_wear_periodic",
        "amplitude_ua": robust_amp,
        "threshold_ua": float(amplitude_ua),
        "peak_to_peak_ua": robust_amp,
        "amplitude_threshold_ua": float(amplitude_ua),
        "start_s": 0.0,
        "end_s": float(values.size / sample_rate - 1.0 / sample_rate),
        "duration_s": float(values.size / sample_rate),
    }


def detect_agc_instability(
    values: Sequence[float],
    sample_rate: float,
    min_changes: int = 5,
    continuity_window_s: float = 5.0,
) -> Dict[str, Any]:
    if values and isinstance(values[0], (tuple, list)):
        times = np.asarray([item[0] for item in values], dtype=float)
        data = np.asarray([item[1] for item in values], dtype=float)
    else:
        times = np.arange(len(values), dtype=float) / sample_rate
        data = np.asarray(values, dtype=float)
    if data.size < 2 or not np.isfinite(sample_rate) or sample_rate <= 0:
        return {
            "status": "not_evaluable",
            "detected": False,
            "change_count": 0,
            "max_burst_count": 0,
        }
    changes = np.flatnonzero(np.diff(data) != 0) + 1
    max_burst = current = 1 if changes.size else 0
    for left, right in zip(changes[:-1], changes[1:]):
        if times[right] - times[left] <= continuity_window_s:
            current += 1
        else:
            current = 1
        max_burst = max(max_burst, current)
    detected = max_burst > min_changes
    return {
        "status": "supporting" if detected else "not_detected",
        "detected": detected,
        "change_count": int(changes.size),
        "max_burst_count": int(max_burst),
        "threshold_count": int(min_changes),
        "continuity_window_s": float(continuity_window_s),
    }


def synthesize_hr_diagnosis(features: Dict[str, Any]) -> Dict[str, Any]:
    if features.get("algorithm_abnormal") and features.get("psd_locked"):
        return {
            "cause": {
                "id": "algorithm_strategy",
                "origin": "algorithm",
                "title": "疑似算法锁频或牵引机制",
            }
        }
    if features.get("loose_wear_periodic") or features.get("agc_unstable"):
        return {"cause": {"id": "loose_wear", "origin": "raw", "title": "疑似佩戴松动"}}
    return {"cause": None}
