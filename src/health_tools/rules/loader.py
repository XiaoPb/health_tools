from pathlib import Path
from typing import Any, Dict, List, Optional

import click
import yaml

from health_tools.models.rules import (
    ChipRule,
    ClassifyRule,
    ConvertRule,
    DataColumn,
    ParseRule,
)
from health_tools.utils.columns import expand_columns as _expand_columns


class RuleLoader:
    _builtin_rules_path: Optional[Path] = None

    @classmethod
    def get_builtin_rules_path(cls) -> Path:
        if cls._builtin_rules_path is None:
            cls._builtin_rules_path = Path(__file__).parent.parent.parent.parent / "rules"
        return cls._builtin_rules_path

    @classmethod
    def _resolve_rule_path(cls, rule_file: str, rule_type: str) -> Path:
        rule_path = Path(rule_file)
        if not rule_path.is_absolute():
            builtin_path = cls.get_builtin_rules_path() / rule_type / rule_file
            if builtin_path.exists():
                rule_path = builtin_path
        return rule_path

    @classmethod
    def _load_yaml(cls, file_path: Path) -> Dict[str, Any]:
        with open(file_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    @classmethod
    def _merge_dicts(cls, base: Dict, override: Dict) -> Dict:
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = cls._merge_dicts(result[key], value)
            else:
                result[key] = value
        return result

    @classmethod
    def load_parse_rule(cls, rule_file: str) -> ParseRule:
        rule_path = cls._resolve_rule_path(rule_file, "parse")
        data = cls._load_yaml(rule_path)

        return ParseRule(
            regex=data.get("regex", ""),
            columns=data.get("columns", []),
            description=data.get("description", ""),
            separator=data.get("separator", ","),
            chip=data.get("chip") or data.get("target_chip"),
        )

    @classmethod
    def load_chip_rule(cls, chip_name: str) -> ChipRule:
        rule_file = f"{chip_name}.yaml"
        rule_path = cls._resolve_rule_path(rule_file, "chip")

        if not rule_path.exists():
            chip_dir = cls.get_builtin_rules_path() / "chip"
            available = [f.stem for f in chip_dir.glob("*.yaml")] if chip_dir.exists() else []
            supported = ", ".join(available) if available else "无"
            raise click.ClickException(
                f"不支持的芯片型号: {chip_name}。当前支持: {supported}"
            )

        data = cls._load_yaml(rule_path)

        return ChipRule(
            chip=data.get("chip", chip_name),
            csv=data.get("csv", {}),
            columns=data.get("columns", []),
            version=data.get("version", "1.0"),
        )

    @classmethod
    def load_classify_rule(
        cls,
        rule_file: str,
        extend_files: Optional[List[str]] = None,
    ) -> ClassifyRule:
        rule_path = cls._resolve_rule_path(rule_file, "classify")
        data = cls._load_yaml(rule_path)

        if "extends" in data:
            extends_path = cls._resolve_rule_path(data["extends"], "classify")
            extends_data = cls._load_yaml(extends_path)
            data = cls._merge_dicts(extends_data, data)

        if extend_files:
            for extend_file in extend_files:
                extend_path = cls._resolve_rule_path(extend_file, "classify")
                extend_data = cls._load_yaml(extend_path)
                if "patterns" in extend_data:
                    if "extract" not in data:
                        data["extract"] = []
                    for extract_item in data.get("extract", []):
                        if "params" in extract_item and "patterns" in extract_item["params"]:
                            extract_item["params"]["patterns"].update(extend_data["patterns"])

        extract_rules = []
        for extract_item in data.get("extract", []):
            extract_rules.append(
                {
                    "name": extract_item.get("name", ""),
                    "function": extract_item.get("function", ""),
                    "params": extract_item.get("params", {}),
                }
            )

        classify_rules = data.get("classify", [])

        accuracy_config = data.get("accuracy", {})

        data_columns = []
        for col_data in data.get("data_columns", []):
            data_columns.append(
                DataColumn(
                    name=col_data.get("name", ""),
                    type=col_data.get("type", "string"),
                    column=col_data.get("column"),
                    column_index=col_data.get("column_index"),
                    source=col_data.get("source", "data"),
                    ranges=col_data.get("ranges", {}),
                    values=col_data.get("values", []),
                    match=col_data.get("match", {}),
                    regex=col_data.get("regex"),
                    group=col_data.get("group"),
                    compute=col_data.get("compute"),
                )
            )

        return ClassifyRule(
            filename=data.get("filename", {}),
            data_columns=data_columns,
            structure=data.get("structure", {}),
            rules=data.get("rules", []),
            default=data.get("default", "unclassified"),
            extract=extract_rules,
            classify_rules=classify_rules,
            accuracy=accuracy_config,
        )

    @classmethod
    def load_convert_rule(cls, rule_file: str) -> ConvertRule:
        rule_path = cls._resolve_rule_path(rule_file, "convert")
        data = cls._load_yaml(rule_path)

        return ConvertRule(
            source_columns=data.get("source_columns", []),
            target_columns=data.get("target_columns", []),
            computed=data.get("computed", {}),
            target_chip=data.get("target_chip"),
            description=data.get("description", ""),
            column_mapping=data.get("column_mapping", {}),
            forward_fill=data.get("forward_fill", []),
            expand_repeat=data.get("expand_repeat", {}),
            csv=data.get("csv", {}),
        )

    @classmethod
    def load_patterns(cls, patterns_file: str) -> Dict[str, List[str]]:
        patterns_path = cls._resolve_rule_path(patterns_file, "classify")
        data = cls._load_yaml(patterns_path)
        return data.get("patterns", {})

    @classmethod
    def expand_columns(cls, columns: List[str]) -> List[str]:
        return _expand_columns(columns)
