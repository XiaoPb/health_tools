"""参考设备数据的全局有效性与局部警告分析。"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np


def _positions(mask: np.ndarray, limit: int = 10) -> str:
    return "，".join(str(int(index)) for index in np.flatnonzero(mask)[:limit])


def analyze_reference(
    values: Sequence[object],
    thresholds: Dict[str, Any],
    *,
    sample_rate: Optional[float] = None,
    timestamps: Optional[Sequence[object]] = None,
) -> Tuple[Dict[str, Any], np.ndarray]:
    """返回全局有效性、局部问题和可用于准确度计算的样本掩码。"""
    ref = np.asarray(values, dtype=float)
    finite = np.isfinite(ref)
    ref_min = float(thresholds.get("ref_min", 0))
    ref_max = float(thresholds.get("ref_max", 1000))
    in_range = finite & (ref >= ref_min) & (ref <= ref_max)
    finite_count = int(np.sum(finite))
    range_valid_ratio = float(np.mean(in_range)) if len(ref) else 0.0
    required_ratio = float(thresholds.get("ref_valid_ratio", 0.8))
    issues = []
    if not finite_count:
        issues.append("参考值全部缺失")
    elif range_valid_ratio < required_ratio:
        issues.append(f"参考值有效范围占比 {range_valid_ratio:.1%}，低于要求 {required_ratio:.1%}")
    elif np.any(finite & ~in_range):
        mask = finite & ~in_range
        issues.append(
            f"参考值局部超出范围 [{ref_min:g}, {ref_max:g}]，" f"位置(前10)={_positions(mask)}"
        )

    rate = float(sample_rate or 1.0)
    stale_seconds = float(thresholds.get("ref_stale_seconds", 120))
    longest = 0
    stale_positions = np.zeros(len(ref), dtype=bool)
    run_start = 0
    for index in range(len(ref) + 1):
        continues = (
            index < len(ref)
            and in_range[index]
            and index > run_start
            and ref[index] == ref[index - 1]
        )
        if continues:
            continue
        run_length = index - run_start
        if run_start < len(ref) and in_range[run_start]:
            longest = max(longest, run_length)
            if rate > 0 and run_length / rate >= stale_seconds and run_length > 1:
                stale_positions[run_start:index] = True
        run_start = index
    longest_seconds = longest / rate if rate > 0 else 0.0
    stale = bool(np.any(stale_positions))
    if stale:
        in_range = in_range & ~stale_positions
        issues.append(
            f"参考值最长连续不变 {longest_seconds:.1f}s，"
            f"位置(前10)={_positions(stale_positions)}，需人工复审"
        )

    if timestamps is not None:
        time_values = np.asarray(timestamps, dtype=float)
        delta = np.diff(time_values)
        invalid_time = ~np.isfinite(delta) | (delta <= 0)
        if np.any(invalid_time):
            issues.append(f"参考时间轴非递增或缺失，位置(前10)={_positions(invalid_time)}")
            affected = np.zeros(len(ref), dtype=bool)
            affected[np.flatnonzero(invalid_time) + 1] = True
            in_range = in_range & ~affected
    else:
        delta = np.full(max(len(ref) - 1, 0), 1.0 / rate if rate > 0 else 1.0)
    differences = np.abs(np.diff(ref))
    pair_valid = in_range[1:] & in_range[:-1] & np.isfinite(delta) & (delta > 0)
    jump_rate = np.zeros_like(differences, dtype=float)
    jump_rate[pair_valid] = differences[pair_valid] / delta[pair_valid]
    jump_threshold = float(
        thresholds.get("ref_jump_per_second", thresholds.get("jump_per_second", 20))
    )
    jump_mask = pair_valid & (jump_rate > jump_threshold)
    if np.any(jump_mask):
        jump_positions = np.zeros(len(ref), dtype=bool)
        jump_positions[np.flatnonzero(jump_mask) + 1] = True
        in_range = in_range & ~jump_positions
        issues.append(
            f"参考值跳变超过 {jump_threshold:g}/s，位置(前10)={_positions(jump_positions)}"
        )

    valid_ratio = float(np.mean(in_range)) if len(ref) else 0.0
    globally_valid = bool(finite_count and valid_ratio >= required_ratio and np.any(in_range))
    return (
        {
            "reference_valid": globally_valid,
            "reference_valid_ratio": valid_ratio,
            "reference_range_valid_ratio": range_valid_ratio,
            "reference_stale": stale,
            "reference_issues": issues,
            "polar_review_required": bool(issues),
            "polar_issues": issues,
        },
        in_range,
    )
