"""原始 check 数据按采样率抽取秒级样本。"""

from typing import Optional

import numpy as np
import pandas as pd


def normalize_frame_rate(sample_rate: float) -> int:
    value = float(sample_rate)
    if not np.isfinite(value) or value <= 0 or not value.is_integer():
        raise ValueError("sample_rate 必须是正整数")
    return int(value)


def predict_sample_rate_from_timestamp(
    frame: pd.DataFrame, *, timestamp_column: str
) -> Optional[int]:
    """根据毫秒时间戳间隔估算原始采样率。"""
    if timestamp_column not in frame.columns:
        return None
    timestamp = pd.to_numeric(frame[timestamp_column], errors="coerce")
    intervals = timestamp.diff().to_numpy(dtype=float)
    intervals = intervals[np.isfinite(intervals) & (intervals > 0)]
    if intervals.size == 0:
        return None
    interval_ms = float(np.median(intervals))
    if interval_ms <= 0:
        return None
    predicted = int(round(1000.0 / interval_ms))
    return predicted if predicted > 0 else None


def build_sample_positions(
    frame: pd.DataFrame, *, sample_rate: float, online_column: str
) -> np.ndarray:
    rate = normalize_frame_rate(sample_rate)
    if online_column not in frame.columns:
        raise ValueError(f"缺少秒采样列: {online_column}")
    online = pd.to_numeric(frame[online_column], errors="coerce")
    values = online.to_numpy(dtype=float, na_value=np.nan)
    valid = np.isfinite(values) & (values != 0)
    starts = np.flatnonzero(valid)
    if starts.size == 0:
        return np.empty(0, dtype=np.int64)
    return np.arange(starts[0], len(frame), rate, dtype=np.int64)


def sample_check_seconds(
    frame: pd.DataFrame,
    *,
    positions: np.ndarray,
    timestamp_column: str,
    ref_column: str,
    online_column: str,
    comp_column: Optional[str],
) -> pd.DataFrame:
    required = (timestamp_column, ref_column, online_column)
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError("缺少秒采样列: " + ", ".join(missing))
    evidence = pd.DataFrame(
        {
            "time": frame[timestamp_column],
            "ref": frame[ref_column],
            "online": frame[online_column],
            "comp": (
                frame[comp_column]
                if comp_column and comp_column in frame.columns
                else pd.Series(pd.NA, index=frame.index, dtype="object")
            ),
        },
        index=frame.index,
    )
    return evidence.iloc[np.asarray(positions, dtype=np.int64)]
