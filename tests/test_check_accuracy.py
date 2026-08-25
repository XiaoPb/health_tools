import csv

import numpy as np
import pandas as pd
import pytest

from health_tools.api.check_operation import (
    _resolve_accuracy_methods,
    _save_compact_report,
    _save_report,
)
from health_tools.api.models import CheckAccuracyResult, CheckRequest, ItemResult, ItemStatus
from health_tools.core.check_accuracy import calculate_check_accuracy, match_accuracy_mark
from health_tools.core.checker import CheckResult as ItemCheckResult
from health_tools.core.checker import FileCheckReport
from health_tools.models.rules import (
    AccuracyConditionRule,
    AccuracyMarkRule,
    CheckAccuracyRule,
)
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
            "online_low", "online.within_5", "lt", 80, "accuracy_online_low", "Online ±5准确度低"
        ),
        AccuracyMarkRule(
            "online_gap",
            "online.within_5",
            "diff_gte",
            10,
            "accuracy_online_below_comp",
            "Online低于Comp 10个百分点",
            right="comp.within_5",
        ),
    )
    assert match_accuracy_mark(result, marks).id == "online_low"


def test_accuracy_mark_minimum_is_strictly_below_threshold() -> None:
    result = CheckAccuracyResult(online={"within_5": 80.0})
    mark = AccuracyMarkRule("low", "online.within_5", "lt", 80, "low", "低")
    assert match_accuracy_mark(result, (mark,)) is None


@pytest.mark.parametrize(
    "mark, expected",
    [
        (AccuracyMarkRule("lt", "online.mae", "lt", 8, "lt", "lt"), False),
        (AccuracyMarkRule("lte", "online.mae", "lte", 8, "lte", "lte"), True),
        (AccuracyMarkRule("gt", "online.mae", "gt", 7, "gt", "gt"), True),
        (AccuracyMarkRule("gte", "online.mae", "gte", 8, "gte", "gte"), True),
        (
            AccuracyMarkRule(
                "diff_gte",
                "online.within_5",
                "diff_gte",
                15,
                "diff_gte",
                "diff_gte",
                right="comp.within_5",
            ),
            True,
        ),
        (
            AccuracyMarkRule(
                "diff_gt",
                "online.within_5",
                "diff_gt",
                15,
                "diff_gt",
                "diff_gt",
                right="comp.within_5",
            ),
            False,
        ),
        (
            AccuracyMarkRule(
                "ratio_lt",
                "online.within_5",
                "ratio_lt",
                0.9,
                "ratio_lt",
                "ratio_lt",
                right="comp.within_5",
            ),
            True,
        ),
        (
            AccuracyMarkRule(
                "ratio_lte",
                "online.within_5",
                "ratio_lte",
                70 / 85,
                "ratio_lte",
                "ratio_lte",
                right="comp.within_5",
            ),
            True,
        ),
    ],
)
def test_declarative_accuracy_mark_operators(mark, expected) -> None:
    result = CheckAccuracyResult(online={"mae": 8.0, "within_5": 70.0}, comp={"within_5": 85.0})

    assert (match_accuracy_mark(result, (mark,)) is mark) is expected


def test_declarative_ratio_mark_does_not_match_zero_or_missing_right_value() -> None:
    mark = AccuracyMarkRule(
        "ratio", "online.within_5", "ratio_lt", 0.9, "ratio", "比例低", right="comp.within_5"
    )

    assert match_accuracy_mark(CheckAccuracyResult(online={"within_5": 70}), (mark,)) is None
    assert (
        match_accuracy_mark(
            CheckAccuracyResult(online={"within_5": 70}, comp={"within_5": 0}), (mark,)
        )
        is None
    )


def test_check_report_places_scene_and_primary_issue_after_total(tmp_path) -> None:
    mark = AccuracyMarkRule("low", "online.within_5", "lt", 80, "accuracy_low", "Online准确度低")
    report = FileCheckReport(
        tmp_path / "sample.csv",
        "gh3036",
        scene="rest",
        name="zhangsan",
        hand="left",
        results=[ItemCheckResult("帧完整性", True, "正常")],
        accuracy_result=CheckAccuracyResult(
            online={"samples": 3, "mae": 2.0, "rmse": 3.0, "correlation": 0.9, "within_5": 66.666},
            matched_mark=mark,
        ),
    )
    output = tmp_path / "check_report.csv"

    _save_report([report], {}, output, tmp_path, False)

    with output.open(newline="", encoding="utf-8-sig") as handle:
        header, row = list(csv.reader(handle))
    assert header[:7] == [
        "文件名",
        "芯片",
        "总异常(结果)",
        "场景分类",
        "姓名",
        "手别",
        "主要异常项",
    ]
    assert row[3:7] == ["rest", "zhangsan", "left", "Online准确度低"]
    assert header[7:11] == [
        "帧完整性(结果)",
        "帧完整性(说明)",
        "Online准确度样本数",
        "Online MAE",
    ]
    assert row[header.index("Online ±5BPM准确度")] == "66.67%"
    assert header[-1] == "文件相对路径"


def test_check_report_includes_skipped_and_failed_items_with_reason_only(tmp_path) -> None:
    output = tmp_path / "check_report.csv"
    items = (
        ItemResult(ItemStatus.SKIP, str(tmp_path / "missing.csv"), reason="无法识别芯片"),
        ItemResult(ItemStatus.FAIL, str(tmp_path / "broken.csv"), reason="处理失败"),
    )

    _save_report([], {}, output, tmp_path, False, items)

    with output.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["总异常(结果)"] for row in rows] == ["SKIP", "FAIL"]
    assert rows[0]["主要异常项"] == "跳过：无法识别芯片"
    assert rows[1]["主要异常项"] == "失败：处理失败"
    assert rows[0]["芯片"] == ""
    assert rows[0]["文件相对路径"] == "missing.csv"
    assert all(
        value == ""
        for key, value in rows[0].items()
        if key.endswith("(结果)") and key != "总异常(结果)"
    )


def test_check_report_includes_failure_detail_after_reason(tmp_path) -> None:
    output = tmp_path / "check_report.csv"
    items = (
        ItemResult(
            ItemStatus.FAIL,
            str(tmp_path / "broken.csv"),
            reason="CSV格式错误",
            detail="ParserError: Expected 4 fields in line 3, saw 5",
        ),
    )

    _save_report([], {}, output, tmp_path, False, items)

    with output.open(newline="", encoding="utf-8-sig") as handle:
        row = next(csv.DictReader(handle))
    assert row["主要异常项"] == "失败：CSV格式错误：ParserError: Expected 4 fields in line 3, saw 5"


def test_compact_report_includes_accuracy_mark_details(tmp_path) -> None:
    mark = AccuracyMarkRule("low", "online.within_5", "lt", 80, "accuracy_low", "Online准确度低")
    report = FileCheckReport(
        tmp_path / "sample.csv",
        "gh3036",
        accuracy_result=CheckAccuracyResult(
            online={"samples": 3, "within_5": 66.67}, matched_mark=mark
        ),
    )
    output = tmp_path / "check_report_compact.csv"

    _save_compact_report([report], output, tmp_path)

    with output.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["检查项"] == "准确度标定"
    assert rows[0]["状态"] == "WARNING"
    assert rows[0]["说明"] == "Online准确度低"
    assert rows[0]["准确度指标"] == "±5BPM"


def test_compact_report_uses_declarative_ratio_value(tmp_path) -> None:
    mark = AccuracyMarkRule(
        "ratio",
        "online.within_5",
        "ratio_lt",
        0.9,
        "accuracy_ratio_low",
        "Online低于Comp的90%",
        right="comp.within_5",
    )
    report = FileCheckReport(
        tmp_path / "ratio.csv",
        "gh3036",
        accuracy_result=CheckAccuracyResult(
            online={"samples": 3, "within_5": 60.0},
            comp={"samples": 3, "within_5": 80.0},
            matched_mark=mark,
        ),
    )
    output = tmp_path / "check_report_compact.csv"

    _save_compact_report([report], output, tmp_path)

    with output.open(newline="", encoding="utf-8-sig") as handle:
        row = next(csv.DictReader(handle))
    assert row["异常数"] == "0.75"
    assert row["异常占比"] == "0.75%"
    assert row["比较对象"] == "Online vs Comp"
    assert row["准确度阈值"] == "0.9"


def test_check_report_uses_resolved_accuracy_methods(tmp_path) -> None:
    report = FileCheckReport(
        tmp_path / "custom.csv",
        "gh3036",
        accuracy_methods=("mae", "correlation"),
        accuracy_result=CheckAccuracyResult(
            online={"samples": 2, "mae": 1.0, "correlation": 0.8},
            comp=None,
        ),
    )
    output = tmp_path / "custom_report.csv"

    _save_report([report], {}, output, tmp_path, False)

    with output.open(newline="", encoding="utf-8-sig") as handle:
        header = next(csv.reader(handle))
    assert "Online MAE" in header
    assert "Online相关系数" in header
    assert "Online ±5BPM准确度" not in header


def test_check_report_uses_request_issue_priority_for_primary_issue(tmp_path) -> None:
    report = FileCheckReport(
        tmp_path / "custom.csv",
        "gh3036",
        results=[
            ItemCheckResult("帧完整性", False, "失败"),
            ItemCheckResult("数据范围", False, "失败"),
        ],
    )
    output = tmp_path / "custom_report.csv"

    _save_report([report], {}, output, tmp_path, False, issue_priority=("range_fail", "frame_fail"))

    with output.open(newline="", encoding="utf-8-sig") as handle:
        row = next(csv.DictReader(handle))
    assert row["主要异常项"] == "数据范围异常"


def test_check_request_accuracy_thresholds_replace_within_methods() -> None:
    request = CheckRequest(
        accuracy_enabled=True,
        accuracy_methods=("mae", "within_5", "within_10", "rmse"),
        accuracy_thresholds=(3.0, 6.0),
    )

    assert _resolve_accuracy_methods(request) == ["mae", "within_3", "within_6", "rmse"]


def test_check_report_columns_follow_request_accuracy_thresholds(tmp_path) -> None:
    request = CheckRequest(
        accuracy_enabled=True,
        accuracy_methods=("mae", "within_5", "within_10"),
        accuracy_thresholds=(3.0, 6.0),
    )
    report = FileCheckReport(
        tmp_path / "custom.csv",
        "gh3036",
        accuracy_methods=tuple(_resolve_accuracy_methods(request)),
        accuracy_result=CheckAccuracyResult(
            online={"samples": 2, "mae": 1.0, "within_3": 90.0, "within_6": 100.0},
            comp=None,
        ),
    )
    output = tmp_path / "custom_report.csv"

    _save_report([report], {}, output, tmp_path, False)

    with output.open(newline="", encoding="utf-8-sig") as handle:
        header = next(csv.reader(handle))
    assert "Online ±3BPM准确度" in header
    assert "Online ±6BPM准确度" in header
    assert "Online ±5BPM准确度" not in header


def test_accuracy_mark_folds_single_condition_shorthand() -> None:
    mark = AccuracyMarkRule("low", "online.within_5", "lt", 80, "accuracy_low", "Online准确度低")
    assert mark.conditions == (AccuracyConditionRule("online.within_5", "lt", 80.0, None),)
    assert mark.left == "online.within_5"
    assert mark.threshold == 80.0
    assert mark.match == "all"


def test_accuracy_mark_keeps_composite_conditions() -> None:
    mark = AccuracyMarkRule(
        id="bad_and_low",
        category="accuracy_bad_and_low",
        label="组合",
        match="any",
        conditions=(
            AccuracyConditionRule("online.within_5", "diff_gte", 10.0, "comp.within_5"),
            AccuracyConditionRule("online.within_5", "lt", 80.0),
        ),
    )
    assert mark.match == "any"
    assert len(mark.conditions) == 2
    assert mark.left is None


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (
            {
                "id": "x",
                "category": "c",
                "label": "l",
                "left": "online.within_5",
                "operator": "lt",
                "threshold": 80.0,
                "conditions": (AccuracyConditionRule("online.within_5", "lt", 80.0),),
            },
            "不能同时提供",
        ),
        (
            {"id": "x", "category": "c", "label": "l"},
            "必须提供",
        ),
        (
            {
                "id": "x",
                "category": "c",
                "label": "l",
                "left": "online.within_5",
                "operator": "lt",
                "match": "xor",
                "conditions": (AccuracyConditionRule("online.within_5", "lt", 80.0),),
            },
            "必须是 all 或 any",
        ),
        (
            {
                "id": "x",
                "category": "c",
                "label": "l",
                "left": "online.within_5",
                "threshold": 80.0,
            },
            "必须提供 left/operator/threshold",
        ),
    ],
)
def test_accuracy_mark_rejects_invalid_combinations(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        AccuracyMarkRule(**kwargs)


def test_accuracy_mark_folds_shorthand_right() -> None:
    mark = AccuracyMarkRule("g", "online.within_5", "diff_gte", 10, "c", "l", right="comp.within_5")
    assert mark.conditions == (
        AccuracyConditionRule("online.within_5", "diff_gte", 10.0, "comp.within_5"),
    )
    assert mark.conditions[0].right == "comp.within_5"
    assert mark.right == "comp.within_5"


def test_accuracy_mark_folds_shorthand_with_empty_conditions() -> None:
    mark = AccuracyMarkRule("g", "online.within_5", "diff_gte", 10, "c", "l", conditions=())
    assert mark.conditions == (AccuracyConditionRule("online.within_5", "diff_gte", 10.0, None),)


def test_accuracy_mark_composite_defaults_to_all_match() -> None:
    mark = AccuracyMarkRule(
        id="g",
        category="c",
        label="l",
        conditions=(AccuracyConditionRule("online.within_5", "diff_gte", 10.0),),
    )
    assert mark.match == "all"


def test_accuracy_mark_rejects_right_with_conditions() -> None:
    with pytest.raises(ValueError, match="不能同时提供"):
        AccuracyMarkRule(
            id="x",
            category="c",
            label="l",
            right="comp.within_5",
            conditions=(AccuracyConditionRule("online.within_5", "lt", 80.0),),
        )


def test_accuracy_mark_rejects_operator_without_left() -> None:
    with pytest.raises(ValueError, match="必须提供 conditions 或 left/operator/threshold"):
        AccuracyMarkRule(
            id="x",
            category="c",
            label="l",
            operator="lt",
            threshold=80.0,
        )
