import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from health_tools.models.rules import ConvertRule  # noqa: F401

logger = logging.getLogger(__name__)


class DataConverter:
    def __init__(self, rule: ConvertRule, chip_columns: Optional[List[str]] = None):
        self.rule = rule
        self.chip_columns = chip_columns

    def convert(self, df: pd.DataFrame, source_file: Optional[Path] = None) -> pd.DataFrame:
        df = self._merge_extra_source(df, source_file)
        if not self.has_matching_columns(df):
            return pd.DataFrame()

        result = pd.DataFrame()

        if self.rule.column_mapping:
            for src, tgt in self.rule.column_mapping.items():
                if src in df.columns:
                    result[tgt] = df[src]
        elif self.rule.source_columns and self.rule.target_columns:
            for src, tgt in zip(self.rule.source_columns, self.rule.target_columns):
                if src in df.columns:
                    result[tgt] = df[src]
        else:
            result = df.copy()

        if self.rule.computed:
            for col_name, formula in self.rule.computed.items():
                result[col_name] = self._compute_column(formula, df)

        if self.rule.expand_repeat:
            result = self._apply_expand_repeat(result)

        if self.rule.forward_fill:
            result = self._apply_forward_fill(result)

        if self.chip_columns:
            missing_cols = [col for col in self.chip_columns if col not in result.columns]
            if missing_cols:
                fill_df = pd.DataFrame(0, index=result.index, columns=missing_cols)
                result = pd.concat([result, fill_df], axis=1)
            result = result[self.chip_columns]

        result = self._ensure_int64(result)
        return result

    def has_matching_columns(self, df: pd.DataFrame) -> bool:
        expected_columns = self._expected_source_columns()
        if not expected_columns:
            return True
        return any(col in df.columns for col in expected_columns)

    def _expected_source_columns(self) -> List[str]:
        if self.rule.column_mapping:
            return list(self.rule.column_mapping.keys())
        if self.rule.source_columns and self.rule.target_columns:
            return self.rule.source_columns
        return []

    def _merge_extra_source(
        self, df: pd.DataFrame, source_file: Optional[Path] = None
    ) -> pd.DataFrame:
        config = self.rule.extra_source or {}
        if not config or source_file is None:
            return df

        extra_file = self._resolve_extra_source_file(source_file, config)
        if extra_file is None:
            return df

        extra_df = self._read_extra_source_csv(extra_file, config)
        if extra_df.empty:
            return df

        align = config.get("align", {})
        left_on = align.get("left_on")
        right_on = align.get("right_on")
        if not left_on or not right_on:
            logger.warning("extra_source 缺少对齐列配置，已跳过: %s", extra_file)
            return df
        if left_on not in df.columns or right_on not in extra_df.columns:
            logger.warning(
                "extra_source 对齐列不存在，已跳过: left_on=%s right_on=%s file=%s",
                left_on,
                right_on,
                extra_file,
            )
            return df

        extra_df = extra_df.copy()
        extra_df[right_on] = self._normalize_align_key(
            extra_df[right_on], align.get("right_extract")
        )
        left_keys = self._normalize_align_key(df[left_on], align.get("left_extract"))
        extra_df = extra_df.drop_duplicates(subset=[right_on], keep="last")

        rename_map = config.get("column_mapping", {}) or {}
        selected_cols = [right_on]
        for col in rename_map:
            if col in extra_df.columns and col not in selected_cols:
                selected_cols.append(col)
        if len(selected_cols) == 1:
            logger.warning("extra_source 未配置可合并列，已跳过: %s", extra_file)
            return df

        merge_df = extra_df[selected_cols].rename(columns=rename_map)
        merge_df = merge_df.rename(columns={right_on: "__extra_align_key__"})
        merged_columns = [col for col in merge_df.columns if col != "__extra_align_key__"]

        merged = df.copy()
        merged["__extra_align_key__"] = left_keys
        merged = merged.merge(merge_df, on="__extra_align_key__", how="left")
        merged = merged.drop(columns=["__extra_align_key__"])
        for col in merged_columns:
            if col in merged.columns:
                merged[col] = merged[col].fillna(0)
        return merged

    def _resolve_extra_source_file(
        self, source_file: Path, config: Dict[str, Any]
    ) -> Optional[Path]:
        path_value = config.get("path")
        if path_value:
            candidate = Path(path_value)
            if not candidate.is_absolute():
                candidate = source_file.parent / candidate
            if candidate.exists():
                return candidate

        suffix = config.get("suffix")
        if suffix:
            matches = sorted(source_file.parent.glob(f"*{suffix}"))
            match = self._select_extra_source_candidate(matches, source_file, config)
            if match:
                return match

        pattern = config.get("pattern")
        if pattern:
            matches = sorted(source_file.parent.glob(pattern))
            match = self._select_extra_source_candidate(matches, source_file, config)
            if match:
                return match

        logger.warning("未找到 extra_source 文件: %s", source_file)
        return None

    def _select_extra_source_candidate(
        self, candidates: List[Path], source_file: Path, config: Dict[str, Any]
    ) -> Optional[Path]:
        for candidate in candidates:
            if candidate.resolve() == source_file.resolve():
                continue
            if self._extra_source_candidate_matches(candidate, config):
                return candidate
        return None

    def _extra_source_candidate_matches(self, file_path: Path, config: Dict[str, Any]) -> bool:
        required_columns = config.get("required_columns") or []
        any_required_columns = config.get("any_required_columns") or []
        if not required_columns and not any_required_columns:
            return True

        try:
            df = self._read_extra_source_csv(file_path, config)
        except Exception as e:
            logger.warning("读取 extra_source 候选文件失败，已跳过: %s, %s", file_path, e)
            return False

        columns = set(str(col).strip() for col in df.columns)
        if any(str(col).strip() not in columns for col in required_columns):
            return False
        if any_required_columns and not any(
            str(col).strip() in columns for col in any_required_columns
        ):
            return False
        return True

    def _read_extra_source_csv(self, file_path: Path, config: Dict[str, Any]) -> pd.DataFrame:
        csv_config = config.get("csv", {}) or {}
        delimiter = csv_config.get("delimiter", ",")
        header_row = csv_config.get("header_row", 1)
        data_start_row = csv_config.get("data_start_row", header_row + 1)
        encoding = csv_config.get("encoding", "utf-8")

        if header_row > 0 and data_start_row > header_row:
            skiprows = [r for r in range(data_start_row - 1) if r != header_row - 1]
            df = pd.read_csv(
                file_path,
                header=0,
                skiprows=skiprows if skiprows else None,
                delimiter=delimiter,
                encoding=encoding,
                on_bad_lines="skip",
            )
            df.columns = [str(col).strip() for col in df.columns]
            return df

        df = pd.read_csv(
            file_path,
            header=header_row - 1 if header_row > 0 else None,
            delimiter=delimiter,
            encoding=encoding,
            on_bad_lines="skip",
        )
        df.columns = [str(col).strip() for col in df.columns]
        return df

    def _normalize_align_key(
        self, series: pd.Series, extract_pattern: Optional[str] = None
    ) -> pd.Series:
        normalized = series.astype(str).str.strip()
        if extract_pattern:
            extracted = normalized.str.extract(extract_pattern, expand=False)
            normalized = extracted.fillna(normalized)
        return normalized

    def _ensure_int64(self, df: pd.DataFrame) -> pd.DataFrame:
        for col in df.select_dtypes(include=["float64"]).columns:
            series = df[col]
            non_null = series.dropna()
            if len(non_null) > 0 and (non_null == non_null.astype("int64")).all():
                df[col] = series.astype("Int64")
        return df

    def _resolve_column_name(self, name: str, df: pd.DataFrame) -> Optional[str]:
        """将 forward_fill/expand_repeat 中的列名解析为 result DataFrame 中的实际列名"""
        if name in df.columns:
            return name
        if self.rule.column_mapping and name in self.rule.column_mapping:
            target = self.rule.column_mapping[name]
            if target in df.columns:
                return target
        return None

    def _apply_expand_repeat(self, df: pd.DataFrame) -> pd.DataFrame:
        total_rows = len(df)
        for col, repeat_count in self.rule.expand_repeat.items():
            resolved = self._resolve_column_name(col, df)
            if resolved is None:
                continue
            values = df[resolved].values
            expanded = np.repeat(values, repeat_count)
            if len(expanded) >= total_rows:
                df[resolved] = expanded[:total_rows]
            else:
                padded = np.full(total_rows, values[-1] if len(values) > 0 else 0)
                padded[: len(expanded)] = expanded
                df[resolved] = padded
        return df

    def _apply_forward_fill(self, df: pd.DataFrame) -> pd.DataFrame:
        for col in self.rule.forward_fill:
            resolved = self._resolve_column_name(col, df)
            if resolved is None:
                continue
            series = pd.to_numeric(df[resolved], errors="coerce")
            nonzero_mask = series.ne(0) & series.notna()
            if not bool(nonzero_mask.any()):
                continue
            filled = series.where(nonzero_mask).ffill().fillna(series)
            try:
                df[resolved] = filled.astype(df[resolved].dtype, copy=False)
            except (TypeError, ValueError):
                df[resolved] = filled
        return df

    def _compute_column(self, formula: str, df: pd.DataFrame) -> pd.Series:
        try:
            result = None
            tokens = re.split(r"\s*([+\-*/])\s*", formula)

            current_op = None
            for token in tokens:
                if token in ["+", "-", "*", "/"]:
                    current_op = token
                    continue

                if token in df.columns:
                    value = pd.to_numeric(df[token], errors="coerce")
                else:
                    try:
                        value = float(token)
                    except ValueError:
                        value = 0

                if result is None:
                    result = value
                elif current_op == "+":
                    result = result + value
                elif current_op == "-":
                    result = result - value
                elif current_op == "*":
                    result = result * value
                elif current_op == "/":
                    if isinstance(value, pd.Series):
                        result = result / value.replace(0, 1)
                    else:
                        result = result / (value if value != 0 else 1)

            return result if result is not None else pd.Series([0] * len(df))
        except Exception as e:
            logger.warning("计算列公式失败 [%s]: %s", formula, e)
            return pd.Series([0] * len(df))
