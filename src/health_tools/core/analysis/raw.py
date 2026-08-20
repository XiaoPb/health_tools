"""原始 CSV 特征提取。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from health_tools.core.analysis.reference import analyze_reference
from health_tools.core.ppg_analysis import compute_pi, prepare_signal, resolve_acc_columns
from health_tools.models.rules import AnalysisRule, ChipRule
from health_tools.rules.loader import RuleLoader
from health_tools.utils.csv_handler import CSVHandler

ACTIVITIES = ("auto", "rest", "walk", "run", "cycle", "strength", "interval", "recovery", "other")

SCENE_ALIASES = {
    "static": "static",
    "静息": "static",
    "静止": "static",
    "dynamic": "dynamic",
    "运动": "dynamic",
    "跑步": "dynamic",
    "步行": "dynamic",
    "骑行": "dynamic",
    "恢复": "dynamic",
}


@dataclass(frozen=True)
class ScenePathInfo:
    """从数据文件目录解析出的场景展示名及规范化模式。"""

    label: str
    mode: str


def infer_scene(path: Path, root: Path) -> Optional[ScenePathInfo]:
    """从 root 下数据文件的目录结构推断场景。

    仅识别内置场景别名，按距离文件最近的目录优先；文件不在 root 下时返回 None。
    """
    try:
        # 统一分隔符，兼容外部传入的 Windows 风格路径字符串。
        normalized_path = Path(str(path).replace("\\", os.sep))
        normalized_root = Path(str(root).replace("\\", os.sep))
        relative = normalized_path.resolve().relative_to(normalized_root.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    directories = list(relative.parts[:-1])
    for part in reversed(directories):
        label = part.strip()
        mode = SCENE_ALIASES.get(label.lower())
        if mode:
            return ScenePathInfo(label=label, mode=mode)
    return None


def infer_activity(
    path: Path, explicit: str = "auto", features: Optional[Dict[str, Any]] = None
) -> str:
    """根据显式标签、路径关键词和可观测特征推断活动类型。"""
    if explicit and explicit != "auto":
        return explicit if explicit in ACTIVITIES else "other"
    text = "/".join(path.parts).lower()
    aliases = {
        "run": ("run", "跑", "jog"),
        "walk": ("walk", "步行", "walking"),
        "cycle": ("cycle", "cycling", "bike", "骑行", "骑车"),
        "strength": ("strength", "力量", "weight", "gym"),
        "interval": ("interval", "间歇", "hiit"),
        "recovery": ("recovery", "恢复"),
        "rest": ("rest", "静息", "静止"),
    }
    for activity, words in aliases.items():
        if any(word in text for word in words):
            return activity
    observed = features or {}
    hr_range = float(observed.get("hr_change_range", 0) or 0)
    start_end = float(observed.get("hr_start_end_change", 0) or 0)
    direction_changes = int(observed.get("hr_direction_changes", 0) or 0)
    if hr_range >= 20 and direction_changes >= 2:
        return "interval"
    if hr_range >= 15 and start_end <= -10:
        return "recovery"
    if observed.get("motion_rms", 0) >= 0.3:
        return "other"
    return "rest"


def detect_chip(path: Path) -> Optional[str]:
    try:
        line = path.open("r", encoding="utf-8", errors="ignore").readline().lower()
    except OSError:
        return None
    for chip in ("gh3036", "gh3220", "gh3300"):
        if chip in line:
            return chip
    return None


def _read(path: Path, chip: Optional[str]) -> Tuple[pd.DataFrame, Optional[ChipRule]]:
    rule = RuleLoader.load_chip_rule(chip) if chip else None
    if rule:
        _, frame = CSVHandler(rule).read(path)
    else:
        frame = pd.read_csv(path)
    return frame, rule


def _numeric(frame: pd.DataFrame, column: Optional[str]) -> Optional[pd.Series]:
    if not column or column not in frame.columns:
        return None
    return pd.to_numeric(frame[column], errors="coerce")


def _infer_sample_rate(frame: pd.DataFrame, timestamp: Optional[str]) -> Optional[float]:
    values = _numeric(frame, timestamp)
    if values is None:
        return None
    diffs = values.diff().dropna()
    diffs = diffs[diffs > 0]
    if diffs.empty:
        return None
    delta = float(diffs.median())
    magnitude = float(values.dropna().abs().median()) if values.notna().any() else 0.0
    if magnitude > 1e14:
        return 1_000_000.0 / delta
    if magnitude > 1e11:
        return 1000.0 / delta
    if delta > 0.1:
        return 1.0 / delta
    return None


def _active_columns(frame: pd.DataFrame, patterns: Iterable[str]) -> List[str]:
    found: List[str] = []
    for column in frame.columns:
        if any(re.match(pattern, str(column), re.IGNORECASE) for pattern in patterns):
            values = _numeric(frame, str(column))
            if values is not None and values.notna().any() and values.abs().sum() > 0:
                found.append(str(column))
    return found


def _run_ratio(values: pd.Series, predicate) -> float:
    numeric = values.dropna().to_numpy(dtype=float)
    if len(numeric) == 0:
        return 1.0
    return float(np.mean(predicate(numeric)))


def _error_segments(
    ref: pd.Series,
    pred: pd.Series,
    sample_rate: float,
    threshold: float,
    reference_mask: Optional[np.ndarray] = None,
    time_axis: Optional[np.ndarray] = None,
) -> Tuple[List[dict], Dict[str, float]]:
    valid = np.isfinite(ref) & np.isfinite(pred) & (ref > 0)
    if reference_mask is not None:
        valid = valid & pd.Series(reference_mask, index=ref.index)
    error = (ref - pred).abs().where(valid)
    values = error.dropna().to_numpy(dtype=float)
    if len(values) == 0:
        return [], {
            "error_ratio": 0.0,
        }
    mask = error.fillna(0).to_numpy() > threshold
    segments: List[dict] = []
    start: Optional[int] = None
    for index, abnormal in enumerate(mask.tolist() + [False]):
        if abnormal and start is None:
            start = index
        elif not abnormal and start is not None:
            part = error.iloc[start:index].dropna()
            if len(part) > 0:
                segments.append(
                    {
                        "start_s": (
                            float(time_axis[start])
                            if time_axis is not None
                            else start / sample_rate
                        ),
                        "end_s": (
                            float(time_axis[index - 1])
                            if time_axis is not None
                            else (index - 1) / sample_rate
                        ),
                        "samples": int(len(part)),
                        "mean_error": float(part.mean()),
                        "max_error": float(part.max()),
                    }
                )
            start = None
    return segments, {
        "error_ratio": float(np.mean(values > threshold)),
    }


def _accuracy_metrics(
    ref: np.ndarray,
    pred: np.ndarray,
    thresholds: Optional[Sequence[float]],
    inclusive: bool,
) -> Dict[str, Any]:
    from health_tools.utils.accuracy import (
        DEFAULT_ACCURACY_THRESHOLDS,
        calculate_accuracy,
        format_accuracy_threshold,
        normalize_accuracy_thresholds,
        resolve_accuracy_methods,
    )

    resolved_thresholds = normalize_accuracy_thresholds(thresholds) or DEFAULT_ACCURACY_THRESHOLDS
    methods = resolve_accuracy_methods(
        ["mae", "within_5", "within_10", "within_15"], resolved_thresholds
    )
    metrics = calculate_accuracy(
        pd.DataFrame({"ref": ref, "pred": pred}),
        "ref",
        "pred",
        methods,
        inclusive=inclusive,
        trim_zero_padding=False,
    )
    if not metrics.get("samples"):
        return {
            "samples": 0,
            "mae": 0.0,
            "max_error": 0.0,
            **{f"within_{format_accuracy_threshold(value)}": 0.0 for value in resolved_thresholds},
        }
    finite = np.isfinite(ref) & np.isfinite(pred)
    metrics["max_error"] = round(float(np.max(np.abs(ref[finite] - pred[finite]))), 2)
    return metrics


def analyze_raw_file(
    path: Path,
    rule: AnalysisRule,
    analysis_type: str,
    chip_name: Optional[str] = None,
    sample_rate: Optional[float] = None,
    ref_column: Optional[str] = None,
    pred_column: Optional[str] = None,
    timestamp_column: Optional[str] = None,
    scene_override: str = "auto",
    activity_override: str = "auto",
    accuracy_thresholds: Optional[Sequence[float]] = None,
    accuracy_inclusive: bool = False,
) -> Tuple[Dict[str, Any], pd.DataFrame, Optional[ChipRule]]:
    from health_tools.utils.accuracy import prepare_accuracy_columns

    chip = chip_name or detect_chip(path)
    frame, chip_rule = _read(path, chip)
    columns = rule.columns
    ref_name = ref_column or columns.get("reference")
    pred_name = pred_column or columns.get("prediction")
    timestamp_name = timestamp_column or columns.get("timestamp")
    ref = _numeric(frame, ref_name)
    pred = _numeric(frame, pred_name)
    rate = sample_rate or _infer_sample_rate(frame, timestamp_name)
    rate = rate or float(rule.sampling.get("sample_rate", 0) or 0)
    ppg_patterns = columns.get("ppg_patterns", [r"^Ipd\d+$", r"^CH\d+$"])
    ppg_columns = _active_columns(frame, ppg_patterns)
    acc_columns = list(columns.get("acc", []))
    if not all(column in frame.columns for column in acc_columns):
        acc_columns = resolve_acc_columns(frame, chip_rule.acc_columns if chip_rule else None)
    threshold = float(rule.thresholds.get("error", 10 if analysis_type == "hr" else 3))
    accuracy_columns = {}
    if ref is not None:
        accuracy_columns["ref"] = ref.to_numpy(dtype=float)
    if pred is not None:
        accuracy_columns["pred"] = pred.to_numpy(dtype=float)
    prepared = prepare_accuracy_columns(accuracy_columns)
    shared_ref = prepared.columns.get("ref", np.array([], dtype=float))
    shared_pred = prepared.columns.get("pred", np.array([], dtype=float))
    time_axis = np.arange(len(frame), dtype=float) / (rate or 1.0)
    shared_time = time_axis[prepared.start : prepared.end]
    reference_features: Dict[str, Any] = {
        "reference_valid": False,
        "reference_issues": [],
        "polar_review_required": False,
        "polar_issues": [],
    }
    reference_mask: Optional[np.ndarray] = None
    if ref is not None:
        reference_features, reference_mask = analyze_reference(
            shared_ref, rule.thresholds, sample_rate=rate
        )
        if analysis_type != "hr":
            reference_features["polar_review_required"] = False
            reference_features["polar_issues"] = []
    ref_active = "ref" in prepared.active_columns
    pred_active = "pred" in prepared.active_columns
    if ref_active and pred_active and prepared.start < prepared.end:
        shared_ref_series = pd.Series(shared_ref)
        shared_pred_series = pd.Series(shared_pred)
        segments, analysis_metrics = _error_segments(
            shared_ref_series,
            shared_pred_series,
            rate or 1.0,
            threshold,
            reference_mask,
            shared_time,
        )
        metrics = {
            **_accuracy_metrics(
                shared_ref,
                shared_pred,
                accuracy_thresholds,
                accuracy_inclusive,
            ),
            **analysis_metrics,
        }
    else:
        segments = []
        metrics = {
            **_accuracy_metrics(
                np.array([], dtype=float),
                np.array([], dtype=float),
                accuracy_thresholds,
                accuracy_inclusive,
            ),
            "error_ratio": 0.0,
        }
    missing_ratio = float(frame.isna().mean().mean()) if not frame.empty else 1.0
    data_complete = not frame.empty and missing_ratio <= float(
        rule.thresholds.get("missing_ratio", 0.01)
    )
    timestamp = _numeric(frame, timestamp_name)
    if timestamp is not None:
        data_complete = data_complete and bool(timestamp.diff().dropna().ge(0).all())
    frame_name = (chip_rule.frame_column if chip_rule else "") or "FRAME_ID"
    frame_ids = _numeric(frame, frame_name)
    if frame_ids is not None and len(frame_ids.dropna()) > 1:
        frame_diff = frame_ids.diff().dropna()
        valid_step = frame_diff.eq(1) | frame_diff.eq(-255)
        data_complete = data_complete and bool(
            (1.0 - float(valid_step.mean())) <= float(rule.thresholds.get("missing_ratio", 0.01))
        )
    signal_saturated = False
    signal_flat = False
    baseline_drift = False
    near_zero_ratio = 0.0
    near_full_ratio = 0.0
    pulse_amplitude = 0.0
    dc_level_ratio = 0.0
    pi_by_channel: Dict[str, float] = {}
    pi_units: Dict[str, str] = {}
    full_scale = float((chip_rule.chip_info if chip_rule else {}).get("adc_full_scale", 0) or 0)
    adc_offset = float((chip_rule.chip_info if chip_rule else {}).get("adc_offset", 0) or 0)
    for column in ppg_columns:
        values = _numeric(frame, column)
        if values is None:
            continue
        signal_flat = signal_flat or _run_ratio(values, lambda x: np.isclose(x, x[0])) >= float(
            rule.thresholds.get("flat_ratio", 0.98)
        )
        if full_scale > 0:
            signal_saturated = signal_saturated or _run_ratio(
                values, lambda x: np.abs(x) >= full_scale * 0.98
            ) >= float(rule.thresholds.get("saturation_ratio", 0.01))
        numeric = values.dropna().to_numpy(dtype=float)
        if len(numeric) > 20:
            if full_scale > 0:
                centered = numeric - adc_offset
                near_zero_ratio = max(
                    near_zero_ratio,
                    float(np.mean(centered <= full_scale * 0.05)),
                )
                near_full_ratio = max(
                    near_full_ratio,
                    float(np.mean(centered >= full_scale * 0.95)),
                )
                dc_level_ratio = max(
                    dc_level_ratio,
                    float(np.clip(abs(np.median(centered)) / full_scale, 0.0, 1.0)),
                )
            pulse_amplitude = max(
                pulse_amplitude,
                float(np.percentile(numeric, 95) - np.percentile(numeric, 5)),
            )
            span = max(float(np.percentile(numeric, 95) - np.percentile(numeric, 5)), 1e-9)
            baseline_drift = baseline_drift or abs(
                float(np.mean(numeric[: max(1, len(numeric) // 10)]))
                - float(np.mean(numeric[-max(1, len(numeric) // 10) :]))
            ) / span > float(rule.thresholds.get("baseline_drift_ratio", 0.5))
            if scene_override != "dynamic":
                try:
                    is_ipd = column.lower().startswith("ipd")
                    pi_input = numeric if is_ipd else numeric - adc_offset
                    pi_units[column] = "pA" if is_ipd else "adc_lsb"
                    ac = prepare_signal(pi_input)
                    pi = compute_pi(pi_input, ac - np.mean(ac), rate or 25.0).dropna()
                    if not pi.empty:
                        pi_by_channel[column] = float(pi.median())
                except Exception:
                    pass
    motion = 0.0
    if len(acc_columns) == 3:
        acc = (
            frame[acc_columns].apply(pd.to_numeric, errors="coerce").dropna().to_numpy(dtype=float)
        )
        if len(acc):
            magnitude = np.sqrt(np.square(acc).sum(axis=1))
            baseline = float(np.median(magnitude)) or 1.0
            motion = float(np.std(magnitude) / baseline)
    scene = scene_override
    if scene == "auto":
        scene = "dynamic" if motion >= float(rule.thresholds.get("motion_rms", 0.1)) else "static"
    motion_excessive = analysis_type == "spo2" and (
        scene == "dynamic" or motion >= float(rule.thresholds.get("motion_rms", 0.1))
    )
    if scene == "dynamic":
        pi_by_channel = {}
    pi_values = list(pi_by_channel.values())
    pi_value = (
        min(pi_values)
        if analysis_type == "spo2" and pi_values
        else (float(np.median(pi_values)) if pi_values else None)
    )
    output_jump = False
    rise_lag = False
    recovery_lag = False
    output_plateau = False
    hr_rise_lag_s: Optional[float] = None
    hr_fall_lag_s: Optional[float] = None
    if pred is not None and rate:
        output_jump = bool(
            pred.diff().abs().mul(rate).gt(float(rule.thresholds.get("jump_per_second", 20))).any()
        )
        if ref is not None:
            aligned = pd.concat([ref.rename("ref"), pred.rename("pred")], axis=1).dropna()
            if len(aligned) > max(int(rate * 4), 10):
                window = max(int(rate * 2), 2)
                ref_delta = aligned["ref"].diff(window)
                pred_delta = aligned["pred"].diff(window)
                change = float(rule.thresholds.get("response_change", 8))
                rise_mask = ref_delta >= change
                fall_mask = ref_delta <= -change
                rise_lag = bool((rise_mask & (pred_delta < change * 0.5)).any())
                recovery_lag = bool((fall_mask & (pred_delta > -change * 0.5)).any())
                hr_rise_lag_s = float(window / rate) if rise_lag else None
                hr_fall_lag_s = float(window / rate) if recovery_lag else None
                ref_span = float(aligned["ref"].max() - aligned["ref"].min())
                pred_span = float(aligned["pred"].max() - aligned["pred"].min())
                output_plateau = bool(ref_span >= change * 2 and pred_span <= ref_span * 0.25)
    min_samples = int(float(rule.thresholds.get("error_min_seconds", 0)) * (rate or 1.0))
    if min_samples > 1:
        segments = [segment for segment in segments if int(segment["samples"]) >= min_samples]
    algorithm_abnormal = bool(segments)
    agc_columns = [
        str(column)
        for column in frame.columns
        if re.search(r"agc[_ ]?info", str(column), re.IGNORECASE)
    ]
    agc_change_count = 0
    for column in agc_columns:
        values = _numeric(frame, column).dropna()
        if len(values) > 1:
            agc_change_count = max(agc_change_count, int(values.diff().dropna().ne(0).sum()))
    agc_change_ratio = (
        float(agc_change_count / max(len(frame) - 1, 1)) if frame is not None else 0.0
    )
    channel_inconsistent = False
    if len(ppg_columns) >= 2:
        left = _numeric(frame, ppg_columns[0])
        right = _numeric(frame, ppg_columns[1])
        if left is not None and right is not None:
            channel_inconsistent = bool(
                left.corr(right) < float(rule.thresholds.get("channel_correlation", 0.3))
            )
    channel_dropout = channel_inconsistent or near_zero_ratio >= float(
        rule.thresholds.get("near_limit_ratio", 0.05)
    )
    pulse_compressed = bool(
        pulse_amplitude <= float(rule.thresholds.get("pulse_amplitude_low", 1.0))
        or (dc_level_ratio > 0 and pulse_amplitude / max(full_scale, 1.0) < 0.01)
    )
    activity_facts: Dict[str, Any] = {"motion_rms": motion}
    activity_hr = ref if ref is not None else pred
    if activity_hr is not None:
        hr_values = activity_hr.dropna().to_numpy(dtype=float)
        if len(hr_values) > 2:
            activity_facts["hr_change_range"] = float(np.ptp(hr_values))
            activity_facts["hr_start_end_change"] = float(hr_values[-1] - hr_values[0])
            deltas = np.diff(hr_values)
            signs = np.sign(deltas[np.abs(deltas) >= 1.0])
            activity_facts["hr_direction_changes"] = int(
                np.sum(signs[1:] != signs[:-1]) if len(signs) > 1 else 0
            )
    activity = infer_activity(path, activity_override, activity_facts)
    features: Dict[str, Any] = {
        "data_complete": data_complete,
        "missing_ratio": missing_ratio,
        "signal_saturated": signal_saturated,
        "signal_flat": signal_flat,
        "baseline_drift": baseline_drift,
        "dc_level_ratio": dc_level_ratio,
        "pulse_amplitude": pulse_amplitude,
        "near_zero_ratio": near_zero_ratio,
        "near_full_ratio": near_full_ratio,
        "near_zero": near_zero_ratio >= float(rule.thresholds.get("near_limit_ratio", 0.05)),
        "near_full": near_full_ratio >= float(rule.thresholds.get("near_limit_ratio", 0.05)),
        "agc_change_count": agc_change_count,
        "agc_change_ratio": agc_change_ratio,
        "agc_unstable": agc_change_ratio >= float(rule.thresholds.get("agc_unstable_ratio", 0.05)),
        "channel_dropout": channel_dropout,
        "pulse_compressed": pulse_compressed,
        "hr_rise_lag_s": hr_rise_lag_s,
        "hr_fall_lag_s": hr_fall_lag_s,
        "rise_lag": rise_lag,
        "recovery_lag": recovery_lag,
        "output_plateau": output_plateau,
        "pi": pi_value,
        "pi_min": min(pi_values) if pi_values else None,
        "pi_by_channel": pi_by_channel,
        "pi_units": pi_units,
        "pi_low": bool(
            pi_value is not None and pi_value < float(rule.thresholds.get("pi_low", 0.5))
        ),
        "motion_rms": motion,
        "motion_excessive": motion_excessive,
        "scene": scene,
        "activity": activity,
        **reference_features,
        "output_jump": output_jump,
        "algorithm_abnormal": algorithm_abnormal,
        "raw_valid": bool(
            data_complete and not signal_saturated and not signal_flat and not baseline_drift
        ),
        "channel_inconsistent": channel_inconsistent,
        "sample_rate": rate,
        "ppg_columns": ppg_columns,
        "acc_columns": acc_columns,
    }
    return (
        {
            "features": features,
            "metrics": metrics,
            "segments": segments,
            "rows": len(frame),
            "chip": chip,
        },
        frame,
        chip_rule,
    )
