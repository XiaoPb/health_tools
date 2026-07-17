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
