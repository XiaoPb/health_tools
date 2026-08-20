from health_tools.core.analysis.models import AnalysisRecord
from health_tools.core.analysis.reporting import _detail_records


def test_detail_records_default_to_normal_low_accuracy_and_sort_stably():
    records = [
        AnalysisRecord(
            "z.csv",
            "z.csv",
            "hr",
            classification=["normal"],
            metrics={"samples": 10, "within_5": 40, "max_error": 12},
        ),
        AnalysisRecord(
            "a.csv",
            "a.csv",
            "hr",
            classification=["normal"],
            metrics={"samples": 10, "within_5": 20, "max_error": 8},
        ),
        AnalysisRecord(
            "warning.csv",
            "warning.csv",
            "hr",
            classification=["acc_warning"],
            metrics={"samples": 10, "within_5": 0, "max_error": 99},
        ),
        AnalysisRecord(
            "good.csv",
            "good.csv",
            "hr",
            classification=["normal"],
            metrics={"samples": 10, "within_5": 100, "max_error": 0},
        ),
    ]

    selected = _detail_records(records)

    assert [record.file for record in selected] == ["a.csv", "z.csv"]


def test_detail_records_include_requested_category_and_focus():
    records = [
        AnalysisRecord(
            "warning.csv",
            "warning.csv",
            "hr",
            classification=["acc_warning"],
            metrics={"samples": 10, "within_5": 0, "max_error": 99},
        ),
        AnalysisRecord(
            "centered.csv",
            "centered.csv",
            "hr",
            classification=["centered"],
            metrics={"samples": 10, "within_5": 0, "max_error": 90},
        ),
    ]

    included = _detail_records(records, include_categories=("acc_warning",))
    focused = _detail_records(records, focus=("centered.csv",))

    assert [record.file for record in included] == ["warning.csv"]
    assert [record.file for record in focused] == ["centered.csv"]
