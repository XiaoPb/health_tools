"""准确度公共逻辑测试。"""

import numpy as np
import pandas as pd
import pytest

from health_tools.utils import (
    DEFAULT_ACCURACY_THRESHOLDS,
    AccuracyCalculator,
    PreparedAccuracyColumns,
    calculate_accuracy,
    calculate_within_percent,
    calculate_within_threshold,
    normalize_accuracy_thresholds,
    prepare_accuracy_columns,
    resolve_accuracy_methods,
)


def test_default_accuracy_thresholds_and_methods() -> None:
    assert DEFAULT_ACCURACY_THRESHOLDS == (5.0, 10.0, 15.0)
    assert resolve_accuracy_methods(None, None) == [
        "std",
        "rmse",
        "mae",
        "within_5",
        "within_10",
        "within_15",
    ]


def test_within_threshold_is_strict_by_default_and_can_be_inclusive() -> None:
    diff = np.array([4.9, 5.0, 5.1])

    assert calculate_within_threshold(diff, 5.0) == pytest.approx(100 / 3)
    assert calculate_within_threshold(diff, 5.0, inclusive=True) == pytest.approx(200 / 3)


def test_within_percent_is_strict_by_default_and_can_be_inclusive() -> None:
    ref = np.array([100.0, 100.0, 100.0])
    pred = np.array([95.1, 95.0, 94.9])

    assert calculate_within_percent(ref, pred, 5.0) == pytest.approx(100 / 3)
    assert calculate_within_percent(ref, pred, 5.0, inclusive=True) == pytest.approx(200 / 3)


def test_normalize_accuracy_thresholds_preserves_order() -> None:
    assert normalize_accuracy_thresholds(None) is None
    assert normalize_accuracy_thresholds([10, 3.5, 5]) == (10.0, 3.5, 5.0)


@pytest.mark.parametrize(
    "thresholds",
    [[], [0], [-1], [np.nan], [np.inf], [5, 5.0], ["invalid"]],
)
def test_normalize_accuracy_thresholds_rejects_invalid_values(thresholds) -> None:
    with pytest.raises(ValueError):
        normalize_accuracy_thresholds(thresholds)


def test_resolve_accuracy_methods_preserves_rule_thresholds_without_override() -> None:
    methods = ["rmse", "within_3", "within_6", "within_9", "mae", "std"]

    assert resolve_accuracy_methods(methods, None) == methods


def test_resolve_accuracy_methods_replaces_within_methods_stably() -> None:
    methods = ["rmse", "within_3", "within_6", "mae", "within_9", "std"]

    assert resolve_accuracy_methods(methods, [3.5, 7]) == [
        "rmse",
        "within_3.5",
        "within_7",
        "mae",
        "std",
    ]


def test_resolve_accuracy_methods_preserves_high_precision_thresholds() -> None:
    methods = resolve_accuracy_methods(["mae", "within_5"], [1.0000001, 1.0000002])

    assert methods == ["mae", "within_1.0000001", "within_1.0000002"]

    result = calculate_accuracy(
        pd.DataFrame({"ref": [10.0], "pred": [8.99999985]}),
        "ref",
        "pred",
        methods=methods,
        trim_zero_padding=False,
    )
    assert result["within_1.0000001"] == 0.0
    assert result["within_1.0000002"] == 100.0


def test_prepare_accuracy_columns_uses_common_boundaries_and_keeps_internal_zero() -> None:
    prepared = prepare_accuracy_columns(
        {
            "polar": [80, 81, 82, 0, 84, 85, 86],
            "online": [0, 81, 82, 0, 84, 85, 0],
            "offline": [0, 0, 82, 0, 84, 0, 0],
            "comp": [0, 0, 0, 0, 0, 0, 0],
        }
    )

    assert isinstance(prepared, PreparedAccuracyColumns)
    assert prepared.active_columns == ("polar", "online", "offline")
    assert (prepared.start, prepared.end) == (2, 5)
    assert prepared.columns["polar"].tolist() == [82.0, 0.0, 84.0]
    assert prepared.columns["online"].tolist() == [82.0, 0.0, 84.0]
    assert prepared.columns["offline"].tolist() == [82.0, 0.0, 84.0]
    assert prepared.columns["comp"].tolist() == [0.0, 0.0, 0.0]


@pytest.mark.parametrize(
    "columns, active_columns",
    [
        ({"ref": [], "pred": []}, ()),
        ({"ref": [np.nan, np.nan], "pred": [np.nan, np.nan]}, ()),
        ({"ref": [np.inf, -np.inf], "pred": [np.inf, -np.inf]}, ()),
        ({"ref": [0, 0], "pred": [0, 0]}, ()),
        ({"ref": [1, 0], "pred": [0, 2]}, ("ref", "pred")),
    ],
)
def test_prepare_accuracy_columns_returns_empty_without_common_ready_range(
    columns, active_columns
) -> None:
    prepared = prepare_accuracy_columns(columns)

    assert prepared.active_columns == active_columns
    assert (prepared.start, prepared.end) == (0, 0)
    assert all(len(values) == 0 for values in prepared.columns.values())


def test_prepare_accuracy_columns_rejects_different_lengths() -> None:
    with pytest.raises(ValueError):
        prepare_accuracy_columns({"ref": [1, 2], "pred": [1]})


def test_calculate_accuracy_returns_zero_samples_when_a_column_is_disabled() -> None:
    result = calculate_accuracy(pd.DataFrame({"ref": [80, 81], "pred": [0, 0]}), "ref", "pred")

    assert result == {"samples": 0}


def test_calculate_accuracy_keeps_internal_zero_and_filters_nonfinite_pairs() -> None:
    df = pd.DataFrame(
        {
            "ref": [0, 80, 0, np.nan, 84, np.inf, 0],
            "pred": [0, 81, 0, 82, 85, 86, 0],
        }
    )

    result = calculate_accuracy(df, "ref", "pred", methods=["mae"])

    assert result == {"mae": pytest.approx(2 / 3, abs=0.01), "samples": 3}


def test_calculate_accuracy_applies_inclusive_to_methods_and_rule_thresholds() -> None:
    df = pd.DataFrame({"ref": [100, 100, 100], "pred": [95.1, 95.0, 94.9]})
    thresholds = [
        {"name": "within_value", "value": 5},
        {"name": "within_percent", "percent": 5},
    ]

    strict = calculate_accuracy(df, "ref", "pred", ["within_5"], thresholds)
    inclusive = calculate_accuracy(df, "ref", "pred", ["within_5"], thresholds, inclusive=True)

    assert strict == {
        "within_5": 33.33,
        "within_value": 33.33,
        "within_percent": 33.33,
        "samples": 3,
    }
    assert inclusive == {
        "within_5": 66.67,
        "within_value": 66.67,
        "within_percent": 66.67,
        "samples": 3,
    }


def test_accuracy_calculator_aligns_pairs_and_weights_only_nonempty_files() -> None:
    calculator = AccuracyCalculator("ref", "pred", methods=["mae"], inclusive=True)

    first = calculator.add_file_result(
        "walk",
        pd.DataFrame({"ref": [10, np.nan, 30], "pred": [11, 21, 31]}),
    )
    second = calculator.add_file_result("walk", pd.DataFrame({"ref": [40, 50], "pred": [42, 52]}))
    empty = calculator.add_file_result("walk", pd.DataFrame({"ref": [0, 0], "pred": [0, 0]}))
    calculator.finalize()

    assert first == {"mae": 1.0, "samples": 2}
    assert second == {"mae": 2.0, "samples": 2}
    assert empty == {"samples": 0}
    assert calculator.category_results["walk"] == {
        "samples": 4,
        "files": 2,
        "mae": 1.5,
    }
    assert calculator.get_total_results() == {"mae": 1.5, "samples": 4}
    assert calculator.inclusive is True
