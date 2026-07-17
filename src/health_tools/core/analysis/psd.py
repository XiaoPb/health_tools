"""离线 PSD/VSHB 特征提取。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from health_tools.core.vshb import read_vshb_result
from health_tools.core.analysis.reference import analyze_reference
from health_tools.models.rules import AnalysisRule


def _matrix(path: Path) -> np.ndarray:
    data = np.genfromtxt(str(path), delimiter=",", dtype=float, invalid_raise=False)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    return data[:, ~np.all(np.isnan(data), axis=0)]


def _orient(data: np.ndarray, expected_time: int) -> np.ndarray:
    if data.size == 0:
        return data
    if expected_time and data.shape[0] == expected_time:
        return data
    if expected_time and data.shape[1] == expected_time:
        return data.T
    return data if data.shape[0] <= data.shape[1] else data.T


def _peak_track(data: np.ndarray, max_bpm: float = 250.0) -> Tuple[np.ndarray, np.ndarray]:
    if data.size == 0 or data.shape[1] < 2:
        return np.array([]), np.array([])
    clean = np.nan_to_num(data, nan=0.0)
    indices = np.argmax(clean, axis=1)
    frequency = indices / max(data.shape[1] - 1, 1) * max_bpm / 60.0
    peak = np.max(clean, axis=1)
    baseline = np.median(np.abs(clean), axis=1)
    clarity = peak / np.maximum(baseline, np.finfo(float).eps)
    return frequency, clarity


def _find_psd(base: Path, suffixes: List[str]) -> Optional[Path]:
    for suffix in suffixes:
        candidate = base.parent / f"{base.name}{suffix}"
        if candidate.exists():
            return candidate
    return None


def _comparison_metrics(
    reference: np.ndarray, prediction: np.ndarray, reference_mask: np.ndarray
) -> Dict[str, Any]:
    valid = reference_mask & np.isfinite(prediction)
    errors = np.abs(reference[valid] - prediction[valid])
    if not len(errors):
        return {}
    return {
        "samples": int(len(errors)),
        "mae": float(np.mean(errors)),
        "max_error": float(np.max(errors)),
        "within_5": float(np.mean(errors <= 5)),
        "within_10": float(np.mean(errors <= 10)),
        "within_15": float(np.mean(errors <= 15)),
    }


def _accuracy_features(
    overlay, error_threshold: float, thresholds: Dict[str, Any]
) -> Dict[str, Any]:
    if overlay.empty:
        return {
            "reference_valid": False,
            "algorithm_abnormal": False,
            "mae": 0.0,
            "max_error": 0.0,
            "error_ratio": 0.0,
            "within_5": 0.0,
            "within_10": 0.0,
            "within_15": 0.0,
            "samples": 0,
            "comparisons": {},
            "polar_review_required": True,
            "polar_issues": ["Polar 数据缺失，需人工复审"],
        }
    ref = np.asarray(overlay["ref"], dtype=float)
    offline = np.asarray(overlay["offline"], dtype=float)
    online = np.asarray(overlay["online"], dtype=float)
    comp = np.asarray(overlay["comp"], dtype=float)
    reference, valid_ref = analyze_reference(ref, thresholds, sample_rate=1.0)
    valid_offline = valid_ref & np.isfinite(offline)
    errors = np.abs(ref[valid_offline] - offline[valid_offline])
    comparisons = {
        "offline": _comparison_metrics(ref, offline, valid_ref),
        "online": _comparison_metrics(ref, online, valid_ref),
    }
    if np.any(np.isfinite(comp) & (comp > 0)):
        comparisons["comp"] = _comparison_metrics(ref, comp, valid_ref)
    return {
        **reference,
        "algorithm_abnormal": bool(len(errors) and np.any(errors > error_threshold)),
        "mae": float(np.mean(errors)) if len(errors) else 0.0,
        "max_error": float(np.max(errors)) if len(errors) else 0.0,
        "error_ratio": float(np.mean(errors > error_threshold)) if len(errors) else 0.0,
        "within_5": float(np.mean(errors <= 5)) if len(errors) else 0.0,
        "within_10": float(np.mean(errors <= 10)) if len(errors) else 0.0,
        "within_15": float(np.mean(errors <= 15)) if len(errors) else 0.0,
        "samples": int(len(errors)),
        "comparisons": {name: value for name, value in comparisons.items() if value},
    }


def _scene(logical: str) -> str:
    if any(value in logical.lower() for value in ("动态", "运动", "run", "walk")):
        return "dynamic"
    if any(value in logical.lower() for value in ("静态", "sit", "sleep")):
        return "static"
    return "unknown"


def analyze_psd_directory(result_dir: Path, rule: AnalysisRule) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    clarity_threshold = float(rule.thresholds.get("psd_clarity", 3))
    lock_hz = float(rule.thresholds.get("psd_lock_hz", 0.2))
    pull_hz = float(rule.thresholds.get("psd_pull_hz", 0.5))
    presence_threshold = float(rule.thresholds.get("psd_presence", 0.6))
    for vshb in sorted(result_dir.rglob("*_result.vshb")):
        base_name = vshb.stem.replace("_result", "")
        logical = (vshb.parent / f"{base_name}.csv").relative_to(result_dir).as_posix()
        base = vshb.parent / base_name
        overlay = read_vshb_result(vshb, positional_online_col=30)
        accuracy = _accuracy_features(
            overlay, float(rule.thresholds.get("error", 10)), rule.thresholds
        )
        ppg_path = _find_psd(base, ["0.prepsd", ".prepsd"])
        acc_path = _find_psd(base, [".accrmspsd", ".accxpsd", ".accypsd", ".acczpsd"])
        if not ppg_path or not acc_path:
            results[logical] = {
                "available": False,
                "reason": "缺少 PPG 或 ACC PSD",
                **accuracy,
                "scene": _scene(logical),
                "vshb_path": str(vshb),
            }
            continue
        expected = len(overlay)
        ppg = _orient(_matrix(ppg_path), expected)
        acc = _orient(_matrix(acc_path), expected)
        length = min(len(ppg), len(acc))
        ppg, acc = ppg[:length], acc[:length]
        ppg_freq, ppg_clarity = _peak_track(ppg)
        acc_freq, acc_clarity = _peak_track(acc)
        if len(ppg_freq) == 0 or len(acc_freq) == 0:
            results[logical] = {
                "available": False,
                "reason": "PSD 矩阵为空",
                **accuracy,
                "scene": _scene(logical),
                "vshb_path": str(vshb),
            }
            continue
        valid = ppg_clarity >= clarity_threshold
        presence = float(np.mean(valid))
        difference = np.abs(ppg_freq - acc_freq)
        ratio = ppg_freq / np.maximum(acc_freq, np.finfo(float).eps)
        locked_ratio = float(np.mean((difference < lock_hz) & valid))
        pulled_ratio = float(np.mean((difference >= lock_hz) & (difference < pull_hz) & valid))
        harmonic_ratio = float(
            np.mean(
                valid
                & (
                    np.isclose(ratio, 2.0, atol=0.1)
                    | np.isclose(ratio, 0.5, atol=0.1)
                    | np.isclose(ratio, 3.0, atol=0.15)
                )
            )
        )
        noisy = presence < presence_threshold or float(np.median(ppg_clarity)) < clarity_threshold
        results[logical] = {
            "available": True,
            "presence": presence,
            "clarity": float(np.median(ppg_clarity)),
            "acc_clarity": float(np.median(acc_clarity)),
            "mean_frequency_difference_hz": (
                float(np.mean(difference[valid])) if np.any(valid) else None
            ),
            "locked_ratio": locked_ratio,
            "pulled_ratio": pulled_ratio,
            "harmonic_ratio": harmonic_ratio,
            "psd_locked": locked_ratio >= 0.5,
            "psd_pulled": pulled_ratio >= 0.5,
            "psd_harmonic": harmonic_ratio >= 0.5,
            "psd_noisy": noisy,
            "psd_interrupted": presence < presence_threshold,
            **accuracy,
            "raw_valid": not noisy,
            "scene": _scene(logical),
            "ppg_path": str(ppg_path),
            "acc_path": str(acc_path),
            "vshb_path": str(vshb),
        }
    return results
