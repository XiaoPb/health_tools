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


def test_read_prunes_trailing_zero_numbered_columns_but_keeps_protected_and_gaps(
    tmp_path: Path,
):
    source = tmp_path / "sample.csv"
    source.write_text(
        "FRAME_ID,ACCX,ALGO_RESULT0,ALGO_RESULT1,ALGO_RESULT2,ALGO_RESULT3\n"
        "0,0,1,0,2,0\n"
        "1,0,1,0,3,0\n",
        encoding="utf-8",
    )
    handler = CSVHandler()

    _, frame = handler.read(
        source,
        trim_trailing_zero=True,
        protected_columns=["FRAME_ID", "ACCX"],
    )

    assert list(frame.columns) == [
        "FRAME_ID",
        "ACCX",
        "ALGO_RESULT0",
        "ALGO_RESULT1",
        "ALGO_RESULT2",
    ]
    assert handler.excluded_columns == ["ALGO_RESULT3"]
