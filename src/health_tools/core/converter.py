import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd


@dataclass
class ConvertRule:
    source_columns: List[str] = field(default_factory=list)
    target_columns: List[str] = field(default_factory=list)
    computed: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        self.source_columns = self._expand_columns(self.source_columns)
        self.target_columns = self._expand_columns(self.target_columns)

    def _expand_columns(self, columns: List[str]) -> List[str]:
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


class DataConverter:
    def __init__(self, rule: ConvertRule):
        self.rule = rule

    def convert(self, df: pd.DataFrame) -> pd.DataFrame:
        result = pd.DataFrame()

        if self.rule.source_columns and self.rule.target_columns:
            for src, tgt in zip(self.rule.source_columns, self.rule.target_columns):
                if src in df.columns:
                    result[tgt] = df[src]
        else:
            result = df.copy()

        if self.rule.computed:
            for col_name, formula in self.rule.computed.items():
                result[col_name] = self._compute_column(formula, df)

        return result

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
                    result = result / value.replace(0, 1)

            return result if result is not None else pd.Series([0] * len(df))
        except Exception:
            return pd.Series([0] * len(df))
