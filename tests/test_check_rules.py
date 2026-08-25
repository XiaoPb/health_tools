"""check 规则模型与内置声明测试。"""

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from health_tools.api.models import BatchResult, CheckResult
from health_tools.commands.check import check_cmd
from health_tools.models.rules import (
    CHECK_ISSUE_PRIORITY_IDS,
    DEFAULT_CHECK_ISSUE_PRIORITY,
    AccuracyConditionRule,
    AccuracyMarkRule,
    CheckAccuracyRule,
    CheckRule,
    normalize_check_issue_priority,
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
      left: online.within_5
      operator: lt
      threshold: 80
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
            "--workers",
            "8",
        ],
    )

    assert result.exit_code == 0, result.output
    request = captured["request"]
    assert request.frame_ratio == 0.5
    assert request.chip_name == "gh3036"
    assert request.acc_axis is False
    assert request.accuracy_enabled is True
    assert request.accuracy_inclusive is True
    assert request.workers == 8


def test_check_cli_defaults_to_single_worker(monkeypatch):
    captured = _capture_check_request(monkeypatch)

    result = CliRunner().invoke(check_cmd, [])

    assert result.exit_code == 0, result.output
    assert captured["request"].workers == 1


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


def test_check_cli_threads_normalized_issue_priority(monkeypatch, tmp_path):
    captured = _capture_check_request(monkeypatch)
    rule = tmp_path / "priority.yaml"
    rule.write_text(
        "version: '1.0'\nissue_priority: [center_fail, frame_fail]\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(check_cmd, ["-r", str(rule)])

    assert result.exit_code == 0, result.output
    assert captured["request"].issue_priority[:2] == ("center_fail", "frame_fail")
    assert "range_fail" in captured["request"].issue_priority


def test_check_sort_summary_uses_mark_order_without_category_prefix(monkeypatch, tmp_path):
    rule = tmp_path / "check.yaml"
    rule.write_text(
        """version: '1.0'
issue_priority: [accuracy, frame_fail]
accuracy:
  enabled: true
  marks:
    - id: online_low
      left: online.within_5
      operator: lt
      threshold: 80
      category: online_low
      label: Online 准确度低
    - id: comp_low
      left: comp.within_5
      operator: lt
      threshold: 70
      category: comp_low
      label: Comp 准确度低
""",
        encoding="utf-8",
    )

    def fake_run_check(request, *, context=None):
        return CheckResult(
            BatchResult("check"),
            sort_counts={
                "comp_low": 1,
                "online_low": 1,
                "frame": 1,
                "ipd": 1,
                "skipped": 0,
            },
        )

    monkeypatch.setattr("health_tools.api.run_check", fake_run_check)
    result = CliRunner().invoke(
        check_cmd,
        ["-r", str(rule), "--sort", "--sort-output", str(tmp_path / "sorted")],
    )

    assert result.exit_code == 0, result.output
    assert result.output.index("online_low=1") < result.output.index("comp_low=1")
    assert result.output.index("comp_low=1") < result.output.index("frame=1")
    assert result.output.index("frame=1") < result.output.index("ipd=1")


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


@pytest.mark.parametrize("input_name", ["input", "samples.csv"])
def test_check_sort_infers_report_using_actual_file_type(monkeypatch, tmp_path, input_name):
    captured = _capture_check_request(monkeypatch)
    input_path = tmp_path / input_name
    input_path.mkdir()

    result = CliRunner().invoke(
        check_cmd,
        ["--sort", "-i", str(input_path), "--sort-output", str(tmp_path / "sorted")],
    )

    assert result.exit_code == 0, result.output
    assert captured["request"].report_path == input_path / "check_report.csv"


def test_check_sort_infers_report_for_extensionless_file(monkeypatch, tmp_path):
    captured = _capture_check_request(monkeypatch)
    input_path = tmp_path / "input"
    input_path.write_text("csv", encoding="utf-8")

    result = CliRunner().invoke(
        check_cmd,
        ["--sort", "-i", str(input_path), "--sort-output", str(tmp_path / "sorted")],
    )

    assert result.exit_code == 0, result.output
    assert captured["request"].report_path == tmp_path / "check_report.csv"


def test_check_help_lists_rule_and_omits_accuracy_options():
    result = CliRunner().invoke(check_cmd, ["--help"])

    assert result.exit_code == 0
    assert "--rule" in result.output
    for option in (
        "--accuracy",
        "--accuracy-ref-column",
        "--accuracy-thresholds",
        "--accuracy-min",
    ):
        assert option not in result.output


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
    assert rule.accuracy.marks[0].category == "accuracy_online_below_comp"


def test_check_rule_models_keep_immutable_accuracy_mark_configuration():
    mark = AccuracyMarkRule(
        id="online_within_5_low",
        left="online.within_5",
        operator="lt",
        threshold=80.0,
        category="accuracy_online_low",
        label="Online ±5准确度低",
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


def test_check_rule_loads_declarative_accuracy_mark(tmp_path):
    rule_path = tmp_path / "declarative.yaml"
    rule_path.write_text(
        """version: '1.0'
accuracy:
  enabled: true
  methods: [mae, within_5]
  thresholds:
    - {name: within_3, value: 3}
  marks:
    - id: online_below_comp
      left: online.within_5
      operator: diff_gte
      right: comp.within_5
      threshold: 10
      category: accuracy_online_below_comp
      label: Online低于Comp 10个百分点
    - id: online_within_3_low
      left: online.within_3
      operator: lt
      threshold: 80
      category: accuracy_online_within_3_low
      label: Online自定义准确度低
""",
        encoding="utf-8",
    )

    rule = RuleLoader.load_check_rule(str(rule_path))

    assert rule.accuracy.marks == (
        AccuracyMarkRule(
            id="online_below_comp",
            left="online.within_5",
            operator="diff_gte",
            right="comp.within_5",
            threshold=10.0,
            category="accuracy_online_below_comp",
            label="Online低于Comp 10个百分点",
        ),
        AccuracyMarkRule(
            id="online_within_3_low",
            left="online.within_3",
            operator="lt",
            threshold=80.0,
            category="accuracy_online_within_3_low",
            label="Online自定义准确度低",
        ),
    )


def test_check_rule_rejects_legacy_accuracy_mark_fields():
    errors = RuleValidator.validate(
        {
            "version": "1.0",
            "accuracy": {
                "methods": ["within_5"],
                "marks": [
                    {
                        "id": "legacy",
                        "comparison": "online",
                        "metric": "within_5",
                        "min": 80,
                        "category": "legacy",
                        "label": "旧格式",
                    }
                ],
            },
        },
        "check",
    )

    message = " ".join(errors)
    assert "旧字段" in message
    assert "comparison" in message


@pytest.mark.parametrize("path", ["online.rmse", "comp.within_3"])
def test_check_rule_rejects_mark_metric_not_produced_by_methods_or_thresholds(path):
    errors = RuleValidator.validate(
        {
            "version": "1.0",
            "accuracy": {
                "methods": ["mae", "within_5"],
                "marks": [
                    {
                        "id": "unknown_metric",
                        "left": path,
                        "operator": "lt",
                        "threshold": 80,
                        "category": "unknown_metric",
                        "label": "未知指标",
                    }
                ],
            },
        },
        "check",
    )

    assert "未由 accuracy.methods 或 accuracy.thresholds 声明" in " ".join(errors)


def test_check_rule_rejects_unsafe_accuracy_mark_id():
    errors = RuleValidator.validate(
        {
            "version": "1.0",
            "accuracy": {
                "enabled": True,
                "marks": [
                    {
                        "id": "../bad",
                        "left": "online.within_5",
                        "operator": "lt",
                        "threshold": 80,
                        "category": "accuracy_online_low",
                        "label": "Online 准确度低",
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


def test_check_rule_issue_priority_defaults_and_partial_configuration():
    rule = CheckRule()
    assert rule.issue_priority == DEFAULT_CHECK_ISSUE_PRIORITY
    assert rule.issue_priority == CHECK_ISSUE_PRIORITY_IDS
    assert normalize_check_issue_priority(["center_fail", "frame_fail"]) == (
        "center_fail",
        "frame_fail",
        "range_fail",
        "acc_fail",
        "timestamp_fail",
        "frame_warning",
        "reference_fail",
        "acc_warning",
        "accuracy",
    )


def test_check_rule_loads_issue_priority_without_storing_in_values(tmp_path):
    rule_path = tmp_path / "priority.yaml"
    rule_path.write_text(
        "version: '1.0'\nissue_priority: [accuracy, frame_fail]\nchecks: [frame]\n",
        encoding="utf-8",
    )
    rule = RuleLoader.load_check_rule(str(rule_path))
    assert rule.issue_priority[:2] == ("accuracy", "frame_fail")
    assert "issue_priority" not in rule.values


@pytest.mark.parametrize(
    "value, expected",
    [
        ("frame_fail", "issue_priority 必须是列表"),
        ([], "issue_priority 必须是非空列表"),
        (["", "frame_fail"], "issue_priority[0] 必须是非空字符串"),
        (["unknown"], "issue_priority 包含未知项"),
        (["frame_fail", "frame_fail"], "issue_priority 不允许重复"),
    ],
)
def test_check_rule_rejects_invalid_issue_priority(value, expected):
    errors = RuleValidator.validate({"version": "1.0", "issue_priority": value}, "check")
    assert expected in " ".join(errors)


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


def test_check_rule_loads_composite_accuracy_marks(tmp_path) -> None:
    rule_path = tmp_path / "accuracy.yaml"
    rule_path.write_text(
        """version: '1.0'
accuracy:
  enabled: true
  marks:
    - id: single_low
      left: online.within_5
      operator: lt
      threshold: 80.0
      label: 单条件低
      category: accuracy_single_low
    - id: bad_and_low
      label: 组合与
      category: accuracy_bad_and_low
      match: all
      conditions:
        - left: online.within_5
          operator: diff_gte
          right: comp.within_5
          threshold: 10.0
        - left: online.within_5
          operator: lt
          threshold: 80.0
    - id: bad_or_low
      label: 组合或
      category: accuracy_bad_or_low
      match: any
      conditions:
        - left: online.within_5
          operator: lt
          threshold: 80.0
        - left: comp.within_5
          operator: lt
          threshold: 80.0
""",
        encoding="utf-8",
    )

    rule = RuleLoader.load_check_rule(str(rule_path))

    single, bad_and, bad_or = rule.accuracy.marks
    assert single.conditions == (AccuracyConditionRule("online.within_5", "lt", 80.0, None),)
    assert single.left == "online.within_5"
    assert bad_and.match == "all"
    assert bad_and.conditions[0].right == "comp.within_5"
    assert bad_and.conditions[1].threshold == 80.0
    assert bad_or.match == "any"
    assert len(bad_or.conditions) == 2


@pytest.mark.parametrize(
    ("yaml_body", "message"),
    [
        (
            """
version: '1.0'
accuracy:
  enabled: true
  marks:
    - id: x
      label: l
      category: c
      left: online.within_5
      operator: lt
      threshold: 80.0
      conditions:
        - left: online.within_5
          operator: lt
          threshold: 80.0
""",
            "不能同时",
        ),
        (
            """
version: '1.0'
accuracy:
  enabled: true
  marks:
    - id: x
      label: l
      category: c
      match: xor
      conditions:
        - left: online.within_5
          operator: lt
          threshold: 80.0
""",
            "match 仅支持",
        ),
        (
            """
version: '1.0'
accuracy:
  enabled: true
  marks:
    - id: x
      label: l
      category: c
      match: all
      conditions:
        - operator: lt
          threshold: 80.0
""",
            "缺少有效的 'left'",
        ),
        (
            """
version: '1.0'
accuracy:
  enabled: true
  marks:
    - id: x
      label: l
      category: c
      match: all
      conditions: []
""",
            "conditions 不能为空",
        ),
        (
            """
version: '1.0'
accuracy:
  enabled: true
  marks:
    - id: x
      label: l
      category: c
""",
            "必须提供 conditions 或 left/operator/threshold",
        ),
    ],
)
def test_check_rule_rejects_invalid_accuracy_marks(yaml_body, message) -> None:
    errors = RuleValidator.validate(yaml.safe_load(yaml_body), "check")
    assert message in "；".join(errors)
