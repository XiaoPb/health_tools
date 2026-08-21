"""check 规则模型与内置声明测试。"""

import pytest

from health_tools.models.rules import (
    AccuracyMarkRule,
    CheckAccuracyRule,
    CheckRule,
)
from health_tools.rules.loader import RuleLoader
from health_tools.rules.validator import RuleValidator


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
