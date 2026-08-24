"""CSV 读取内存行为测试。"""

from pathlib import Path

import pandas as pd

from health_tools.utils.csv_handler import CSVHandler


def test_read_does_not_build_chunk_list_before_returning_frame(monkeypatch, tmp_path: Path):
    source = tmp_path / "sample.csv"
    source.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    calls = []
    original = pd.read_csv

    def capture(*args, **kwargs):
        calls.append(kwargs.copy())
        return original(*args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", capture)

    _, frame = CSVHandler().read(source)

    assert frame.shape == (2, 2)
    assert len(calls) == 1
    assert "chunksize" not in calls[0]


def test_read_downcasts_integer_columns_when_values_fit_int32(tmp_path: Path):
    source = tmp_path / "sample.csv"
    source.write_text("a,b\n1,2000000000\n3,4\n", encoding="utf-8")

    _, frame = CSVHandler().read(source)

    assert str(frame.dtypes["a"]) == "int32"
    assert str(frame.dtypes["b"]) == "int32"
