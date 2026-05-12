from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from health_tools.models.rules import ChipRule, ParsePattern, ParseRule  # noqa: F401


class LogParser:
    def __init__(self, rule: ParseRule, chip_columns: Optional[List[str]] = None):
        self.rule = rule
        self.chip_columns = chip_columns

    def _extract_record(self, line: str) -> Optional[dict]:
        match = self.rule._compiled_regex.search(line)
        if not match:
            return None

        groups = match.groups()
        num_columns = len(self.rule.columns)

        if len(groups) == num_columns:
            return dict(zip(self.rule.columns, groups))

        if len(groups) == 1 and num_columns > 1:
            raw = groups[0].strip().rstrip(self.rule.separator)
            parts = [p.strip() for p in raw.split(self.rule.separator)]
            if len(parts) == num_columns:
                return dict(zip(self.rule.columns, parts))
            if len(parts) > num_columns:
                return dict(zip(self.rule.columns, parts[:num_columns]))

        return None

    def _extract_record_with_pattern(
        self, line: str, pattern: ParsePattern
    ) -> Optional[dict]:
        match = pattern._compiled_regex.search(line)
        if not match:
            return None

        groups = match.groups()
        num_columns = len(pattern.columns)

        if len(groups) == num_columns:
            return dict(zip(pattern.columns, groups))

        if len(groups) == 1 and num_columns > 1:
            raw = groups[0].strip().rstrip(pattern.separator)
            parts = [p.strip() for p in raw.split(pattern.separator)]
            if len(parts) == num_columns:
                return dict(zip(pattern.columns, parts))
            if len(parts) > num_columns:
                return dict(zip(pattern.columns, parts[:num_columns]))

        return None

    def _expand_to_chip_format(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.chip_columns:
            return df
        result = pd.DataFrame(0, index=df.index, columns=self.chip_columns)
        for col in df.columns:
            if col in result.columns:
                result[col] = df[col]
        return result

    def parse_file(self, file_path: Path, encoding: str = "utf-8") -> Optional[pd.DataFrame]:
        with open(file_path, "r", encoding=encoding) as f:
            lines = f.readlines()

        records = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            record = self._extract_record(line)
            if record:
                records.append(record)

        if records:
            df = pd.DataFrame(records)
            return self._expand_to_chip_format(df)
        return None

    def parse_file_multi(
        self, file_path: Path, encoding: str = "utf-8"
    ) -> Dict[str, pd.DataFrame]:
        with open(file_path, "r", encoding=encoding) as f:
            lines = f.readlines()

        records_map: Dict[str, list] = {name: [] for name in self.rule.patterns}

        for line in lines:
            line = line.strip()
            if not line:
                continue
            for name, pattern in self.rule.patterns.items():
                record = self._extract_record_with_pattern(line, pattern)
                if record:
                    records_map[name].append(record)
                    break

        result = {}
        for name, records in records_map.items():
            if records:
                df = pd.DataFrame(records)
                result[name] = self._expand_to_chip_format(df)
        return result

    def parse_text(self, text: str) -> Optional[pd.DataFrame]:
        lines = text.split("\n")
        records = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            record = self._extract_record(line)
            if record:
                records.append(record)

        if records:
            df = pd.DataFrame(records)
            return self._expand_to_chip_format(df)
        return None
