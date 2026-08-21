import numpy as np
import pandas as pd
import pytest

from health_tools.api.models import CheckAccuracyResult
from health_tools.core.check_accuracy import calculate_check_accuracy, match_accuracy_mark
from health_tools.models.rules import AccuracyMarkRule, CheckAccuracyRule
from health_tools.utils.accuracy import calculate_accuracy, prepare_accuracy_columns


def config(**overrides) -> CheckAccuracyRule:
    values = {
        "enabled": True,
        "ref_column": "REF",
        "online_column": "ONLINE",
        "comp_column": "COMP",
        "methods": ("mae", "rmse", "correlation", "within_5"),
    }
    values.update(overrides)
    return CheckAccuracyRule(**values)


def test_check_accuracy_matches_offline_shared_boundary() -> None:
    frame = pd.DataFrame(
        {
            "REF": [0, 80, 85, 90, 0],
            "ONLINE": [0, 84, 95, 90, 0],
            "COMP": [0, 82, 85, 100, 0],
        }
    )

    result = calculate_check_accuracy(frame, config())

    assert result.online is not None
    assert result.comp is not None
    assert result.online["samples"] == 3
    assert result.online["within_5"] == 66.67
    assert result.comp["within_5"] == 66.67


def test_check_accuracy_skips_all_zero_comp() -> None:
    frame = pd.DataFrame({"REF": [80, 81], "ONLINE": [80, 82], "COMP": [0, 0]})

    result = calculate_check_accuracy(frame, config())

    assert result.online is not None
    assert result.online["samples"] == 2
    assert result.comp is None


def test_check_accuracy_disables_both_comparisons_when_ref_is_all_zero() -> None:
    frame = pd.DataFrame({"REF": [0, 0], "ONLINE": [80, 82], "COMP": [80, 81]})

    result = calculate_check_accuracy(frame, config())

    assert result.online == {"samples": 0}
    assert result.comp is None


def test_check_accuracy_still_computes_comp_when_online_is_all_zero() -> None:
    frame = pd.DataFrame({"REF": [80, 81], "ONLINE": [0, 0], "COMP": [80, 82]})

    result = calculate_check_accuracy(frame, config(methods=("mae",)))

    assert result.online == {"samples": 0}
    assert result.comp == {"mae": 0.5, "samples": 2}


@pytest.mark.parametrize(
    "comp_column, columns",
    [
        (None, {"REF": [80, 81], "ONLINE": [80, 82]}),
        ("COMP", {"REF": [80, 81], "ONLINE": [80, 82]}),
    ],
)
def test_check_accuracy_skips_unconfigured_or_missing_comp(comp_column, columns) -> None:
    result = calculate_check_accuracy(pd.DataFrame(columns), config(comp_column=comp_column))

    assert result.online is not None
    assert result.online["samples"] == 2
    assert result.comp is None


@pytest.mark.parametrize("missing", ["REF", "ONLINE"])
def test_check_accuracy_requires_ref_and_online_columns(missing: str) -> None:
    frame = pd.DataFrame({name: [80, 81] for name in ("REF", "ONLINE", "COMP") if name != missing})

    with pytest.raises(ValueError, match=f"缺少准确度列: {missing}"):
        calculate_check_accuracy(frame, config())


def test_check_accuracy_matches_shared_accuracy_helpers() -> None:
    frame = pd.DataFrame(
        {
            "REF": [0, 80, 0, np.nan, 84, 90, 0],
            "ONLINE": [0, 81, 0, 82, 85, 95, 0],
            "COMP": [0, 82, 0, 83, np.inf, 96, 0],
        }
    )
    rule = config(
        methods=("mae", "rmse", "correlation", "within_5"),
        thresholds=({"name": "within_3", "value": 3},),
        inclusive=True,
    )
    prepared = prepare_accuracy_columns(
        {"ref": frame["REF"], "online": frame["ONLINE"], "comp": frame["COMP"]}
    )
    metric_frame = pd.DataFrame(prepared.columns)

    result = calculate_check_accuracy(frame, rule)
    expected_online = calculate_accuracy(
        metric_frame,
        "ref",
        "online",
        list(rule.methods),
        list(rule.thresholds),
        rule.inclusive,
        trim_zero_padding=False,
    )
    expected_comp = calculate_accuracy(
        metric_frame,
        "ref",
        "comp",
        list(rule.methods),
        list(rule.thresholds),
        rule.inclusive,
        trim_zero_padding=False,
    )

    assert result.online == expected_online
    assert result.comp == expected_comp


def test_accuracy_marks_use_rule_order_and_percentage_point_gap() -> None:
    result = CheckAccuracyResult(online={"within_5": 70.0}, comp={"within_5": 85.0})
    marks = (
        AccuracyMarkRule(
            "online_low", "online", "within_5", "accuracy_online_low", "Online ±5准确度低", min=80
        ),
        AccuracyMarkRule(
            "online_gap",
            "online_below_comp",
            "within_5",
            "accuracy_online_below_comp",
            "Online低于Comp 10个百分点",
            min_gap=10,
        ),
    )
    assert match_accuracy_mark(result, marks).id == "online_low"


def test_accuracy_mark_minimum_is_strictly_below_threshold() -> None:
    result = CheckAccuracyResult(online={"within_5": 80.0})
    mark = AccuracyMarkRule("low", "online", "within_5", "low", "低", min=80)
    assert match_accuracy_mark(result, (mark,)) is None
