import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


@dataclass
class DataColumn:
    name: str
    type: str = "string"
    column: Optional[str] = None
    column_index: Optional[int] = None
    source: str = "data"
    ranges: Dict[str, List[int]] = field(default_factory=dict)
    values: List[str] = field(default_factory=list)
    match: Dict[str, List[str]] = field(default_factory=dict)
    regex: Optional[str] = None
    group: Optional[int] = None
    compute: Optional[str] = None


@dataclass
class ClassifyRule:
    filename: Dict[str, Any] = field(default_factory=dict)
    data_columns: List[DataColumn] = field(default_factory=list)
    structure: Dict[str, str] = field(default_factory=dict)
    rules: List[Dict[str, Any]] = field(default_factory=list)
    default: str = "unclassified"


class DataClassifier:
    def __init__(self, rule: ClassifyRule):
        self.rule = rule
        self._filename_fields: Dict[str, str] = {}

    def create_structure(self, base_dir: Path) -> None:
        for parent, children in self.rule.structure.items():
            parent_path = base_dir / parent
            parent_path.mkdir(parents=True, exist_ok=True)

            if children:
                child_names = children.split("|")
                for child in child_names:
                    child_path = parent_path / child
                    child_path.mkdir(parents=True, exist_ok=True)

    def classify(self, file_path: Path, base_dir: Path) -> Optional[Path]:
        self._parse_filename(file_path)

        data_values = self._extract_data_values(file_path)

        for rule in self.rule.rules:
            target = rule.get("target", "")
            conditions = rule.get("conditions", {})

            resolved_target = self._resolve_target(target, data_values, conditions)

            if resolved_target:
                return base_dir / resolved_target

        return None

    def _parse_filename(self, file_path: Path) -> None:
        self._filename_fields = {}

        if not self.rule.filename:
            return

        regex = self.rule.filename.get("regex", "")
        fields = self.rule.filename.get("fields", [])

        if regex and fields:
            match = re.search(regex, file_path.name)
            if match:
                groups = match.groups()
                for i, field_name in enumerate(fields):
                    if i < len(groups):
                        self._filename_fields[field_name] = groups[i]

    def _extract_data_values(self, file_path: Path) -> Dict[str, Any]:
        values = {}

        for col_def in self.rule.data_columns:
            value = self._extract_column_value(file_path, col_def)
            if value is not None:
                values[col_def.name] = value

        return values

    def _extract_column_value(self, file_path: Path, col_def: DataColumn) -> Any:
        if col_def.source == "filename":
            return self._extract_from_filename(file_path, col_def)
        elif col_def.source == "parent_dir":
            return self._extract_from_parent_dir(file_path, col_def)
        else:
            return self._extract_from_data(file_path, col_def)

    def _extract_from_filename(self, file_path: Path, col_def: DataColumn) -> Optional[str]:
        filename = file_path.name

        if col_def.match:
            for value, patterns in col_def.match.items():
                for pattern in patterns:
                    if pattern.lower() in filename.lower():
                        return value

        if col_def.regex:
            match = re.search(col_def.regex, filename)
            if match and col_def.group:
                groups = match.groups()
                if col_def.group <= len(groups):
                    return groups[col_def.group - 1]

        return None

    def _extract_from_parent_dir(self, file_path: Path, col_def: DataColumn) -> Optional[str]:
        parent_name = file_path.parent.name

        if col_def.match:
            for value, patterns in col_def.match.items():
                for pattern in patterns:
                    if pattern.lower() in parent_name.lower():
                        return value

        return None

    def _extract_from_data(self, file_path: Path, col_def: DataColumn) -> Any:
        try:
            df = pd.read_csv(file_path)

            if col_def.column:
                if col_def.column not in df.columns:
                    return None
                data = df[col_def.column]
            elif col_def.column_index is not None:
                if col_def.column_index >= len(df.columns):
                    return None
                data = df.iloc[:, col_def.column_index]
            else:
                return None

            if col_def.type == "int":
                data = pd.to_numeric(data, errors="coerce")

            if col_def.ranges:
                mean_val = data.mean()
                for range_name, range_vals in col_def.ranges.items():
                    if range_vals[0] <= mean_val <= range_vals[1]:
                        return range_name

            if col_def.values:
                mode_val = data.mode()
                if len(mode_val) > 0:
                    most_common = str(mode_val.iloc[0])
                    if most_common in col_def.values:
                        return most_common

            return None

        except Exception:
            return None

    def _resolve_target(
        self,
        target: str,
        data_values: Dict[str, Any],
        conditions: Dict[str, Dict[str, str]],
    ) -> Optional[str]:
        result = target

        for key, value in self._filename_fields.items():
            result = result.replace(f"{{{key}}}", str(value))

        for key, value in data_values.items():
            result = result.replace(f"{{{key}}}", str(value))

        for cond_key, cond_values in conditions.items():
            if f"{{{cond_key}}}" in result:
                resolved = self._resolve_condition(cond_key, cond_values, data_values)
                if resolved:
                    result = result.replace(f"{{{cond_key}}}", resolved)
                else:
                    return None

        if "{" in result and "}" in result:
            return None

        return result

    def _resolve_condition(
        self,
        key: str,
        conditions: Dict[str, str],
        data_values: Dict[str, Any],
    ) -> Optional[str]:
        for value, condition in conditions.items():
            if self._evaluate_condition(condition, data_values):
                return value
        return None

    def _evaluate_condition(self, condition: str, data_values: Dict[str, Any]) -> bool:
        try:
            for key, value in data_values.items():
                condition = condition.replace(key, repr(value))

            condition = condition.replace(" and ", " and ")
            condition = condition.replace(" or ", " or ")

            return bool(eval(condition))
        except Exception:
            return False
