"""classify 分类逻辑单元测试。"""

from pathlib import Path

from health_tools.api import ClassifyRequest, ExecutionContext, run_classify
from health_tools.core.classifier import DataClassifier
from health_tools.models.rules import ClassifyRule


def _write_csv(path: Path, rows: int = 200) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["time,value\n"] + [f"{i},{i}\n" for i in range(rows)]
    path.write_text("".join(lines), encoding="utf-8")
    return path


def test_path_regex_named_groups_extract_variables(tmp_path: Path):
    """路径正则的命名捕获组应提取为可在 target 中引用的变量。"""
    source = tmp_path / "input"
    csv_path = _write_csv(source / "asian" / "zhangsan" / "sit" / "data_001.csv")

    rule = ClassifyRule(
        path={
            "regex": r"(?P<race>\w+)/(?P<name>\w+)/(?P<scene>\w+)/[^/]+\.csv",
        },
        structure={"placeholder": ""},
        rules=[{"target": "{scene}"}],
    )
    classifier = DataClassifier(rule)

    target_dir = classifier.classify(csv_path, tmp_path / "output", input_root=source)

    assert target_dir is not None
    assert target_dir == tmp_path / "output" / "sit"


def test_path_regex_positional_groups_with_fields(tmp_path: Path):
    """路径正则的位置捕获组配合 fields 列表应按顺序提取变量。"""
    source = tmp_path / "input"
    csv_path = _write_csv(source / "asian" / "zhangsan" / "sit" / "data_001.csv")

    rule = ClassifyRule(
        path={
            "regex": r"(\w+)/(\w+)/(\w+)/[^/]+\.csv",
            "fields": ["race", "name", "scene"],
        },
        structure={"placeholder": ""},
        rules=[{"target": "{scene}/{race}"}],
    )
    classifier = DataClassifier(rule)

    target_dir = classifier.classify(csv_path, tmp_path / "output", input_root=source)

    assert target_dir is not None
    assert target_dir == tmp_path / "output" / "sit" / "asian"


def test_classify_without_input_root_skips_path_parsing(tmp_path: Path):
    """不传 input_root 时路径正则不生效，保持向后兼容。"""
    csv_path = _write_csv(tmp_path / "data_001.csv")

    rule = ClassifyRule(
        path={"regex": r"(?P<scene>\w+)/[^/]+\.csv"},
        structure={"placeholder": ""},
        rules=[{"target": "{scene}"}],
    )
    classifier = DataClassifier(rule)

    # 无 input_root，path 变量未提取 → {scene} 无法解析 → 返回 None
    target_dir = classifier.classify(csv_path, tmp_path / "output")
    assert target_dir is None


def test_classify_path_regex_no_match_falls_back_empty(tmp_path: Path):
    """传了 input_root 但 path 正则不匹配时，path 字段为空、target 无法解析返回 None。"""
    source = tmp_path / "input"
    # 路径只有两层，正则要求三层，不匹配
    csv_path = _write_csv(source / "asian" / "data_001.csv")

    rule = ClassifyRule(
        path={"regex": r"(?P<race>\w+)/(?P<name>\w+)/(?P<scene>\w+)/[^/]+\.csv"},
        structure={"placeholder": ""},
        rules=[{"target": "{scene}"}],
    )
    classifier = DataClassifier(rule)

    target_dir = classifier.classify(csv_path, tmp_path / "output", input_root=source)

    # 正则不匹配 → path 字段为空 → {scene} 残留 → 返回 None
    assert target_dir is None
    assert classifier.get_last_values()["path"] == {}


def test_resolve_filename_without_rename_preserves_original(tmp_path: Path):
    """无 rename 字段时保持原文件名（向后兼容）。"""
    csv_path = _write_csv(tmp_path / "data_001.csv")

    rule = ClassifyRule(structure={"placeholder": ""}, rules=[{"target": "out"}])
    classifier = DataClassifier(rule)
    classifier.classify(csv_path, tmp_path / "output")

    assert classifier.resolve_filename(csv_path) == "data_001.csv"


def test_resolve_filename_applies_template_with_path_vars(tmp_path: Path):
    """rename 模板应组合路径变量与原文件名。"""
    source = tmp_path / "input"
    csv_path = _write_csv(source / "asian" / "zhangsan" / "sit" / "data_001.csv")

    rule = ClassifyRule(
        path={"regex": r"(?P<race>\w+)/(?P<name>\w+)/(?P<scene>\w+)/[^/]+\.csv"},
        rename="{race}_{name}_{scene}_{filename}",
        structure={"placeholder": ""},
        rules=[{"target": "{scene}"}],
    )
    classifier = DataClassifier(rule)
    classifier.classify(csv_path, tmp_path / "output", input_root=source)

    assert classifier.resolve_filename(csv_path) == "asian_zhangsan_sit_data_001.csv"


def test_resolve_filename_supports_stem_placeholder(tmp_path: Path):
    """{stem} 占位符应替换为不含扩展名的文件名。"""
    source = tmp_path / "input"
    csv_path = _write_csv(source / "asian" / "zhangsan" / "sit" / "data_001.csv")

    rule = ClassifyRule(
        path={"regex": r"(?P<race>\w+)/\w+/\w+/[^/]+\.csv"},
        rename="{race}_{stem}.csv",
        structure={"placeholder": ""},
        rules=[{"target": "{race}"}],
    )
    classifier = DataClassifier(rule)
    classifier.classify(csv_path, tmp_path / "output", input_root=source)

    assert classifier.resolve_filename(csv_path) == "asian_data_001.csv"


def test_check_filters_passes_when_no_filters(tmp_path: Path):
    """未配置 filters 时所有文件都通过。"""
    csv_path = _write_csv(tmp_path / "data.csv", rows=10)
    rule = ClassifyRule(structure={"placeholder": ""}, rules=[{"target": "out"}])
    classifier = DataClassifier(rule)

    assert classifier.check_filters(csv_path, min_rows=0, min_size_kb=0.0) is None


def test_check_filters_skips_small_row_count(tmp_path: Path):
    """行数不足时返回跳过原因。"""
    csv_path = _write_csv(tmp_path / "data.csv", rows=50)
    rule = ClassifyRule(structure={"placeholder": ""}, rules=[{"target": "out"}])
    classifier = DataClassifier(rule)

    reason = classifier.check_filters(csv_path, min_rows=100, min_size_kb=0.0)
    assert reason is not None
    assert "行数不足" in reason
    assert "50" in reason
    assert "100" in reason


def test_check_filters_skips_small_file_size(tmp_path: Path):
    """文件大小不足时返回跳过原因。"""
    csv_path = _write_csv(tmp_path / "data.csv", rows=5)
    rule = ClassifyRule(structure={"placeholder": ""}, rules=[{"target": "out"}])
    classifier = DataClassifier(rule)

    reason = classifier.check_filters(csv_path, min_rows=0, min_size_kb=1024.0)
    assert reason is not None
    assert "文件过小" in reason


def test_check_filters_caches_dataframe_for_extract(tmp_path: Path):
    """通过行数检查后，CSV 应被缓存供 _extract_values 复用，不重复读取。"""
    csv_path = _write_csv(tmp_path / "data.csv", rows=200)
    rule = ClassifyRule(structure={"placeholder": ""}, rules=[{"target": "out"}])
    classifier = DataClassifier(rule)

    classifier.check_filters(csv_path, min_rows=100, min_size_kb=0.0)
    assert classifier._cached_file == csv_path
    assert classifier._cached_df is not None
    assert len(classifier._cached_df) == 200


def test_check_filters_handles_read_failure(tmp_path: Path):
    """CSV 读取失败时返回失败原因而非抛出异常。"""
    csv_path = tmp_path / "missing.csv"  # 文件不存在，触发读取异常
    rule = ClassifyRule(structure={"placeholder": ""}, rules=[{"target": "out"}])
    classifier = DataClassifier(rule)

    reason = classifier.check_filters(csv_path, min_rows=100, min_size_kb=0.0)
    assert reason is not None
    assert "行数不足" not in reason
    assert "文件过小" not in reason


def _write_rule(tmp_path: Path, source: str) -> Path:
    rule_path = tmp_path / "classify" / "scenario.yaml"
    rule_path.parent.mkdir(parents=True, exist_ok=True)
    rule_path.write_text(source, encoding="utf-8")
    return rule_path


SCENARIO_RULE = r"""version: "1.0"
description: 人种/姓名/场景 路径重命名示例
path:
  regex: '(?P<race>\w+)/(?P<name>\w+)/(?P<scene>\w+)/[^/]+\.csv'
filters:
  min_rows: 100
  min_size_kb: 0
structure:
  placeholder: ""
rules:
  - target: '{scene}'
rename: '{race}_{name}_{scene}_{filename}'
default: unclassified
"""


def test_run_classify_path_rename_and_filters_user_scenario(tmp_path: Path):
    """端到端：{race}/{name}/{scene}/*.csv -> {scene}/{race}_{name}_{scene}_*.csv。

    小文件（行数不足）被跳过，合规文件按模板重命名并复制到目标目录。
    """
    source = tmp_path / "input"
    _write_csv(source / "asian" / "zhangsan" / "sit" / "data_001.csv", rows=200)
    _write_csv(source / "asian" / "zhangsan" / "sit" / "data_002.csv", rows=200)
    _write_csv(source / "caucasian" / "lisi" / "walk" / "data_003.csv", rows=200)
    # 行数不足的小文件应被跳过
    _write_csv(source / "asian" / "zhangsan" / "sit" / "small.csv", rows=10)

    rule_path = _write_rule(tmp_path, SCENARIO_RULE)
    output = tmp_path / "output"

    result = run_classify(
        ClassifyRequest(source, output, rule_file=str(rule_path)),
        context=ExecutionContext(),
    )

    assert result.ok_count == 3
    assert result.skip_count == 1

    assert (output / "sit" / "asian_zhangsan_sit_data_001.csv").exists()
    assert (output / "sit" / "asian_zhangsan_sit_data_002.csv").exists()
    assert (output / "walk" / "caucasian_lisi_walk_data_003.csv").exists()
    assert not list(output.rglob("asian_zhangsan_sit_small*.csv"))

    skipped = [item for item in result.items if item.status.value == "SKIP"]
    assert len(skipped) == 1
    assert "行数不足" in skipped[0].reason


def test_run_classify_min_rows_cli_overrides_rule(tmp_path: Path):
    """CLI --min-rows 覆盖规则中的 min_rows。"""
    source = tmp_path / "input"
    _write_csv(source / "asian" / "zhangsan" / "sit" / "data_001.csv", rows=150)
    rule_path = _write_rule(tmp_path, SCENARIO_RULE)
    output = tmp_path / "output"

    # 规则要求 100 行，文件有 150 行（通过）；CLI 覆盖为 200 行（不通过）
    result = run_classify(
        ClassifyRequest(source, output, rule_file=str(rule_path), min_rows=200),
        context=ExecutionContext(),
    )

    assert result.ok_count == 0
    assert result.skip_count == 1


SIZE_FILTER_RULE = r"""version: "1.0"
description: 按文件大小过滤
path:
  regex: '(?P<race>\w+)/[^/]+\.csv'
filters:
  min_rows: 0
  min_size_kb: 5
structure:
  placeholder: ""
rules:
  - target: '{race}'
default: unclassified
"""


def test_run_classify_min_size_kb_rule_filters_small_file(tmp_path: Path):
    """规则 filters.min_size_kb 过滤小文件，跳过原因含"文件过小"。"""
    source = tmp_path / "input"
    # 200 行 CSV 约 1.4KB，小于规则阈值 5KB
    _write_csv(source / "asian" / "data_001.csv", rows=200)
    rule_path = _write_rule(tmp_path, SIZE_FILTER_RULE)
    output = tmp_path / "output"

    result = run_classify(
        ClassifyRequest(source, output, rule_file=str(rule_path)),
        context=ExecutionContext(),
    )

    assert result.ok_count == 0
    assert result.skip_count == 1
    skipped = [item for item in result.items if item.status.value == "SKIP"]
    assert len(skipped) == 1
    assert "文件过小" in skipped[0].reason


def test_run_classify_dry_run_writes_no_files(tmp_path: Path):
    """dry-run 下不写入任何文件，但报告计划目标路径。"""
    source = tmp_path / "input"
    _write_csv(source / "asian" / "zhangsan" / "sit" / "data_001.csv", rows=200)
    rule_path = _write_rule(tmp_path, SCENARIO_RULE)
    output = tmp_path / "output"

    result = run_classify(
        ClassifyRequest(source, output, rule_file=str(rule_path), dry_run=True),
        context=ExecutionContext(),
    )

    assert result.ok_count == 0
    assert result.skip_count == 1
    # 没有任何文件被写入
    assert not any(output.rglob("*.csv"))

    item = result.items[0]
    assert "预览模式" in item.reason
    # 计划目标路径仍记录在 output 字段
    assert "asian_zhangsan_sit_data_001.csv" in item.output
