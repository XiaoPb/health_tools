import threading
import time
from pathlib import Path

import pytest
from click.testing import CliRunner
from rich.console import Console

from health_tools.cli import main
from health_tools.commands.offline import _build_accuracy_tables
from health_tools.core.psd_plotter import PsdPlotResult


def test_planned_plot_outputs_cover_normal_plot_types(tmp_path: Path):
    from dataclasses import replace

    from health_tools.api import PlotRequest
    from health_tools.api.file_operations import _planned_plot_outputs

    output = tmp_path / "out"
    base = PlotRequest(Path("a.csv"), output, plot_type="time")

    assert _planned_plot_outputs(Path("a.csv"), base, None, ["CH0"], None) == (
        output / "a_time.png",
    )
    assert _planned_plot_outputs(
        Path("a.csv"), replace(base, plot_type="both"), None, ["CH0"], None
    ) == (output / "a_time.png", output / "a_freq.png")
    assert _planned_plot_outputs(
        Path("a.csv"), replace(base, plot_type="stft"), None, ["CH0"], None
    ) == (output / "a_stft.png",)
    assert _planned_plot_outputs(
        Path("a.csv"), replace(base, plot_type="ac"), None, None, [["CH0"], ["CH1"]]
    ) == (output / "a_ac_CH0.png", output / "a_ac_CH1.png")
    assert _planned_plot_outputs(
        Path("a.csv"), replace(base, plot_type="fft"), None, ["CH0", "CH1"], None
    ) == (output / "a_fft_CH0.png", output / "a_fft_CH1.png")


def test_plot_rejects_output_conflict_before_rendering(monkeypatch, tmp_path: Path):
    from health_tools.api import PlotRequest, run_plot
    from health_tools.api.errors import RequestValidationError

    input_dir = tmp_path / "input"
    (input_dir / "A").mkdir(parents=True)
    (input_dir / "B").mkdir(parents=True)
    (input_dir / "A" / "sample.csv").write_text("x\n1\n", encoding="utf-8")
    (input_dir / "B" / "sample.csv").write_text("x\n2\n", encoding="utf-8")
    monkeypatch.setattr(
        "health_tools.api.file_operations._plot_one",
        lambda *args: pytest.fail("输出冲突时不得开始绘图"),
    )

    with pytest.raises(RequestValidationError, match="绘图输出文件冲突"):
        run_plot(PlotRequest(input_dir, tmp_path / "out", plot_type="time"))


@pytest.mark.parametrize("workers", [0, 9, True, "2"])
def test_plot_rejects_invalid_public_workers(workers, tmp_path: Path):
    from health_tools.api import PlotRequest, RequestValidationError, run_plot

    with pytest.raises(RequestValidationError, match="workers 必须是 1-8 的整数"):
        run_plot(PlotRequest(tmp_path, tmp_path / "out", workers=workers))


def test_plot_concurrent_tasks_use_independent_plotters_and_stable_order(
    monkeypatch, tmp_path: Path
):
    from health_tools.api import PlotRequest, run_plot
    from health_tools.api.models import ItemStatus

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    names = [f"{index:02d}.csv" for index in range(10)]
    for name in names:
        (input_dir / name).write_text("x\n1\n", encoding="utf-8")

    lock = threading.Lock()
    active = 0
    peak = 0
    plotter_ids = []
    plotters = []

    class FakePlotter:
        def __init__(self, **kwargs):
            self.fmt = kwargs["fmt"]
            plotters.append(self)

        def plot_time(self, frame, target, channels):
            nonlocal active, peak
            with lock:
                plotter_ids.append(id(self))
                active += 1
                peak = max(peak, active)
            time.sleep((10 - int(target.stem.removesuffix("_time"))) * 0.003)
            with lock:
                active -= 1
            if target.name == "04_time.png":
                raise ValueError("坏数据")

    monkeypatch.setattr("health_tools.core.plotter.DataPlotter", FakePlotter)

    class FakeFrame:
        def __len__(self):
            return 1

    monkeypatch.setattr("health_tools.utils.csv_handler.read_csv_df", lambda *args: FakeFrame())

    result = run_plot(PlotRequest(input_dir, tmp_path / "out", plot_type="time", workers=8))

    assert len(plotters) == 10
    assert len(set(plotter_ids)) == 10
    assert peak == 8
    assert [Path(item.input).name for item in result.items] == names
    assert result.items[4].status is ItemStatus.FAIL
    assert sum(item.status is ItemStatus.OK for item in result.items) == 9


class _FakeOfflineRunnerPreview:
    resolved_version = None
    ppg_warnings = []

    def resolve_ppg_mapping(self):
        return {}


def test_accuracy_tables_only_print_matching_reference_rows():
    import pandas as pd

    report_df = pd.DataFrame(
        [
            {
                "file": "polar_file",
                "category": "7.4",
                "reference": "polar",
                "samples": 10,
                "MAE(offline)": 1.0,
                "MAE(online)": 2.0,
                "MAE(comp)": 1.5,
            },
            {
                "file": "offline_file",
                "category": "7.4",
                "reference": "offline",
                "samples": 10,
                "MAE(online_vs_offline)": 3.0,
            },
            {
                "file": "TOTAL",
                "category": "",
                "reference": "",
                "samples": 20,
                "MAE(offline)": 1.0,
                "MAE(online)": 2.0,
                "MAE(comp)": 1.5,
                "MAE(online_vs_offline)": 3.0,
            },
        ]
    )

    tables = _build_accuracy_tables(report_df)

    assert len(tables) == 2
    polar_console = Console(record=True, width=160)
    compare_console = Console(record=True, width=160)
    polar_console.print(tables[0])
    compare_console.print(tables[1])
    polar_text = polar_console.export_text()
    compare_text = compare_console.export_text()
    assert "polar_file" in polar_text
    assert "offline_file" not in polar_text
    assert "offline_file" in compare_text
    assert "polar_file" not in compare_text
    assert "MAE(comp)" in polar_text


def test_progress_track_uses_default_rich_progress_columns(monkeypatch):
    import health_tools.utils.progress as progress_module

    calls = []

    class FakeProgress:
        def __init__(self, *args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def track(self, items, description, total=None):
            calls.append({"description": description, "total": total})
            yield from items

    monkeypatch.setattr(progress_module, "Progress", FakeProgress)

    assert list(progress_module.progress_track([1, 2], "转换CSV...", console="console")) == [1, 2]
    assert calls == [
        {"args": (), "kwargs": {"console": "console"}},
        {"description": "转换CSV...", "total": None},
    ]


def test_progress_track_can_be_disabled():
    from health_tools.utils.progress import progress_track

    assert list(progress_track([1, 2, 3], "测试进度", enabled=False)) == [1, 2, 3]


def test_parallel_process_uses_rich_progress(monkeypatch):
    from health_tools.utils import parallel

    calls = []

    def fake_progress_track(items, description, console=None, enabled=True, total=None):
        calls.append(
            {
                "description": description,
                "enabled": enabled,
                "total": total,
            }
        )
        yield from items

    monkeypatch.setattr(parallel, "progress_track", fake_progress_track)

    result = parallel.parallel_process(lambda x: x * 2, [1, 2, 3], max_workers=1, desc="处理文件")

    assert result == [2, 4, 6]
    assert calls == [{"description": "处理文件", "enabled": True, "total": 3}]


def test_plot_command_forwards_workers(monkeypatch, tmp_path: Path):
    import health_tools.api as api

    requests = []

    def fake_run_plot(request, *, context=None):
        requests.append(request)
        return api.BatchResult("plot")

    monkeypatch.setattr(api, "run_plot", fake_run_plot)

    result = CliRunner().invoke(
        main,
        [
            "plot",
            "-i",
            str(tmp_path / "input"),
            "-o",
            str(tmp_path / "output"),
            "--workers",
            "3",
        ],
    )

    assert result.exit_code == 0
    assert requests[0].workers == 3


def test_offline_command_forwards_workers(monkeypatch):
    import health_tools.api as api

    requests = []

    def fake_run_offline(request, *, context=None):
        requests.append(request)
        return api.OfflineResult(api.BatchResult("offline"))

    monkeypatch.setattr(api, "run_offline", fake_run_offline)

    result = CliRunner().invoke(main, ["offline", "--workers", "5", "--list"])

    assert result.exit_code == 0
    assert requests[0].workers == 5


def test_parallel_commands_describe_workers_limit():
    runner = CliRunner()

    for command in ("plot", "offline"):
        result = runner.invoke(main, [command, "--help"])

        assert result.exit_code == 0
        assert "并行线程数，最多 8" in result.output


def _prepare_parallel_offline_api(monkeypatch, tmp_path: Path):
    import health_tools.api.offline_operation as offline_operation
    from health_tools.core.offline import OfflineRunResult

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    executable = tmp_path / "tools" / "gh3036" / "exclusive" / "v1" / "TEE_Algorithm.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")

    class FakeRunner(_FakeOfflineRunnerPreview):
        def __init__(self, chip, version=None, **kwargs):
            self.version = version

        def run(self, input_path, output_path, **kwargs):
            return OfflineRunResult(success=True)

    monkeypatch.setattr(offline_operation, "_filter_input_files", lambda *args: None)
    monkeypatch.setattr("health_tools.core.offline.find_exe", lambda *args: executable)
    monkeypatch.setattr("health_tools.core.offline.load_local_cmd_config", lambda *args: None)
    monkeypatch.setattr("health_tools.core.offline.OfflineRunner", FakeRunner)
    return input_dir, output_dir


def test_offline_parallel_child_directories_run_before_merge_plot_and_accuracy(
    monkeypatch, tmp_path: Path
):
    import pandas as pd

    from health_tools.api import OfflineRequest, run_offline
    from health_tools.core.offline import OfflineRunResult
    from health_tools.core.offline_parallel import (
        OfflineMergeResult,
        OfflineTaskBatch,
        OfflineTaskResult,
    )

    input_dir, output_dir = _prepare_parallel_offline_api(monkeypatch, tmp_path)
    for name in ("B", "A"):
        child = input_dir / name
        child.mkdir()
        (child / f"{name}.csv").write_text("x\n1\n", encoding="utf-8")
    root_csv = input_dir / "root.csv"
    root_csv.write_text("x\n1\n", encoding="utf-8")
    events = []
    captured = {}
    runner_ids = []

    def fake_run_tasks(tasks, runner_factory, input_root, **kwargs):
        captured["tasks"] = tasks
        captured["workers"] = kwargs["workers"]
        results = []
        for task in tasks:
            runner = runner_factory(task)
            runner_ids.append(id(runner))
            events.append(f"run:{task.relative_dir}")
            results.append(OfflineTaskResult(task, OfflineRunResult(success=True), "succeeded"))
        return OfflineTaskBatch(tuple(results), ())

    def fake_merge(version_output, task_results, **kwargs):
        events.append("merge")
        captured["merge_cleanup"] = kwargs["cleanup"]
        reorganized = version_output / "数据整理"
        reorganized.mkdir(parents=True)
        return OfflineMergeResult(tuple(task_results), ())

    def fake_plot(self, result_dir, **kwargs):
        events.append("plot")
        captured["plot_input"] = result_dir
        captured["plot_workers"] = kwargs["workers"]
        return PsdPlotResult((), ())

    def fake_accuracy(result_dir, **kwargs):
        events.append("accuracy")
        captured["accuracy_input"] = result_dir
        return pd.DataFrame({"file": ["TOTAL"]})

    monkeypatch.setattr("health_tools.core.offline_parallel.run_offline_tasks", fake_run_tasks)
    monkeypatch.setattr("health_tools.core.offline_parallel.merge_task_outputs", fake_merge)
    monkeypatch.setattr("health_tools.core.psd_plotter.PsdPlotter.plot", fake_plot)
    monkeypatch.setattr("health_tools.core.offline.calculate_offline_accuracy", fake_accuracy)

    result = run_offline(
        OfflineRequest(
            input_path=input_dir,
            output_path=output_dir,
            chip_name="gh3036",
            ver="v1",
            workers=4,
        )
    )

    assert [task.relative_dir for task in captured["tasks"]] == [Path("A"), Path("B")]
    assert all(task.input_dir != root_csv for task in captured["tasks"])
    assert captured["workers"] == 4
    assert captured["plot_workers"] == 4
    assert len(set(runner_ids)) == 2
    assert events == ["run:A", "run:B", "merge", "plot", "accuracy"]
    assert captured["merge_cleanup"] is True
    final_reorganized = output_dir / "v1" / "数据整理"
    assert captured["plot_input"] == final_reorganized
    assert captured["accuracy_input"] == final_reorganized
    assert final_reorganized in result.batch.artifacts


def test_offline_parallel_root_task_uses_one_worker(monkeypatch, tmp_path: Path):
    from health_tools.api import OfflineRequest, run_offline
    from health_tools.core.offline import OfflineRunResult
    from health_tools.core.offline_parallel import (
        OfflineMergeResult,
        OfflineTaskBatch,
        OfflineTaskResult,
    )

    input_dir, output_dir = _prepare_parallel_offline_api(monkeypatch, tmp_path)
    (input_dir / "root.csv").write_text("x\n1\n", encoding="utf-8")
    captured = {}

    def fake_run_tasks(tasks, runner_factory, input_root, **kwargs):
        captured["tasks"] = tasks
        captured["workers"] = kwargs["workers"]
        result = OfflineTaskResult(tasks[0], OfflineRunResult(success=True), "succeeded")
        return OfflineTaskBatch((result,), ())

    def fake_merge(version_output, task_results, **kwargs):
        (version_output / "数据整理").mkdir(parents=True)
        return OfflineMergeResult(tuple(task_results), ())

    monkeypatch.setattr("health_tools.core.offline_parallel.run_offline_tasks", fake_run_tasks)
    monkeypatch.setattr("health_tools.core.offline_parallel.merge_task_outputs", fake_merge)

    run_offline(
        OfflineRequest(
            input_path=input_dir,
            output_path=output_dir,
            chip_name="gh3036",
            ver="v1",
            workers=8,
            no_plot=True,
            no_accuracy=True,
        )
    )

    assert len(captured["tasks"]) == 1
    assert captured["tasks"][0].input_dir == input_dir
    assert captured["tasks"][0].relative_dir == Path()
    assert captured["workers"] == 1


@pytest.mark.parametrize("workers", [0, 9, True, "2"])
def test_offline_parallel_rejects_invalid_public_workers(workers):
    from health_tools.api import OfflineRequest, RequestValidationError, run_offline

    with pytest.raises(RequestValidationError, match="workers 必须是 1-8 的整数"):
        run_offline(OfflineRequest(workers=workers, do_list=True))


def test_offline_rejects_root_csv_when_child_directories_have_no_csv(monkeypatch, tmp_path: Path):
    from health_tools.api import OfflineRequest, OperationError, run_offline

    input_dir, output_dir = _prepare_parallel_offline_api(monkeypatch, tmp_path)
    (input_dir / "root.csv").write_text("x\n1\n", encoding="utf-8")
    (input_dir / "empty").mkdir()

    with pytest.raises(OperationError, match="一级子目录中没有可处理 CSV"):
        run_offline(
            OfflineRequest(
                input_path=input_dir,
                output_path=output_dir,
                chip_name="gh3036",
                ver="v1",
                no_plot=True,
                no_accuracy=True,
            )
        )


def test_offline_repeated_run_cleans_stale_version_outputs_and_reports_final_paths(
    monkeypatch, tmp_path: Path
):
    from health_tools.api import ItemStatus, OfflineRequest, run_offline
    from health_tools.core.offline import OfflineRunResult

    input_dir, output_dir = _prepare_parallel_offline_api(monkeypatch, tmp_path)
    for name in ("A", "B"):
        child = input_dir / name
        child.mkdir()
        (child / f"{name}.csv").write_text("x\n1\n", encoding="utf-8")

    class WritingRunner(_FakeOfflineRunnerPreview):
        def __init__(self, chip, version=None, **kwargs):
            pass

        def run(self, input_path, output_path, **kwargs):
            csv_files = sorted(Path(input_path).rglob("*.csv"))
            output_path.mkdir(parents=True, exist_ok=True)
            for index, csv_file in enumerate(csv_files):
                (output_path / f"{index:06d}_{csv_file.stem}_result.vshb").write_text(
                    "1,2,3\n", encoding="utf-8"
                )
            return OfflineRunResult(success=True)

    monkeypatch.setattr("health_tools.core.offline.OfflineRunner", WritingRunner)
    request = OfflineRequest(
        input_path=input_dir,
        output_path=output_dir,
        chip_name="gh3036",
        ver="v1",
        no_plot=True,
        no_accuracy=True,
    )

    first = run_offline(request)
    version_output = output_dir / "v1"
    assert (version_output / "数据整理" / "A" / "000000_A_result.vshb").exists()
    assert (version_output / "数据整理" / "B" / "000000_B_result.vshb").exists()
    assert [Path(item.output) for item in first.batch.items if item.status is ItemStatus.OK] == [
        version_output / "数据整理" / "A",
        version_output / "数据整理" / "B",
    ]

    (version_output / "psd_bmpfile").mkdir()
    (version_output / "psd_bmpfile" / "stale.png").write_text("old", encoding="utf-8")
    (version_output / "accuracy_report.csv").write_text("old", encoding="utf-8")
    (version_output / ".offline_tasks" / "stale").mkdir(parents=True)
    for path in (input_dir / "B").iterdir():
        path.unlink()
    (input_dir / "B").rmdir()

    second = run_offline(request)

    assert (version_output / "数据整理" / "A" / "000000_A_result.vshb").exists()
    assert not (version_output / "数据整理" / "B").exists()
    assert not (version_output / "psd_bmpfile").exists()
    assert not (version_output / "accuracy_report.csv").exists()
    assert not (version_output / ".offline_tasks").exists()
    assert [Path(item.output) for item in second.batch.items if item.status is ItemStatus.OK] == [
        version_output / "数据整理" / "A"
    ]


def test_offline_retry_summary_warns_and_final_failure_keeps_artifacts(monkeypatch, tmp_path: Path):
    from dataclasses import replace

    from health_tools.api import ItemStatus, OfflineRequest, run_offline
    from health_tools.core.offline import OfflineRunResult
    from health_tools.core.offline_input_filter import MovedOfflineInput
    from health_tools.core.offline_parallel import (
        OfflineMergeResult,
        OfflineTaskBatch,
        OfflineTaskResult,
    )

    input_dir, output_dir = _prepare_parallel_offline_api(monkeypatch, tmp_path)
    for name in ("A", "B"):
        child = input_dir / name
        child.mkdir()
        (child / f"{name}.csv").write_text("x\n1\n", encoding="utf-8")

    def fake_run_tasks(tasks, runner_factory, input_root, **kwargs):
        moved_target = tmp_path / "input_mv" / "A" / "bad.csv"
        recovered_task = replace(
            tasks[0],
            attempts=2,
            moved_files=(
                MovedOfflineInput(input_dir / "A" / "bad.csv", moved_target, "算法执行失败"),
            ),
        )
        failed_task = replace(tasks[1], attempts=1)
        return OfflineTaskBatch(
            (
                OfflineTaskResult(
                    recovered_task,
                    OfflineRunResult(
                        success=True,
                        command="secret command",
                        log_path=tmp_path / "custom-success.log",
                    ),
                    "succeeded",
                ),
            ),
            (
                OfflineTaskResult(
                    failed_task,
                    OfflineRunResult(
                        success=False,
                        error="boom",
                        command="secret command",
                        log_path=failed_task.log_path,
                    ),
                    "failed",
                    "日志未定位失败 CSV",
                ),
            ),
        )

    def fake_merge(version_output, task_results, **kwargs):
        assert kwargs["cleanup"] is False
        reorganized = version_output / "数据整理"
        reorganized.mkdir(parents=True)
        artifact = reorganized / "A" / "result.vshb"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("ok", encoding="utf-8")
        return OfflineMergeResult(tuple(task_results), ())

    monkeypatch.setattr("health_tools.core.offline_parallel.run_offline_tasks", fake_run_tasks)
    monkeypatch.setattr("health_tools.core.offline_parallel.merge_task_outputs", fake_merge)

    result = run_offline(
        OfflineRequest(
            input_path=input_dir,
            output_path=output_dir,
            chip_name="gh3036",
            ver="v1",
            no_plot=True,
            no_accuracy=True,
        )
    )

    assert [item.status for item in result.batch.items] == [ItemStatus.WARN, ItemStatus.FAIL]
    assert Path(result.batch.items[0].output) == output_dir / "v1" / "数据整理" / "A"
    assert "尝试次数: 2" in result.batch.items[0].detail
    assert "input_mv" in result.batch.items[0].detail
    assert f"子进程日志: {tmp_path / 'custom-success.log'}" in result.batch.items[0].detail
    assert "命令:" not in result.batch.items[0].detail
    assert result.batch.items[1].reason == "日志未定位失败 CSV"
    assert (
        f"子进程日志: {output_dir / 'v1' / 'offline_logs' / '0001_B.log'}"
        in result.batch.items[1].detail
    )
    assert "错误: boom" in result.batch.items[1].detail
    assert "命令:" not in result.batch.items[1].detail
    assert output_dir / "v1" / "数据整理" in result.batch.artifacts


def test_offline_cli_prints_summary_then_returns_nonzero_for_final_fail(monkeypatch):
    import health_tools.api as api

    monkeypatch.setattr(
        api,
        "run_offline",
        lambda request, *, context=None: api.OfflineResult(
            api.BatchResult(
                "offline",
                (api.ItemResult(api.ItemStatus.FAIL, "A", reason="boom"),),
            )
        ),
    )

    result = CliRunner().invoke(main, ["offline"])

    assert result.exit_code != 0
    assert "boom" in result.output
    assert "offline" in result.output


def test_plot_directory_uses_api_file_orchestration(monkeypatch, tmp_path: Path):
    from health_tools.api import ItemResult, ItemStatus

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "a.csv").write_text("x\n1\n", encoding="utf-8")
    (input_dir / "b.csv").write_text("x\n2\n", encoding="utf-8")
    plotted = []

    class FakePlotter:
        def __init__(self, **kwargs):
            self.fmt = kwargs["fmt"]

    monkeypatch.setattr(
        "health_tools.api.file_operations._plot_one",
        lambda file, *args: plotted.append(file.name)
        or ItemResult(ItemStatus.OK, str(file), str(output_dir / f"{file.stem}.png")),
    )
    monkeypatch.setattr("health_tools.core.plotter.DataPlotter", FakePlotter)

    result = CliRunner().invoke(
        main,
        [
            "plot",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "--type",
            "time",
            "--no-show",
        ],
    )

    assert result.exit_code == 0
    assert plotted == ["a.csv", "b.csv"]


def test_plot_psd_creates_output_dir_and_uses_psd_plotter(monkeypatch, tmp_path: Path):
    from health_tools.core.psd_plotter import PsdPlotResult

    calls = []
    input_dir = tmp_path / "result"
    output_dir = tmp_path / "new_output"
    input_dir.mkdir()

    def fake_plot(
        self,
        result_dir,
        save_dir=None,
        show_progress=False,
        acc_mode="axis",
        save_to_source=False,
        workers=8,
    ):
        calls.append((result_dir, save_dir, show_progress, acc_mode, save_to_source, workers))
        return PsdPlotResult((save_dir / "sample.png",), ())

    monkeypatch.setattr("health_tools.core.psd_plotter.PsdPlotter.plot", fake_plot)

    result = CliRunner().invoke(
        main,
        [
            "plot",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "--type",
            "psd",
        ],
    )

    assert result.exit_code == 0
    assert output_dir.exists()
    assert calls == [(input_dir, output_dir, False, "axis", False, 8)]


def test_plot_psd_can_select_accrms_mode(monkeypatch, tmp_path: Path):
    from health_tools.core.psd_plotter import PsdPlotResult

    calls = []
    input_dir = tmp_path / "result"
    output_dir = tmp_path / "new_output"
    input_dir.mkdir()

    def fake_plot(
        self,
        result_dir,
        save_dir=None,
        show_progress=False,
        acc_mode="axis",
        save_to_source=False,
        workers=8,
    ):
        calls.append((result_dir, save_dir, show_progress, acc_mode, save_to_source, workers))
        return PsdPlotResult((save_dir / "sample.png",), ())

    monkeypatch.setattr("health_tools.core.psd_plotter.PsdPlotter.plot", fake_plot)

    result = CliRunner().invoke(
        main,
        [
            "plot",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "--type",
            "psd",
            "--psd-acc",
            "rms",
        ],
    )

    assert result.exit_code == 0
    assert calls == [(input_dir, output_dir, False, "rms", False, 8)]


def test_plot_psd_forwards_custom_accuracy_options(monkeypatch, tmp_path: Path):
    from health_tools.core.psd_plotter import PsdPlotResult

    calls = []
    input_dir = tmp_path / "result"
    output_dir = tmp_path / "new_output"
    input_dir.mkdir()

    def fake_plot(
        self,
        result_dir,
        save_dir=None,
        show_progress=False,
        acc_mode="axis",
        save_to_source=False,
        accuracy_thresholds=None,
        accuracy_inclusive=False,
        workers=8,
    ):
        calls.append((accuracy_thresholds, accuracy_inclusive, workers))
        return PsdPlotResult((save_dir / "sample.png",), ())

    monkeypatch.setattr("health_tools.core.psd_plotter.PsdPlotter.plot", fake_plot)

    result = CliRunner().invoke(
        main,
        [
            "plot",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "--type",
            "psd",
            "--accuracy-thresholds",
            "3.5,7",
            "--accuracy-inclusive",
        ],
    )

    assert result.exit_code == 0
    assert calls == [((3.5, 7.0), True, 8)]


def test_plot_psd_maps_successes_and_failures_to_batch(monkeypatch, tmp_path: Path):
    from health_tools.api import PlotRequest, run_plot
    from health_tools.api.models import ItemStatus
    from health_tools.core.psd_plotter import PsdPlotResult

    input_dir = tmp_path / "result"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    saved_path = output_dir / "ok.png"
    failed_path = input_dir / "bad_result.vshb"
    seen = {}

    def fake_plot(self, result_dir, **kwargs):
        seen["workers"] = kwargs["workers"]
        return PsdPlotResult((saved_path,), ((failed_path, "坏数据"),))

    monkeypatch.setattr("health_tools.core.psd_plotter.PsdPlotter.plot", fake_plot)

    result = run_plot(PlotRequest(input_dir, output_dir, plot_type="psd", workers=3))

    assert seen == {"workers": 3}
    assert [item.status for item in result.items] == [ItemStatus.OK, ItemStatus.FAIL]
    assert result.items[1].input == str(failed_path)
    assert result.items[1].detail == "坏数据"
    assert result.artifacts == (saved_path,)


def test_plot_psd_requires_directory(tmp_path: Path):
    input_file = tmp_path / "result.csv"
    output_dir = tmp_path / "output"
    input_file.write_text("x\n1\n", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "plot",
            "-i",
            str(input_file),
            "-o",
            str(output_dir),
            "--type",
            "psd",
        ],
    )

    assert result.exit_code == 1
    assert "PSD绘图输入必须是离线结果目录" in result.output


def test_plot_rejects_unknown_type(tmp_path: Path):
    input_file = tmp_path / "data.csv"
    output_dir = tmp_path / "output"
    input_file.write_text("x\n1\n", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "plot",
            "-i",
            str(input_file),
            "-o",
            str(output_dir),
            "--type",
            "unknown",
        ],
    )

    assert result.exit_code == 1
    assert "不支持的图表类型" in result.output


def test_plot_ac_supports_semicolon_channel_groups(monkeypatch, tmp_path: Path):
    import pandas as pd

    input_file = tmp_path / "sample.csv"
    output_dir = tmp_path / "output"
    pd.DataFrame(
        {
            "ACCX": [1, 2],
            "ACCY": [2, 3],
            "ACCZ": [3, 4],
            "CH0": [10, 11],
            "CH1": [20, 21],
            "CH2": [30, 31],
        }
    ).to_csv(input_file, index=False)
    calls = []

    class FakePlotter:
        def __init__(self, **kwargs):
            self.fmt = kwargs["fmt"]

        def plot_ac(self, df, output_file, channels, acc_columns):
            calls.append((output_file.name, channels, acc_columns))

    monkeypatch.setattr("health_tools.core.plotter.DataPlotter", FakePlotter)

    result = CliRunner().invoke(
        main,
        [
            "plot",
            "-i",
            str(input_file),
            "-o",
            str(output_dir),
            "--type",
            "ac",
            "--channels",
            "CH0,CH2;CH1",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        ("sample_ac_CH0-CH2.png", ["CH0", "CH2"], ["ACCX", "ACCY", "ACCZ"]),
        ("sample_ac_CH1.png", ["CH1"], ["ACCX", "ACCY", "ACCZ"]),
    ]


def test_plot_ac_rejects_channel_group_over_four(tmp_path: Path):
    input_file = tmp_path / "sample.csv"
    input_file.write_text("CH0\n1\n", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "plot",
            "-i",
            str(input_file),
            "-o",
            str(tmp_path / "output"),
            "--type",
            "ac",
            "--channels",
            "CH0,CH1,CH2,CH3,CH4",
        ],
    )

    assert result.exit_code == 1
    assert "每组最多支持 4 个通道" in result.output
    assert "CH0,CH1,CH2,CH3,CH4" in result.output


def test_plot_ac_auto_selects_first_four_nonzero_chip_channels(monkeypatch, tmp_path: Path):
    import pandas as pd

    from health_tools.models.rules import ChipRule

    input_file = tmp_path / "sample.csv"
    output_dir = tmp_path / "output"
    data = {"ACCX": [1, 2], "ACCY": [2, 3], "ACCZ": [3, 4]}
    data.update({f"CH{index}": [index + 1, index + 2] for index in range(5)})
    pd.DataFrame(data).to_csv(input_file, index=False)
    calls = []

    class FakePlotter:
        def __init__(self, **kwargs):
            self.fmt = kwargs["fmt"]

        def plot_ac(self, df, output_file, channels, acc_columns):
            calls.append((output_file.name, channels))

    rule = ChipRule(chip="gh3220", csv={}, columns=[])
    monkeypatch.setattr("health_tools.rules.loader.RuleLoader.load_chip_rule", lambda _name: rule)
    monkeypatch.setattr("health_tools.core.plotter.DataPlotter", FakePlotter)

    result = CliRunner().invoke(
        main,
        [
            "plot",
            "-i",
            str(input_file),
            "-o",
            str(output_dir),
            "--type",
            "ac",
            "--chip",
            "gh3220",
        ],
    )

    assert result.exit_code == 0
    assert calls == [("sample_ac.png", ["CH0", "CH1", "CH2", "CH3"])]
    assert "未绘制通道: CH4" in result.output


def test_plot_fft_creates_one_output_per_channel(monkeypatch, tmp_path: Path):
    import pandas as pd

    input_file = tmp_path / "sample.csv"
    output_dir = tmp_path / "output"
    pd.DataFrame({"CH0": [1, 2], "CH2": [3, 4]}).to_csv(input_file, index=False)
    calls = []

    class FakePlotter:
        def __init__(self, **kwargs):
            self.fmt = kwargs["fmt"]

        def plot_fft(self, df, output_file, channel):
            calls.append((output_file.name, channel))

    monkeypatch.setattr("health_tools.core.plotter.DataPlotter", FakePlotter)

    result = CliRunner().invoke(
        main,
        [
            "plot",
            "-i",
            str(input_file),
            "-o",
            str(output_dir),
            "--type",
            "fft",
            "--channels",
            "CH0,CH2",
        ],
    )

    assert result.exit_code == 0
    assert calls == [("sample_fft_CH0.png", "CH0"), ("sample_fft_CH2.png", "CH2")]


def test_plot_fft_auto_selection_is_not_limited_to_four_channels(monkeypatch, tmp_path: Path):
    import pandas as pd

    from health_tools.models.rules import ChipRule

    input_file = tmp_path / "sample.csv"
    output_dir = tmp_path / "output"
    pd.DataFrame({f"CH{index}": [index + 1, index + 2] for index in range(5)}).to_csv(
        input_file, index=False
    )
    calls = []

    class FakePlotter:
        def __init__(self, **kwargs):
            self.fmt = kwargs["fmt"]

        def plot_fft(self, df, output_file, channel):
            calls.append(channel)

    rule = ChipRule(chip="gh3220", csv={}, columns=[])
    monkeypatch.setattr("health_tools.rules.loader.RuleLoader.load_chip_rule", lambda _name: rule)
    monkeypatch.setattr("health_tools.core.plotter.DataPlotter", FakePlotter)

    result = CliRunner().invoke(
        main,
        [
            "plot",
            "-i",
            str(input_file),
            "-o",
            str(output_dir),
            "--type",
            "fft",
            "--chip",
            "gh3220",
        ],
    )

    assert result.exit_code == 0
    assert calls == ["CH0", "CH1", "CH2", "CH3", "CH4"]


def test_plot_analysis_rejects_bandpass_at_nyquist(tmp_path: Path):
    input_file = tmp_path / "sample.csv"
    input_file.write_text("CH0\n1\n", encoding="utf-8")

    result = CliRunner().invoke(
        main,
        [
            "plot",
            "-i",
            str(input_file),
            "-o",
            str(tmp_path / "output"),
            "--type",
            "fft",
            "--channels",
            "CH0",
            "--sample-rate",
            "10",
            "--bandpass",
            "0.5-5.0",
        ],
    )

    assert result.exit_code == 1
    assert "必须小于奈奎斯特频率" in result.output


def test_convert_merge_uses_progress_track(monkeypatch, tmp_path: Path):
    import pandas as pd

    import health_tools.commands.convert as convert_module
    from health_tools.core.converter import DataConverter
    from health_tools.models.rules import ConvertRule

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.csv").write_text("time,value\n1,10\n", encoding="utf-8")
    output_file = tmp_path / "merged.csv"
    calls = []

    def fake_progress_track(items, description, console=None, enabled=True, total=None):
        materialized = list(items)
        calls.append((description, enabled, len(materialized)))
        yield from materialized

    monkeypatch.setattr(convert_module, "progress_track", fake_progress_track)

    rule = ConvertRule(column_mapping={"time": "TimeStamp", "value": "VALUE"})
    convert_module._merge_and_convert(
        input_dir,
        output_file,
        DataConverter(rule),
        None,
        None,
        None,
        None,
        verbose=False,
    )

    assert calls == [("读取CSV...", True, 1)]
    assert list(pd.read_csv(output_file).columns) == ["TimeStamp", "VALUE"]


def test_factory_directory_uses_api_calculator(monkeypatch, tmp_path: Path):
    import pandas as pd

    input_dir = tmp_path / "input"
    output_file = tmp_path / "factory.csv"
    input_dir.mkdir()
    (input_dir / "a.csv").write_text("ch0\n1\n2\n", encoding="utf-8")

    class FakeResult:
        channel = "ch0"
        gain = None
        current = None

    class FakeCalculator:
        adc_full_scale = 1
        adc_offset = 0
        adc_vref = 1.8
        tia_ratio = 2

        def calculate(self, df, ch_list, extractor=None):
            return [FakeResult()]

        def to_dataframe(self, results, file_name):
            return pd.DataFrame({"file_name": [file_name], "ch_num": [len(results)]})

    monkeypatch.setattr(
        "health_tools.api.file_operations._factory_calculator",
        lambda *args, **kwargs: FakeCalculator(),
    )
    monkeypatch.setattr(
        "health_tools.utils.csv_handler.read_csv_df", lambda path, chip_rule: pd.read_csv(path)
    )

    result = CliRunner().invoke(
        main,
        [
            "factory",
            "-i",
            str(input_dir),
            "-o",
            str(output_file),
        ],
    )

    assert result.exit_code == 0
    assert output_file.exists()


def test_split_command_enables_progress(monkeypatch, tmp_path: Path):
    import health_tools.core.splitter as splitter_module

    seen = {}

    def fake_split_directory(self, *args, **kwargs):
        seen["show_progress"] = kwargs["show_progress"]
        return []

    monkeypatch.setattr(splitter_module.DataSplitter, "split_directory", fake_split_directory)
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    result = CliRunner().invoke(main, ["split", "-i", str(input_dir), "-o", str(tmp_path / "out")])

    assert result.exit_code == 0
    assert seen == {}


def test_evaluate_command_enables_progress(monkeypatch, tmp_path: Path):
    from health_tools.models.rules import EvaluateRule

    seen = {}

    class FakeEvaluator:
        from health_tools.utils.reporting import ResultCollector

        last_collector = ResultCollector()

        def __init__(self, *args, **kwargs):
            pass

        def evaluate_directory(self, *args, **kwargs):
            seen["show_progress"] = kwargs["show_progress"]
            return {}

    monkeypatch.setattr(
        "health_tools.rules.loader.RuleLoader.load_evaluate_rule",
        lambda path: EvaluateRule(),
    )
    monkeypatch.setattr("health_tools.core.evaluator.BatchEvaluator", FakeEvaluator)
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    result = CliRunner().invoke(
        main,
        ["evaluate", "-i", str(input_dir), "-o", str(tmp_path / "out")],
    )

    assert result.exit_code == 0
    assert seen == {"show_progress": False}


def test_offline_command_enables_stage_progress(monkeypatch, tmp_path: Path):
    import pandas as pd

    calls = []
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    monkeypatch.setattr(
        "health_tools.core.offline.reorganize_output",
        lambda input_path, output_path, show_progress=False: calls.append(
            ("reorganize", show_progress)
        )
        or output_path,
    )
    monkeypatch.setattr(
        "health_tools.core.psd_plotter.PsdPlotter.plot",
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False, workers=8: calls.append(
            ("plot", show_progress, acc_mode, save_to_source)
        )
        or PsdPlotResult((), ()),
    )
    monkeypatch.setattr(
        "health_tools.core.offline.calculate_offline_accuracy",
        lambda output_path, show_progress=False: calls.append(("accuracy", show_progress))
        or pd.DataFrame({"file": ["TOTAL"]}),
    )

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "--no-run",
        ],
    )

    assert result.exit_code == 0
    assert calls == [("reorganize", False), ("plot", False, "axis", True), ("accuracy", False)]


def test_offline_forwards_custom_accuracy_options(monkeypatch, tmp_path: Path):
    import pandas as pd

    calls = []
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    monkeypatch.setattr(
        "health_tools.core.offline.reorganize_output",
        lambda input_path, output_path, show_progress=False: output_path,
    )

    def fake_plot(
        self,
        result_dir,
        save_dir=None,
        show_progress=False,
        acc_mode="axis",
        save_to_source=False,
        accuracy_thresholds=None,
        accuracy_inclusive=False,
        workers=8,
    ):
        calls.append(("plot", accuracy_thresholds, accuracy_inclusive, workers))
        return PsdPlotResult((), ())

    def fake_accuracy(
        output_path,
        show_progress=False,
        accuracy_thresholds=None,
        accuracy_inclusive=False,
    ):
        calls.append(("accuracy", accuracy_thresholds, accuracy_inclusive))
        return pd.DataFrame({"file": ["TOTAL"]})

    monkeypatch.setattr("health_tools.core.psd_plotter.PsdPlotter.plot", fake_plot)
    monkeypatch.setattr("health_tools.core.offline.calculate_offline_accuracy", fake_accuracy)

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "--no-run",
            "--accuracy-thresholds",
            "3.5,7",
            "--accuracy-inclusive",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        ("plot", (3.5, 7.0), True, 8),
        ("accuracy", (3.5, 7.0), True),
    ]


def test_offline_medium_version_defaults_psd_to_accrms(monkeypatch, tmp_path: Path):
    import pandas as pd

    calls = []
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    exe_path = tmp_path / "tools" / "gh3220" / "medium" / "v1" / "TEE_Algorithm.exe"
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("", encoding="utf-8")

    monkeypatch.setattr("health_tools.core.offline.find_exe", lambda chip, ver=None: exe_path)
    monkeypatch.setattr(
        "health_tools.core.offline.reorganize_output",
        lambda input_path, output_path, show_progress=False: output_path,
    )
    monkeypatch.setattr(
        "health_tools.core.psd_plotter.PsdPlotter.plot",
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False, workers=8: calls.append(
            acc_mode
        )
        or PsdPlotResult((), ()),
    )
    monkeypatch.setattr(
        "health_tools.core.offline.calculate_offline_accuracy",
        lambda output_path, show_progress=False: pd.DataFrame({"file": ["TOTAL"]}),
    )

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "-c",
            "gh3220",
            "--no-run",
        ],
    )

    assert result.exit_code == 0
    assert calls == ["rms"]


def test_offline_single_version_uses_version_output_dir(monkeypatch, tmp_path: Path):
    import pandas as pd

    calls = []
    monkeypatch.setattr(
        "health_tools.api.offline_operation._filter_input_files", lambda *args: None
    )
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    output_dir = tmp_path / "output"
    exe_path = tmp_path / "tools" / "gh3300" / "exclusive" / "v1" / "TEE_Algorithm.exe"
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("", encoding="utf-8")

    class FakeRunner(_FakeOfflineRunnerPreview):
        def __init__(self, chip, version=None, **kwargs):
            self.version = version

        def run(
            self,
            input_path,
            output_path,
            timeout=300,
            settle_timeout=10,
            is_cancelled=None,
            **kwargs,
        ):
            calls.append(("run", self.version, output_path))
            output_path.mkdir(parents=True, exist_ok=True)
            return type("RunResult", (), {"success": True, "warning": None})()

    monkeypatch.setattr("health_tools.core.offline.find_exe", lambda chip, ver=None: exe_path)
    monkeypatch.setattr("health_tools.core.offline.OfflineRunner", FakeRunner)
    monkeypatch.setattr(
        "health_tools.core.offline.reorganize_output",
        lambda input_path, output_path, show_progress=False: output_path,
    )
    monkeypatch.setattr(
        "health_tools.core.offline.calculate_offline_accuracy",
        lambda output_path, show_progress=False: pd.DataFrame({"file": ["TOTAL"]}),
    )
    monkeypatch.setattr(
        "health_tools.core.psd_plotter.PsdPlotter.plot",
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False, workers=8: PsdPlotResult(
            (), ()
        ),
    )

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "-c",
            "gh3300",
            "--version",
            "v1",
        ],
    )

    assert result.exit_code == 0
    assert (
        "run",
        "v1",
        output_dir / "v1" / ".offline_tasks" / "0000_root" / "raw",
    ) in calls


def test_offline_default_timeout_scales_after_fifty_files(monkeypatch, tmp_path: Path):
    import pandas as pd

    calls = []
    monkeypatch.setattr(
        "health_tools.api.offline_operation._filter_input_files", lambda *args: None
    )
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for idx in range(51):
        (input_dir / f"sample_{idx}.csv").write_text("x\n1\n", encoding="utf-8")
    output_dir = tmp_path / "output"
    exe_path = tmp_path / "tools" / "gh3300" / "exclusive" / "v1" / "TEE_Algorithm.exe"
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("", encoding="utf-8")

    class FakeRunner(_FakeOfflineRunnerPreview):
        def __init__(self, chip, version=None, **kwargs):
            pass

        def run(
            self,
            input_path,
            output_path,
            timeout=300,
            settle_timeout=10,
            is_cancelled=None,
            **kwargs,
        ):
            calls.append(timeout)
            output_path.mkdir(parents=True, exist_ok=True)
            return type("RunResult", (), {"success": True, "warning": None})()

    monkeypatch.setattr("health_tools.core.offline.find_exe", lambda chip, ver=None: exe_path)
    monkeypatch.setattr("health_tools.core.offline.OfflineRunner", FakeRunner)
    monkeypatch.setattr(
        "health_tools.core.offline.reorganize_output",
        lambda input_path, output_path, show_progress=False: output_path,
    )
    monkeypatch.setattr(
        "health_tools.core.offline.calculate_offline_accuracy",
        lambda output_path, show_progress=False: pd.DataFrame({"file": ["TOTAL"]}),
    )
    monkeypatch.setattr(
        "health_tools.core.psd_plotter.PsdPlotter.plot",
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False, workers=8: PsdPlotResult(
            (), ()
        ),
    )

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "-c",
            "gh3300",
            "--version",
            "v1",
        ],
    )

    assert result.exit_code == 0
    assert calls == [320]


def test_offline_explicit_timeout_overrides_scaled_default(monkeypatch, tmp_path: Path):
    import pandas as pd

    calls = []
    monkeypatch.setattr(
        "health_tools.api.offline_operation._filter_input_files", lambda *args: None
    )
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for idx in range(60):
        (input_dir / f"sample_{idx}.csv").write_text("x\n1\n", encoding="utf-8")
    output_dir = tmp_path / "output"
    exe_path = tmp_path / "tools" / "gh3300" / "exclusive" / "v1" / "TEE_Algorithm.exe"
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("", encoding="utf-8")

    class FakeRunner(_FakeOfflineRunnerPreview):
        def __init__(self, chip, version=None, **kwargs):
            pass

        def run(
            self,
            input_path,
            output_path,
            timeout=300,
            settle_timeout=10,
            is_cancelled=None,
            **kwargs,
        ):
            calls.append(timeout)
            output_path.mkdir(parents=True, exist_ok=True)
            return type("RunResult", (), {"success": True, "warning": None})()

    monkeypatch.setattr("health_tools.core.offline.find_exe", lambda chip, ver=None: exe_path)
    monkeypatch.setattr("health_tools.core.offline.OfflineRunner", FakeRunner)
    monkeypatch.setattr(
        "health_tools.core.offline.reorganize_output",
        lambda input_path, output_path, show_progress=False: output_path,
    )
    monkeypatch.setattr(
        "health_tools.core.offline.calculate_offline_accuracy",
        lambda output_path, show_progress=False: pd.DataFrame({"file": ["TOTAL"]}),
    )
    monkeypatch.setattr(
        "health_tools.core.psd_plotter.PsdPlotter.plot",
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False, workers=8: PsdPlotResult(
            (), ()
        ),
    )

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "-c",
            "gh3300",
            "--version",
            "v1",
            "--timeout",
            "123",
        ],
    )

    assert result.exit_code == 0
    assert calls == [123]


def test_offline_default_version_uses_resolved_version_output_dir(monkeypatch, tmp_path: Path):
    import pandas as pd

    calls = []
    monkeypatch.setattr(
        "health_tools.api.offline_operation._filter_input_files", lambda *args: None
    )
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    output_dir = tmp_path / "output"
    exe_path = tmp_path / "tools" / "gh3300" / "exclusive" / "default_v1" / "TEE_Algorithm.exe"
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("", encoding="utf-8")

    class FakeRunner(_FakeOfflineRunnerPreview):
        def __init__(self, chip, version=None, **kwargs):
            self.version = version

        def run(
            self,
            input_path,
            output_path,
            timeout=300,
            settle_timeout=10,
            is_cancelled=None,
            **kwargs,
        ):
            calls.append(("run", self.version, output_path))
            output_path.mkdir(parents=True, exist_ok=True)
            return type("RunResult", (), {"success": True, "warning": None})()

    monkeypatch.setattr("health_tools.core.offline.find_exe", lambda chip, ver=None: exe_path)
    monkeypatch.setattr("health_tools.core.offline.OfflineRunner", FakeRunner)
    monkeypatch.setattr(
        "health_tools.core.offline.reorganize_output",
        lambda input_path, output_path, show_progress=False: output_path,
    )
    monkeypatch.setattr(
        "health_tools.core.offline.calculate_offline_accuracy",
        lambda output_path, show_progress=False: pd.DataFrame({"file": ["TOTAL"]}),
    )
    monkeypatch.setattr(
        "health_tools.core.psd_plotter.PsdPlotter.plot",
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False, workers=8: PsdPlotResult(
            (), ()
        ),
    )

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "-c",
            "gh3300",
        ],
    )

    assert result.exit_code == 0
    assert (
        "run",
        None,
        output_dir / "default_v1" / ".offline_tasks" / "0000_root" / "raw",
    ) in calls


def test_offline_versions_runs_each_version_and_writes_combined_accuracy(
    monkeypatch, tmp_path: Path
):
    import pandas as pd

    calls = []
    monkeypatch.setattr(
        "health_tools.api.offline_operation._filter_input_files", lambda *args: None
    )
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    output_dir = tmp_path / "output"
    exe_root = tmp_path / "tools" / "gh3300" / "exclusive"
    for version in ["v1", "v2"]:
        exe_path = exe_root / version / "TEE_Algorithm.exe"
        exe_path.parent.mkdir(parents=True)
        exe_path.write_text("", encoding="utf-8")

    def fake_find_exe(chip, ver=None):
        return exe_root / ver / "TEE_Algorithm.exe"

    class FakeRunner(_FakeOfflineRunnerPreview):
        def __init__(self, chip, version=None, **kwargs):
            self.version = version

        def run(
            self,
            input_path,
            output_path,
            timeout=300,
            settle_timeout=10,
            is_cancelled=None,
            **kwargs,
        ):
            calls.append(("run", self.version, output_path))
            output_path.mkdir(parents=True, exist_ok=True)
            return type("RunResult", (), {"success": True, "warning": None})()

    def fake_reorganize(input_path, output_path, show_progress=False):
        calls.append(("reorganize", output_path.name, show_progress))
        reorg_dir = output_path / "数据整理"
        reorg_dir.mkdir(parents=True, exist_ok=True)
        return reorg_dir

    def fake_accuracy(output_path, show_progress=False):
        calls.append(("accuracy", output_path.parent.name, show_progress))
        return pd.DataFrame({"file": ["TOTAL"], "samples": [10]})

    monkeypatch.setattr("health_tools.core.offline.find_exe", fake_find_exe)
    monkeypatch.setattr("health_tools.core.offline.OfflineRunner", FakeRunner)
    monkeypatch.setattr("health_tools.core.offline.reorganize_output", fake_reorganize)
    monkeypatch.setattr("health_tools.core.offline.calculate_offline_accuracy", fake_accuracy)
    monkeypatch.setattr(
        "health_tools.core.psd_plotter.PsdPlotter.plot",
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False, workers=8: PsdPlotResult(
            (), ()
        ),
    )

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "-c",
            "gh3300",
            "--versions",
            "v1, v2, v1",
            "--no-plot",
        ],
    )

    assert result.exit_code == 0
    assert (
        "run",
        "v1",
        output_dir / "v1" / ".offline_tasks" / "0000_root" / "raw",
    ) in calls
    assert (
        "run",
        "v2",
        output_dir / "v2" / ".offline_tasks" / "0000_root" / "raw",
    ) in calls
    combined = pd.read_csv(output_dir / "accuracy_report_all_versions.csv")
    assert list(combined["version"]) == ["v1", "v2"]
    assert list(combined["file"]) == ["TOTAL", "TOTAL"]


def test_offline_all_versions_expands_config_versions(monkeypatch, tmp_path: Path):
    import pandas as pd

    calls = []
    monkeypatch.setattr(
        "health_tools.api.offline_operation._filter_input_files", lambda *args: None
    )
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    output_dir = tmp_path / "output"
    exe_root = tmp_path / "tools" / "gh3300"

    def fake_find_exe(chip, ver=None):
        category = "exclusive" if ver == "v1" else "medium"
        exe_path = exe_root / category / ver / "TEE_Algorithm.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.write_text("", encoding="utf-8")
        return exe_path

    class FakeRunner(_FakeOfflineRunnerPreview):
        def __init__(self, chip, version=None, **kwargs):
            self.version = version

        def run(
            self,
            input_path,
            output_path,
            timeout=300,
            settle_timeout=10,
            is_cancelled=None,
            **kwargs,
        ):
            calls.append(self.version)
            output_path.mkdir(parents=True, exist_ok=True)
            return type("RunResult", (), {"success": True, "warning": None})()

    monkeypatch.setattr("health_tools.core.offline.find_exe", fake_find_exe)
    monkeypatch.setattr("health_tools.core.offline.OfflineRunner", FakeRunner)
    monkeypatch.setattr(
        "health_tools.core.offline.get_offline_config",
        lambda: type(
            "Cfg",
            (),
            {
                "versions": {
                    "gh3300": {
                        "versions": {"exclusive": ["v1"], "medium": ["v2"]},
                        "default": "v1",
                    }
                }
            },
        )(),
    )
    monkeypatch.setattr(
        "health_tools.core.offline.reorganize_output",
        lambda input_path, output_path, show_progress=False: output_path,
    )
    monkeypatch.setattr(
        "health_tools.core.offline.calculate_offline_accuracy",
        lambda output_path, show_progress=False: pd.DataFrame({"file": ["TOTAL"]}),
    )
    monkeypatch.setattr(
        "health_tools.core.psd_plotter.PsdPlotter.plot",
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False, workers=8: PsdPlotResult(
            (), ()
        ),
    )

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "-c",
            "gh3300",
            "--all-versions",
            "--no-plot",
        ],
    )

    assert result.exit_code == 0
    assert calls == ["v1", "v2"]


def test_offline_no_run_versions_collects_existing_reorganized_vshb(monkeypatch, tmp_path: Path):
    import pandas as pd

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "GH3036_RES"
    input_dir.mkdir()
    (input_dir / "sample.csv").write_text("x\n1\n", encoding="utf-8")
    row = "1,80,79,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0," "80,1,99,0,0,0,81\n"
    for version in ["v1", "v2"]:
        reorg_dir = output_dir / version / "数据整理"
        reorg_dir.mkdir(parents=True)
        (reorg_dir / "000000_sample_result.vshb").write_text(row, encoding="utf-8")

    exe_root = tmp_path / "tools" / "gh3036" / "exclusive"

    def fake_find_exe(chip, ver=None):
        exe_path = exe_root / ver / "TEE_Algorithm.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.write_text("", encoding="utf-8")
        return exe_path

    monkeypatch.setattr("health_tools.core.offline.find_exe", fake_find_exe)
    monkeypatch.setattr(
        "health_tools.core.psd_plotter.PsdPlotter.plot",
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False, workers=8: PsdPlotResult(
            (), ()
        ),
    )

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "-c",
            "gh3036",
            "--versions",
            "v1,v2",
            "--no-run",
            "--no-plot",
        ],
    )

    assert result.exit_code == 0
    combined = pd.read_csv(output_dir / "accuracy_report_all_versions.csv")
    assert list(combined["version"]) == ["v1", "v1", "v1", "v2", "v2", "v2"]
    assert combined["file"].tolist().count("TOTAL") == 2


def test_offline_no_run_versions_reuses_existing_reorganized_dirs(monkeypatch, tmp_path: Path):
    import pandas as pd

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "GH3036_RES"
    input_dir.mkdir()
    (input_dir / "sample.csv").write_text("x\n1\n", encoding="utf-8")
    for version in ["v1", "v2"]:
        reorg_dir = output_dir / version / "数据整理"
        reorg_dir.mkdir(parents=True)
        (reorg_dir / "000000_sample_result.vshb").write_text(
            "1,80,79,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0," "80,1,99,0,0,0,81\n",
            encoding="utf-8",
        )
        private_marker = output_dir / version / ".offline_tasks" / "keep.txt"
        private_marker.parent.mkdir()
        private_marker.write_text("keep", encoding="utf-8")

    exe_root = tmp_path / "tools" / "gh3036" / "exclusive"

    def fake_find_exe(chip, ver=None):
        exe_path = exe_root / ver / "TEE_Algorithm.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.write_text("", encoding="utf-8")
        return exe_path

    def fail_reorganize(input_path, output_path, show_progress=False):
        raise AssertionError("已有数据整理目录时不应重新整理")

    monkeypatch.setattr("health_tools.core.offline.find_exe", fake_find_exe)
    monkeypatch.setattr("health_tools.core.offline.reorganize_output", fail_reorganize)
    monkeypatch.setattr(
        "health_tools.core.psd_plotter.PsdPlotter.plot",
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False, workers=8: PsdPlotResult(
            (), ()
        ),
    )

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "-c",
            "gh3036",
            "--versions",
            "v1,v2",
            "--no-run",
            "--no-plot",
        ],
    )

    assert result.exit_code == 0
    combined = pd.read_csv(output_dir / "accuracy_report_all_versions.csv")
    assert combined["file"].tolist().count("TOTAL") == 2
    assert all(
        (output_dir / version / ".offline_tasks" / "keep.txt").exists() for version in ("v1", "v2")
    )


def test_offline_no_run_discovers_version_dirs_under_output_parent(monkeypatch, tmp_path: Path):
    import pandas as pd

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "GH3036_RES"
    input_dir.mkdir()
    (input_dir / "sample.csv").write_text("x\n1\n", encoding="utf-8")
    for version in ["GH_HR_exc_keep-B6lite_v1.0.1.2", "GH_HR_exc_keep-B6lite_v1.0.1.3"]:
        reorg_dir = output_dir / version / "数据整理"
        reorg_dir.mkdir(parents=True)
        (reorg_dir / "000000_sample_result.vshb").write_text(
            "1,80,79,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0," "80,1,99,0,0,0,81\n",
            encoding="utf-8",
        )

    def fail_reorganize(input_path, output_path, show_progress=False):
        raise AssertionError("已有数据整理目录时不应重新整理")

    monkeypatch.setattr("health_tools.core.offline.reorganize_output", fail_reorganize)
    monkeypatch.setattr(
        "health_tools.core.psd_plotter.PsdPlotter.plot",
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False, workers=8: PsdPlotResult(
            (), ()
        ),
    )

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "--no-run",
            "--no-plot",
        ],
    )

    assert result.exit_code == 0
    combined = pd.read_csv(output_dir / "accuracy_report_all_versions.csv")
    assert list(combined["version"]) == [
        "GH_HR_exc_keep-B6lite_v1.0.1.2",
        "GH_HR_exc_keep-B6lite_v1.0.1.2",
        "GH_HR_exc_keep-B6lite_v1.0.1.2",
        "GH_HR_exc_keep-B6lite_v1.0.1.3",
        "GH_HR_exc_keep-B6lite_v1.0.1.3",
        "GH_HR_exc_keep-B6lite_v1.0.1.3",
    ]
    assert combined["file"].tolist().count("TOTAL") == 2


def test_offline_version_options_are_mutually_exclusive(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-c",
            "gh3300",
            "--version",
            "v1",
            "--versions",
            "v2",
        ],
    )

    assert result.exit_code == 1
    assert "--version 不能与 --versions" in result.output


def test_offline_all_versions_rejects_explicit_version(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-c",
            "gh3300",
            "--version",
            "v1",
            "--all-versions",
        ],
    )

    assert result.exit_code == 1
    assert "--all-versions 不能与 --version/--versions" in result.output
