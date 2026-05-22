import re
from typing import List, Optional

import numpy as np
import pandas as pd

from health_tools.models.rules import ConvertRule  # noqa: F401


class DataConverter:
    def __init__(self, rule: ConvertRule, chip_columns: Optional[List[str]] = None):
        self.rule = rule
        self.chip_columns = chip_columns

    def convert(self, df: pd.DataFrame) -> pd.DataFrame:
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
            series = df[resolved].reset_index(drop=True)
            nonzero_mask = series.ne(0)
            if not nonzero_mask.any():
                continue
            first_pos = int(nonzero_mask.idxmax())
            filled = series.iloc[first_pos:].replace(0, pd.NA).ffill().fillna(0)
            series.iloc[first_pos:] = filled.values
            df[resolved] = series.values
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
        except Exception:
            return pd.Series([0] * len(df))
