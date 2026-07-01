"""ACC异常检测单元测试。"""

import csv
from pathlib import Path

import pandas as pd
import pytest

from health_tools.commands.check import _save_report_csv
from health_tools.core.checker import DataChecker
from health_tools.core.checker import FileCheckReport
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
        assert report.zero.count == 0
        assert not report.has_anomaly

    def test_single_zero_segment(self, checker):
        accx = [1, 0, 0, 0, 1]
        accy = [1, 0, 0, 0, 1]
        accz = [1, 0, 0, 0, 1]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.zero.count == 1
        assert report.zero.first_frame == 1
        assert report.zero.max_duration == 3

    def test_multiple_zero_segments(self, checker):
        accx = [0, 0, 1, 2, 0, 0, 0, 1]
        accy = [0, 0, 1, 2, 0, 0, 0, 1]
        accz = [0, 0, 1, 2, 0, 0, 0, 1]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.zero.count == 2
        assert report.zero.first_frame == 0
        assert report.zero.max_duration == 3

    def test_partial_zero_not_detected(self, checker):
        accx = [0, 0, 0, 0, 0]
        accy = [1, 1, 1, 1, 1]
        accz = [0, 0, 0, 0, 0]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.zero.count == 0


class TestAccStatic:
    def test_no_static(self, checker):
        df = _make_df([1, 2, 3, 4, 5], [5, 4, 3, 2, 1], [10, 20, 30, 40, 50])
        report = checker.check_acc_anomaly(df)
        assert report.static_xyz.count == 0
        assert report.static_x.count == 0

    def test_single_channel_static(self, checker):
        accx = [1, 1, 1, 1, 1, 1, 5, 6, 7]
        accy = [1, 2, 3, 4, 5, 6, 7, 8, 9]
        accz = [1, 2, 3, 4, 5, 6, 7, 8, 9]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.static_x.count >= 1
        assert report.static_xyz.count == 0

    def test_all_channels_static(self, checker):
        accx = [1, 1, 1, 1, 1, 1, 5, 6, 7]
        accy = [2, 2, 2, 2, 2, 2, 5, 6, 7]
        accz = [3, 3, 3, 3, 3, 3, 5, 6, 7]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.static_xyz.count >= 1
        assert report.static_x.count == 0

    def test_short_unchanged_not_anomaly(self, checker):
        accx = [1, 1, 1, 5, 6, 7, 8]
        accy = [1, 2, 3, 4, 5, 6, 7]
        accz = [1, 2, 3, 4, 5, 6, 7]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.static_x.count == 0
        assert report.static_xyz.count == 0


class TestAccCyclic:
    def test_no_cyclic(self, checker):
        df = _make_df(
            [1, 2, 3, 4, 5, 6, 7, 8], [8, 7, 6, 5, 4, 3, 2, 1], [10, 20, 30, 40, 50, 60, 70, 80]
        )
        report = checker.check_acc_anomaly(df)
        assert report.cyclic_xyz.count == 0
        assert report.cyclic_x.count == 0

    def test_simple_cyclic_pattern(self, checker):
        pattern = [10, 30, 50]
        accx = pattern * 4
        accy = list(range(len(accx)))
        accz = list(range(len(accx)))
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.cyclic_x.count >= 1
        assert report.cyclic_xyz.count == 0

    def test_cyclic_all_channels(self, checker):
        pattern = [10, 30, 50, 70]
        n = len(pattern) * 3
        accx = (pattern * 3)[:n]
        accy = ([5, 25, 45, 65] * 3)[:n]
        accz = ([100, 200] * 6)[:n]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.cyclic_xyz.count >= 1

    def test_static_not_counted_as_cyclic(self, checker):
        accx = [5, 5, 5, 5, 5, 5, 5, 5]
        accy = [1, 2, 3, 4, 5, 6, 7, 8]
        accz = [1, 2, 3, 4, 5, 6, 7, 8]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.cyclic_x.count == 0
        assert report.cyclic_xyz.count == 0


class TestAccMixed:
    def test_combined_anomalies(self, checker):
        accx = [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 10, 50, 10, 50, 10, 50, 7, 8, 9]
        accy = [0, 0, 0, 0, 2, 2, 2, 2, 2, 2, 2, 20, 60, 20, 60, 20, 60, 7, 8, 9]
        accz = [0, 0, 0, 0, 3, 3, 3, 3, 3, 3, 3, 30, 70, 30, 70, 30, 70, 7, 8, 9]
        df = _make_df(accx, accy, accz)
        report = checker.check_acc_anomaly(df)
        assert report.zero.count >= 1
        assert report.static_xyz.count >= 1
        assert report.cyclic_xyz.count >= 1
        assert report.has_anomaly

    def test_empty_acc_columns(self, checker):
        df = pd.DataFrame({"OTHER": [1, 2, 3]})
        report = checker.check_acc_anomaly(df)
        assert not report.has_anomaly
        assert report.total_frames == 3


class TestAccColumnResolution:
    """测试ACC列名解析：规则指定 vs 自动检测"""

    def test_rule_specified_columns(self):
        rule = ChipRule(
            chip="gh3220",
            csv={"info_row": 0, "header_row": 1, "data_start_row": 2, "delimiter": ","},
            columns=["TimeStamp", "x", "y", "z"],
            acc_columns={"x": "x", "y": "y", "z": "z"},
        )
        chk = DataChecker(rule)
        df = pd.DataFrame({"x": [0, 0, 0, 0], "y": [0, 0, 0, 0], "z": [0, 0, 0, 0]})
        report = chk.check_acc_anomaly(df)
        assert report.zero.count == 1
        assert report.has_anomaly

    def test_auto_detect_acc_prefix(self):
        rule = ChipRule(
            chip="gh3220",
            csv={"info_row": 0, "header_row": 1, "data_start_row": 2, "delimiter": ","},
            columns=["TimeStamp", "AccX", "AccY", "AccZ"],
        )
        chk = DataChecker(rule)
        df = pd.DataFrame(
            {
                "AccX": [1, 1, 1, 1, 1, 1, 1],
                "AccY": [2, 3, 4, 5, 6, 7, 8],
                "AccZ": [3, 4, 5, 6, 7, 8, 9],
            }
        )
        report = chk.check_acc_anomaly(df)
        assert report.static_x.count >= 1

    def test_auto_detect_bare_xyz(self):
        rule = ChipRule(
            chip="gh3220",
            csv={"info_row": 0, "header_row": 1, "data_start_row": 2, "delimiter": ","},
            columns=["TimeStamp", "X", "Y", "Z"],
        )
        chk = DataChecker(rule)
        df = pd.DataFrame(
            {"X": [10, 50, 10, 50, 10, 50], "Y": [30, 70, 30, 70, 30, 70], "Z": [5, 6, 7, 8, 9, 10]}
        )
        report = chk.check_acc_anomaly(df)
        # X and Y have cyclic but not Z, so not all three → single channel
        assert report.cyclic_x.count >= 1 or report.cyclic_xyz.count >= 1

    def test_auto_detect_case_insensitive(self):
        rule = ChipRule(
            chip="gh3220",
            csv={"info_row": 0, "header_row": 1, "data_start_row": 2, "delimiter": ","},
            columns=["TimeStamp", "accx", "accy", "accz"],
        )
        chk = DataChecker(rule)
        df = pd.DataFrame({"accx": [0, 0, 0], "accy": [0, 0, 0], "accz": [0, 0, 0]})
        report = chk.check_acc_anomaly(df)
        assert report.zero.count == 1

    def test_no_matching_columns(self):
        rule = ChipRule(
            chip="gh3220",
            csv={"info_row": 0, "header_row": 1, "data_start_row": 2, "delimiter": ","},
            columns=["TimeStamp", "ch0", "ch1", "ch2"],
        )
        chk = DataChecker(rule)
        df = pd.DataFrame({"ch0": [1, 2, 3], "ch1": [4, 5, 6], "ch2": [7, 8, 9]})
        report = chk.check_acc_anomaly(df)
        assert not report.has_anomaly


class TestFrameColumnResolution:
    """测试帧号列解析"""

    def test_auto_detect_frame_id(self):
        rule = ChipRule(
            chip="gh3220",
            csv={"info_row": 0, "header_row": 1, "data_start_row": 2, "delimiter": ","},
            columns=["TimeStamp", "FRAME_ID", "ACCX", "ACCY", "ACCZ"],
        )
        chk = DataChecker(rule)
        df = pd.DataFrame(
            {
                "FRAME_ID": [100, 101, 102, 103, 104],
                "ACCX": [1, 0, 0, 0, 1],
                "ACCY": [1, 0, 0, 0, 1],
                "ACCZ": [1, 0, 0, 0, 1],
            }
        )
        report = chk.check_acc_anomaly(df)
        assert report.zero.first_frame == 101

    def test_rule_specified_frame_column(self):
        rule = ChipRule(
            chip="gh3220",
            csv={"info_row": 0, "header_row": 1, "data_start_row": 2, "delimiter": ","},
            columns=["TimeStamp", "seq", "ACCX", "ACCY", "ACCZ"],
            frame_column="seq",
        )
        chk = DataChecker(rule)
        df = pd.DataFrame(
            {
                "seq": [500, 501, 502, 503, 504],
                "ACCX": [1, 0, 0, 0, 1],
                "ACCY": [1, 0, 0, 0, 1],
                "ACCZ": [1, 0, 0, 0, 1],
            }
        )
        report = chk.check_acc_anomaly(df)
        assert report.zero.first_frame == 501

    def test_fallback_to_row_index(self):
        rule = ChipRule(
            chip="gh3220",
            csv={"info_row": 0, "header_row": 1, "data_start_row": 2, "delimiter": ","},
            columns=["TimeStamp", "ACCX", "ACCY", "ACCZ"],
        )
        chk = DataChecker(rule)
        df = pd.DataFrame(
            {"ACCX": [1, 0, 0, 0, 1], "ACCY": [1, 0, 0, 0, 1], "ACCZ": [1, 0, 0, 0, 1]}
        )
        report = chk.check_acc_anomaly(df)
        assert report.zero.first_frame == 1


class TestCheckResultStatus:
    """测试检查项三态结果。"""

    def test_range_pass_warning_fail(self):
        rule = ChipRule(
            chip="gh3036",
            csv={"info_row": 0, "header_row": 1, "data_start_row": 2, "delimiter": ","},
            columns=["Rawdata0"],
        )
        chk = DataChecker(rule)

        pass_df = pd.DataFrame({"Rawdata0": [1, 2, 3, 4]})
        pass_result = chk.check_data_range(pass_df, threshold_ratio=1)
        assert pass_result.status == "PASS"
        assert pass_result.passed

        warning_df = pd.DataFrame({"Rawdata0": [1] * 99 + [2**23 + 1]})
        warning_result = chk.check_data_range(warning_df, threshold_ratio=1)
        assert warning_result.status == "WARNING"
        assert warning_result.passed
        assert warning_result.abnormal_ratio == pytest.approx(1.0)

        fail_df = pd.DataFrame({"Rawdata0": [1] * 98 + [2**23 + 1, 2**23 + 2]})
        fail_result = chk.check_data_range(fail_df, threshold_ratio=1)
        assert fail_result.status == "FAIL"
        assert not fail_result.passed

    def test_frame_ratio_boundary_is_warning(self, checker):
        df = pd.DataFrame({"FRAME_ID": list(range(50)) + list(range(51, 100))})
        result = checker.check_frame_completeness(df, threshold_ratio=1)
        assert result.status == "WARNING"
        assert result.passed
        assert result.abnormal_ratio == pytest.approx(1.0)

    def test_file_total_status_treats_warning_as_pass(self, checker):
        df = pd.DataFrame({"FRAME_ID": list(range(50)) + list(range(51, 100))})
        warning = checker.check_frame_completeness(df, threshold_ratio=1)
        fail = checker.check_frame_completeness(df, threshold_ratio=0.5)

        warning_report = FileCheckReport(file_path=Path("warning.csv"), chip="gh3220")
        warning_report.results.append(warning)
        assert warning_report.total_status == "PASS"

        fail_report = FileCheckReport(file_path=Path("fail.csv"), chip="gh3220")
        fail_report.results.append(fail)
        assert fail_report.total_status == "FAIL"

    def test_acc_result_uses_deduplicated_anomaly_frames(self, checker):
        df = _make_df(
            [0, 0, 0, 0, 1, 2, 3, 4, 10, 50, 10, 50, 10, 50],
            [0, 0, 0, 0, 2, 3, 4, 5, 20, 60, 20, 60, 20, 60],
            [0, 0, 0, 0, 3, 4, 5, 6, 30, 70, 30, 70, 30, 70],
        )
        report = checker.check_acc_anomaly(df)
        result = checker.build_acc_result(report, threshold_ratio=100)
        assert report.anomaly_frame_count == 10
        assert result.status == "WARNING"
        assert result.abnormal_ratio == pytest.approx(10 / 14 * 100)

    def test_csv_report_writes_total_and_three_state_status(self, tmp_path):
        report = FileCheckReport(file_path=tmp_path / "data.csv", chip="gh3220")
        result = DataChecker._build_result(
            name="帧完整性",
            abnormal_count=1,
            total_count=100,
            threshold_ratio=1,
            pass_summary="无异常",
            abnormal_summary="丢包 1 帧",
        )
        report.results.append(result)
        output = tmp_path / "check_report.csv"

        _save_report_csv([report], {}, output, base_dir=tmp_path)

        with open(output, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))

        assert rows[0][:5] == ["文件名", "芯片", "总异常(结果)", "帧完整性(结果)", "帧完整性(说明)"]
        assert rows[1][:5] == ["data.csv", "gh3220", "PASS", "WARNING", "丢包 1 帧"]
        assert rows[0][-1] == "文件相对路径"
        assert rows[1][-1] == "data.csv"


class TestTimestampInterval:
    """测试时间戳间隔稳定性检查。"""

    def test_numeric_timestamp_interval_pass(self, checker):
        df = pd.DataFrame({"timestamp": [0, 40, 80, 120, 160]})
        result = checker.check_timestamp_interval(df, "timestamp", ratio_tolerance=0.2)

        assert result.status == "PASS"
        assert result.passed
        assert "基准间隔 40" in result.summary

    def test_timestamp_ratio_uses_percent_number(self, checker):
        df = pd.DataFrame({"timestamp": [0, 40, 80, 120.2, 160.2]})
        result = checker.check_timestamp_interval(
            df,
            "timestamp",
            ratio_tolerance=0.2,
            threshold_ratio=0.1,
        )

        assert result.status == "FAIL"
        assert not result.passed
        assert result.abnormal_ratio == pytest.approx(25.0)

    def test_timestamp_ms_tolerance_also_applies(self, checker):
        df = pd.DataFrame({"timestamp": [0, 40, 80, 122, 162]})
        result = checker.check_timestamp_interval(
            df,
            "timestamp",
            ratio_tolerance=20,
            ms_tolerance=1,
            threshold_ratio=0.1,
        )

        assert result.status == "FAIL"
        assert "异常间隔 1/4" in result.summary

    def test_string_timestamp_interval_pass(self, checker):
        df = pd.DataFrame(
            {"timestamp": ["11:17:20.000", "11:17:20.040", "11:17:20.080", "11:17:20.120"]}
        )
        result = checker.check_timestamp_interval(df, "timestamp", ratio_tolerance=1)

        assert result.status == "PASS"
        assert result.passed

    def test_timestamp_missing_column_fail(self, checker):
        result = checker.check_timestamp_interval(pd.DataFrame({"time": [1, 2, 3]}), "timestamp")

        assert result.status == "FAIL"
        assert not result.passed
        assert "未找到时间戳列" in result.summary

    def test_timestamp_parse_fail(self, checker):
        result = checker.check_timestamp_interval(
            pd.DataFrame({"timestamp": ["a", "b", "c"]}),
            "timestamp",
        )

        assert result.status == "FAIL"
        assert "无法解析" in result.summary

    def test_timestamp_backward_fail(self, checker):
        result = checker.check_timestamp_interval(
            pd.DataFrame({"timestamp": [0, 40, 30, 70]}),
            "timestamp",
        )

        assert result.status == "FAIL"
        assert "时间戳倒退" in result.summary
