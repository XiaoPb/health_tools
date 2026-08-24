"""check XLSX 报告分类聚合与工作簿写出的单元测试。"""

from collections import Counter

from openpyxl import load_workbook

from health_tools.utils.check_xlsx import (
    _count_field,
    _format_distribution,
    _row_category,
    _safe_sheet_title,
    build_category_summary,
    expand_issue_category_order,
    write_check_workbook,
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


def test_write_check_workbook_creates_ordered_sheets(tmp_path):
    rows = [
        {
            "文件名": "a.csv",
            "总异常(结果)": "FAIL",
            "帧完整性(结果)": "FAIL",
            "场景分类": "rest",
            "姓名": "alice",
            "准确度标定分类": "",
        }
    ]
    output = tmp_path / "check_report.xlsx"
    write_check_workbook(
        output,
        rows,
        [{"文件名": "a.csv", "检查项": "帧完整性", "状态": "FAIL"}],
        issue_priority=("frame_fail", "accuracy"),
        accuracy_categories=(),
        category_descriptions={"frame": ("帧完整性(结果)=FAIL", "帧不完整")},
    )
    book = load_workbook(output)
    assert book.sheetnames == ["总表", "分类说明", "frame", "精简总表"]
    assert book["总表"]["A2"].value == "a.csv"
    assert book["frame"]["A2"].value == "a.csv"


def test_write_check_workbook_keeps_base_sheets_when_empty(tmp_path):
    output = tmp_path / "empty.xlsx"
    write_check_workbook(
        output,
        [],
        [],
        issue_priority=("frame_fail",),
        accuracy_categories=(),
        category_descriptions={},
    )
    book = load_workbook(output)
    assert book.sheetnames == ["总表", "分类说明", "精简总表"]
    assert book["分类说明"]["A1"].value == "优先级"
    assert book["总表"].max_row == 1


def test_safe_sheet_title_sanitizes_illegal_characters_and_truncates():
    assert _safe_sheet_title("a[b]:c*d?e/f\\g", set()) == "a_b__c_d_e_f_g"
    assert _safe_sheet_title("  frame  ", set()) == "frame"
    assert _safe_sheet_title("x" * 40, set()) == "x" * 31
    assert _safe_sheet_title("", set()) == "sheet"
    assert _safe_sheet_title("   ", set()) == "sheet"


def test_safe_sheet_title_appends_suffix_on_conflict_and_reserved_history():
    assert _safe_sheet_title("frame", {"frame"}) == "frame_2"
    assert _safe_sheet_title("frame", {"frame", "frame_2"}) == "frame_3"
    assert _safe_sheet_title("History", set()) == "History_2"
    assert _safe_sheet_title("History", {"History_2"}) == "History_3"


def test_write_check_workbook_applies_numeric_formats(tmp_path):
    rows = [
        {"文件名": "a.csv", "帧完整性(结果)": "FAIL", "场景分类": "rest", "姓名": "alice"},
        {"文件名": "b.csv", "帧完整性(结果)": "FAIL", "场景分类": "walk", "姓名": "bob"},
        {"文件名": "c.csv", "帧完整性(结果)": "PASS", "场景分类": "rest", "姓名": "carol"},
    ]
    output = tmp_path / "formats.xlsx"
    write_check_workbook(
        output,
        rows,
        [],
        issue_priority=("frame_fail",),
        accuracy_categories=(),
        category_descriptions={"frame": ("帧完整性(结果)=FAIL", "帧不完整")},
    )
    book = load_workbook(output)
    summary = book["分类说明"]
    assert summary["A2"].value == "frame_fail"
    assert summary["B2"].value == "frame"
    assert summary["C2"].value == 2
    assert summary["C2"].number_format == "0"
    assert summary["D2"].value == 2 / 3
    assert summary["D2"].number_format == "0.00%"
    assert summary["E2"].value == "帧完整性(结果)=FAIL"
    assert summary["H2"].value == "帧不完整"


def test_write_check_workbook_sets_freeze_panes_and_auto_filter(tmp_path):
    rows = [{"文件名": "a.csv", "帧完整性(结果)": "FAIL"}]
    output = tmp_path / "frozen.xlsx"
    write_check_workbook(
        output,
        rows,
        [{"文件名": "a.csv"}],
        issue_priority=("frame_fail",),
        accuracy_categories=(),
        category_descriptions={"frame": ("帧完整性(结果)=FAIL", "帧不完整")},
    )
    book = load_workbook(output)
    for name in ("总表", "分类说明", "frame", "精简总表"):
        ws = book[name]
        assert ws.freeze_panes == "A2"
        assert ws.auto_filter.ref is not None


def test_write_check_workbook_creates_category_sheets_only_for_hit_categories(tmp_path):
    rows = [
        {"文件名": "a.csv", "帧完整性(结果)": "FAIL"},
        {"文件名": "b.csv", "数据范围(结果)": "FAIL"},
        {"文件名": "c.csv", "帧完整性(结果)": "PASS"},
    ]
    output = tmp_path / "categories.xlsx"
    write_check_workbook(
        output,
        rows,
        [],
        issue_priority=("frame_fail", "range_fail", "timestamp_fail"),
        accuracy_categories=(),
        category_descriptions={"frame": ("帧完整性(结果)=FAIL", "帧不完整")},
    )
    book = load_workbook(output)
    assert book.sheetnames == ["总表", "分类说明", "frame", "range", "精简总表"]
    assert book["frame"].max_row == 2
    assert book["range"]["A2"].value == "b.csv"


def test_write_check_workbook_accuracy_sheet_sanitizes_title_keeps_data(tmp_path):
    rows = [{"文件名": "a.csv", "准确度标定分类": "acc[online]:low", "姓名": "alice"}]
    output = tmp_path / "accuracy.xlsx"
    write_check_workbook(
        output,
        rows,
        [],
        issue_priority=("accuracy",),
        accuracy_categories=("acc[online]:low",),
        category_descriptions={},
    )
    book = load_workbook(output)
    assert book.sheetnames == ["总表", "分类说明", "acc_online__low", "精简总表"]
    ws = book["acc_online__low"]
    headers = [cell.value for cell in ws[1]]
    mark_column = headers.index("准确度标定分类") + 1
    assert ws.cell(row=2, column=mark_column).value == "acc[online]:low"
    assert book["分类说明"]["A2"].value == "accuracy"
    assert book["分类说明"]["B2"].value == "acc[online]:low"


def test_write_check_workbook_compact_sheet_matches_compact_rows(tmp_path):
    compact_rows = [
        {"文件名": "a.csv", "检查项": "帧完整性", "状态": "FAIL"},
        {"文件名": "b.csv", "检查项": "数据范围", "状态": "FAIL"},
    ]
    output = tmp_path / "compact.xlsx"
    write_check_workbook(
        output,
        [],
        compact_rows,
        issue_priority=("frame_fail",),
        accuracy_categories=(),
        category_descriptions={},
    )
    book = load_workbook(output)
    ws = book["精简总表"]
    assert [cell.value for cell in ws[1]] == ["文件名", "检查项", "状态"]
    assert [cell.value for cell in ws[2]] == ["a.csv", "帧完整性", "FAIL"]
    assert [cell.value for cell in ws[3]] == ["b.csv", "数据范围", "FAIL"]
    assert ws.max_row == 3


def test_write_check_workbook_category_matching_fixed_names_gets_suffix(tmp_path):
    rows = [{"文件名": "a.csv", "准确度标定分类": "精简总表"}]
    output = tmp_path / "reserved.xlsx"
    write_check_workbook(
        output,
        rows,
        [],
        issue_priority=("accuracy",),
        accuracy_categories=("精简总表",),
        category_descriptions={},
    )
    book = load_workbook(output)
    assert book.sheetnames == ["总表", "分类说明", "精简总表_2", "精简总表"]
