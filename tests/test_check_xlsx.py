"""check XLSX 报告分类聚合纯数据接口的单元测试。"""

from collections import Counter

from health_tools.utils.check_xlsx import (
    _count_field,
    _format_distribution,
    _row_category,
    build_category_summary,
    expand_issue_category_order,
)


def test_expand_issue_category_order_expands_accuracy_marks_in_place():
    rows = [{"准确度标定分类": "accuracy_online_low"}, {"准确度标定分类": "accuracy_comp_low"}]
    assert expand_issue_category_order(
        ("accuracy", "frame_fail"), rows, ("accuracy_online_low", "accuracy_comp_low")
    ) == ("accuracy_online_low", "accuracy_comp_low")


def test_build_category_summary_calculates_ratios():
    rows = [
        {"场景分类": "rest", "姓名": "alice"},
        {"场景分类": "rest", "姓名": "bob"},
    ]
    summary = build_category_summary(
        rows,
        category="frame",
        condition="帧完整性(结果)=FAIL",
        explanation="帧不完整",
        total_count=2,
    )
    assert summary["count"] == 2
    assert summary["ratio"] == 1.0
    assert summary["scene_distribution"] == "rest: 2 (100.00%)"
    assert "alice: 1 (50.00%)" in summary["person_distribution"]


def test_expand_issue_category_order_keeps_stable_category_mapping():
    rows = [
        {"帧完整性(结果)": "FAIL"},
        {"数据范围(结果)": "FAIL"},
        {"ACC异常(结果)": "FAIL"},
        {"时间戳间隔(结果)": "FAIL"},
        {"帧完整性(结果)": "WARNING"},
        {"心率金标(结果)": "FAIL"},
        {"ACC异常(结果)": "WARNING"},
        {"数据居中(结果)": "FAIL"},
    ]
    assert expand_issue_category_order(
        (
            "frame_fail",
            "range_fail",
            "acc_fail",
            "timestamp_fail",
            "frame_warning",
            "reference_fail",
            "acc_warning",
            "center_fail",
        ),
        rows,
        (),
    ) == (
        "frame",
        "range",
        "acc_fail",
        "timestamp",
        "frame_warning",
        "reference",
        "acc_warning",
        "center",
    )


def test_expand_issue_category_order_filters_categories_missing_from_rows():
    rows = [{"帧完整性(结果)": "FAIL"}]
    assert expand_issue_category_order(
        ("frame_fail", "range_fail", "timestamp_fail"), rows, ()
    ) == ("frame",)


def test_expand_issue_category_order_uses_accuracy_declaration_order():
    rows = [
        {"准确度标定分类": "accuracy_comp_low"},
        {"准确度标定分类": "accuracy_online_low"},
    ]
    assert expand_issue_category_order(
        ("accuracy",), rows, ("accuracy_online_low", "accuracy_comp_low")
    ) == ("accuracy_online_low", "accuracy_comp_low")


def test_row_category_matches_status_columns_in_priority_order():
    row = {
        "帧完整性(结果)": "FAIL",
        "数据范围(结果)": "FAIL",
        "ACC异常(结果)": "FAIL",
        "总异常(结果)": "FAIL",
    }
    assert _row_category(row, ("frame_fail", "range_fail", "acc_fail")) == "frame"
    assert _row_category(row, ("range_fail", "frame_fail")) == "range"
    assert _row_category(row, ("acc_fail",)) == "acc_fail"


def test_row_category_reference_matches_either_reference_column():
    for column in ("心率金标(结果)", "血氧金标(结果)"):
        row = {"总异常(结果)": "FAIL", column: "FAIL", "数据居中(结果)": "FAIL"}
        assert _row_category(row, ("reference_fail", "center_fail")) == "reference"


def test_row_category_accuracy_returns_mark_category_value():
    row = {"准确度标定分类": "accuracy_online_low", "帧完整性(结果)": "FAIL"}
    assert _row_category(row, ("accuracy", "frame_fail")) == "accuracy_online_low"
    assert _row_category(row, ("frame_fail", "accuracy")) == "frame"


def test_row_category_ignores_primary_issue_text():
    row = {"主要异常项": "帧不完整", "帧完整性(结果)": "PASS"}
    assert _row_category(row, ("frame_fail",)) == ""


def test_format_distribution_normalizes_empty_name_and_zero_total():
    counter = Counter({"": 2, "rest": 1})
    assert _format_distribution(counter, 3) == "default: 2 (66.67%), rest: 1 (33.33%)"
    assert _format_distribution(counter, 0) == "default: 2 (0.00%), rest: 1 (0.00%)"


def test_expand_issue_category_order_dedupes_duplicate_issue_ids():
    rows = [{"帧完整性(结果)": "FAIL"}, {"准确度标定分类": "accuracy_online_low"}]
    assert expand_issue_category_order(
        ("frame_fail", "frame_fail", "accuracy"), rows, ("accuracy_online_low",)
    ) == ("frame", "accuracy_online_low")


def test_expand_issue_category_order_dedupes_duplicate_accuracy_categories():
    rows = [{"准确度标定分类": "accuracy_online_low"}]
    assert expand_issue_category_order(
        ("accuracy",), rows, ("accuracy_online_low", "accuracy_online_low")
    ) == ("accuracy_online_low",)


def test_expand_issue_category_order_empty_rows_returns_empty_tuple():
    assert (
        expand_issue_category_order(("accuracy", "frame_fail"), [], ("accuracy_online_low",)) == ()
    )


def test_build_category_summary_zero_total_count_ratio_is_zero():
    rows = [{"场景分类": "rest", "姓名": "alice"}]
    summary = build_category_summary(rows, "frame", "cond", "expl", total_count=0)
    assert summary["count"] == 1
    assert summary["ratio"] == 0.0
    assert summary["scene_distribution"] == "rest: 1 (100.00%)"


def test_build_category_summary_empty_rows_zero_counts():
    summary = build_category_summary([], "frame", "cond", "expl", total_count=5)
    assert summary["count"] == 0
    assert summary["ratio"] == 0.0
    assert summary["scene_distribution"] == ""
    assert summary["person_distribution"] == ""


def test_row_category_missing_status_columns_returns_empty():
    row = {"姓名": "alice", "主要异常项": "帧不完整"}
    assert _row_category(row, ("frame_fail", "range_fail")) == ""


def test_row_category_matches_status_values_case_insensitively():
    row = {"帧完整性(结果)": "fail", "数据范围(结果)": "FAIL"}
    assert _row_category(row, ("frame_fail", "range_fail")) == "frame"
    assert _row_category(row, ("range_fail", "frame_fail")) == "range"


def test_row_category_skips_unknown_rule_ids():
    row = {"帧完整性(结果)": "FAIL"}
    assert _row_category(row, ("unknown_rule", "frame_fail")) == "frame"
    assert _row_category(row, ("unknown_rule", "other_unknown")) == ""


def test_count_field_normalizes_whitespace_only_values_to_default():
    rows = [
        {"场景分类": "   ", "姓名": "  "},
        {"场景分类": "rest", "姓名": "alice"},
    ]
    assert _count_field(rows, "场景分类") == Counter({"default": 1, "rest": 1})
    assert _count_field(rows, "姓名") == Counter({"default": 1, "alice": 1})


def test_build_category_summary_normalizes_whitespace_only_distribution_values():
    rows = [{"场景分类": " \t ", "姓名": "  "}]
    summary = build_category_summary(rows, "frame", "cond", "expl", total_count=1)
    assert summary["scene_distribution"] == "default: 1 (100.00%)"
    assert summary["person_distribution"] == "default: 1 (100.00%)"
