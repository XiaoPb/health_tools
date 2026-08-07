from pathlib import Path

import pytest

from health_tools.api import (
    RequestValidationError,
    RuleListRequest,
    RuleLoadError,
    RuleReadRequest,
    RuleSaveRequest,
    RuleSource,
    RuleType,
    run_list_rules,
    run_read_rule,
    run_save_rule,
)
from health_tools.api import rule_operations
from health_tools.rules.loader import RuleLoader
from health_tools.rules.validator import RuleValidator

PARSE_SOURCE = """version: '1.0'
regex: '(\\d+)'
columns: [value]
"""

MULTI_PARSE_SOURCE = """version: '1.0'
patterns:
  hr:
    regex: '^\\[HR\\],(.+)$'
    columns: [timestamp, frame, acc_x]
    separator: ','
  hrv:
    regex: '^\\[HRV\\] rri0:(\\d+), rri1:(\\d+)$'
    columns: [rri0, rri1]
"""

CLASSIFY_PATTERNS_SOURCE = """version: '1.0'
description: posture keywords
patterns:
  sit: [静坐, sitting]
  supine: [平躺]
"""

CLASSIFY_PIPELINE_SOURCE = """version: '1.0'
extract:
  - name: spo2_median
    function: calculate_median
    params: {column: REF_RESULT5, samples: 50}
classify:
  - target: normal
    condition: spo2_median >= 95
default: unclassified
"""

VALID_SOURCES = {
    RuleType.CHIP: """version: '1.0'
chip: demo
csv:
  header_row: 0
  data_start_row: 1
columns: [value]
""",
    RuleType.PARSE: PARSE_SOURCE,
    RuleType.CLASSIFY: """version: '1.0'
structure: {source: filename}
rules: []
""",
    RuleType.CONVERT: """version: '1.0'
column_mapping: {}
""",
    RuleType.EVALUATE: """type: hr
ref_column: REF
pred_column: PRED
methods: [mae]
""",
    RuleType.ANALYSIS: """version: '1.0'
type: other
columns: {reference: REF, prediction: PRED}
detectors: [integrity, accuracy]
thresholds: {error: 5}
causes:
  - id: raw_missing
    title: data missing
    origin: raw
    when: {feature: data_complete, op: eq, value: false}
""",
}


@pytest.fixture
def rule_roots(monkeypatch, tmp_path: Path):
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    monkeypatch.setattr(RuleLoader, "_builtin_rules_path", builtin)
    monkeypatch.setattr(rule_operations, "_user_rules_root", lambda: user)
    return builtin, user


def _write(root: Path, rule_type: str, name: str, source: str = PARSE_SOURCE) -> Path:
    path = root / rule_type / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(source.encode("utf-8"))
    return path


def test_list_rules_merges_sources_and_filters_type(rule_roots):
    builtin, user = rule_roots
    _write(builtin, "parse", "shared.yaml")
    user_path = _write(user, "parse", "shared.yaml", PARSE_SOURCE + "description: user\n")
    _write(builtin, "chip", "chip.yaml", "chip: demo\n")

    result = run_list_rules(RuleListRequest(RuleType.PARSE))

    assert [rule.name for rule in result.rules] == ["shared.yaml"]
    rule = result.rules[0]
    assert rule.source == RuleSource.USER
    assert rule.path == user_path
    assert rule.writable is True
    assert rule.overrides_builtin is True
    assert [variant.source for variant in rule.variants] == [
        RuleSource.USER,
        RuleSource.BUILTIN,
    ]


def test_read_rule_supports_effective_and_explicit_builtin(rule_roots):
    builtin, user = rule_roots
    builtin_source = PARSE_SOURCE + "description: builtin\n"
    user_source = PARSE_SOURCE + "description: user\n"
    _write(builtin, "parse", "shared.yaml", builtin_source)
    _write(user, "parse", "shared.yaml", user_source)

    effective = run_read_rule(RuleReadRequest(RuleType.PARSE, "shared.yaml"))
    selected_builtin = run_read_rule(
        RuleReadRequest(RuleType.PARSE, "shared.yaml", RuleSource.BUILTIN)
    )

    assert effective.source == user_source
    assert selected_builtin.source == builtin_source
    assert effective.revision != selected_builtin.revision
    assert selected_builtin.rule.source == RuleSource.BUILTIN
    assert selected_builtin.rule.writable is False


def test_read_missing_source_and_invalid_utf8_raise_rule_load_error(rule_roots):
    builtin, _ = rule_roots
    path = _write(builtin, "parse", "invalid.yaml")

    with pytest.raises(RuleLoadError, match="不存在 user 版本"):
        run_read_rule(RuleReadRequest(RuleType.PARSE, "invalid.yaml", RuleSource.USER))

    path.write_bytes(b"\xff\xfe")
    with pytest.raises(RuleLoadError, match="无法读取规则"):
        run_read_rule(RuleReadRequest(RuleType.PARSE, "invalid.yaml"))


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", "../bad.yaml", "nested/bad.yaml", "nested\\bad.yaml", "bad.txt"],
)
def test_rule_name_rejects_unsafe_paths(rule_roots, name: str):
    with pytest.raises(RequestValidationError):
        run_read_rule(RuleReadRequest(RuleType.PARSE, name))


def test_save_new_rule_and_update_with_matching_revision(rule_roots):
    _, user = rule_roots

    created = run_save_rule(RuleSaveRequest(RuleType.PARSE, "new.yaml", PARSE_SOURCE))
    updated_source = PARSE_SOURCE + "description: updated\n"
    updated = run_save_rule(
        RuleSaveRequest(
            RuleType.PARSE,
            "new.yaml",
            updated_source,
            expected_revision=created.revision,
        )
    )

    assert created.rule.path == user / "parse" / "new.yaml"
    assert updated.source == updated_source
    assert updated.revision != created.revision


@pytest.mark.parametrize("rule_type", tuple(RuleType))
def test_save_supports_all_public_rule_types(rule_roots, rule_type: RuleType):
    result = run_save_rule(
        RuleSaveRequest(rule_type, f"{rule_type.value}.yaml", VALID_SOURCES[rule_type])
    )

    assert result.rule.rule_type == rule_type
    assert result.rule.source == RuleSource.USER


@pytest.mark.parametrize(
    ("rule_type", "name", "source"),
    [
        (RuleType.PARSE, "multi.yaml", MULTI_PARSE_SOURCE),
        (RuleType.CLASSIFY, "patterns.yaml", CLASSIFY_PATTERNS_SOURCE),
        (RuleType.CLASSIFY, "pipeline.yaml", CLASSIFY_PIPELINE_SOURCE),
    ],
)
def test_save_supports_public_rule_variants(rule_roots, rule_type, name, source):
    saved = run_save_rule(RuleSaveRequest(rule_type, name, source))

    assert saved.source == source
    assert saved.rule.rule_type == rule_type


def test_save_builtin_rule_creates_user_override(rule_roots):
    builtin, user = rule_roots
    _write(builtin, "parse", "shared.yaml")
    original = run_read_rule(RuleReadRequest(RuleType.PARSE, "shared.yaml"))

    saved = run_save_rule(
        RuleSaveRequest(
            RuleType.PARSE,
            "shared.yaml",
            PARSE_SOURCE + "description: override\n",
            expected_revision=original.revision,
        )
    )

    assert saved.rule.path == user / "parse" / "shared.yaml"
    assert saved.rule.overrides_builtin is True
    assert (builtin / "parse" / "shared.yaml").read_text(encoding="utf-8") == PARSE_SOURCE


def test_save_requires_revision_and_detects_external_change(rule_roots):
    builtin, user = rule_roots
    _write(builtin, "parse", "shared.yaml")
    original = run_read_rule(RuleReadRequest(RuleType.PARSE, "shared.yaml"))

    with pytest.raises(RequestValidationError, match="必须提供 expected_revision"):
        run_save_rule(RuleSaveRequest(RuleType.PARSE, "shared.yaml", PARSE_SOURCE))

    _write(user, "parse", "shared.yaml", PARSE_SOURCE + "description: external\n")
    with pytest.raises(RequestValidationError, match="revision 冲突"):
        run_save_rule(
            RuleSaveRequest(
                RuleType.PARSE,
                "shared.yaml",
                PARSE_SOURCE + "description: ui\n",
                expected_revision=original.revision,
            )
        )
    assert "external" in (user / "parse" / "shared.yaml").read_text(encoding="utf-8")


def test_save_new_rule_rejects_nonempty_expected_revision(rule_roots):
    with pytest.raises(RequestValidationError, match="current=None"):
        run_save_rule(
            RuleSaveRequest(
                RuleType.PARSE,
                "new.yaml",
                PARSE_SOURCE,
                expected_revision="missing",
            )
        )


@pytest.mark.parametrize("source", ["- item\n", "null\n", "key: [\n"])
def test_save_rejects_invalid_yaml_roots(rule_roots, source: str):
    with pytest.raises(RequestValidationError):
        run_save_rule(RuleSaveRequest(RuleType.PARSE, "new.yaml", source))


def test_save_rejects_structurally_invalid_rule(rule_roots):
    with pytest.raises(RuleLoadError, match="规则校验失败"):
        run_save_rule(RuleSaveRequest(RuleType.PARSE, "new.yaml", "version: '1.0'\n"))


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "version: '1.0'\npatterns:\n  broken:\n    regex: '('\n    columns: [value]\n",
            "正则表达式错误",
        ),
        (
            "version: '1.0'\npatterns:\n  broken:\n    regex: '(a)(b)'\n" "    columns: [value]\n",
            "捕获组数量",
        ),
        (
            "version: '1.0'\npatterns:\n  broken:\n    regex: '(.*)'\n"
            "    columns: [a, b]\n    separator: ''\n",
            "separator",
        ),
    ],
)
def test_save_rejects_invalid_multi_parse_patterns(rule_roots, source: str, message: str):
    with pytest.raises(RuleLoadError, match=message):
        run_save_rule(RuleSaveRequest(RuleType.PARSE, "invalid.yaml", source))


@pytest.mark.parametrize(
    "source",
    [
        "version: '1.0'\npatterns: {}\n",
        "version: '1.0'\npatterns:\n  sit: sit\n",
        "version: '1.0'\npatterns:\n  sit: [静坐, 1]\n",
    ],
)
def test_save_rejects_invalid_classify_pattern_libraries(rule_roots, source: str):
    with pytest.raises(RuleLoadError, match="patterns"):
        run_save_rule(RuleSaveRequest(RuleType.CLASSIFY, "invalid.yaml", source))


def test_evaluate_validator_supports_valid_and_invalid_rules(tmp_path: Path):
    directory = tmp_path / "evaluate"
    valid = _write(
        tmp_path,
        "evaluate",
        "valid.yaml",
        "type: hr\nref_column: REF\npred_column: PRED\nmethods: [mae]\n",
    )
    invalid = directory / "invalid.yaml"
    invalid.write_text("type: unknown\n", encoding="utf-8")

    assert RuleValidator.validate_file(valid) == []
    assert "评估规则 'type' 必须是 hr 或 spo2" in RuleValidator.validate_file(invalid)


def test_analysis_validator_rejects_algorithm_actions(tmp_path: Path):
    invalid = _write(
        tmp_path,
        "analysis",
        "invalid.yaml",
        """version: '1.0'
type: other
columns: {reference: REF, prediction: PRED}
detectors: [accuracy]
thresholds: {}
causes:
  - id: algorithm_issue
    title: algorithm issue
    origin: algorithm
    when: {feature: algorithm_abnormal, op: eq, value: true}
    actions: [tune algorithm]
""",
    )

    assert any(
        "算法原因不能提供 actions" in error for error in RuleValidator.validate_file(invalid)
    )


def test_validate_classify_accepts_path_rename_filters(tmp_path: Path):
    """合法的 path/rename/filters 字段应通过校验。"""
    path = _write(
        tmp_path,
        "classify",
        "valid.yaml",
        """version: '1.0'
path:
  regex: '(?P<race>\\w+)/(?P<name>\\w+)/[^/]+\\.csv'
  fields: [race, name]
filters:
  min_rows: 100
  min_size_kb: 10
structure: {out: ''}
rules:
  - target: '{race}'
rename: '{race}_{name}_{filename}'
""",
    )
    assert RuleValidator.validate_file(path) == []


def test_validate_classify_rejects_bad_path_regex(tmp_path: Path):
    """path.regex 无法编译时应报错。"""
    path = _write(
        tmp_path,
        "classify",
        "bad_regex.yaml",
        "version: '1.0'\npath:\n  regex: '('\nstructure: {out: ''}\nrules: []\n",
    )
    errors = RuleValidator.validate_file(path)
    assert any("path" in e and "正则" in e for e in errors)


def test_validate_classify_rejects_negative_filter(tmp_path: Path):
    """filters.min_rows 为负数时应报错。"""
    path = _write(
        tmp_path,
        "classify",
        "bad_filter.yaml",
        "version: '1.0'\nfilters:\n  min_rows: -1\nstructure: {out: ''}\nrules: []\n",
    )
    errors = RuleValidator.validate_file(path)
    assert any("filters" in e for e in errors)


def test_validate_convert_rule_accepts_valid_split(tmp_path: Path):
    path = tmp_path / "convert" / "ok.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "version: '1.0'\n"
        "column_mapping: {time: TimeStamp}\n"
        "split:\n"
        "  by_column: FRAME_ID\n"
        "  column_value: 0\n",
        encoding="utf-8",
    )

    assert RuleValidator.validate_file(path) == []


def test_validate_convert_rule_rejects_invalid_split(tmp_path: Path):
    path = tmp_path / "convert" / "bad.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "version: '1.0'\n"
        "column_mapping: {time: TimeStamp}\n"
        "split:\n"
        "  by_size: 0\n"
        "  by_time: 60\n",
        encoding="utf-8",
    )

    errors = RuleValidator.validate_file(path)

    assert any("需要且仅需要" in error for error in errors)
    assert any("by_size" in error for error in errors)
    assert any("正整数" in error for error in errors)


def test_validate_convert_rule_rejects_bool_by_size(tmp_path: Path):
    path = tmp_path / "convert" / "bool_size.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "version: '1.0'\n" "column_mapping: {time: TimeStamp}\n" "split:\n" "  by_size: true\n",
        encoding="utf-8",
    )

    errors = RuleValidator.validate_file(path)

    assert any("正整数" in error for error in errors)
