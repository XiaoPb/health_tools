import re
from pathlib import Path
from typing import List

import yaml

from health_tools.utils.columns import expand_columns as _expand_cols


class RuleValidator:
    @staticmethod
    def validate_file(file_path: Path, strict: bool = False) -> List[str]:
        errors = []

        if not file_path.exists():
            return [f"文件不存在: {file_path}"]

        if file_path.suffix not in (".yaml", ".yml"):
            return [f"文件必须是YAML格式: {file_path.suffix}"]

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                rule = yaml.safe_load(f)
        except yaml.YAMLError as e:
            return [f"YAML解析错误: {e}"]

        if not isinstance(rule, dict):
            return ["规则文件必须是一个字典结构"]

        rule_type = RuleValidator._detect_rule_type(file_path)

        if rule_type == "chip":
            errors.extend(RuleValidator._validate_chip_rule(rule, strict))
        elif rule_type == "parse":
            errors.extend(RuleValidator._validate_parse_rule(rule, strict))
        elif rule_type == "classify":
            errors.extend(RuleValidator._validate_classify_rule(rule, strict))
        elif rule_type == "convert":
            errors.extend(RuleValidator._validate_convert_rule(rule, strict))
        else:
            errors.append("无法识别的规则类型")

        return errors

    @staticmethod
    def _detect_rule_type(rule_path: Path) -> str:
        parts = rule_path.parts
        if "chip" in parts:
            return "chip"
        elif "parse" in parts:
            return "parse"
        elif "classify" in parts:
            return "classify"
        elif "convert" in parts:
            return "convert"
        return "unknown"

    @staticmethod
    def _validate_chip_rule(rule: dict, strict: bool) -> List[str]:
        errors = []

        if "version" not in rule:
            errors.append("缺少 'version' 字段")

        if "chip" not in rule:
            errors.append("芯片规则缺少 'chip' 字段")

        if "csv" not in rule:
            errors.append("芯片规则缺少 'csv' 字段")
        elif isinstance(rule.get("csv"), dict):
            csv_config = rule["csv"]
            if "header_row" not in csv_config:
                errors.append("csv配置缺少 'header_row' 字段")
            if "data_start_row" not in csv_config:
                errors.append("csv配置缺少 'data_start_row' 字段")

        if "columns" not in rule:
            errors.append("芯片规则缺少 'columns' 字段")
        else:
            columns = RuleValidator._expand_columns(rule["columns"])
            if not columns:
                errors.append("'columns' 字段不能为空")

        return errors

    @staticmethod
    def _validate_parse_rule(rule: dict, strict: bool) -> List[str]:
        errors = []

        if "version" not in rule:
            errors.append("缺少 'version' 字段")

        if "regex" not in rule:
            errors.append("解析规则缺少 'regex' 字段")
        else:
            try:
                pattern = re.compile(rule["regex"])
                groups = pattern.groups
            except re.error as e:
                errors.append(f"正则表达式错误: {e}")
                return errors

        if "columns" not in rule:
            errors.append("解析规则缺少 'columns' 字段")
        else:
            columns = RuleValidator._expand_columns(rule["columns"])
            if not columns:
                errors.append("'columns' 字段不能为空")

            if "regex" in rule:
                try:
                    pattern = re.compile(rule["regex"])
                    groups = pattern.groups
                    if len(columns) != groups:
                        errors.append(f"正则捕获组数量({groups})与列名数量({len(columns)})不匹配")
                except re.error:
                    pass

        if strict and "description" not in rule:
            errors.append("[严格模式] 缺少 'description' 字段")

        return errors

    @staticmethod
    def _validate_classify_rule(rule: dict, strict: bool) -> List[str]:
        errors = []

        if "version" not in rule:
            errors.append("缺少 'version' 字段")

        if "structure" not in rule:
            errors.append("分类规则缺少 'structure' 字段")
        elif not rule["structure"]:
            errors.append("'structure' 字段不能为空")

        if strict:
            if "rules" not in rule:
                errors.append("[严格模式] 缺少 'rules' 字段")

        return errors

    @staticmethod
    def _validate_convert_rule(rule: dict, strict: bool) -> List[str]:
        errors = []

        if "version" not in rule:
            errors.append("缺少 'version' 字段")

        has_mapping = "column_mapping" in rule and isinstance(rule.get("column_mapping"), dict)
        has_source_target = "source_columns" in rule and "target_columns" in rule

        if not has_mapping and not has_source_target:
            errors.append(
                "转换规则需要提供 'column_mapping' 或同时提供 " "'source_columns'/'target_columns'"
            )

        if has_source_target:
            src_cols = RuleValidator._expand_columns(rule["source_columns"])
            tgt_cols = RuleValidator._expand_columns(rule["target_columns"])
            if len(src_cols) != len(tgt_cols):
                errors.append(f"源列数({len(src_cols)})与目标列数({len(tgt_cols)})不匹配")

        extra_source = rule.get("extra_source")
        if extra_source is not None:
            if isinstance(extra_source, list):
                for index, item in enumerate(extra_source):
                    if not isinstance(item, dict):
                        errors.append(f"'extra_source[{index}]' 必须是字典")
                    else:
                        errors.extend(
                            RuleValidator._validate_extra_source_config(
                                item, f"extra_source[{index}]"
                            )
                        )
            elif isinstance(extra_source, dict):
                errors.extend(
                    RuleValidator._validate_extra_source_config(extra_source, "extra_source")
                )
            else:
                errors.append("'extra_source' 必须是字典或列表")

        return errors

    @staticmethod
    def _validate_extra_source_config(config: dict, prefix: str) -> List[str]:
        errors = []
        if "column_mapping" in config and not isinstance(config.get("column_mapping"), dict):
            errors.append(f"'{prefix}.column_mapping' 必须是字典")
        for key in ("required_columns", "any_required_columns"):
            if key in config and not isinstance(config.get(key), list):
                errors.append(f"'{prefix}.{key}' 必须是列表")
        align = config.get("align")
        if align is not None:
            if not isinstance(align, dict):
                errors.append(f"'{prefix}.align' 必须是字典")
            elif not align.get("left_on") or not align.get("right_on"):
                errors.append(f"'{prefix}.align' 需要同时提供 'left_on' 和 'right_on'")
        return errors

    @staticmethod
    def _expand_columns(columns: list) -> list:
        return _expand_cols([str(c) for c in columns])
