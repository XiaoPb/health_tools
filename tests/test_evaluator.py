from pathlib import Path

import pytest

from health_tools.core.evaluator import BatchEvaluator
from health_tools.models.rules import EvaluateRule


def _write_evaluate_csv(path: Path) -> Path:
    path.write_text(
        "ref,pred\n" "80,0\n" "81,81\n" "82,87\n" "0,0\n" "84,89\n" "85,85\n" "86,0\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("inclusive", "expected"),
    [(False, 60.0), (True, 100.0)],
)
def test_batch_evaluator_uses_shared_zero_boundary_and_comparison_mode(
    tmp_path: Path, inclusive: bool, expected: float
):
    rule = EvaluateRule(
        ref_column="ref",
        pred_column="pred",
        methods=["mae", "within_5"],
    )
    evaluator = BatchEvaluator(
        rule,
        accuracy_thresholds=(5.0,),
        accuracy_inclusive=inclusive,
    )

    result = evaluator._evaluate_file(_write_evaluate_csv(tmp_path / "sample.csv"))

    assert result is not None
    assert result["metrics_all"]["samples"] == 5
    assert result["metrics_all"]["within_5"] == expected
    assert result["metrics_all"]["mae"] == 2.0


def test_batch_evaluator_preserves_spo2_rule_thresholds_without_override(tmp_path: Path):
    rule = EvaluateRule(
        type="spo2",
        ref_column="ref",
        pred_column="pred",
        methods=["mae", "within_3", "within_6", "within_9"],
    )
    evaluator = BatchEvaluator(rule)

    result = evaluator._evaluate_file(_write_evaluate_csv(tmp_path / "sample.csv"))

    assert result is not None
    assert {"within_3", "within_6", "within_9"}.issubset(result["metrics_all"])


def test_batch_evaluator_excludes_all_zero_prediction(tmp_path: Path):
    path = tmp_path / "all_zero.csv"
    path.write_text("ref,pred\n80,0\n81,0\n82,0\n", encoding="utf-8")
    evaluator = BatchEvaluator(
        EvaluateRule(ref_column="ref", pred_column="pred", methods=["mae", "within_5"])
    )

    result = evaluator._evaluate_file(path)

    assert result is not None
    assert result["metrics_all"] == {"samples": 0}
