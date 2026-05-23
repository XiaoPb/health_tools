import ast
import logging
import operator as op
import re
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from health_tools.models.rules import ClassifyRule, DataColumn  # noqa: F401
from health_tools.utils.classify_helpers import get_function
from health_tools.utils.csv_handler import CSVHandler

logger = logging.getLogger(__name__)

_SAFE_OPS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
    ast.Lt: op.lt,
    ast.LtE: op.le,
    ast.Gt: op.gt,
    ast.GtE: op.ge,
    ast.Eq: op.eq,
    ast.NotEq: op.ne,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
    ast.Invert: op.invert,
}


class _SafeEvalError(Exception):
    pass


def _safe_eval(expr: str, variables: Dict[str, Any]) -> bool:
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError:
        raise _SafeEvalError(f"语法错误: {expr}")

    def _eval(node):
        if isinstance(node, ast.BoolOp):
            values = [_eval(v) for v in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            return any(values)
        elif isinstance(node, ast.Compare):
            left = _eval(node.left)
            result = True
            for op_node, comparator in zip(node.ops, node.comparators):
                right = _eval(comparator)
                op_type = type(op_node)
                if op_type not in _SAFE_OPS:
                    raise _SafeEvalError(f"不支持的操作符: {op_type.__name__}")
                if not _SAFE_OPS[op_type](left, right):
                    result = False
                left = right
            return result
        elif isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            op_type = type(node.op)
            if op_type not in _SAFE_OPS:
                raise _SafeEvalError(f"不支持的操作符: {op_type.__name__}")
            return _SAFE_OPS[op_type](left, right)
        elif isinstance(node, ast.UnaryOp):
            operand = _eval(node.operand)
            op_type = type(node.op)
            if op_type not in _SAFE_OPS:
                raise _SafeEvalError(f"不支持的操作符: {op_type.__name__}")
            return _SAFE_OPS[op_type](operand)
        elif isinstance(node, ast.Name):
            name = node.id
            if name in ("True", "False", "None"):
                return {"True": True, "False": False, "None": None}[name]
            if name in variables:
                return variables[name]
            raise _SafeEvalError(f"未定义的变量: {name}")
        elif isinstance(node, ast.Constant):
            return node.value
        else:
            raise _SafeEvalError(f"不支持的AST节点: {type(node).__name__}")

    result = _eval(tree.body)
    return bool(result)


class DataClassifier:
    def __init__(self, rule: ClassifyRule, chip_rule=None):
        self.rule = rule
        self.chip_rule = chip_rule
        self.csv_handler = CSVHandler(chip_rule)
        self._filename_fields: Dict[str, str] = {}
        self._extracted_values: Dict[str, Any] = {}
        self._cached_df: Optional[pd.DataFrame] = None
        self._cached_file: Optional[Path] = None

    def create_structure(self, base_dir: Path) -> None:
        for parent, children in self.rule.structure.items():
            parent_resolved = self._resolve_variables(parent)
            parent_path = base_dir / parent_resolved
            parent_path.mkdir(parents=True, exist_ok=True)

            if children:
                child_names = children.split("|")
                for child in child_names:
                    child_resolved = self._resolve_variables(child)
                    child_path = parent_path / child_resolved
                    child_path.mkdir(parents=True, exist_ok=True)

    def _resolve_variables(self, text: str) -> str:
        result = text
        for key, value in self._filename_fields.items():
            result = result.replace(f"{{{key}}}", str(value))
        for key, value in self._extracted_values.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result

    def classify(self, file_path: Path, base_dir: Path) -> Optional[Path]:
        self._parse_filename(file_path)

        self._extracted_values = self._extract_values(file_path)

        if self.rule.classify_rules:
            for rule in self.rule.classify_rules:
                target = rule.get("target", "")
                condition = rule.get("condition", "")

                if condition and self._evaluate_condition(condition, self._extracted_values):
                    resolved_target = self._resolve_variables(target)
                    for key, value in self._extracted_values.items():
                        resolved_target = resolved_target.replace(f"{{{key}}}", str(value))
                    return base_dir / resolved_target
        else:
            for rule in self.rule.rules:
                target = rule.get("target", "")
                conditions = rule.get("conditions", {})

                resolved_target = self._resolve_target(target, self._extracted_values, conditions)

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

    def _extract_values(self, file_path: Path) -> Dict[str, Any]:
        values = {}

        for col_def in self.rule.data_columns:
            value = self._extract_column_value(file_path, col_def)
            if value is not None:
                values[col_def.name] = value

        if self.rule.extract:
            try:
                info, df = self.csv_handler.read(file_path)

                for extract_item in self.rule.extract:
                    name = extract_item.get("name", "")
                    func_name = extract_item.get("function", "")
                    params = extract_item.get("params", {})

                    func = get_function(func_name)
                    if func:
                        if "patterns" in params:
                            value = func(file_path, params["patterns"])
                        elif "column" in params:
                            value = func(df, params["column"], params.get("samples", 50))
                        else:
                            value = func(df, **params)

                        values[name] = value
            except Exception as e:
                logger.warning("提取数据失败 %s: %s", file_path.name, e)

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
                    if pattern in filename:
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
                    if pattern in parent_name:
                        return value

        return None

    def _extract_from_data(self, file_path: Path, col_def: DataColumn) -> Any:
        try:
            if self._cached_file != file_path:
                _, self._cached_df = self.csv_handler.read(file_path)
                self._cached_file = file_path

            df = self._cached_df
            if df is None or df.empty:
                return None

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
                    if len(range_vals) >= 2 and range_vals[0] <= mean_val <= range_vals[1]:
                        return range_name

            if col_def.values:
                mode_val = data.mode()
                if len(mode_val) > 0:
                    most_common = str(mode_val.iloc[0])
                    if most_common in col_def.values:
                        return most_common

            return None

        except Exception as e:
            logger.warning("从数据提取列 %s 失败 %s: %s", col_def.name, file_path.name, e)
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
            return _safe_eval(condition, data_values)
        except _SafeEvalError as e:
            logger.warning("条件求值错误: %s", e)
            return False
        except Exception as e:
            logger.warning("条件求值异常: %s", e)
            return False

    def get_accuracy_config(self) -> Dict[str, Any]:
        return self.rule.accuracy
