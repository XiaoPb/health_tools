import numpy as np

from health_tools.core.analysis.hr_diagnostics import (
    detect_agc_instability,
    detect_ipd_periodic_drift,
)


def test_ipd_periodic_drift_uses_configurable_two_ua_threshold():
    values = 100.0 + 2.0 * np.sin(np.linspace(0, 20 * np.pi, 250))
    result = detect_ipd_periodic_drift(values, 25.0, amplitude_ua=2.0)
    assert result["status"] == "detected"
    assert result["amplitude_ua"] > 2.0


def test_agc_requires_more_than_five_changes_in_five_seconds():
    values = np.zeros(250)
    values[[0, 20, 40, 60, 80, 100]] = np.arange(6)
    result = detect_agc_instability(values, 25.0)
    assert result["change_count"] == 10
    assert result["max_burst_count"] > 5
    assert result["status"] == "detected"
