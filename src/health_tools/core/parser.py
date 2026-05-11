from pathlib import Path
from typing import Optional

import pandas as pd

from health_tools.models.rules import ChipRule, ParseRule  # noqa: F401


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
