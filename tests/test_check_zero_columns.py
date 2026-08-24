"""检查任务全零尾部通道裁剪测试。"""

from types import SimpleNamespace

import pandas as pd

from health_tools.api.check_operation import _rule_mismatch
from health_tools.core.checker import DataChecker
from health_tools.models.rules import ChipRule
from health_tools.utils.csv_handler import CSVHandler


def test_drop_trailing_zero_columns_keeps_frame_acc_and_gaps_before_last_active(tmp_path):
    source = tmp_path / "sample.csv"
    source.write_text(
        "FRAME_ID,ACCX,Rawdata0,Rawdata1,Rawdata2,ALGO_RESULT0,ALGO_RESULT1,"
        "ALGO_RESULT2,ALGO_RESULT3,ALGO_RESULT4,ALGO_RESULT5,ALGO_RESULT6,"
        "ALGO_RESULT7,ALGO_RESULT8,AGC_INFO_CH0,AGC_INFO_CH1\n"
        "0,0,0,10,0,1,0,0,0,0,0,3,0,0,1,0\n"
        "1,0,0,11,0,2,0,0,0,0,0,4,0,0,1,0\n",
        encoding="utf-8",
    )
    handler = CSVHandler()

    _, reduced = handler.read(
        source,
        trim_trailing_zero=True,
        protected_columns=["FRAME_ID", "ACCX"],
    )

    assert handler.excluded_columns == [
        "Rawdata2",
        "ALGO_RESULT7",
        "ALGO_RESULT8",
        "AGC_INFO_CH1",
    ]
    assert "Rawdata0" in reduced.columns
    assert "Rawdata1" in reduced.columns
    assert "Rawdata2" not in reduced.columns
    assert "ALGO_RESULT1" in reduced.columns
    assert "ALGO_RESULT2" in reduced.columns
    assert "ALGO_RESULT4" in reduced.columns
    assert "ALGO_RESULT6" in reduced.columns
    assert "ALGO_RESULT7" not in reduced.columns
    assert "ALGO_RESULT8" not in reduced.columns
    assert "AGC_INFO_CH1" not in reduced.columns
    assert "FRAME_ID" in reduced.columns
    assert "ACCX" in reduced.columns


def test_checks_pass_when_zero_data_and_ipd_columns_were_trimmed():
    frame = pd.DataFrame({"FRAME_ID": [0, 1]})
    rule = ChipRule(
        chip="gh3036",
        csv={"info_row": 0, "header_row": 1, "data_start_row": 2, "delimiter": ","},
        columns=["FRAME_ID", "Rawdata1", "Ipd1"],
        check_columns={"data": ["Rawdata1"], "ipd": ["Ipd1"]},
    )
    checker = DataChecker(rule)
    checker._check_context = SimpleNamespace(
        frame=frame,
        data_columns=[],
        ipd_columns=[],
        agc_columns=[],
        acc_columns=[],
        frame_column="FRAME_ID",
        excluded_zero_data_columns=["Rawdata1"],
        excluded_zero_ipd_columns=["Ipd1"],
    )

    mismatch = _rule_mismatch(
        checker,
        frame,
        {"range", "center", "ipd"},
        timestamp_column=None,
        chip="gh3036",
        require_acc=False,
    )
    range_result = checker.check_data_range(frame)
    centering_result = checker.check_data_centering(frame)
    ipd_result = checker.check_ipd_conversion(frame)

    assert mismatch == ""
    assert range_result.status == "PASS"
    assert centering_result.status == "PASS"
    assert ipd_result.status == "PASS"


def test_drop_trailing_zero_columns_scans_only_first_500_data_rows(tmp_path):
    source = tmp_path / "sample_501_rows.csv"
    columns = ["FRAME_ID"] + [f"ALGO_RESULT{i}" for i in range(8)]
    rows = []
    for frame_id in range(501):
        values = [0] * 8
        values[0] = 1
        if frame_id == 499:
            values[6] = 6
        if frame_id == 500:
            values[7] = 7
        rows.append(",".join(str(value) for value in [frame_id] + values))
    source.write_text(
        ",".join(columns) + "\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    handler = CSVHandler()

    _, reduced = handler.read(
        source,
        trim_trailing_zero=True,
        protected_columns=["FRAME_ID"],
    )

    assert handler.excluded_columns == ["ALGO_RESULT7"]
    assert "FRAME_ID" in reduced.columns
    assert "ALGO_RESULT4" in reduced.columns
    assert "ALGO_RESULT6" in reduced.columns
    assert "ALGO_RESULT7" not in reduced.columns
    assert len(reduced) == 501
    assert reduced["FRAME_ID"].iloc[-1] == 500
