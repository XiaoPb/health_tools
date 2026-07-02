from pathlib import Path

from click.testing import CliRunner

from health_tools.cli import main


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
        lambda self, result_dir, save_dir=None, show_progress=False: calls.append(
            ("plot", show_progress)
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
    assert calls == [("reorganize", True), ("plot", True), ("accuracy", True)]
