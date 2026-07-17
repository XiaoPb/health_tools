from pathlib import Path

import pytest

from health_tools import config as config_module
from health_tools.api import (
    ConfigAction,
    ConfigRequest,
    OfflineCatalogRequest,
    OperationError,
    RequestValidationError,
    run_config,
    run_offline_catalog,
)
from health_tools.api import offline_catalog
from health_tools.core.offline import EXE_NAME, OfflineConfig


@pytest.fixture
def isolated_config(monkeypatch, tmp_path: Path):
    config_dir = tmp_path / ".ghealth_tools"
    monkeypatch.setattr(config_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_module, "CONFIG_FILE", config_dir / "config.yaml")
    monkeypatch.setattr(config_module, "DEFAULT_RULES_DIR", config_dir / "rules")
    monkeypatch.setattr(config_module, "_config_cache", None)
    return config_module.CONFIG_FILE


def test_config_show_returns_source_and_revision(isolated_config: Path):
    config_module.save_config({"rules_dir": "rules"})

    result = run_config(ConfigRequest(ConfigAction.SHOW))

    assert result.config["rules_dir"] == "rules"
    assert result.source == isolated_config.read_text(encoding="utf-8")
    assert len(result.revision or "") == 64


def test_config_replace_creates_then_requires_matching_revision(isolated_config: Path):
    created = run_config(ConfigRequest(ConfigAction.REPLACE, source="rules_dir: first\n"))

    assert created.config["rules_dir"] == "first"
    assert created.source == "rules_dir: first\n"
    assert config_module.load_config()["rules_dir"] == "first"

    with pytest.raises(RequestValidationError, match="revision 冲突"):
        run_config(ConfigRequest(ConfigAction.REPLACE, source="rules_dir: lost\n"))

    updated = run_config(
        ConfigRequest(
            ConfigAction.REPLACE,
            source="rules_dir: second\n",
            expected_revision=created.revision,
        )
    )
    assert updated.config["rules_dir"] == "second"
    assert config_module.load_config()["rules_dir"] == "second"


def test_config_replace_detects_external_change_and_preserves_file(isolated_config: Path):
    original = run_config(ConfigRequest(ConfigAction.REPLACE, source="value: one\n"))
    isolated_config.write_bytes(b"value: external\n")

    with pytest.raises(RequestValidationError, match="revision 冲突"):
        run_config(
            ConfigRequest(
                ConfigAction.REPLACE,
                source="value: ui\n",
                expected_revision=original.revision,
            )
        )

    assert isolated_config.read_bytes() == b"value: external\n"


@pytest.mark.parametrize("source", ["- item\n", "null\n", "key: [\n"])
def test_config_replace_rejects_invalid_yaml_root(isolated_config: Path, source: str):
    with pytest.raises(RequestValidationError):
        run_config(ConfigRequest(ConfigAction.REPLACE, source=source))


def test_config_replace_rejects_mutually_exclusive_fields(isolated_config: Path):
    with pytest.raises(RequestValidationError, match="不能与 value 或 force"):
        run_config(ConfigRequest(ConfigAction.REPLACE, value="x", source="value: x\n"))
    with pytest.raises(RequestValidationError, match="仅适用于 REPLACE"):
        run_config(ConfigRequest(ConfigAction.SHOW, expected_revision="rev"))
    with pytest.raises(RequestValidationError, match="source 必须是字符串"):
        run_config(ConfigRequest(ConfigAction.REPLACE, source=123))  # type: ignore[arg-type]


def test_existing_config_action_remains_compatible_and_atomic(
    isolated_config: Path, tmp_path: Path
):
    result = run_config(ConfigRequest(ConfigAction.SET_RULES_DIR, value=str(tmp_path / "rules")))

    assert result.config["rules_dir"] == str(tmp_path / "rules")
    assert result.changed_paths == (isolated_config,)
    assert result.revision is not None


def test_offline_catalog_returns_sorted_versions_and_exe_availability(monkeypatch, tmp_path: Path):
    tools = tmp_path / "tools"
    available = tools / "gh3036" / "basic" / "v2" / EXE_NAME
    available.parent.mkdir(parents=True)
    available.write_bytes(b"exe")
    config = OfflineConfig(
        tools_path=tools,
        versions={
            "gh3220": {"versions": {"exclusive": ["v3"]}, "default": "v3"},
            "gh3036": {
                "versions": {"basic": ["v2", "v1"]},
                "default": "v2",
                "default_category": "basic",
            },
        },
    )
    monkeypatch.setattr(offline_catalog, "_get_offline_config", lambda: config)

    result = run_offline_catalog(OfflineCatalogRequest())

    assert [(item.chip_name, item.category, item.version) for item in result.versions] == [
        ("gh3036", "basic", "v1"),
        ("gh3036", "basic", "v2"),
        ("gh3220", "exclusive", "v3"),
    ]
    assert result.versions[1].is_default is True
    assert result.versions[1].exe_available is True
    assert result.versions[0].exe_available is False


def test_offline_catalog_filters_chip_and_supports_legacy_versions(monkeypatch, tmp_path: Path):
    tools = tmp_path / "tools"
    executable = tools / "gh3036" / "exclusive" / "v1" / EXE_NAME
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"exe")
    config = OfflineConfig(
        tools_path=tools,
        versions={
            "gh3036": {"versions": ["v1"], "default": "v1"},
            "gh3220": {"versions": ["v2"], "default": "v2"},
        },
    )
    monkeypatch.setattr(offline_catalog, "_get_offline_config", lambda: config)

    result = run_offline_catalog(OfflineCatalogRequest("gh3036"))

    assert len(result.versions) == 1
    assert result.versions[0].category is None
    assert result.versions[0].is_default is True
    assert result.versions[0].exe_available is True


def test_offline_catalog_rejects_invalid_request_and_config(monkeypatch, tmp_path: Path):
    with pytest.raises(RequestValidationError, match="chip_name 不能为空"):
        run_offline_catalog(OfflineCatalogRequest(" "))

    monkeypatch.setattr(
        offline_catalog,
        "_get_offline_config",
        lambda: OfflineConfig(tools_path=tmp_path, versions={"gh3036": {"versions": "bad"}}),
    )
    with pytest.raises(OperationError, match="versions 必须是映射或列表"):
        run_offline_catalog(OfflineCatalogRequest())
