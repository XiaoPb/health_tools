import pytest

from health_tools.api.analysis_operation import _request_key
from health_tools.api.models import AnalyzeRequest
from health_tools.core.analysis.classification import (
    ClassificationRecord,
    classify_file,
    compact_classification_rows,
    load_classification_rules,
)


def test_classification_record_keeps_labels_and_serializes():
    record = ClassificationRecord(
        "a.csv", labels=("acc_warning", "near_zero"), primary="acc_warning"
    )
    assert record.labels == ("acc_warning", "near_zero")
    assert record.to_dict()["labels"] == ["acc_warning", "near_zero"]


def test_cli_rules_have_priority_and_match_path():
    rules = load_classification_rules(
        yaml_text="categories:\n  - name: yaml\n    pattern: sample\n    labels: [other]\n    priority: 1\n",
        cli=("cli=sample",),
    )
    result = classify_file("sample.csv", rules=rules)
    assert result.primary == "cli"
    assert "other" in result.labels


def test_invalid_regex_is_readable():
    with pytest.raises(ValueError, match="正则无效"):
        load_classification_rules(
            yaml_text="categories:\n  - {name: bad, pattern: '[', labels: [other]}"
        )


def test_compact_rows_include_each_label():
    record = ClassificationRecord("a.csv", scene="static", labels=("other", "near_zero"))
    rows = compact_classification_rows([record])
    assert {row["category"] for row in rows} == {"other", "near_zero"}


def test_classification_options_change_request_fingerprint_key(tmp_path):
    base = AnalyzeRequest(tmp_path / "input", tmp_path / "out")
    custom = AnalyzeRequest(
        tmp_path / "input", tmp_path / "out", classify_rule="rules.yaml", classify=("x=a",)
    )
    assert _request_key(base, base.input_path)["classify"] != _request_key(
        custom, custom.input_path
    )["classify"]
