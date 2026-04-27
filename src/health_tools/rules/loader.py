import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from health_tools.core.classifier import ClassifyRule, DataColumn
from health_tools.core.converter import ConvertRule
from health_tools.core.parser import ChipRule, ParseRule


class RuleLoader:
    _builtin_rules_path: Optional[Path] = None

    @classmethod
    def get_builtin_rules_path(cls) -> Path:
        if cls._builtin_rules_path is None:
            cls._builtin_rules_path = Path(__file__).parent.parent.parent.parent / "rules"
        return cls._builtin_rules_path

    @classmethod
    def load_parse_rule(cls, rule_file: str) -> ParseRule:
        rule_path = Path(rule_file)
        if not rule_path.is_absolute():
            builtin_path = cls.get_builtin_rules_path() / "parse" / rule_file
            if builtin_path.exists():
                rule_path = builtin_path
            else:
                rule_path = Path(rule_file)

        with open(rule_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return ParseRule(
            regex=data.get("regex", ""),
            columns=data.get("columns", []),
            description=data.get("description", ""),
        )

    @classmethod
    def load_chip_rule(cls, chip_name: str) -> ChipRule:
        rule_file = f"{chip_name}.yaml"
        rule_path = Path(rule_file)
        if not rule_path.is_absolute():
            builtin_path = cls.get_builtin_rules_path() / "chip" / rule_file
            if builtin_path.exists():
                rule_path = builtin_path
            else:
                rule_path = Path(rule_file)

        with open(rule_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return ChipRule(
            chip=data.get("chip", chip_name),
            csv=data.get("csv", {}),
            columns=data.get("columns", []),
            version=data.get("version", "1.0"),
        )

    @classmethod
    def load_classify_rule(cls, rule_file: str) -> ClassifyRule:
        rule_path = Path(rule_file)
        if not rule_path.is_absolute():
            builtin_path = cls.get_builtin_rules_path() / "classify" / rule_file
            if builtin_path.exists():
                rule_path = builtin_path
            else:
                rule_path = Path(rule_file)

        with open(rule_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

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
        )

    @classmethod
    def load_convert_rule(cls, rule_file: str) -> ConvertRule:
        rule_path = Path(rule_file)
        if not rule_path.is_absolute():
            builtin_path = cls.get_builtin_rules_path() / "convert" / rule_file
            if builtin_path.exists():
                rule_path = builtin_path
            else:
                rule_path = Path(rule_file)

        with open(rule_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return ConvertRule(
            source_columns=data.get("source_columns", []),
            target_columns=data.get("target_columns", []),
            computed=data.get("computed", {}),
        )

    @classmethod
    def expand_columns(cls, columns: List[str]) -> List[str]:
        expanded = []
        for col in columns:
            match = re.match(r"^(.+?)\[(\d+)-(\d+)\]$", col)
            if match:
                prefix, start, end = match.groups()
                for i in range(int(start), int(end) + 1):
                    expanded.append(f"{prefix}{i}")
            else:
                expanded.append(col)
        return expanded
