import numpy as np
import pandas as pd
import pytest

from health_tools.core.ppg_analysis import (
    SignalAnalysisError,
    bandpass_signal,
    compute_pi,
    compute_single_sided_fft,
    prepare_signal,
    resolve_acc_columns,
    resolve_ppg_channels,
)


def test_prepare_signal_interpolates_missing_values():
    result = prepare_signal(pd.Series([1.0, None, 3.0]))

    np.testing.assert_allclose(result, [1.0, 2.0, 3.0])


def test_bandpass_signal_keeps_in_band_and_suppresses_out_of_band():
    sample_rate = 100
    time = np.arange(sample_rate * 10) / sample_rate
    source = np.sin(2 * np.pi * time) + np.sin(2 * np.pi * 10 * time)

    filtered = bandpass_signal(source, sample_rate, 0.5, 4.0)
    freqs, amplitude = compute_single_sided_fft(filtered, sample_rate)

    amp_1hz = amplitude[np.argmin(np.abs(freqs - 1.0))]
    amp_10hz = amplitude[np.argmin(np.abs(freqs - 10.0))]
    assert amp_1hz > amp_10hz * 20


def test_bandpass_signal_rejects_invalid_frequency_range():
    with pytest.raises(SignalAnalysisError, match="奈奎斯特"):
        bandpass_signal(np.arange(100), 10, 0.5, 5.0)


def test_compute_pi_uses_centered_complete_five_second_window():
    sample_rate = 10
    raw = np.full(100, 100.0)
    ac = np.full(100, 2.0)

    result = compute_pi(raw, ac, sample_rate)

    assert result.first_valid_index() == 25
    assert result.last_valid_index() == 75
    assert result.iloc[25] == pytest.approx(2.0)
    assert result.iloc[75] == pytest.approx(2.0)


def test_compute_pi_returns_nan_when_dc_is_zero():
    result = compute_pi(np.zeros(50), np.ones(50), sample_rate=10)

    assert result.isna().all()


def test_compute_single_sided_fft_finds_peak_and_excludes_dc():
    sample_rate = 50
    time = np.arange(sample_rate * 4) / sample_rate
    source = 100 + 3 * np.sin(2 * np.pi * 2 * time)

    freqs, amplitude = compute_single_sided_fft(source, sample_rate)

    assert np.all(freqs > 0)
    assert freqs[-1] == pytest.approx(sample_rate / 2)
    assert freqs[np.argmax(amplitude)] == pytest.approx(2.0)


def test_resolve_ppg_channels_uses_chip_prefix_and_skips_zero_channels():
    df = pd.DataFrame(
        {
            "Ipd0": [0, 0],
            "Ipd2": [1, 2],
            "ACCX": [3, 4],
            "Ipd1": [5, 6],
        }
    )

    assert resolve_ppg_channels(df, "gh3036") == ["Ipd2", "Ipd1"]


def test_resolve_ppg_channels_rejects_unknown_chip():
    with pytest.raises(SignalAnalysisError, match="--channels"):
        resolve_ppg_channels(pd.DataFrame({"PPG": [1, 2]}), "")


def test_resolve_acc_columns_prefers_rule_mapping_then_detects_standard_names():
    mapped = pd.DataFrame({"ax": [1], "ay": [2], "az": [3]})
    standard = pd.DataFrame({"ACCX": [1], "ACCY": [2], "ACCZ": [3]})

    assert resolve_acc_columns(mapped, {"x": "ax", "y": "ay", "z": "az"}) == [
        "ax",
        "ay",
        "az",
    ]
    assert resolve_acc_columns(standard) == ["ACCX", "ACCY", "ACCZ"]
