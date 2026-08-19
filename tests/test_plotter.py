from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from matplotlib.figure import Figure

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
            "CH1": 200 + 5 * np.sin(2 * np.pi * 1.2 * time),
        }
    )


def test_plot_ac_draws_three_subplots_and_keeps_channel_colors(monkeypatch, tmp_path: Path):
    saved = []
    original_savefig = Figure.savefig

    def capture_savefig(figure, *args, **kwargs):
        saved.append(figure)
        return original_savefig(figure, *args, **kwargs)

    monkeypatch.setattr(Figure, "savefig", capture_savefig)
    output = tmp_path / "ac.png"

    DataPlotter(sample_rate=10).plot_ac(
        _analysis_df(), output, ["CH0", "CH1"], ["ACCX", "ACCY", "ACCZ"]
    )

    fig = saved[0]
    assert output.stat().st_size > 0
    assert len(fig.axes) == 6
    assert [line.get_label() for line in fig.axes[0].lines] == ["ACCX"]
    assert [line.get_label() for line in fig.axes[3].lines] == ["ACCY"]
    assert [line.get_label() for line in fig.axes[4].lines] == ["ACCZ"]
    assert [line.get_label() for line in fig.axes[1].lines] == ["CH0", "CH1"]
    assert [line.get_label() for line in fig.axes[2].lines] == ["CH0", "CH1"]
    assert [line.get_label() for line in fig.axes[5].lines] == ["R"]
    assert fig.axes[1].lines[0].get_color() == fig.axes[2].lines[0].get_color()
    assert fig.axes[1].lines[1].get_color() == fig.axes[2].lines[1].get_color()


def test_plot_ac_uses_symmetric_limits_from_dominant_peak_distribution(monkeypatch, tmp_path: Path):
    filtered = {
        "CH0": np.array([0.0, 1.0, 0.0, 1.1, 0.0, 0.9, 0.0, 20.0, 0.0]),
        "CH1": np.array([0.0, 2.0, 0.0, 2.1, 0.0, 1.9, 0.0, 2.2, 0.0]),
    }

    monkeypatch.setattr(
        "health_tools.core.plotter.bandpass_signal",
        lambda raw, *args, **kwargs: filtered["CH0" if raw[0] == 100 else "CH1"],
    )
    monkeypatch.setattr(
        "health_tools.core.plotter.compute_pi",
        lambda raw, ac, sample_rate: pd.Series(np.ones(len(ac))),
    )
    saved = []
    monkeypatch.setattr(Figure, "savefig", lambda figure, *args, **kwargs: saved.append(figure))

    df = pd.DataFrame(
        {
            "ACCX": np.zeros(9),
            "ACCY": np.zeros(9),
            "ACCZ": np.zeros(9),
            "CH0": np.full(9, 100.0),
            "CH1": np.full(9, 200.0),
        }
    )
    DataPlotter(sample_rate=10).plot_ac(
        df, tmp_path / "ac.png", ["CH0", "CH1"], ["ACCX", "ACCY", "ACCZ"]
    )

    lower, upper = saved[0].axes[1].get_ylim()
    assert lower == pytest.approx(-upper)
    assert upper < 20


def test_plot_ac_reads_explicit_r_column(tmp_path: Path, monkeypatch):
    saved = []
    monkeypatch.setattr(Figure, "savefig", lambda figure, *args, **kwargs: saved.append(figure))
    df = _analysis_df()
    df["R_VALUE"] = np.linspace(1.0, 2.0, len(df))

    DataPlotter(sample_rate=10).plot_ac(
        df,
        tmp_path / "ac.png",
        ["CH0", "CH1"],
        ["ACCX", "ACCY", "ACCZ"],
        r_column="R_VALUE",
    )

    assert np.array_equal(saved[0].axes[5].lines[0].get_ydata(), df["R_VALUE"].to_numpy())


def test_plot_ac_calculates_r_from_selected_channel_order(tmp_path: Path, monkeypatch):
    saved = []
    monkeypatch.setattr(Figure, "savefig", lambda figure, *args, **kwargs: saved.append(figure))
    monkeypatch.setattr(
        "health_tools.core.plotter.compute_pi",
        lambda raw, ac, sample_rate: pd.Series(np.full(len(ac), 2.0 if raw[0] < 150 else 4.0)),
    )

    DataPlotter(sample_rate=10).plot_ac(
        _analysis_df(),
        tmp_path / "ac.png",
        ["CH1", "CH0"],
        ["ACCX", "ACCY", "ACCZ"],
    )

    assert np.all(saved[0].axes[5].lines[0].get_ydata() == 20000.0)


@pytest.mark.parametrize("channels", [["CH0"], ["CH0", "CH1", "CH2"], ["CH0", "CH1", "CH2", "CH3"]])
def test_plot_ac_without_r_column_skips_r_axis_unless_exactly_two_channels(
    channels: list[str], tmp_path: Path, monkeypatch
):
    saved = []
    monkeypatch.setattr(Figure, "savefig", lambda figure, *args, **kwargs: saved.append(figure))
    df = _analysis_df()
    df["CH2"] = df["CH0"]
    df["CH3"] = df["CH1"]

    DataPlotter(sample_rate=10).plot_ac(df, tmp_path / "ac.png", channels, ["ACCX", "ACCY", "ACCZ"])

    assert len(saved[0].axes) == 5
    assert all(axis.get_ylabel() != "R" for axis in saved[0].axes)


def test_plot_ac_explicit_r_column_draws_with_one_selected_channel(tmp_path: Path, monkeypatch):
    saved = []
    monkeypatch.setattr(Figure, "savefig", lambda figure, *args, **kwargs: saved.append(figure))
    df = _analysis_df()
    df["R_VALUE"] = np.linspace(1.0, 2.0, len(df))

    DataPlotter(sample_rate=10).plot_ac(
        df,
        tmp_path / "ac.png",
        ["CH0"],
        ["ACCX", "ACCY", "ACCZ"],
        r_column="R_VALUE",
    )

    assert len(saved[0].axes) == 6
    assert np.array_equal(saved[0].axes[5].lines[0].get_ydata(), df["R_VALUE"].to_numpy())


def test_plot_ac_rejects_more_than_four_channels(tmp_path: Path):
    df = _analysis_df()
    for index in range(3, 6):
        df[f"CH{index}"] = df["CH0"]

    with pytest.raises(SignalAnalysisError, match="最多支持 4 个"):
        DataPlotter(sample_rate=10).plot_ac(
            df,
            tmp_path / "ac.png",
            ["CH0", "CH1", "CH3", "CH4", "CH5"],
            ["ACCX", "ACCY", "ACCZ"],
        )


def test_plot_fft_uses_independent_y_axes_and_excludes_dc(monkeypatch, tmp_path: Path):
    saved = []
    original_savefig = Figure.savefig

    def capture_savefig(figure, *args, **kwargs):
        saved.append(figure)
        return original_savefig(figure, *args, **kwargs)

    monkeypatch.setattr(Figure, "savefig", capture_savefig)
    sample_rate = 50
    time = np.arange(sample_rate * 4) / sample_rate
    df = pd.DataFrame({"CH0": 100 + 3 * np.sin(2 * np.pi * 2 * time)})
    output = tmp_path / "fft.png"

    DataPlotter(sample_rate=sample_rate).plot_fft(df, output, "CH0")

    fig = saved[0]
    assert output.stat().st_size > 0
    assert len(fig.axes) == 2
    assert fig.axes[0].get_ylabel() == "Raw amplitude"
    assert fig.axes[1].get_ylabel() == "Filtered amplitude"
    assert min(fig.axes[0].lines[0].get_xdata()) > 0


def test_plot_time_generates_png_in_worker_threads_without_pyplot_backend(
    monkeypatch, tmp_path: Path
):
    """工作线程绘图不应经过 pyplot 的全局 GUI 后端。"""
    monkeypatch.delenv("MPLBACKEND", raising=False)

    def fail_pyplot_subplots(*_args, **_kwargs):
        raise RuntimeError("pyplot GUI backend was used")

    monkeypatch.setattr(plt, "subplots", fail_pyplot_subplots)
    frame = _analysis_df()
    outputs = [tmp_path / f"worker-{index}.png" for index in range(2)]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(DataPlotter(sample_rate=10).plot_time, frame, output, ["CH0"])
            for output in outputs
        ]
        for future in futures:
            future.result()

    for output in outputs:
        assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert output.stat().st_size > 0
