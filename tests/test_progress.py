from pathlib import Path

from click.testing import CliRunner
from rich.console import Console

from health_tools.cli import main
from health_tools.commands.offline import _build_accuracy_tables


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


def test_plot_directory_uses_progress_track(monkeypatch, tmp_path: Path):
    import health_tools.commands.plot as plot_module

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "a.csv").write_text("x\n1\n", encoding="utf-8")
    (input_dir / "b.csv").write_text("x\n2\n", encoding="utf-8")
    calls = []
    plotted = []

    class FakePlotter:
        def __init__(self, **kwargs):
            self.fmt = kwargs["fmt"]

    def fake_progress_track(items, description, console=None, enabled=True, total=None):
        materialized = list(items)
        calls.append((description, enabled, len(materialized)))
        yield from materialized

    monkeypatch.setattr(plot_module, "progress_track", fake_progress_track)
    monkeypatch.setattr(plot_module, "_plot_file", lambda file, *args: plotted.append(file.name))
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
    assert calls == [("绘制图表...", True, 2)]
    assert plotted == ["a.csv", "b.csv"]


def test_plot_psd_creates_output_dir_and_uses_psd_plotter(monkeypatch, tmp_path: Path):
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
    ):
        calls.append((result_dir, save_dir, show_progress, acc_mode, save_to_source))
        return [save_dir / "sample.png"]

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
    assert calls == [(input_dir, output_dir, True, "axis", False)]


def test_plot_psd_can_select_accrms_mode(monkeypatch, tmp_path: Path):
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
    ):
        calls.append((result_dir, save_dir, show_progress, acc_mode, save_to_source))
        return [save_dir / "sample.png"]

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
    assert calls == [(input_dir, output_dir, True, "rms", False)]


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


def test_factory_directory_uses_progress_track(monkeypatch, tmp_path: Path):
    import pandas as pd

    import health_tools.commands.factory as factory_module

    input_dir = tmp_path / "input"
    output_file = tmp_path / "factory.csv"
    input_dir.mkdir()
    (input_dir / "a.csv").write_text("ch0\n1\n2\n", encoding="utf-8")
    calls = []

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

    def fake_progress_track(items, description, console=None, enabled=True, total=None):
        materialized = list(items)
        calls.append((description, enabled, len(materialized)))
        yield from materialized

    monkeypatch.setattr(factory_module, "progress_track", fake_progress_track)
    monkeypatch.setattr(
        factory_module, "_build_calculator", lambda *args, **kwargs: FakeCalculator()
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
    assert calls == [("计算产测指标...", True, 1)]


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
    assert seen == {"show_progress": True}


def test_evaluate_command_enables_progress(monkeypatch, tmp_path: Path):
    from health_tools.models.rules import EvaluateRule

    seen = {}

    class FakeEvaluator:
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
    assert seen == {"show_progress": True}


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
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False: calls.append(
            ("plot", show_progress, acc_mode, save_to_source)
        )
        or [],
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
    assert calls == [("reorganize", True), ("plot", True, "axis", True), ("accuracy", True)]


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
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False: calls.append(
            acc_mode
        )
        or [],
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
    monkeypatch.setattr("health_tools.commands.offline._filter_input_files", lambda *args: None)
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    output_dir = tmp_path / "output"
    exe_path = tmp_path / "tools" / "gh3300" / "exclusive" / "v1" / "TEE_Algorithm.exe"
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("", encoding="utf-8")

    class FakeRunner(_FakeOfflineRunnerPreview):
        def __init__(self, chip, version=None, **kwargs):
            self.version = version

        def run(self, input_path, output_path, timeout=300, settle_timeout=10):
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
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False: [],
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
    assert ("run", "v1", output_dir / "v1") in calls


def test_offline_default_timeout_scales_after_fifty_files(monkeypatch, tmp_path: Path):
    import pandas as pd

    calls = []
    monkeypatch.setattr("health_tools.commands.offline._filter_input_files", lambda *args: None)
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

        def run(self, input_path, output_path, timeout=300, settle_timeout=10):
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
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False: [],
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
    monkeypatch.setattr("health_tools.commands.offline._filter_input_files", lambda *args: None)
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

        def run(self, input_path, output_path, timeout=300, settle_timeout=10):
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
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False: [],
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
    monkeypatch.setattr("health_tools.commands.offline._filter_input_files", lambda *args: None)
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    output_dir = tmp_path / "output"
    exe_path = tmp_path / "tools" / "gh3300" / "exclusive" / "default_v1" / "TEE_Algorithm.exe"
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("", encoding="utf-8")

    class FakeRunner(_FakeOfflineRunnerPreview):
        def __init__(self, chip, version=None, **kwargs):
            self.version = version

        def run(self, input_path, output_path, timeout=300, settle_timeout=10):
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
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False: [],
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
    assert ("run", None, output_dir / "default_v1") in calls


def test_offline_versions_runs_each_version_and_writes_combined_accuracy(
    monkeypatch, tmp_path: Path
):
    import pandas as pd

    calls = []
    monkeypatch.setattr("health_tools.commands.offline._filter_input_files", lambda *args: None)
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

        def run(self, input_path, output_path, timeout=300, settle_timeout=10):
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
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False: [],
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
    assert ("run", "v1", output_dir / "v1") in calls
    assert ("run", "v2", output_dir / "v2") in calls
    combined = pd.read_csv(output_dir / "accuracy_report_all_versions.csv")
    assert list(combined["version"]) == ["v1", "v2"]
    assert list(combined["file"]) == ["TOTAL", "TOTAL"]


def test_offline_all_versions_expands_config_versions(monkeypatch, tmp_path: Path):
    import pandas as pd

    calls = []
    monkeypatch.setattr("health_tools.commands.offline._filter_input_files", lambda *args: None)
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

        def run(self, input_path, output_path, timeout=300, settle_timeout=10):
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
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False: [],
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
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False: [],
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
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False: [],
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
        lambda self, result_dir, save_dir=None, show_progress=False, acc_mode="axis", save_to_source=False: [],
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
