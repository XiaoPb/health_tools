import numpy as np

from health_tools.core.analysis.hr_diagnostics import (
    detect_agc_instability,
    detect_ipd_periodic_drift,
    synthesize_hr_diagnosis,
)


def test_detect_ipd_periodic_drift_reports_window_and_threshold():
    rate = 25.0
    t = np.arange(0, 12, 1 / rate)
    ipd = 12.0 + 3.0 * np.sin(2 * np.pi * t / 3.0)

    result = detect_ipd_periodic_drift(
        ipd, rate, baseline_window_s=2.0, amplitude_ua=2.0, min_duration_s=5.0
    )

    assert result["id"] == "loose_wear_periodic"
    assert result["detected"] is True
    assert result["start_s"] == 0.0
    assert result["end_s"] >= 11.0
    assert result["peak_to_peak_ua"] > 2.0
    assert result["amplitude_threshold_ua"] == 2.0


def test_detect_ipd_periodic_drift_does_not_promote_single_spike():
    values = np.ones(250) * 10.0
    values[120] = 30.0

    result = detect_ipd_periodic_drift(values, 25.0, 2.0, amplitude_ua=2.0, min_duration_s=5.0)

    assert result["detected"] is False
    assert result["status"] == "not_detected"


def test_detect_ipd_periodic_drift_marks_short_input_not_evaluable():
    result = detect_ipd_periodic_drift([1.0, 2.0], 25.0, 2.0, min_duration_s=5.0)

    assert result["status"] == "not_evaluable"
    assert result["detected"] is False


def test_detect_agc_instability_requires_six_changes_in_five_seconds():
    result = detect_agc_instability(
        [(0.0, 1), (0.5, 2), (1.0, 3), (1.5, 4), (2.0, 5), (2.5, 6), (3.0, 7)],
        sample_rate=25.0,
    )

    assert result["detected"] is True
    assert result["change_count"] == 6
    assert result["max_burst_count"] == 6
    assert result["status"] == "supporting"


def test_detect_agc_instability_ignores_changes_spread_over_five_seconds():
    values = [(0.0, 1), (6.0, 2), (12.0, 3), (18.0, 4), (24.0, 5), (30.0, 6), (36.0, 7)]

    result = detect_agc_instability(values, sample_rate=25.0)

    assert result["detected"] is False
    assert result["max_burst_count"] == 1


def test_synthesize_hr_diagnosis_does_not_add_actions_for_algorithm_cause():
    result = synthesize_hr_diagnosis(
        {
            "raw_valid": True,
            "reference_valid": True,
            "algorithm_abnormal": True,
            "psd_locked": True,
        }
    )

    assert result["cause"]["origin"] == "algorithm"
    assert "suggestions" not in result["cause"]
