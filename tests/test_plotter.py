from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from health_tools.core.plotter import DataPlotter
from health_tools.core.ppg_analysis import SignalAnalysisError


def _analysis_df(sample_rate: int = 10, seconds: int = 10) -> pd.DataFrame:
    time = np.arange(sample_rate * seconds) / sample_rate
    return pd.DataFrame(
        {
            "ACCX": np.sin(time),
            "ACCY": np.cos(time),
            "ACCZ": np.sin(time * 2),
            "CH0": 100 + 3 * np.sin(2 * np.pi * time),
            "CH2": 200 + 5 * np.sin(2 * np.pi * 1.2 * time),
        }
    )


def test_plot_ac_draws_three_subplots_and_keeps_channel_colors(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(plt, "close", lambda *_args, **_kwargs: None)
    output = tmp_path / "ac.png"

    DataPlotter(sample_rate=10).plot_ac(
        _analysis_df(), output, ["CH0", "CH2"], ["ACCX", "ACCY", "ACCZ"]
    )

    fig = plt.gcf()
    assert output.stat().st_size > 0
    assert len(fig.axes) == 3
    assert [line.get_label() for line in fig.axes[0].lines] == ["ACCX", "ACCY", "ACCZ"]
    assert [line.get_label() for line in fig.axes[1].lines] == ["CH0", "CH2"]
    assert [line.get_label() for line in fig.axes[2].lines] == ["CH0", "CH2"]
    assert fig.axes[1].lines[0].get_color() == fig.axes[2].lines[0].get_color()
    assert fig.axes[1].lines[1].get_color() == fig.axes[2].lines[1].get_color()
    plt.close("all")


def test_plot_ac_rejects_more_than_four_channels(tmp_path: Path):
    df = _analysis_df()
    for index in range(3, 6):
        df[f"CH{index}"] = df["CH0"]

    with pytest.raises(SignalAnalysisError, match="最多支持 4 个"):
        DataPlotter(sample_rate=10).plot_ac(
            df,
            tmp_path / "ac.png",
            ["CH0", "CH2", "CH3", "CH4", "CH5"],
            ["ACCX", "ACCY", "ACCZ"],
        )


def test_plot_fft_uses_independent_y_axes_and_excludes_dc(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(plt, "close", lambda *_args, **_kwargs: None)
    sample_rate = 50
    time = np.arange(sample_rate * 4) / sample_rate
    df = pd.DataFrame({"CH0": 100 + 3 * np.sin(2 * np.pi * 2 * time)})
    output = tmp_path / "fft.png"

    DataPlotter(sample_rate=sample_rate).plot_fft(df, output, "CH0")

    fig = plt.gcf()
    assert output.stat().st_size > 0
    assert len(fig.axes) == 2
    assert fig.axes[0].get_ylabel() == "Raw amplitude"
    assert fig.axes[1].get_ylabel() == "Filtered amplitude"
    assert min(fig.axes[0].lines[0].get_xdata()) > 0
    plt.close("all")
