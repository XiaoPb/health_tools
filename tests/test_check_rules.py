"""check 规则模型与内置声明测试。"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from health_tools.api.models import BatchResult, CheckResult
from health_tools.commands.check import check_cmd
from health_tools.models.rules import (
    AccuracyMarkRule,
    CheckAccuracyRule,
    CheckRule,
)
from health_tools.rules.loader import RuleLoader
from health_tools.rules.validator import RuleValidator


def _capture_check_request(monkeypatch):
    captured = {}

    def fake_run_check(request, *, context=None):
        captured["request"] = request
        return CheckResult(BatchResult("check"))

    monkeypatch.setattr("health_tools.api.run_check", fake_run_check)
    return captured


def _write_check_rule(tmp_path: Path) -> Path:
    rule = tmp_path / "check.yaml"
    rule.write_text(
        """version: '1.0'
chip: gh3220
checks: [frame, ref]
ratios:
  frame: 2
acc_axis: true
timestamp:
  column: TS
  ratio: 15
reference:
  hr_column: REF_HR
accuracy:
  enabled: true
  ref_column: REF
  online_column: ONLINE
  comp_column: COMP
  methods: [mae, within_5]
  thresholds:
    - {name: within_3, value: 3}
  inclusive: true
  marks:
    - id: online_low
      comparison: online
      metric: within_5
      min: 80
      category: accuracy_online_low
      label: Online 准确度低
""",
        encoding="utf-8",
    )
    return rule


def test_check_cli_explicit_values_override_rule(monkeypatch, tmp_path):
    captured = _capture_check_request(monkeypatch)
    rule = _write_check_rule(tmp_path)

    result = CliRunner().invoke(
        check_cmd,
        [
            "-r",
            str(rule),
            "-c",
            "gh3036",
            "--frame-ratio",
            "0.5",
            "--no-acc-axis",
            "--no-accuracy",
            "--accuracy-strict",
            "--workers",
            "8",
        ],
    )

    assert result.exit_code == 0, result.output
    request = captured["request"]
    assert request.frame_ratio == 0.5
    assert request.chip_name == "gh3036"
    assert request.acc_axis is False
    assert request.accuracy_enabled is False
    assert request.accuracy_inclusive is False
    assert request.workers == 8


def test_check_rule_fills_unspecified_policy_values(monkeypatch, tmp_path):
    captured = _capture_check_request(monkeypatch)
    rule = _write_check_rule(tmp_path)

    result = CliRunner().invoke(check_cmd, ["-r", str(rule), "--workers", "8"])

    assert result.exit_code == 0, result.output
    request = captured["request"]
    assert request.rule_file == str(rule)
    assert request.checks == "frame,ref"
    assert request.frame_ratio == 2.0
    assert request.chip_name == "gh3220"
    assert request.acc_axis is True
    assert request.timestamp_column == "TS"
    assert request.timestamp_ratio == 15.0
    assert request.ref_hr_column == "REF_HR"
    assert request.accuracy_enabled is True
    assert request.accuracy_ref_column == "REF"
    assert request.accuracy_online_column == "ONLINE"
    assert request.accuracy_comp_column == "COMP"
    assert request.accuracy_methods == ("mae", "within_5")
    assert request.accuracy_custom_thresholds == ({"name": "within_3", "value": 3},)
    assert request.accuracy_inclusive is True
    assert request.accuracy_marks[0].id == "online_low"
    assert request.workers == 8


def test_check_cli_accuracy_marks_replace_rule_marks(monkeypatch, tmp_path):
    captured = _capture_check_request(monkeypatch)
    rule = _write_check_rule(tmp_path)

    result = CliRunner().invoke(
        check_cmd,
        [
            "-r",
            str(rule),
            "--accuracy-min",
            "comp:within_5:70:accuracy_comp_low:Comp 准确度低",
            "--online-comp-gap",
            "within_5:10:accuracy_gap:Online低于Comp",
        ],
    )

    assert result.exit_code == 0, result.output
    marks = captured["request"].accuracy_marks
    assert [mark.comparison for mark in marks] == ["comp", "online_below_comp"]
    assert marks[0].min == 70.0
    assert marks[1].min_gap == 10.0


def test_check_cli_accuracy_marks_keep_reverse_interleaved_order(monkeypatch):
    captured = _capture_check_request(monkeypatch)

    result = CliRunner().invoke(
        check_cmd,
        [
            "--online-comp-gap",
            "within_5:10:first_gap",
            "--accuracy-min",
            "online:within_5:80:online_low",
            "--online-comp-gap",
            "within_10:15:second_gap",
        ],
    )

    assert result.exit_code == 0, result.output
    marks = captured["request"].accuracy_marks
    assert [mark.category for mark in marks] == ["first_gap", "online_low", "second_gap"]
    assert len({mark.id for mark in marks}) == 3


@pytest.mark.parametrize("category", ["../outside", "nested/path", r"nested\path", "has space"])
def test_check_cli_accuracy_marks_reject_unsafe_category(category):
    result = CliRunner().invoke(
        check_cmd,
        ["--accuracy-min", f"online:within_5:80:{category}"],
    )

    assert result.exit_code == 2
    assert "安全的单段目录名" in result.output


def test_check_cli_accuracy_marks_reject_duplicate_category_across_option_types():
    result = CliRunner().invoke(
        check_cmd,
        [
            "--accuracy-min",
            "online:within_5:80:duplicate",
            "--online-comp-gap",
            "within_5:10:duplicate",
        ],
    )

    assert result.exit_code == 2
    assert "category 重复" in result.output


def test_check_sort_infers_report_from_check_output_path(monkeypatch, tmp_path):
    captured = _capture_check_request(monkeypatch)
    report = tmp_path / "reports" / "custom.csv"

    result = CliRunner().invoke(
        check_cmd,
        ["--sort", "-o", str(report), "--sort-output", str(tmp_path / "sorted")],
    )

    assert result.exit_code == 0, result.output
    assert captured["request"].report_path == report


def test_check_sort_infers_default_report_from_input(monkeypatch, tmp_path):
    captured = _capture_check_request(monkeypatch)
    input_dir = tmp_path / "input"

    result = CliRunner().invoke(
        check_cmd,
        ["--sort", "-i", str(input_dir), "--sort-output", str(tmp_path / "sorted")],
    )

    assert result.exit_code == 0, result.output
    assert captured["request"].report_path == input_dir / "check_report.csv"


def test_check_help_lists_rule_and_accuracy_options():
    result = CliRunner().invoke(check_cmd, ["--help"])

    assert result.exit_code == 0
    for option in (
        "--rule",
        "--accuracy / --no-accuracy",
        "--accuracy-ref-column",
        "--accuracy-online-column",
        "--accuracy-comp-column",
        "--accuracy-thresholds",
        "--accuracy-inclusive / --accuracy-strict",
        "--accuracy-min",
        "--online-comp-gap",
    ):
        assert option in result.output


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--accuracy-min", "other:within_5:80:category"),
        ("--accuracy-min", "online:within_5:not-a-number:category"),
        ("--online-comp-gap", "within_5:10"),
    ],
)
def test_check_rejects_invalid_accuracy_mark_options(option, value):
    result = CliRunner().invoke(check_cmd, [option, value])

    assert result.exit_code == 2
    assert "Error:" in result.output


def test_load_check_rule_keeps_all_supported_parameters():
    rule = RuleLoader.load_check_rule("default.yaml")

    assert rule.checks == (
        "range",
        "ipd",
        "frame",
        "center",
        "acc",
        "agc",
        "ref",
    )
    assert rule.ratios.frame == 1.0
    assert rule.timestamp.ratio == 20.0
    assert rule.reference.sample_rate == 25.0
    assert rule.accuracy.ref_column == "REF_RESULT0"
    assert rule.accuracy.methods == (
        "mae",
        "within_5",
        "within_10",
        "within_15",
        "rmse",
        "correlation",
    )
    assert rule.accuracy.marks[0].category == "accuracy_online_low"


def test_check_rule_models_keep_immutable_accuracy_mark_configuration():
    mark = AccuracyMarkRule(
        id="online_within_5_low",
        comparison="online",
        metric="within_5",
        category="accuracy_online_low",
        label="Online ±5准确度低",
        min=80.0,
    )
    accuracy = CheckAccuracyRule(
        enabled=True,
        ref_column="REF_RESULT0",
        online_column="ALGO_RESULT0",
        comp_column="COMP_RESULT0",
        methods=("mae", "within_5"),
        marks=(mark,),
    )
    rule = CheckRule(
        version="1.0",
        description="测试",
        chip="gh3036",
        values={
            "checks": ["frame"],
            "ratios": {"frame": 1.0},
            "timestamp": {"ratio": 20.0},
            "reference": {"sample_rate": 25.0},
        },
        accuracy=accuracy,
    )

    assert rule.accuracy.marks == (mark,)
    assert rule.accuracy.methods == ("mae", "within_5")
    assert rule.values["checks"] == ["frame"]


def test_check_rule_rejects_runtime_paths_and_controls():
    errors = RuleValidator.validate(
        {
            "version": "1.0",
            "input": "data",
            "output": "report.csv",
            "sort": True,
            "workers": 8,
            "accuracy": {"enabled": False},
        },
        "check",
    )

    message = " ".join(errors)
    assert "input" in message
    assert "output" in message
    assert "sort" in message
    assert "workers" in message


def test_validate_check_rule_rejects_invalid_accuracy_mark():
    errors = RuleValidator.validate(
        {
            "version": "1.0",
            "accuracy": {
                "enabled": True,
                "ref_column": "REF_RESULT0",
                "online_column": "ALGO_RESULT0",
                "marks": [{"id": "bad", "comparison": "online", "metric": "within_5"}],
            },
        },
        "check",
    )

    assert "marks[0]" in " ".join(errors)


def test_check_rule_reports_malformed_check_items_without_crashing():
    errors = RuleValidator.validate(
        {
            "version": "1.0",
            "checks": ["frame", ["bad"], {"name": "range"}, 1],
        },
        "check",
    )

    message = " ".join(errors)
    assert "checks" in message
    assert "checks[1]" in message


def test_check_rule_rejects_unsafe_accuracy_mark_id():
    errors = RuleValidator.validate(
        {
            "version": "1.0",
            "accuracy": {
                "enabled": True,
                "marks": [
                    {
                        "id": "../bad",
                        "comparison": "online",
                        "metric": "within_5",
                        "category": "accuracy_online_low",
                        "label": "Online 准确度低",
                        "min": 80,
                    }
                ],
            },
        },
        "check",
    )

    assert "id" in " ".join(errors)


def test_check_rule_rejects_non_boolean_flags_and_non_integer_counts():
    errors = RuleValidator.validate(
        {
            "version": "1.0",
            "tolerance": 1.5,
            "static_min": float("nan"),
            "acc_axis": "false",
            "accuracy": {"enabled": "false", "inclusive": 0},
        },
        "check",
    )

    message = " ".join(errors)
    assert "tolerance" in message
    assert "static_min" in message
    assert "acc_axis" in message
    assert "accuracy.enabled" in message
    assert "accuracy.inclusive" in message


@pytest.mark.parametrize(
    "thresholds",
    [
        {"name": "within_5", "value": 5},
        [{"name": "within_5"}],
        [{"name": "within_5", "value": 5, "percent": 10}],
        [{"name": "within_5", "value": -1}],
        [{"name": "within_5", "value": "5"}],
        [{"name": "within_5", "percent": float("inf")}],
        [{"name": 1, "value": 5}],
    ],
)
def test_check_rule_rejects_malformed_accuracy_thresholds(thresholds):
    errors = RuleValidator.validate(
        {"version": "1.0", "accuracy": {"thresholds": thresholds}},
        "check",
    )

    assert "accuracy.thresholds" in " ".join(errors)
