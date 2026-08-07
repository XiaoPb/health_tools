import importlib.util
from pathlib import Path

import pytest

from health_tools.api import (
    ConvertRequest,
    ExecutionContext,
    ItemStatus,
    OperationCancelled,
    ParseRequest,
    RequestValidationError,
    SplitRequest,
    ValidateRequest,
    run_convert,
    run_parse,
    run_split,
    run_validate,
)
from health_tools.cli import PRIMARY_COMMANDS


def _write_parse_rule(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "version: '1.0'\n" "regex: 'DATA:(\\d+),(\\d+)'\n" "columns: [red, ir]\n",
        encoding="utf-8",
    )
    return path


def test_run_parse_reports_progress_and_writes_csv(tmp_path: Path):
    source = tmp_path / "sample.log"
    source.write_text("ignore\nDATA:1,2\nDATA:3,4\n", encoding="utf-8")
    rule = _write_parse_rule(tmp_path / "parse" / "sample.yaml")
    output = tmp_path / "sample.csv"
    events = []

    result = run_parse(
        ParseRequest(source, output, rule_file=str(rule)),
        context=ExecutionContext(on_progress=events.append),
    )

    assert result.ok_count == 1
    assert result.artifacts == (output,)
    assert output.read_text(encoding="utf-8").splitlines() == ["red,ir", "1,2", "3,4"]
    assert [(event.completed, event.total) for event in events] == [(0, 1), (1, 1)]


def test_run_parse_cancel_keeps_completed_output_and_partial_result(tmp_path: Path):
    source_dir = tmp_path / "logs"
    source_dir.mkdir()
    for name in ("a.log", "b.log"):
        (source_dir / name).write_text("DATA:1,2\n", encoding="utf-8")
    rule = _write_parse_rule(tmp_path / "parse" / "sample.yaml")
    cancelled = False

    def on_progress(event):
        nonlocal cancelled
        if event.completed == 1:
            cancelled = True

    context = ExecutionContext(on_progress=on_progress, is_cancelled=lambda: cancelled)
    with pytest.raises(OperationCancelled) as exc_info:
        run_parse(
            ParseRequest(source_dir, tmp_path / "output", rule_file=str(rule)),
            context=context,
        )

    partial = exc_info.value.partial_result
    assert partial.ok_count == 1
    assert len(list((tmp_path / "output").glob("*.csv"))) == 1


def test_run_convert_and_split_return_artifacts(tmp_path: Path):
    source = tmp_path / "source.csv"
    source.write_text("source\n1\n2\n3\n", encoding="utf-8")
    rule = tmp_path / "convert" / "simple.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\ncolumn_mapping:\n  source: target\n",
        encoding="utf-8",
    )
    converted_path = tmp_path / "converted.csv"

    converted = run_convert(ConvertRequest(source, converted_path, rule_file=str(rule)))
    split = run_split(SplitRequest(converted_path, tmp_path / "split", by_size=2))

    assert converted.ok_count == 1
    assert converted.artifacts == (converted_path,)
    assert split.ok_count == 1
    assert len(split.artifacts) == 2
    assert all(path.exists() for path in split.artifacts)


def test_run_validate_returns_errors_without_raising(tmp_path: Path):
    valid_rule = _write_parse_rule(tmp_path / "parse" / "valid.yaml")
    invalid_rule = tmp_path / "parse" / "invalid.yaml"
    invalid_rule.write_text("version: '1.0'\ncolumns: [x]\n", encoding="utf-8")

    assert run_validate(ValidateRequest(valid_rule)).valid is True
    invalid = run_validate(ValidateRequest(invalid_rule))
    assert invalid.valid is False
    assert "解析规则缺少 'regex' 字段" in invalid.errors


def test_missing_input_raises_public_validation_error(tmp_path: Path):
    with pytest.raises(RequestValidationError, match="输入路径不存在"):
        run_split(SplitRequest(tmp_path / "missing.csv", tmp_path / "output"))


def test_all_cli_commands_delegate_to_public_api():
    commands_dir = Path(__file__).parents[1] / "src" / "health_tools" / "commands"
    for command in PRIMARY_COMMANDS:
        source = (commands_dir / f"{command}.py").read_text(encoding="utf-8")
        assert "from health_tools.api import" in source, command


def test_distribution_has_no_ui_or_streamlit_dependency():
    root = Path(__file__).parents[1]
    source_text = "\n".join(
        path.read_text(encoding="utf-8") for path in (root / "src" / "health_tools").rglob("*.py")
    )
    project = (root / "pyproject.toml").read_text(encoding="utf-8")

    assert importlib.util.find_spec("health_tools.ui") is None
    assert "streamlit" not in source_text.lower()
    assert "streamlit" not in project.lower()
    assert len(PRIMARY_COMMANDS) == 14


def test_importing_public_api_does_not_load_terminal_frameworks():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, health_tools.api; "
            "assert 'click' not in sys.modules; assert 'rich' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_rule_api_calls_do_not_load_terminal_frameworks():
    import subprocess
    import sys

    script = """
import sys
from health_tools.api import (
    RequestValidationError,
    RuleListRequest,
    RuleSaveRequest,
    RuleType,
    run_list_rules,
    run_save_rule,
)
run_list_rules(RuleListRequest())
try:
    run_save_rule(RuleSaveRequest(RuleType.PARSE, "__api_import_check__.yaml", "[]"))
except RequestValidationError:
    pass
assert "click" not in sys.modules
assert "rich" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_offline_runner_terminates_cancellable_process(monkeypatch, tmp_path: Path):
    from health_tools.core import offline

    state = {"terminated": False}

    class FakeProcess:
        def terminate(self):
            state["terminated"] = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            raise AssertionError("正常终止后不应 kill")

        def poll(self):
            return None

    runner = offline.OfflineRunner.__new__(offline.OfflineRunner)
    runner.exe_path = tmp_path / offline.EXE_NAME
    runner.tool_dir = tmp_path
    runner._build_command = lambda input_dir, output_dir: "fake command"
    monkeypatch.setattr(offline.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(offline, "count_supported_csv_files", lambda path: 1)

    with pytest.raises(InterruptedError, match="已取消"):
        runner.run(
            tmp_path / "input",
            tmp_path / "output",
            is_cancelled=lambda: True,
        )

    assert state["terminated"] is True


def test_run_convert_single_file_with_rule_split_writes_chunks(tmp_path: Path):
    source = tmp_path / "source.csv"
    source.write_text("frame,value\n0,1\n1,2\n2,3\n", encoding="utf-8")
    rule = tmp_path / "convert" / "split.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  frame: FRAME_ID\n  value: VALUE\n"
        "split:\n  by_size: 2\n",
        encoding="utf-8",
    )
    output = tmp_path / "out.csv"

    result = run_convert(ConvertRequest(source, output, rule_file=str(rule)))

    assert result.ok_count == 1
    assert len(result.artifacts) == 2
    assert (tmp_path / "out_1.csv").exists()
    assert (tmp_path / "out_2.csv").exists()


def test_run_convert_merge_with_rule_split_writes_chunks(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.csv").write_text("frame,value\n0,1\n1,2\n", encoding="utf-8")
    (input_dir / "b.csv").write_text("frame,value\n2,3\n", encoding="utf-8")
    rule = tmp_path / "convert" / "split.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  frame: FRAME_ID\n  value: VALUE\n"
        "split:\n  by_size: 2\n",
        encoding="utf-8",
    )
    output = tmp_path / "merged.csv"

    result = run_convert(ConvertRequest(input_dir, output, rule_file=str(rule), merge=True))

    assert result.ok_count == 2
    assert len(result.artifacts) == 2
    assert (tmp_path / "merged_1.csv").exists()
    assert (tmp_path / "merged_2.csv").exists()


def test_run_convert_directory_with_rule_split_keeps_relative_paths(tmp_path: Path):
    input_dir = tmp_path / "input"
    (input_dir / "sub").mkdir(parents=True)
    (input_dir / "sub" / "a.csv").write_text("frame,value\n0,1\n1,2\n2,3\n", encoding="utf-8")
    rule = tmp_path / "convert" / "split.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  frame: FRAME_ID\n  value: VALUE\n"
        "split:\n  by_size: 2\n",
        encoding="utf-8",
    )
    output = tmp_path / "output"

    result = run_convert(ConvertRequest(input_dir, output, rule_file=str(rule)))

    assert result.ok_count == 1
    assert len(result.artifacts) == 2
    assert (output / "sub" / "a_1.csv").exists()
    assert (output / "sub" / "a_2.csv").exists()


def test_run_convert_single_file_with_missing_split_column_is_fail(tmp_path: Path):
    source = tmp_path / "source.csv"
    source.write_text("frame,value\n0,1\n1,2\n", encoding="utf-8")
    rule = tmp_path / "convert" / "bad_split.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  frame: FRAME_ID\n  value: VALUE\n"
        "split:\n  by_column: MISSING\n",
        encoding="utf-8",
    )
    output = tmp_path / "out.csv"

    result = run_convert(ConvertRequest(source, output, rule_file=str(rule)))

    assert result.fail_count == 1
    assert result.items[0].reason == "列缺失"


def test_run_convert_merge_with_missing_split_column_is_fail(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.csv").write_text("frame,value\n0,1\n1,2\n", encoding="utf-8")
    (input_dir / "b.csv").write_text("frame,value\n2,3\n", encoding="utf-8")
    rule = tmp_path / "convert" / "bad_split.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  frame: FRAME_ID\n  value: VALUE\n"
        "split:\n  by_column: MISSING\n",
        encoding="utf-8",
    )
    output = tmp_path / "merged.csv"

    result = run_convert(ConvertRequest(input_dir, output, rule_file=str(rule), merge=True))

    assert result.ok_count == 2
    assert result.fail_count == 1
    assert result.items[-1].reason == "列缺失"


def test_run_convert_merge_with_header_only_inputs_skips(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.csv").write_text("frame,value\n", encoding="utf-8")
    (input_dir / "b.csv").write_text("frame,value\n", encoding="utf-8")
    rule = tmp_path / "convert" / "split.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  frame: FRAME_ID\n  value: VALUE\n"
        "split:\n  by_size: 2\n",
        encoding="utf-8",
    )
    output = tmp_path / "merged.csv"

    result = run_convert(ConvertRequest(input_dir, output, rule_file=str(rule), merge=True))

    assert result.skip_count == 1
    assert len(result.artifacts) == 0


def test_run_convert_merge_rule_split_precedes_cli_split(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.csv").write_text("frame,value\n0,1\n1,2\n", encoding="utf-8")
    (input_dir / "b.csv").write_text("frame,value\n2,3\n3,4\n", encoding="utf-8")
    rule = tmp_path / "convert" / "split.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  frame: FRAME_ID\n  value: VALUE\n"
        "split:\n  by_size: 2\n",
        encoding="utf-8",
    )
    output = tmp_path / "merged.csv"

    result = run_convert(
        ConvertRequest(input_dir, output, rule_file=str(rule), merge=True, split=4)
    )

    assert len(result.artifacts) == 2
    assert (tmp_path / "merged_1.csv").exists()
    assert (tmp_path / "merged_2.csv").exists()


def test_run_convert_directory_with_missing_split_column_is_fail(tmp_path: Path):
    input_dir = tmp_path / "input"
    (input_dir / "sub").mkdir(parents=True)
    (input_dir / "sub" / "a.csv").write_text("frame,value\n0,1\n1,2\n", encoding="utf-8")
    rule = tmp_path / "convert" / "bad_split.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  frame: FRAME_ID\n  value: VALUE\n"
        "split:\n  by_column: MISSING\n",
        encoding="utf-8",
    )
    output = tmp_path / "output"

    result = run_convert(ConvertRequest(input_dir, output, rule_file=str(rule)))

    assert result.fail_count == 1
    assert result.items[0].reason == "列缺失"


_CLASSIFY_RULE = (
    "version: '1.0'\n"
    "column_mapping:\n  frame: FRAME_ID\n  value: VALUE\n"
    "classify:\n"
    "  default: unclassified\n"
    "  extract:\n"
    "    - name: val_median\n"
    "      function: calculate_median\n"
    "      params:\n"
    "        column: VALUE\n"
    "  classify:\n"
    "    - target: high\n"
    "      condition: 'val_median >= 3'\n"
    "    - target: low\n"
    "      condition: 'val_median < 3'\n"
)


def test_run_convert_single_file_with_classify_writes_category_dir(tmp_path: Path):
    source = tmp_path / "source.csv"
    source.write_text("frame,value\n0,1\n1,2\n", encoding="utf-8")
    rule = tmp_path / "convert" / "classify.yaml"
    rule.parent.mkdir()
    rule.write_text(_CLASSIFY_RULE, encoding="utf-8")
    output = tmp_path / "out.csv"

    result = run_convert(ConvertRequest(source, output, rule_file=str(rule)))

    assert result.ok_count == 1
    assert result.items[0].category == "low"
    assert len(result.artifacts) == 1
    assert result.artifacts[0] == tmp_path / "low" / "out.csv"
    assert (tmp_path / "low" / "out.csv").exists()


def test_run_convert_directory_with_classify_preserves_subdirs(tmp_path: Path):
    input_dir = tmp_path / "input"
    (input_dir / "sub").mkdir(parents=True)
    (input_dir / "sub" / "a.csv").write_text("frame,value\n0,5\n1,6\n", encoding="utf-8")
    rule = tmp_path / "convert" / "classify.yaml"
    rule.parent.mkdir()
    rule.write_text(_CLASSIFY_RULE, encoding="utf-8")
    output = tmp_path / "output"

    result = run_convert(ConvertRequest(input_dir, output, rule_file=str(rule)))

    assert result.ok_count == 1
    assert (output / "sub" / "high" / "a.csv").exists()


def test_run_convert_merge_with_classify_writes_category_dir(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.csv").write_text("frame,value\n0,1\n1,2\n", encoding="utf-8")
    (input_dir / "b.csv").write_text("frame,value\n2,3\n", encoding="utf-8")
    rule = tmp_path / "convert" / "classify.yaml"
    rule.parent.mkdir()
    rule.write_text(_CLASSIFY_RULE, encoding="utf-8")
    output = tmp_path / "merged.csv"

    result = run_convert(ConvertRequest(input_dir, output, rule_file=str(rule), merge=True))

    assert (tmp_path / "low" / "merged.csv").exists()
    assert len(result.artifacts) == 1
    assert result.artifacts[0] == tmp_path / "low" / "merged.csv"


def test_run_convert_classify_no_match_uses_default(tmp_path: Path):
    source = tmp_path / "source.csv"
    source.write_text("frame,value\n0,1\n1,2\n", encoding="utf-8")
    rule = tmp_path / "convert" / "classify.yaml"
    rule.parent.mkdir()
    rule.write_text(
        _CLASSIFY_RULE.replace("'val_median >= 3'", "'val_median >= 999'").replace(
            "'val_median < 3'", "'val_median < 0'"
        ),
        encoding="utf-8",
    )
    output = tmp_path / "out.csv"

    result = run_convert(ConvertRequest(source, output, rule_file=str(rule)))

    assert result.ok_count == 1
    assert result.items[0].category == "unclassified"
    assert (tmp_path / "unclassified" / "out.csv").exists()


def test_run_convert_split_with_classify_classifies_each_chunk(tmp_path: Path):
    source = tmp_path / "source.csv"
    source.write_text("frame,value\n0,1\n1,2\n2,3\n3,4\n", encoding="utf-8")
    rule = tmp_path / "convert" / "split_classify.yaml"
    rule.parent.mkdir()
    rule.write_text(
        _CLASSIFY_RULE.replace(
            "classify:",
            "split:\n  by_size: 2\nclassify:",
            1,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "out.csv"

    result = run_convert(ConvertRequest(source, output, rule_file=str(rule)))

    assert result.ok_count == 1
    assert result.items[0].category == ""
    assert len(result.artifacts) == 2
    assert (tmp_path / "low" / "out_1.csv").exists()
    assert (tmp_path / "high" / "out_2.csv").exists()


def test_run_convert_classify_filename_reclassification(tmp_path: Path):
    source = tmp_path / "sit_session.csv"
    source.write_text("value\n1\n2\n", encoding="utf-8")
    rule = tmp_path / "convert" / "classify_filename.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  value: VALUE\n"
        "classify:\n"
        "  filename:\n"
        "    regex: '(?P<motion>sit|walk).*\\.csv'\n"
        "    fields: [motion]\n"
        "  structure:\n"
        "    sit: ''\n"
        "    walk: ''\n"
        "  rules:\n"
        "    - target: '{motion}'\n"
        "  default: unclassified\n",
        encoding="utf-8",
    )
    output = tmp_path / "out.csv"

    result = run_convert(ConvertRequest(source, output, rule_file=str(rule)))

    assert result.ok_count == 1
    assert (tmp_path / "sit" / "out.csv").exists()


def test_run_convert_classify_rename_output_filename(tmp_path: Path):
    source = tmp_path / "20260808_gh3036_sit_25Hz.csv"
    source.write_text("value\n1\n2\n", encoding="utf-8")
    rule = tmp_path / "convert" / "classify_rename.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  value: VALUE\n"
        "classify:\n"
        "  filename:\n"
        "    regex: '(\\d{8})_(\\w+)_(\\w+)_(\\d+Hz)'\n"
        "    fields: [date, chip, motion, sample_rate]\n"
        "  structure:\n"
        "    sit: ''\n"
        "    walk: ''\n"
        "  rules:\n"
        "    - target: '{motion}'\n"
        "  rename: '{date}_{motion}_{stem}.csv'\n"
        "  default: unclassified\n",
        encoding="utf-8",
    )
    output = tmp_path / "out.csv"

    result = run_convert(ConvertRequest(source, output, rule_file=str(rule)))

    renamed = "20260808_sit_20260808_gh3036_sit_25Hz.csv"
    assert result.items[0].category == "sit"
    assert (tmp_path / "sit" / renamed).exists()


def test_run_convert_directory_classify_path_regex(tmp_path: Path):
    input_dir = tmp_path / "input"
    (input_dir / "sit").mkdir(parents=True)
    (input_dir / "sit" / "a.csv").write_text("value\n1\n2\n", encoding="utf-8")
    rule = tmp_path / "convert" / "classify_path.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  value: VALUE\n"
        "classify:\n"
        "  path:\n"
        "    regex: '(?P<scene>\\w+)/[^/]+\\.csv'\n"
        "  structure:\n"
        "    sit: ''\n"
        "  rules:\n"
        "    - target: '{scene}'\n"
        "  default: unclassified\n",
        encoding="utf-8",
    )
    output = tmp_path / "output"

    result = run_convert(ConvertRequest(input_dir, output, rule_file=str(rule)))

    assert result.ok_count == 1
    assert (output / "sit" / "sit" / "a.csv").exists()


def test_run_convert_split_with_classify_and_rename_appends_index(tmp_path: Path):
    source = tmp_path / "20260808_gh3036_sit_25Hz.csv"
    source.write_text("frame,value\n0,1\n1,2\n2,3\n3,4\n", encoding="utf-8")
    rule = tmp_path / "convert" / "split_classify_rename.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  frame: FRAME_ID\n  value: VALUE\n"
        "split:\n  by_size: 2\n"
        "classify:\n"
        "  filename:\n"
        "    regex: '([0-9]{8})_([a-z0-9]+)_([a-z]+)_([0-9]+Hz)'\n"
        "    fields: [date, chip, motion, sample_rate]\n"
        "  structure:\n"
        "    sit: ''\n"
        "    walk: ''\n"
        "  rules:\n"
        "    - target: '{motion}'\n"
        "  rename: '{date}_{motion}_{stem}.csv'\n"
        "  default: unclassified\n",
        encoding="utf-8",
    )
    output = tmp_path / "out.csv"

    result = run_convert(ConvertRequest(source, output, rule_file=str(rule)))

    renamed = "20260808_sit_20260808_gh3036_sit_25Hz"
    assert result.ok_count == 1
    assert len(result.artifacts) == 2
    assert (tmp_path / "sit" / f"{renamed}_1.csv").exists()
    assert (tmp_path / "sit" / f"{renamed}_2.csv").exists()


def test_run_convert_directory_with_classify_rename(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "20260808_gh3036_sit_25Hz.csv").write_text("value\n1\n2\n", encoding="utf-8")
    rule = tmp_path / "convert" / "classify_dir_rename.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  value: VALUE\n"
        "classify:\n"
        "  filename:\n"
        "    regex: '([0-9]{8})_([a-z0-9]+)_([a-z]+)_([0-9]+Hz)'\n"
        "    fields: [date, chip, motion, sample_rate]\n"
        "  structure:\n"
        "    sit: ''\n"
        "    walk: ''\n"
        "  rules:\n"
        "    - target: '{motion}'\n"
        "  rename: '{date}_{motion}_{stem}.csv'\n"
        "  default: unclassified\n",
        encoding="utf-8",
    )
    output = tmp_path / "output"

    result = run_convert(ConvertRequest(input_dir, output, rule_file=str(rule)))

    assert result.ok_count == 1
    assert (output / "sit" / "20260808_sit_20260808_gh3036_sit_25Hz.csv").exists()


def test_run_convert_classify_invalid_filename_regex_is_fail(tmp_path: Path):
    source = tmp_path / "source.csv"
    source.write_text("value\n1\n2\n", encoding="utf-8")
    rule = tmp_path / "convert" / "classify_bad_regex.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  value: VALUE\n"
        "classify:\n"
        "  filename:\n"
        "    regex: '('\n"
        "    fields: [motion]\n"
        "  default: unclassified\n",
        encoding="utf-8",
    )
    output = tmp_path / "out.csv"

    result = run_convert(ConvertRequest(source, output, rule_file=str(rule)))

    assert result.ok_count == 0
    assert result.items[0].status == ItemStatus.FAIL


def test_run_convert_merge_classify_invalid_filename_regex_is_fail(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.csv").write_text("value\n1\n2\n", encoding="utf-8")
    rule = tmp_path / "convert" / "classify_bad_regex.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  value: VALUE\n"
        "classify:\n"
        "  filename:\n"
        "    regex: '('\n"
        "    fields: [motion]\n"
        "  default: unclassified\n",
        encoding="utf-8",
    )
    output = tmp_path / "merged.csv"

    result = run_convert(ConvertRequest(input_dir, output, rule_file=str(rule), merge=True))

    assert result.fail_count == 1
    assert any(item.status == ItemStatus.FAIL for item in result.items)
