"""check 性能优化的行为与重复计算回归测试。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from health_tools.api import check_operation
from health_tools.api.context import ExecutionContext
from health_tools.api.errors import OperationCancelled
from health_tools.api.models import CheckRequest, ItemStatus
from health_tools.core.checker import CheckResult, DataChecker
from health_tools.models.rules import ChipRule


def test_primary_issue_and_sort_category_keep_primary_rules_order():
    row = {
        "帧完整性(结果)": "FAIL",
        "数据范围(结果)": "FAIL",
        "ACC异常(结果)": "FAIL",
        "总异常(结果)": "FAIL",
    }
    assert check_operation.primary_issue(row) == "帧不完整"
    assert check_operation._sort_category(row) == "frame"

    row["帧完整性(结果)"] = "PASS"
    assert check_operation.primary_issue(row) == "数据范围异常"
    assert check_operation._sort_category(row) == "range"

    row["数据范围(结果)"] = "PASS"
    assert check_operation.primary_issue(row) == "ACC异常"
    assert check_operation._sort_category(row) == "acc_fail"

    accuracy_row = {
        "总异常(结果)": "FAIL",
        "准确度标定分类": "accuracy_online_low",
        "准确度标定说明": "online 偏低",
        "AGC变化(结果)": "FAIL",
        "Ipd转换(结果)": "FAIL",
    }
    assert check_operation.primary_issue(accuracy_row) == "online 偏低"
    assert check_operation._sort_category(accuracy_row) == "accuracy_online_low"


class _TrackingExecutor(ThreadPoolExecutor):
    def __init__(self, *args, tracker, **kwargs):
        super().__init__(*args, **kwargs)
        self.tracker = tracker

    def submit(self, *args, **kwargs):
        future = super().submit(*args, **kwargs)
        self.tracker["pending"] += 1
        self.tracker["max_pending"] = max(self.tracker["max_pending"], self.tracker["pending"])
        return future


def test_run_check_uses_bounded_pending_window(monkeypatch, tmp_path):
    """大批量输入不应一次性提交超过 workers*2 个 Future。"""
    paths = [tmp_path / f"sample-{index}.csv" for index in range(6)]
    tracker = {"pending": 0, "max_pending": 0}
    collected = set()

    class FakeCSVHandler:
        def __init__(self, _rule):
            pass

        def read(self, _path):
            return {}, pd.DataFrame({"PPG": [1.0], "FRAME_ID": [0]})

    class FakeChecker:
        def __init__(self, *_args, **_kwargs):
            pass

        def check_data_range(self, *_args, **_kwargs):
            return CheckResult("数据范围", True, "通过")

    monkeypatch.setattr(check_operation, "_discover_check_inputs", lambda _target: paths)
    monkeypatch.setattr(check_operation, "_detect_chip", lambda _path: "gh3036")
    monkeypatch.setattr(check_operation, "_rule_mismatch", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        "health_tools.rules.loader.RuleLoader.load_chip_rule",
        staticmethod(lambda _name: SimpleNamespace()),
    )
    monkeypatch.setattr("health_tools.utils.csv_handler.CSVHandler", FakeCSVHandler)
    monkeypatch.setattr("health_tools.core.checker.DataChecker", FakeChecker)
    monkeypatch.setattr(check_operation, "_save_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(check_operation, "_save_compact_report", lambda *args, **kwargs: None)

    original_as_completed = __import__("concurrent.futures", fromlist=["as_completed"]).as_completed
    original_wait = __import__("concurrent.futures", fromlist=["wait"]).wait

    def tracking_as_completed(futures):
        for future in original_as_completed(futures):
            if id(future) not in collected:
                collected.add(id(future))
                tracker["pending"] -= 1
            yield future

    def tracking_wait(futures, *args, **kwargs):
        done, not_done = original_wait(futures, *args, **kwargs)
        for future in done:
            if id(future) not in collected:
                collected.add(id(future))
                tracker["pending"] -= 1
        return done, not_done

    def tracking_executor(*args, **kwargs):
        return _TrackingExecutor(*args, tracker=tracker, **kwargs)

    monkeypatch.setattr("concurrent.futures.ThreadPoolExecutor", tracking_executor)
    monkeypatch.setattr("concurrent.futures.as_completed", tracking_as_completed)
    monkeypatch.setattr("concurrent.futures.wait", tracking_wait)

    result = check_operation.run_check(
        CheckRequest(input_path=tmp_path, checks="range", chip_name="gh3036", workers=2)
    )

    assert result.batch.ok_count == len(paths)
    assert tracker["max_pending"] <= 4


def test_run_check_caps_requested_workers_for_large_batches(monkeypatch, tmp_path):
    """超大 workers 请求不应创建超过硬上限的文件检查线程。"""
    paths = [tmp_path / f"sample-{index}.csv" for index in range(40)]
    tracker = {"max_workers": 0}

    class FakeCSVHandler:
        def __init__(self, _rule):
            pass

        def read(self, _path):
            return {}, pd.DataFrame({"PPG": [1.0], "FRAME_ID": [0]})

    class FakeChecker:
        def __init__(self, *_args, **_kwargs):
            pass

        def check_data_range(self, *_args, **_kwargs):
            return CheckResult("数据范围", True, "通过")

    class TrackingExecutor(ThreadPoolExecutor):
        def __init__(self, max_workers, *args, **kwargs):
            tracker["max_workers"] = max_workers
            super().__init__(max_workers, *args, **kwargs)

    monkeypatch.setattr(check_operation, "_discover_check_inputs", lambda _target: paths)
    monkeypatch.setattr(check_operation, "_detect_chip", lambda _path: "gh3036")
    monkeypatch.setattr(check_operation, "_rule_mismatch", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        "health_tools.rules.loader.RuleLoader.load_chip_rule",
        staticmethod(lambda _name: SimpleNamespace()),
    )
    monkeypatch.setattr("health_tools.utils.csv_handler.CSVHandler", FakeCSVHandler)
    monkeypatch.setattr("health_tools.core.checker.DataChecker", FakeChecker)
    monkeypatch.setattr("concurrent.futures.ThreadPoolExecutor", TrackingExecutor)
    monkeypatch.setattr(check_operation, "_save_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(check_operation, "_save_compact_report", lambda *args, **kwargs: None)

    result = check_operation.run_check(
        CheckRequest(input_path=tmp_path, checks="range", chip_name="gh3036", workers=2310)
    )

    assert result.batch.ok_count == len(paths)
    assert tracker["max_workers"] <= 32


def test_run_check_cancel_keeps_completed_items_without_submitting_more(monkeypatch, tmp_path):
    """完成一个文件后取消时应保留结果，且不再补充待处理任务。"""
    paths = [tmp_path / f"sample-{index}.csv" for index in range(4)]
    release_pending = Event()
    submit_count = 0
    cancelled = False

    class FakeCSVHandler:
        def __init__(self, _rule):
            pass

        def read(self, path):
            if path != paths[0]:
                release_pending.wait(timeout=2)
            return {}, pd.DataFrame({"PPG": [1.0], "FRAME_ID": [0]})

    class FakeChecker:
        def __init__(self, *_args, **_kwargs):
            pass

        def check_data_range(self, *_args, **_kwargs):
            return CheckResult("数据范围", True, "通过")

    class CountingExecutor(ThreadPoolExecutor):
        def submit(self, *args, **kwargs):
            nonlocal submit_count
            submit_count += 1
            return super().submit(*args, **kwargs)

    def on_progress(event):
        nonlocal cancelled
        if event.stage == "files" and event.completed == 1:
            cancelled = True
            release_pending.set()

    monkeypatch.setattr(check_operation, "_discover_check_inputs", lambda _target: paths)
    monkeypatch.setattr(check_operation, "_detect_chip", lambda _path: "gh3036")
    monkeypatch.setattr(check_operation, "_rule_mismatch", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        "health_tools.rules.loader.RuleLoader.load_chip_rule",
        staticmethod(lambda _name: SimpleNamespace()),
    )
    monkeypatch.setattr("health_tools.utils.csv_handler.CSVHandler", FakeCSVHandler)
    monkeypatch.setattr("health_tools.core.checker.DataChecker", FakeChecker)
    monkeypatch.setattr("concurrent.futures.ThreadPoolExecutor", CountingExecutor)

    context = ExecutionContext(on_progress=on_progress, is_cancelled=lambda: cancelled)
    with pytest.raises(OperationCancelled) as exc_info:
        check_operation.run_check(
            CheckRequest(input_path=tmp_path, checks="range", chip_name="gh3036", workers=1),
            context=context,
        )

    partial = exc_info.value.partial_result
    assert partial.items[0].status == ItemStatus.OK
    assert partial.items[0].input == str(paths[0])
    assert submit_count == 2


def _patch_sampling_run(monkeypatch, tmp_path):
    source = tmp_path / "sample.csv"
    source.write_text("placeholder", encoding="utf-8")
    frame = pd.DataFrame(
        {
            "TimeStamp": np.arange(8) * 40,
            "REF_RESULT0": np.arange(8) + 60,
            "REF_RESULT5": np.arange(8) + 90,
            "ALGO_RESULT0": np.arange(8) + 60,
            "COMP": np.arange(8) + 60,
        }
    )

    class FakeCSVHandler:
        def __init__(self, _rule):
            pass

        def read(self, _path):
            return {}, frame.copy()

    class FakeChecker:
        def __init__(self, *_args, **_kwargs):
            pass

        def check_timestamp_interval(self, *_args, **_kwargs):
            return CheckResult("时间戳间隔", True, "通过")

        def check_reference_data(self, *_args, **_kwargs):
            return CheckResult("心率金标", True, "通过")

    monkeypatch.setattr(check_operation, "_discover_check_inputs", lambda _target: [source])
    monkeypatch.setattr(check_operation, "_detect_chip", lambda _path: "gh3036")
    monkeypatch.setattr(check_operation, "_rule_mismatch", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        "health_tools.rules.loader.RuleLoader.load_chip_rule",
        staticmethod(lambda _name: SimpleNamespace()),
    )
    monkeypatch.setattr("health_tools.utils.csv_handler.CSVHandler", FakeCSVHandler)
    monkeypatch.setattr("health_tools.core.checker.DataChecker", FakeChecker)
    monkeypatch.setattr(check_operation, "_save_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(check_operation, "_save_compact_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "health_tools.core.check_accuracy.calculate_check_accuracy",
        lambda *_args, **_kwargs: None,
    )


def test_sampling_positions_and_identical_sample_frames_are_cached(monkeypatch, tmp_path):
    _patch_sampling_run(monkeypatch, tmp_path)
    calls = {"positions": 0, "samples": []}

    def build_positions(*args, **kwargs):
        calls["positions"] += 1
        return np.array([0, 2, 4, 6], dtype=np.int64)

    def sample_seconds(frame, **kwargs):
        calls["samples"].append(
            (kwargs["ref_column"], kwargs["online_column"], kwargs["comp_column"])
        )
        return pd.DataFrame(
            {
                "time": frame["TimeStamp"].iloc[[0, 2, 4, 6]],
                "ref": frame[kwargs["ref_column"]].iloc[[0, 2, 4, 6]].to_numpy(),
                "online": frame[kwargs["online_column"]].iloc[[0, 2, 4, 6]].to_numpy(),
                "comp": frame["COMP"].iloc[[0, 2, 4, 6]].to_numpy(),
            }
        )

    monkeypatch.setattr("health_tools.core.check_sampling.build_sample_positions", build_positions)
    monkeypatch.setattr("health_tools.core.check_sampling.sample_check_seconds", sample_seconds)

    result = check_operation.run_check(
        CheckRequest(
            input_path=tmp_path,
            chip_name="gh3036",
            checks="ref",
            ref_hr_column="REF_RESULT0",
            ref_spo2_column="REF_RESULT5",
            accuracy_enabled=True,
            accuracy_ref_column="REF_RESULT0",
            accuracy_online_column="ALGO_RESULT0",
            accuracy_comp_column="COMP",
            workers=1,
        )
    )

    assert result.batch.ok_count == 1
    assert calls["positions"] == 1
    assert calls["samples"].count(("REF_RESULT0", "ALGO_RESULT0", "COMP")) == 1
    assert calls["samples"].count(("REF_RESULT5", "ALGO_RESULT0", "COMP")) == 1


def test_sampling_cache_key_keeps_distinct_reference_columns_separate(monkeypatch, tmp_path):
    _patch_sampling_run(monkeypatch, tmp_path)
    calls = []

    monkeypatch.setattr(
        "health_tools.core.check_sampling.build_sample_positions",
        lambda *args, **kwargs: np.array([0, 2, 4, 6], dtype=np.int64),
    )

    def sample_seconds(frame, **kwargs):
        calls.append(kwargs["ref_column"])
        return pd.DataFrame(
            {
                "time": frame["TimeStamp"].iloc[[0, 2, 4, 6]],
                "ref": frame[kwargs["ref_column"]].iloc[[0, 2, 4, 6]].to_numpy(),
                "online": frame[kwargs["online_column"]].iloc[[0, 2, 4, 6]].to_numpy(),
                "comp": frame["COMP"].iloc[[0, 2, 4, 6]].to_numpy(),
            }
        )

    monkeypatch.setattr("health_tools.core.check_sampling.sample_check_seconds", sample_seconds)
    result = check_operation.run_check(
        CheckRequest(
            input_path=tmp_path,
            chip_name="gh3036",
            checks="ref",
            ref_hr_column="REF_RESULT0",
            ref_spo2_column="REF_RESULT5",
            accuracy_enabled=True,
            accuracy_ref_column="REF_RESULT5",
            accuracy_online_column="ALGO_RESULT0",
            accuracy_comp_column="COMP",
            workers=1,
        )
    )

    assert result.batch.ok_count == 1
    assert calls.count("REF_RESULT0") == 1
    assert calls.count("REF_RESULT5") == 1


def test_sampling_cache_key_keeps_distinct_timestamp_columns_separate(monkeypatch, tmp_path):
    frame = pd.DataFrame(
        {
            "TimeStamp": [0, 40, 80],
            "AltTimeStamp": [0, 50, 100],
            "REF": [60, 61, 62],
            "ONLINE": [60, 61, 62],
        }
    )
    file_context = check_operation._FileCheckContext(
        path=tmp_path / "sample.csv",
        chip="gh3036",
        chip_rule=SimpleNamespace(),
        frame=frame,
        checker=SimpleNamespace(),
        data_columns=[],
        frame_column="",
        acc_columns=[],
        ipd_columns=[],
        agc_columns=[],
    )
    calls = []

    def sample_seconds(source, **kwargs):
        calls.append(kwargs["timestamp_column"])
        return pd.DataFrame({"time": source[kwargs["timestamp_column"]]})

    monkeypatch.setattr("health_tools.core.check_sampling.sample_check_seconds", sample_seconds)
    common = {
        "positions": np.array([0, 1, 2], dtype=np.int64),
        "sample_rate": 25.0,
        "ref_column": "REF",
        "online_column": "ONLINE",
        "comp_column": None,
    }

    first = file_context.sample_frame(timestamp_column="TimeStamp", **common)
    second = file_context.sample_frame(timestamp_column="AltTimeStamp", **common)

    assert calls == ["TimeStamp", "AltTimeStamp"]
    assert first["time"].tolist() != second["time"].tolist()


def test_timestamp_sample_rate_prediction_is_evaluated_once(monkeypatch, tmp_path):
    _patch_sampling_run(monkeypatch, tmp_path)
    calls = []

    monkeypatch.setattr(
        "health_tools.core.check_sampling.predict_sample_rate_from_timestamp",
        lambda *args, **kwargs: calls.append(kwargs["timestamp_column"]) or 25,
    )

    class TimestampChecker:
        def __init__(self, *_args, **_kwargs):
            pass

        def check_timestamp_interval(self, *_args, **_kwargs):
            return CheckResult("时间戳间隔", False, "异常")

        def check_reference_data(self, *_args, **_kwargs):
            return CheckResult("心率金标", True, "通过")

    monkeypatch.setattr("health_tools.core.checker.DataChecker", TimestampChecker)
    result = check_operation.run_check(
        CheckRequest(
            input_path=tmp_path,
            chip_name="gh3036",
            checks="ref",
            timestamp_column="TimeStamp",
            ref_hr_column="REF_RESULT0",
            workers=1,
        )
    )

    assert result.batch.ok_count == 1
    assert calls == ["TimeStamp"]


def test_invalid_timestamp_parse_error_is_reused_by_public_check(monkeypatch, tmp_path):
    source = tmp_path / "sample.csv"
    source.write_text("placeholder", encoding="utf-8")
    frame = pd.DataFrame({"TimeStamp": ["bad", "worse", "invalid"]})
    rule = ChipRule(
        chip="gh3036",
        csv={"info_row": 0, "header_row": 1, "data_start_row": 2, "delimiter": ","},
        columns=["TimeStamp"],
    )
    parse_calls = 0
    original_parse = DataChecker._parse_timestamp_intervals_ms

    class FakeCSVHandler:
        def __init__(self, _rule):
            pass

        def read(self, _path):
            return {}, frame.copy()

    def counting_parse(series):
        nonlocal parse_calls
        parse_calls += 1
        return original_parse(series)

    monkeypatch.setattr(check_operation, "_discover_check_inputs", lambda _target: [source])
    monkeypatch.setattr(check_operation, "_rule_mismatch", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        "health_tools.rules.loader.RuleLoader.load_chip_rule", staticmethod(lambda _name: rule)
    )
    monkeypatch.setattr("health_tools.utils.csv_handler.CSVHandler", FakeCSVHandler)
    monkeypatch.setattr(DataChecker, "_parse_timestamp_intervals_ms", staticmethod(counting_parse))
    monkeypatch.setattr(check_operation, "_save_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(check_operation, "_save_compact_report", lambda *args, **kwargs: None)

    result = check_operation.run_check(
        CheckRequest(
            input_path=source,
            chip_name="gh3036",
            checks="ref",
            timestamp_column="TimeStamp",
            workers=1,
        )
    )

    assert len(result.batch.items) == 1
    assert parse_calls == 1


def test_range_and_center_reuse_numeric_series_for_zero_channel_filter(monkeypatch, tmp_path):
    frame = pd.DataFrame(
        {
            "Rawdata0": ["0", "0", "0"],
            "Rawdata1": ["3000000", "3100000", "3200000"],
        }
    )
    rule = ChipRule(
        chip="gh3036",
        csv={"info_row": 0, "header_row": 1, "data_start_row": 2, "delimiter": ","},
        columns=["Rawdata0", "Rawdata1"],
        check_columns={"data": ["Rawdata0", "Rawdata1"]},
    )
    checker = DataChecker(rule)
    check_operation._FileCheckContext.create(
        tmp_path / "sample.csv", "gh3036", rule, frame, checker
    )
    calls = 0
    original_to_numeric = pd.to_numeric

    def counting_to_numeric(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_to_numeric(*args, **kwargs)

    monkeypatch.setattr(pd, "to_numeric", counting_to_numeric)

    checker.check_data_range(frame)
    checker.check_data_centering(frame)

    assert calls == 2
