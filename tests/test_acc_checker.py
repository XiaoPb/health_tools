"""ACC异常检测单元测试。"""

import pandas as pd
import pytest

from health_tools.core.checker import DataChecker
from health_tools.models.rules import ChipRule


@pytest.fixture
def checker():
    rule = ChipRule(
        chip="gh3220",
        csv={"info_row": 0, "header_row": 1, "data_start_row": 2, "delimiter": ","},
        columns=["TimeStamp", "FRAME_ID", "ACCX", "ACCY", "ACCZ"],
    )
    return DataChecker(rule)


def _make_df(accx, accy, accz):
    return pd.DataFrame({"ACCX": accx, "ACCY": accy, "ACCZ": accz})


class TestAccAllZero:
    def test_no_zero(self, checker):
        df = _make_df([1, 2, 3, 4, 5], [1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
        report = checker.check_acc_anomaly(df)
        assert report.zero_count == 0
        assert not report.has_anomaly

    def test_single_zero_segment(self, checker):
        accx = [1, 0, 0, 0, 1]
        accy = [1, 0, 0, 0, 1]
        accz = [1, 0, 0, 0, 1]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.zero_count == 1
        assert report.zero_channels == "XYZ"
        assert report.zero_first_frame == 1
        assert report.zero_max_duration == 3

    def test_multiple_zero_segments(self, checker):
        accx = [0, 0, 1, 2, 0, 0, 0, 1]
        accy = [0, 0, 1, 2, 0, 0, 0, 1]
        accz = [0, 0, 1, 2, 0, 0, 0, 1]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.zero_count == 2
        assert report.zero_first_frame == 0
        assert report.zero_max_duration == 3

    def test_partial_zero_not_detected(self, checker):
        accx = [0, 0, 0, 0, 0]
        accy = [1, 1, 1, 1, 1]
        accz = [0, 0, 0, 0, 0]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.zero_count == 0


class TestAccStatic:
    def test_no_static(self, checker):
        df = _make_df([1, 2, 3, 4, 5], [5, 4, 3, 2, 1], [10, 20, 30, 40, 50])
        report = checker.check_acc_anomaly(df)
        assert report.static_count == 0

    def test_single_channel_static(self, checker):
        accx = [1, 1, 1, 1, 5, 6, 7]
        accy = [1, 2, 3, 4, 5, 6, 7]
        accz = [1, 2, 3, 4, 5, 6, 7]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.static_count >= 1
        assert "X" in report.static_channels

    def test_all_channels_static(self, checker):
        accx = [1, 1, 1, 1, 5, 6, 7]
        accy = [2, 2, 2, 2, 5, 6, 7]
        accz = [3, 3, 3, 3, 5, 6, 7]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.static_count >= 1
        assert report.static_channels == "XYZ"

    def test_short_unchanged_not_anomaly(self, checker):
        accx = [1, 1, 1, 5, 6, 7, 8]
        accy = [1, 2, 3, 4, 5, 6, 7]
        accz = [1, 2, 3, 4, 5, 6, 7]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.static_count == 0


class TestAccCyclic:
    def test_no_cyclic(self, checker):
        df = _make_df(
            [1, 2, 3, 4, 5, 6, 7, 8], [8, 7, 6, 5, 4, 3, 2, 1], [10, 20, 30, 40, 50, 60, 70, 80]
        )
        report = checker.check_acc_anomaly(df)
        assert report.cyclic_count == 0

    def test_simple_cyclic_pattern(self, checker):
        pattern = [1, 2, 3]
        accx = pattern * 4
        accy = list(range(len(accx)))
        accz = list(range(len(accx)))
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.cyclic_count >= 1
        assert "X" in report.cyclic_channels

    def test_cyclic_all_channels(self, checker):
        pattern = [10, 20, 30, 40]
        n = len(pattern) * 3
        accx = (pattern * 3)[:n]
        accy = ([5, 6, 7, 8] * 3)[:n]
        accz = ([100, 200] * 6)[:n]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.cyclic_count >= 1

    def test_static_not_counted_as_cyclic(self, checker):
        accx = [5, 5, 5, 5, 5, 5, 5, 5]
        accy = [1, 2, 3, 4, 5, 6, 7, 8]
        accz = [1, 2, 3, 4, 5, 6, 7, 8]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.cyclic_count == 0


class TestAccMixed:
    def test_combined_anomalies(self, checker):
        accx = [0, 0, 0, 0, 1, 1, 1, 1, 1, 2, 3, 2, 3, 2, 3, 7, 8, 9]
        accy = [0, 0, 0, 0, 2, 2, 2, 2, 2, 4, 5, 4, 5, 4, 5, 7, 8, 9]
        accz = [0, 0, 0, 0, 3, 3, 3, 3, 3, 6, 7, 6, 7, 6, 7, 7, 8, 9]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.zero_count >= 1
        assert report.static_count >= 1
        assert report.cyclic_count >= 1
        assert report.has_anomaly

    def test_empty_acc_columns(self, checker):
        df = pd.DataFrame({"OTHER": [1, 2, 3]})
        report = checker.check_acc_anomaly(df)
        assert not report.has_anomaly
        assert report.total_frames == 3
