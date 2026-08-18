"""离线 PSD/VSHB 特征提取。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from health_tools.core.analysis.reference import analyze_reference
from health_tools.core.vshb import read_vshb_result
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
    reference: np.ndarray,
    prediction: np.ndarray,
    accuracy_thresholds: Optional[Sequence[float]],
    accuracy_inclusive: bool,
) -> Dict[str, Any]:
    from health_tools.utils.accuracy import (
        DEFAULT_ACCURACY_THRESHOLDS,
        calculate_accuracy,
        normalize_accuracy_thresholds,
        resolve_accuracy_methods,
    )

    thresholds = normalize_accuracy_thresholds(accuracy_thresholds) or DEFAULT_ACCURACY_THRESHOLDS
    methods = resolve_accuracy_methods(["mae", "within_5", "within_10", "within_15"], thresholds)
    metrics = calculate_accuracy(
        pd.DataFrame({"ref": reference, "pred": prediction}),
        "ref",
        "pred",
        methods,
        inclusive=accuracy_inclusive,
        trim_zero_padding=False,
    )
    if not metrics.get("samples"):
        return {}
    finite = np.isfinite(reference) & np.isfinite(prediction)
    metrics["max_error"] = round(float(np.max(np.abs(reference[finite] - prediction[finite]))), 2)
    return metrics


def _accuracy_features(
    overlay,
    error_threshold: float,
    thresholds: Dict[str, Any],
    accuracy_thresholds: Optional[Sequence[float]] = None,
    accuracy_inclusive: bool = False,
) -> Dict[str, Any]:
    from health_tools.utils.accuracy import (
        DEFAULT_ACCURACY_THRESHOLDS,
        format_accuracy_threshold,
        normalize_accuracy_thresholds,
        prepare_accuracy_columns,
    )

    resolved_thresholds = (
        normalize_accuracy_thresholds(accuracy_thresholds) or DEFAULT_ACCURACY_THRESHOLDS
    )
    empty_accuracy = {
        "mae": 0.0,
        "max_error": 0.0,
        "error_ratio": 0.0,
        **{f"within_{format_accuracy_threshold(value)}": 0.0 for value in resolved_thresholds},
        "samples": 0,
        "comparisons": {},
    }
    if overlay.empty:
        return {
            "reference_valid": False,
            "algorithm_abnormal": False,
            **empty_accuracy,
            "polar_review_required": True,
            "polar_issues": ["Polar 数据缺失，需人工复审"],
        }
    prepared = prepare_accuracy_columns(
        {
            "polar": np.asarray(overlay["ref"], dtype=float),
            "offline": np.asarray(overlay["offline"], dtype=float),
            "online": np.asarray(overlay["online"], dtype=float),
            "comp": np.asarray(overlay["comp"], dtype=float),
        }
    )
    columns = prepared.columns
    active = set(prepared.active_columns)
    reference, _ = analyze_reference(columns["polar"], thresholds, sample_rate=1.0)
    comparison_columns = []
    if "polar" in active:
        comparison_columns.extend(
            (name, "polar", name) for name in ("offline", "online", "comp") if name in active
        )
    elif {"offline", "online"}.issubset(active):
        comparison_columns.append(("online_vs_offline", "offline", "online"))
    comparisons = {
        name: _comparison_metrics(
            columns[reference_name],
            columns[prediction_name],
            accuracy_thresholds,
            accuracy_inclusive,
        )
        for name, reference_name, prediction_name in comparison_columns
    }
    comparisons = {name: metrics for name, metrics in comparisons.items() if metrics}
    primary_name = next(
        (
            name
            for name in ("offline", "online", "comp", "online_vs_offline")
            if int(comparisons.get(name, {}).get("samples") or 0) > 0
        ),
        "",
    )
    primary = comparisons.get(primary_name, {})
    if primary:
        if primary_name == "online_vs_offline":
            reference_name, prediction_name = "offline", "online"
        else:
            reference_name, prediction_name = "polar", primary_name
        finite = np.isfinite(columns[reference_name]) & np.isfinite(columns[prediction_name])
        errors = np.abs(columns[reference_name][finite] - columns[prediction_name][finite])
    else:
        errors = np.array([], dtype=float)
    return {
        **reference,
        "algorithm_abnormal": bool(len(errors) and np.any(errors > error_threshold)),
        **({**empty_accuracy, **primary} if primary else empty_accuracy),
        "error_ratio": float(np.mean(errors > error_threshold)) if len(errors) else 0.0,
        "comparisons": comparisons,
    }


def _scene(logical: str) -> str:
    if any(value in logical.lower() for value in ("动态", "运动", "run", "walk")):
        return "dynamic"
    if any(value in logical.lower() for value in ("静态", "sit", "sleep")):
        return "static"
    return "unknown"


def analyze_psd_directory(
    result_dir: Path,
    rule: AnalysisRule,
    accuracy_thresholds: Optional[Sequence[float]] = None,
    accuracy_inclusive: bool = False,
) -> Dict[str, Dict[str, Any]]:
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
            overlay,
            float(rule.thresholds.get("error", 10)),
            rule.thresholds,
            accuracy_thresholds,
            accuracy_inclusive,
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
