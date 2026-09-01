"""离线并发任务模型测试。"""

import threading
import time
from pathlib import Path

import pytest

from health_tools.core.offline import OfflineRunResult
from health_tools.core.offline_parallel import (
    OfflineTask,
    OfflineTaskResult,
    assign_task_outputs,
    discover_offline_tasks,
    merge_task_outputs,
    run_offline_tasks,
    safe_task_name,
)


def test_discover_tasks_uses_root_only_without_child_directories(tmp_path: Path):
    (tmp_path / "root.csv").write_text("x\n", encoding="utf-8")

    tasks = discover_offline_tasks(tmp_path)

    assert [(task.input_dir, task.relative_dir) for task in tasks] == [(tmp_path, Path())]


def test_discover_tasks_uses_csv_child_directories_and_ignores_root_csv(tmp_path: Path):
    (tmp_path / "root.csv").write_text("x\n", encoding="utf-8")
    for name in ("B", "A"):
        folder = tmp_path / name / "nested"
        folder.mkdir(parents=True)
        (folder / f"{name}.csv").write_text("x\n", encoding="utf-8")
    (tmp_path / "empty").mkdir()

    tasks = discover_offline_tasks(tmp_path)

    assert [task.relative_dir for task in tasks] == [Path("A"), Path("B")]


def test_discover_tasks_does_not_fall_back_to_root_when_children_have_no_csv(tmp_path: Path):
    (tmp_path / "root.csv").write_text("x\n", encoding="utf-8")
    (tmp_path / "empty").mkdir()

    assert discover_offline_tasks(tmp_path) == []


def test_assign_task_outputs_adds_private_raw_layer(tmp_path: Path):
    for name in ("B", "A"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / f"{name}.csv").write_text("x\n", encoding="utf-8")
    tasks = discover_offline_tasks(tmp_path)

    assigned = assign_task_outputs(tasks, tmp_path / "version")

    assert assigned[0].raw_output == tmp_path / "version/.offline_tasks/0000_A/raw"
    assert assigned[1].raw_output == tmp_path / "version/.offline_tasks/0001_B/raw"
    assert assigned[0].log_path == tmp_path / "version/offline_logs/0000_A.log"
    assert assigned[1].log_path == tmp_path / "version/offline_logs/0001_B.log"


def test_safe_task_name_preserves_unicode_and_replaces_punctuation():
    assert safe_task_name("室内跑步&步行") == "室内跑步_步行"
    assert safe_task_name("户外步行(公园)") == "户外步行_公园"
    assert safe_task_name("A folder/with spaces") == "A_folder_with_spaces"
    assert safe_task_name("()") == "task"
    assert safe_task_name("") == "task"


def _successful_task_result(task: OfflineTask) -> OfflineTaskResult:
    return OfflineTaskResult(task, OfflineRunResult(success=True), "succeeded")


def test_merge_task_outputs_preserves_child_directory_structure(tmp_path: Path):
    input_dir = tmp_path / "input" / "A" / "nested"
    input_dir.mkdir(parents=True)
    (input_dir / "a.csv").write_text("x\n", encoding="utf-8")
    version_output = tmp_path / "version"
    task = assign_task_outputs(
        [OfflineTask("0000_A", input_dir.parent, Path("A"))], version_output
    )[0]
    assert task.raw_output is not None
    raw_result = task.raw_output / "000000_a_result.vshb"
    raw_result.parent.mkdir(parents=True)
    raw_result.write_text("1,2,3\n", encoding="utf-8")

    result = merge_task_outputs(version_output, [_successful_task_result(task)])

    target = version_output / "数据整理" / "A" / "nested" / raw_result.name
    assert result.failed == ()
    assert result.succeeded[0].task == task
    assert target.exists()
    assert not (version_output / ".offline_tasks").exists()


def test_merge_task_outputs_does_not_add_root_layer_for_root_task(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.csv").write_text("x\n", encoding="utf-8")
    version_output = tmp_path / "version"
    task = assign_task_outputs([OfflineTask("0000_root", input_dir, Path())], version_output)[0]
    assert task.raw_output is not None
    raw_result = task.raw_output / "000000_a_result.vshb"
    raw_result.parent.mkdir(parents=True)
    raw_result.write_text("1,2,3\n", encoding="utf-8")

    result = merge_task_outputs(version_output, [_successful_task_result(task)])

    assert result.failed == ()
    assert (version_output / "数据整理" / raw_result.name).exists()
    assert not (version_output / "数据整理" / "root").exists()


def test_merge_task_outputs_preserves_task_logs(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.csv").write_text("x\n", encoding="utf-8")
    version_output = tmp_path / "version"
    task = assign_task_outputs([OfflineTask("0000_root", input_dir, Path())], version_output)[0]
    assert task.raw_output is not None
    assert task.log_path is not None
    raw_result = task.raw_output / "000000_a_result.vshb"
    raw_result.parent.mkdir(parents=True)
    raw_result.write_text("1,2,3\n", encoding="utf-8")
    task.log_path.parent.mkdir(parents=True)
    task.log_path.write_text("diagnostic\n", encoding="utf-8")

    result = merge_task_outputs(version_output, [_successful_task_result(task)])

    assert result.failed == ()
    assert task.log_path.read_text(encoding="utf-8") == "diagnostic\n"


def test_merge_task_outputs_rejects_duplicate_targets_before_final_move(tmp_path: Path):
    version_output = tmp_path / "version"
    task_results = []
    sources = []
    for task_id, input_name in (("0000_A", "input_a"), ("0001_A", "input_b")):
        input_dir = tmp_path / input_name
        input_dir.mkdir()
        (input_dir / "sample.csv").write_text("x\n", encoding="utf-8")
        task = assign_task_outputs([OfflineTask(task_id, input_dir, Path("A"))], version_output)[0]
        assert task.raw_output is not None
        source = task.raw_output / "000000_sample_result.vshb"
        source.parent.mkdir(parents=True)
        source.write_text("same\n", encoding="utf-8")
        sources.append(source)
        task_results.append(_successful_task_result(task))

    result = merge_task_outputs(version_output, task_results)

    assert result.succeeded == ()
    assert len(result.failed) == 2
    assert all("目标文件冲突" in item.reason for item in result.failed)
    assert not (version_output / "数据整理" / "A" / sources[0].name).exists()
    assert all(
        (task_result.task.raw_output / "数据整理" / sources[0].name).exists()
        for task_result in task_results
        if task_result.task.raw_output is not None
    )
    assert (version_output / ".offline_tasks").exists()


def test_merge_task_outputs_rejects_existing_target_before_final_move(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "sample.csv").write_text("x\n", encoding="utf-8")
    version_output = tmp_path / "version"
    task = assign_task_outputs([OfflineTask("0000_A", input_dir, Path("A"))], version_output)[0]
    assert task.raw_output is not None
    first_source = task.raw_output / "000000_sample_result.vshb"
    second_source = task.raw_output / "000000_sample.prepsd"
    first_source.parent.mkdir(parents=True)
    first_source.write_text("new\n", encoding="utf-8")
    second_source.write_text("new\n", encoding="utf-8")
    existing = version_output / "数据整理" / "A" / first_source.name
    existing.parent.mkdir(parents=True)
    existing.write_text("old\n", encoding="utf-8")

    result = merge_task_outputs(version_output, [_successful_task_result(task)])

    assert result.succeeded == ()
    assert len(result.failed) == 1
    assert "目标文件冲突" in result.failed[0].reason
    assert existing.read_text(encoding="utf-8") == "old\n"
    assert not (version_output / "数据整理" / "A" / second_source.name).exists()
    assert (task.raw_output / "数据整理" / first_source.name).exists()
    assert (task.raw_output / "数据整理" / second_source.name).exists()
    assert (version_output / ".offline_tasks").exists()


def test_merge_task_outputs_rolls_back_when_second_move_fails(monkeypatch, tmp_path: Path):
    import shutil

    version_output = tmp_path / "version"
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for name in ("a", "b"):
        (input_dir / f"{name}.csv").write_text("x\n", encoding="utf-8")
    task = assign_task_outputs([OfflineTask("0000_root", input_dir, Path())], version_output)[0]
    assert task.raw_output is not None
    for index, name in enumerate(("a", "b")):
        source = task.raw_output / f"{index:06d}_{name}_result.vshb"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(name, encoding="utf-8")

    real_move = shutil.move
    final_move_calls = 0

    def fail_second_move(source, destination):
        nonlocal final_move_calls
        if ".offline_tasks" not in str(destination):
            final_move_calls += 1
            if final_move_calls == 2:
                raise OSError("磁盘写入失败")
        return real_move(source, destination)

    monkeypatch.setattr("health_tools.core.offline_parallel.shutil.move", fail_second_move)

    result = merge_task_outputs(version_output, [_successful_task_result(task)])

    assert result.succeeded == ()
    assert len(result.failed) == 1
    assert "合并输出失败" in result.failed[0].reason
    assert "磁盘写入失败" in result.failed[0].reason
    assert not any((version_output / "数据整理").rglob("*_result.vshb"))
    assert sorted(path.name for path in task.raw_output.rglob("*_result.vshb")) == [
        "000000_a_result.vshb",
        "000001_b_result.vshb",
    ]
    assert (version_output / ".offline_tasks").exists()


def test_run_offline_tasks_caps_active_workers_and_preserves_order(tmp_path: Path):
    tasks = assign_task_outputs(
        [OfflineTask(f"{index:04d}", tmp_path, Path()) for index in range(10)],
        tmp_path / "version",
    )
    lock = threading.Lock()
    active = 0
    peak = 0

    class Runner:
        def run(self, *_args, **_kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return OfflineRunResult(success=True)

    result = run_offline_tasks(tasks, lambda _task: Runner(), tmp_path, workers=20)

    assert peak == 8
    assert [item.task.task_id for item in result.succeeded] == [task.task_id for task in tasks]


def test_run_offline_tasks_sorts_results_by_task_id_not_input_order(tmp_path: Path):
    tasks = assign_task_outputs(
        [OfflineTask("0002", tmp_path, Path()), OfflineTask("0001", tmp_path, Path())],
        tmp_path / "version",
    )

    class Runner:
        def run(self, *_args, **_kwargs):
            return OfflineRunResult(success=True)

    result = run_offline_tasks(tasks, lambda _task: Runner(), tmp_path, workers=1)

    assert [item.task.task_id for item in result.succeeded] == ["0001", "0002"]


def test_run_offline_tasks_retries_different_failed_csvs(tmp_path: Path):
    input_dir = tmp_path / "A"
    input_dir.mkdir()
    first = input_dir / "bad1.csv"
    second = input_dir / "bad2.csv"
    good = input_dir / "good.csv"
    first.write_text("x\n", encoding="utf-8")
    second.write_text("x\n", encoding="utf-8")
    good.write_text("x\n", encoding="utf-8")
    task = assign_task_outputs([OfflineTask("0000_A", input_dir, Path("A"))], tmp_path / "version")[
        0
    ]
    runners = []

    class Runner:
        def __init__(self):
            self.attempt = len(runners) + 1
            runners.append(self)

        def run(self, *_args, **_kwargs):
            if self.attempt == 1:
                return OfflineRunResult(success=False, last_csv_path=first)
            if self.attempt == 2:
                return OfflineRunResult(success=False, last_csv_path=second)
            return OfflineRunResult(success=True)

    result = run_offline_tasks([task], lambda _task: Runner(), tmp_path, workers=1)

    assert result.failed == ()
    assert result.succeeded[0].task.attempts == 3
    assert len(runners) == 3
    assert len({id(runner) for runner in runners}) == 3
    assert result.succeeded[0].task.last_failed_csv == second.resolve()
    assert [item.source.name for item in result.succeeded[0].task.moved_files] == [
        "bad1.csv",
        "bad2.csv",
    ]
    assert (tmp_path.parent / f"{tmp_path.name}_mv/A/bad1.csv").exists()
    assert (tmp_path.parent / f"{tmp_path.name}_mv/A/bad2.csv").exists()


def test_run_offline_tasks_passes_shared_log_path_and_attempt_number(tmp_path: Path):
    input_dir = tmp_path / "A"
    input_dir.mkdir()
    bad = input_dir / "bad.csv"
    good = input_dir / "good.csv"
    bad.write_text("x\n", encoding="utf-8")
    good.write_text("x\n", encoding="utf-8")
    task = assign_task_outputs([OfflineTask("0000_A", input_dir, Path("A"))], tmp_path / "version")[
        0
    ]
    calls = []

    class Runner:
        def run(self, *_args, **kwargs):
            calls.append((kwargs["log_path"], kwargs["attempt"]))
            if len(calls) == 1:
                return OfflineRunResult(success=False, last_csv_path=bad)
            return OfflineRunResult(success=True)

    result = run_offline_tasks([task], lambda _task: Runner(), tmp_path, workers=1)

    assert result.failed == ()
    assert calls == [(task.log_path, 1), (task.log_path, 2)]


def test_run_offline_tasks_appends_retry_after_other_pending_tasks(tmp_path: Path):
    inputs = []
    for name in ("A", "B", "C"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "good.csv").write_text("x\n", encoding="utf-8")
        inputs.append(OfflineTask(f"000{name}", folder, Path(name)))
    failed_csv = inputs[0].input_dir / "bad.csv"
    failed_csv.write_text("x\n", encoding="utf-8")
    tasks = assign_task_outputs(inputs, tmp_path / "version")
    attempts = []

    class Runner:
        def __init__(self, task):
            self.task = task

        def run(self, *_args, **_kwargs):
            attempts.append(self.task.task_id)
            if self.task.task_id == "000A" and attempts.count("000A") == 1:
                return OfflineRunResult(success=False, last_csv_path=failed_csv)
            return OfflineRunResult(success=True)

    result = run_offline_tasks(tasks, Runner, tmp_path, workers=1)

    assert attempts == ["000A", "000B", "000C", "000A"]
    assert [item.task.task_id for item in result.succeeded] == ["000A", "000B", "000C"]


def test_run_offline_tasks_workers_one_preserves_attempt_order(tmp_path: Path):
    inputs = []
    for index in range(3):
        folder = tmp_path / str(index)
        folder.mkdir()
        (folder / "good.csv").write_text("x\n", encoding="utf-8")
        inputs.append(OfflineTask(f"{index:04d}", folder, Path(str(index))))
    tasks = assign_task_outputs(inputs, tmp_path / "version")
    calls = []

    class Runner:
        def __init__(self, task):
            self.task = task

        def run(self, *_args, **_kwargs):
            calls.append(self.task.task_id)
            return OfflineRunResult(success=True)

    result = run_offline_tasks(tasks, Runner, tmp_path, workers=1)

    assert calls == [task.task_id for task in tasks]
    assert [item.task.task_id for item in result.succeeded] == calls


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("same_csv", "重复失败文件"),
        ("no_path", "日志未定位失败 CSV"),
        ("missing_path", "失败 CSV 已不存在"),
        ("empty_after_move", "隔离后目录没有剩余 CSV"),
    ],
)
def test_run_offline_tasks_isolates_unrecoverable_failures(tmp_path: Path, mode: str, reason: str):
    failed_dir = tmp_path / "failed"
    good_dir = tmp_path / "good"
    failed_dir.mkdir()
    good_dir.mkdir()
    bad = failed_dir / "bad.csv"
    bad.write_text("x\n", encoding="utf-8")
    (good_dir / "good.csv").write_text("x\n", encoding="utf-8")
    if mode not in {"empty_after_move", "no_path", "missing_path"}:
        (failed_dir / "remaining.csv").write_text("x\n", encoding="utf-8")
    missing = failed_dir / "missing.csv"
    tasks = assign_task_outputs(
        [
            OfflineTask("0000_failed", failed_dir, Path("failed")),
            OfflineTask("0001_good", good_dir, Path("good")),
        ],
        tmp_path / "version",
    )
    calls = 0

    class Runner:
        def __init__(self, task):
            self.task = task

        def run(self, *_args, **_kwargs):
            nonlocal calls
            if self.task.task_id == "0001_good":
                return OfflineRunResult(success=True)
            calls += 1
            if mode == "no_path":
                return OfflineRunResult(success=False)
            if mode == "missing_path":
                return OfflineRunResult(success=False, last_csv_path=missing)
            return OfflineRunResult(success=False, last_csv_path=bad)

    result = run_offline_tasks(tasks, Runner, tmp_path, workers=2)

    assert [item.task.task_id for item in result.succeeded] == ["0001_good"]
    assert [item.reason for item in result.failed] == [reason]
    assert result.failed[0].task.attempts == (2 if mode == "same_csv" else 1)
    assert calls == (2 if mode == "same_csv" else 1)
    if mode == "same_csv":
        assert result.failed[0].task.last_failed_csv == bad.resolve()
        assert [item.source for item in result.failed[0].task.moved_files] == [bad.resolve()]


def test_run_offline_tasks_isolates_runner_exception(tmp_path: Path):
    tasks = assign_task_outputs(
        [OfflineTask("0000_bad", tmp_path, Path()), OfflineTask("0001_good", tmp_path, Path())],
        tmp_path / "version",
    )

    class Runner:
        def __init__(self, task):
            self.task = task

        def run(self, *_args, **_kwargs):
            if self.task.task_id == "0000_bad":
                raise RuntimeError("boom")
            return OfflineRunResult(success=True)

    result = run_offline_tasks(tasks, Runner, tmp_path, workers=2)

    assert [item.task.task_id for item in result.succeeded] == ["0001_good"]
    assert result.failed[0].reason == "boom"
    assert result.failed[0].task.attempts == 1


def test_run_offline_tasks_cancellation_stops_queue_refill(tmp_path: Path):
    tasks = assign_task_outputs(
        [OfflineTask(f"{index:04d}", tmp_path, Path()) for index in range(5)],
        tmp_path / "version",
    )
    initial_workers_ready = threading.Event()
    lock = threading.Lock()
    submitted = []
    observed_cancel = []
    cancelled = False

    class Runner:
        def __init__(self, task):
            with lock:
                submitted.append(task.task_id)
                if len(submitted) == 2:
                    initial_workers_ready.set()
            self.task = task

        def run(self, *_args, is_cancelled=None, **_kwargs):
            while True:
                if is_cancelled():
                    with lock:
                        observed_cancel.append(self.task.task_id)
                    break
                time.sleep(0.001)
            return OfflineRunResult(success=False)

    def cancel():
        return cancelled

    def trigger_cancel():
        nonlocal cancelled
        assert initial_workers_ready.wait(1)
        cancelled = True

    thread = threading.Thread(target=trigger_cancel)
    thread.start()
    with pytest.raises(InterruptedError):
        run_offline_tasks(tasks, Runner, tmp_path, workers=2, is_cancelled=cancel)
    thread.join()

    assert submitted == [task.task_id for task in tasks[:2]]
    assert sorted(observed_cancel) == [task.task_id for task in tasks[:2]]
