"""check 规则模型与内置声明测试。"""

from health_tools.models.rules import (
    AccuracyMarkRule,
    CheckAccuracyRule,
    CheckRule,
)
from health_tools.rules.loader import RuleLoader


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
        "accuracy",
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
