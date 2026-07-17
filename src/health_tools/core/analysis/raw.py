"""原始 CSV 特征提取。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from health_tools.core.ppg_analysis import compute_pi, prepare_signal, resolve_acc_columns
from health_tools.models.rules import AnalysisRule, ChipRule
from health_tools.rules.loader import RuleLoader
from health_tools.utils.csv_handler import CSVHandler


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
    ref: pd.Series, pred: pd.Series, sample_rate: float, threshold: float
) -> Tuple[List[dict], Dict[str, float]]:
    valid = ref.notna() & pred.notna() & (ref > 0)
    error = (ref - pred).abs().where(valid)
    values = error.dropna().to_numpy(dtype=float)
    if len(values) == 0:
        return [], {
            "samples": 0,
            "mae": 0.0,
            "max_error": 0.0,
            "error_ratio": 0.0,
            "within_5": 0.0,
            "within_10": 0.0,
            "within_15": 0.0,
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
                        "start_s": start / sample_rate,
                        "end_s": (index - 1) / sample_rate,
                        "samples": int(len(part)),
                        "mean_error": float(part.mean()),
                        "max_error": float(part.max()),
                    }
                )
            start = None
    return segments, {
        "samples": int(len(values)),
        "mae": float(np.mean(values)),
        "max_error": float(np.max(values)),
        "error_ratio": float(np.mean(values > threshold)),
        "within_5": float(np.mean(values <= 5)),
        "within_10": float(np.mean(values <= 10)),
        "within_15": float(np.mean(values <= 15)),
    }


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
) -> Tuple[Dict[str, Any], pd.DataFrame, Optional[ChipRule]]:
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
    segments, metrics = (
        _error_segments(ref, pred, rate or 1.0, threshold)
        if ref is not None and pred is not None
        else ([], {})
    )
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
    pi_values: List[float] = []
    full_scale = float((chip_rule.chip_info if chip_rule else {}).get("adc_full_scale", 0) or 0)
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
            span = max(float(np.percentile(numeric, 95) - np.percentile(numeric, 5)), 1e-9)
            baseline_drift = baseline_drift or abs(
                float(np.mean(numeric[: max(1, len(numeric) // 10)]))
                - float(np.mean(numeric[-max(1, len(numeric) // 10) :]))
            ) / span > float(rule.thresholds.get("baseline_drift_ratio", 0.5))
            if scene_override != "dynamic":
                try:
                    ac = prepare_signal(numeric)
                    pi = compute_pi(numeric, ac - np.mean(ac), rate or 25.0).dropna()
                    if not pi.empty:
                        pi_values.append(float(pi.median()))
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
        pi_values = []
    reference_valid = bool(ref is not None and ref.notna().sum() > 0)
    if reference_valid:
        reference_valid = bool(
            (
                (ref.dropna() >= float(rule.thresholds.get("ref_min", 0)))
                & (ref.dropna() <= float(rule.thresholds.get("ref_max", 1000)))
            ).mean()
            >= 0.8
        )
    if reference_valid and ref is not None and rate:
        groups = ref.ne(ref.shift()).cumsum()
        longest = int(ref.groupby(groups).size().max()) if len(ref) else 0
        reference_valid = longest / rate < float(rule.thresholds.get("ref_stale_seconds", 120))
    output_jump = False
    if pred is not None and rate:
        output_jump = bool(
            pred.diff().abs().mul(rate).gt(float(rule.thresholds.get("jump_per_second", 20))).any()
        )
    min_samples = int(float(rule.thresholds.get("error_min_seconds", 0)) * (rate or 1.0))
    if min_samples > 1:
        segments = [segment for segment in segments if int(segment["samples"]) >= min_samples]
    algorithm_abnormal = bool(segments)
    channel_inconsistent = False
    if len(ppg_columns) >= 2:
        left = _numeric(frame, ppg_columns[0])
        right = _numeric(frame, ppg_columns[1])
        if left is not None and right is not None:
            channel_inconsistent = bool(
                left.corr(right) < float(rule.thresholds.get("channel_correlation", 0.3))
            )
    features: Dict[str, Any] = {
        "data_complete": data_complete,
        "missing_ratio": missing_ratio,
        "signal_saturated": signal_saturated,
        "signal_flat": signal_flat,
        "baseline_drift": baseline_drift,
        "pi": float(np.median(pi_values)) if pi_values else None,
        "pi_low": bool(
            pi_values and float(np.median(pi_values)) < float(rule.thresholds.get("pi_low", 0.5))
        ),
        "motion_rms": motion,
        "motion_excessive": motion_excessive,
        "scene": scene,
        "reference_valid": reference_valid,
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
