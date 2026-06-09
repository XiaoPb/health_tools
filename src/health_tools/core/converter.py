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
        extra_df[right_on] = self._normalize_align_key(extra_df[right_on])
        left_keys = self._normalize_align_key(df[left_on])
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
            if matches:
                return matches[0]

        pattern = config.get("pattern")
        if pattern:
            matches = sorted(source_file.parent.glob(pattern))
            if matches:
                return matches[0]

        logger.warning("未找到 extra_source 文件: %s", source_file)
        return None

    def _read_extra_source_csv(self, file_path: Path, config: Dict[str, Any]) -> pd.DataFrame:
        csv_config = config.get("csv", {}) or {}
        delimiter = csv_config.get("delimiter", ",")
        header_row = csv_config.get("header_row", 1)
        data_start_row = csv_config.get("data_start_row", header_row + 1)
        encoding = csv_config.get("encoding", "utf-8")

        if header_row > 0 and data_start_row > header_row:
            skiprows = [r for r in range(data_start_row - 1) if r != header_row - 1]
            return pd.read_csv(
                file_path,
                header=0,
                skiprows=skiprows if skiprows else None,
                delimiter=delimiter,
                encoding=encoding,
                on_bad_lines="skip",
            )

        return pd.read_csv(
            file_path,
            header=header_row - 1 if header_row > 0 else None,
            delimiter=delimiter,
            encoding=encoding,
            on_bad_lines="skip",
        )

    def _normalize_align_key(self, series: pd.Series) -> pd.Series:
        return series.astype(str).str.strip()

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
            values = df[resolved].to_numpy(dtype=np.int64, copy=True)
            first_nonzero = None
            for i in range(len(values)):
                v = values[i]
                if isinstance(v, np.ndarray):
                    v = v.item() if v.size == 1 else 0
                if v != 0:
                    first_nonzero = i
                    break
            if first_nonzero is None:
                continue
            last_val = values[first_nonzero]
            for i in range(first_nonzero + 1, len(values)):
                cur = values[i]
                if isinstance(cur, np.ndarray):
                    cur = cur.item() if cur.size == 1 else 0
                if cur == 0:
                    values[i] = last_val
                else:
                    last_val = cur
            df[resolved] = values
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
