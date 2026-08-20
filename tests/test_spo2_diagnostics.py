import numpy as np

from health_tools.core.analysis.spo2_diagnostics import analyze_fft_quality, classify_spo2_motion


def test_spo2_motion_threshold_separates_rest_and_motion():
    assert classify_spo2_motion({"x": np.ones(100), "y": np.ones(100)}, 25.0)["scene"] == "rest"
    moving = np.ones(100) + np.r_[np.zeros(50), np.ones(50)]
    assert classify_spo2_motion({"x": moving, "y": moving}, 25.0)["scene"] == "motion"


def test_fft_quality_identifies_weak_channel():
    t = np.arange(250) / 25.0
    result = analyze_fft_quality({"red": np.sin(2 * np.pi * 1.2 * t), "ir": np.zeros(250)}, 25.0)
    assert result["weak_channels"] == ["ir"]
