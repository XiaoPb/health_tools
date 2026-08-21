import numpy as np
import pandas as pd
import pytest

from health_tools.core.check_sampling import (
    build_sample_positions,
    normalize_frame_rate,
    predict_sample_rate_from_timestamp,
    sample_check_seconds,
)


def test_sample_check_seconds_starts_at_first_nonzero_online_and_keeps_rows_aligned():
    frame = pd.DataFrame(
        {
            "TimeStamp": range(1000, 1060),
            "REF": range(2000, 2060),
            "ONLINE": [0, 0, 0, 80] + list(range(81, 137)),
            "COMP": range(3000, 3060),
        }
    )

    positions = build_sample_positions(frame, sample_rate=25, online_column="ONLINE")
    sampled = sample_check_seconds(
        frame,
        positions=positions,
        timestamp_column="TimeStamp",
        ref_column="REF",
        online_column="ONLINE",
        comp_column="COMP",
    )

    assert sampled.index.tolist() == [3, 28, 53]
    assert sampled["time"].tolist() == [1003, 1028, 1053]
    assert sampled["ref"].tolist() == [2003, 2028, 2053]
    assert sampled["online"].tolist() == [80, 105, 130]
    assert sampled["comp"].tolist() == [3003, 3028, 3053]


def test_sample_check_seconds_keeps_empty_comp_column_when_unconfigured():
    frame = pd.DataFrame({"TimeStamp": [0, 40], "REF": [80, 81], "ONLINE": [80, 81]})
    positions = build_sample_positions(frame, sample_rate=1, online_column="ONLINE")
    sampled = sample_check_seconds(
        frame,
        positions=positions,
        timestamp_column="TimeStamp",
        ref_column="REF",
        online_column="ONLINE",
        comp_column=None,
    )
    assert sampled.columns.tolist() == ["time", "ref", "online", "comp"]
    assert sampled["comp"].isna().all()


def test_sample_check_seconds_returns_header_only_without_nonzero_online():
    frame = pd.DataFrame({"TimeStamp": [0, 40, 80], "REF": [80, 81, 82], "ONLINE": [0, np.nan, 0]})
    positions = build_sample_positions(frame, sample_rate=25, online_column="ONLINE")
    sampled = sample_check_seconds(
        frame,
        positions=positions,
        timestamp_column="TimeStamp",
        ref_column="REF",
        online_column="ONLINE",
        comp_column=None,
    )
    assert sampled.empty
    assert sampled.columns.tolist() == ["time", "ref", "online", "comp"]


@pytest.mark.parametrize("value", [0, -1, 25.5, float("nan"), float("inf")])
def test_normalize_frame_rate_rejects_non_positive_or_fractional_values(value):
    with pytest.raises(ValueError, match="正整数"):
        normalize_frame_rate(value)


def test_normalize_frame_rate_accepts_integer_float():
    assert normalize_frame_rate(25.0) == 25


def test_predict_sample_rate_from_timestamp_uses_median_millisecond_interval():
    frame = pd.DataFrame({"TimeStamp": [1000, 1010, 1020, 1030]})
    assert predict_sample_rate_from_timestamp(frame, timestamp_column="TimeStamp") == 100
