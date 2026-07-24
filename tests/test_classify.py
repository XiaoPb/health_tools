"""classify 分类逻辑单元测试。"""

from pathlib import Path

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
