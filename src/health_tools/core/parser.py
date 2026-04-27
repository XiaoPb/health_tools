import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pandas as pd


@dataclass
class ParseRule:
    regex: str
    columns: List[str]
    description: str = ""

    def __post_init__(self):
        self.columns = self._expand_columns(self.columns)
        self._compiled_regex = re.compile(self.regex)

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


@dataclass
class ChipRule:
    chip: str
    csv: dict
    columns: List[str]
    version: str = "1.0"

    def __post_init__(self):
        self.columns = self._expand_columns(self.columns)

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

    @property
    def header_row(self) -> int:
        return self.csv.get("header_row", 1)

    @property
    def data_start_row(self) -> int:
        return self.csv.get("data_start_row", 2)

    @property
    def delimiter(self) -> str:
        return self.csv.get("delimiter", ",")

    @property
    def encoding(self) -> str:
        return self.csv.get("encoding", "utf-8")


class LogParser:
    def __init__(self, rule: ParseRule):
        self.rule = rule

    def parse_file(self, file_path: Path, encoding: str = "utf-8") -> Optional[pd.DataFrame]:
        with open(file_path, "r", encoding=encoding) as f:
            lines = f.readlines()

        records = []
        for line in lines:
            line = line.strip()
            if not line:
                continue

            match = self.rule._compiled_regex.match(line)
            if match:
                groups = match.groups()
                if len(groups) == len(self.rule.columns):
                    record = dict(zip(self.rule.columns, groups))
                    records.append(record)

        if records:
            return pd.DataFrame(records)
        return None

    def parse_text(self, text: str) -> Optional[pd.DataFrame]:
        lines = text.split("\n")
        records = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            match = self.rule._compiled_regex.match(line)
            if match:
                groups = match.groups()
                if len(groups) == len(self.rule.columns):
                    record = dict(zip(self.rule.columns, groups))
                    records.append(record)

        if records:
            return pd.DataFrame(records)
        return None
